"""
Spark Agent — Web UI server.

Provides a FastAPI backend serving the Vite/React frontend and REST API
endpoints for managing configuration, environment variables, and sessions.

Usage:
    python -m spark_cli.main dashboard    # Start with dashboard.* config
    python -m spark_cli.main dashboard --port 8080
"""

import asyncio
import hashlib
import json
import logging
import mimetypes
import os
import platform
import queue as thread_queue
import re
import shutil
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yaml

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from spark_cli import __version__, __release_date__
from spark_cli.config import (
    DEFAULT_CONFIG,
    OPTIONAL_ENV_VARS,
    get_config_path,
    get_env_path,
    get_spark_home,
    load_config,
    load_env,
    save_config,
    save_env_value,
    remove_env_value,
    check_config_version,
    redact_key,
)
from spark_cli.onboarding_validation import (
    normalize_http_base_url,
    normalize_model_name,
    validate_env_assignment,
)
from gateway.status import get_running_pid, read_runtime_status
from spark_cli.dashboard_auth import (
    dashboard_token_path,
    ensure_dashboard_token_file,
    extract_bearer_token,
    get_configured_dashboard_secret,
    validate_dashboard_request,
)
from spark_cli.canvas_routes import register_canvas_routes
from spark_cli.kanban_routes import register_kanban_routes
from spark_cli.workflow_routes import register_workflow_routes
from spark_cli.workspace_routes import register_workspace_routes
from spark_cli.connectors_routes import register_connectors_routes, set_server_port as _set_connectors_port

try:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, JSONResponse, Response
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel
    from starlette.middleware.base import BaseHTTPMiddleware
except ImportError:
    raise SystemExit(
        "Web UI requires fastapi and uvicorn.\n"
        "Run 'spark web' to auto-install, or: pip install spark-agent[web]"
    )

WEB_DIST = Path(__file__).parent / "web_dist"
_log = logging.getLogger(__name__)

# Captured at startup — fan-out SSE events from sync agent threads
_web_event_loop: Optional[asyncio.AbstractEventLoop] = None
_event_subscribers: set = set()  # asyncio.Queue
_admin_runs: dict[str, dict[str, Any]] = {}
_admin_run_queues: dict[str, thread_queue.Queue] = {}


@dataclass
class WebActiveTurn:
    started_at: float
    last_event_at: float
    status: str
    interrupt_requested: bool
    active_agent_session_id: Optional[str]
    phase: str
    stream_text: str = ""
    stream_revision: int = 0


_web_active_turns: dict[str, WebActiveTurn] = {}

_EVENT_QUEUE_SIZE = 512
_PRIORITY_EVENT_TOPICS = {
    "chat.turn_done",
    "chat.interrupted",
    "chat.session_migrated",
    "chat.approval_requested",
    "chat.approval_resolved",
    "chat.subagent.created",
    "chat.subagent.completed",
    "chat.subagent.failed",
    "chat.subagent.interrupted",
}
_DROPPABLE_EVENT_TOPICS = {
    "chat.token",
    "chat.status",
    "chat.reasoning",
    "chat.tool_start",
    "chat.tool_end",
    "chat.subagent.thinking",
    "chat.subagent.tool_started",
    "chat.subagent.tool_output",
    "chat.subagent.tool_completed",
}
_event_drop_counts: dict[str, int] = {}

# strip_ansi handles complete ECMA-48 sequences. Web streaming can occasionally
# see a split/incomplete sequence, so remove any remaining control prefix too.
_WEB_ANSI_FRAGMENT_RE = re.compile(
    r"\x1b(?:\[[\x30-\x3f]*[\x20-\x2f]*|\][^\x07\x1b]*|[PX^_][\s\S]*|[\x20-\x2f]*[\x30-\x7e]?|$)"
    r"|[\x80-\x9f]",
    re.DOTALL,
)


def _sanitize_web_chat_text(text: str) -> str:
    """Remove terminal control sequences before text reaches desktop/web chat."""
    from tools.ansi_strip import strip_ansi

    clean = strip_ansi(text)
    if not clean:
        return clean
    return _WEB_ANSI_FRAGMENT_RE.sub("", clean)


def _sanitize_web_chat_value(value: Any) -> Any:
    """Recursively sanitize strings in chat-bound payload copies."""
    if isinstance(value, str):
        return _sanitize_web_chat_text(value)
    if isinstance(value, list):
        return [_sanitize_web_chat_value(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_web_chat_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize_web_chat_value(item) for key, item in value.items()}
    return value


def _resolve_web_turn_ids(session_id: Optional[str]) -> dict[str, Optional[str]]:
    """Resolve a user-facing session id to the latest active conversation leaf."""
    if not session_id:
        return {"requested": session_id, "resolved": session_id, "latest": session_id}
    try:
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            resolved = db.resolve_session_id(session_id) or session_id
            latest = db.resolve_latest_descendant(resolved) if resolved else resolved
            return {"requested": session_id, "resolved": resolved, "latest": latest or resolved}
        finally:
            db.close()
    except Exception:
        _log.debug("web turn id resolution failed session=%s", session_id, exc_info=True)
        return {"requested": session_id, "resolved": session_id, "latest": session_id}


def _web_turn_candidates(session_id: Optional[str]) -> set[str]:
    ids = _resolve_web_turn_ids(session_id)
    return {str(v) for v in ids.values() if v}


def _web_turn_key(session_id: str) -> str:
    ids = _resolve_web_turn_ids(session_id)
    return str(ids.get("latest") or ids.get("resolved") or session_id)


def _mark_web_turn_active(
    session_id: str,
    *,
    status: str = "Starting…",
    phase: str = "starting",
    active_agent_session_id: Optional[str] = None,
) -> WebActiveTurn:
    key = _web_turn_key(session_id)
    now = time.time()
    turn = WebActiveTurn(
        started_at=now,
        last_event_at=now,
        status=status,
        interrupt_requested=False,
        active_agent_session_id=active_agent_session_id,
        phase=phase,
    )
    _web_active_turns[key] = turn
    return turn


def _touch_web_turn(
    session_id: Optional[str],
    *,
    status: Optional[str] = None,
    phase: Optional[str] = None,
    interrupt_requested: Optional[bool] = None,
    active_agent_session_id: Optional[str] = None,
) -> None:
    if not session_id:
        return
    for candidate in _web_turn_candidates(session_id):
        turn = _web_active_turns.get(candidate)
        if not turn:
            continue
        turn.last_event_at = time.time()
        if status is not None:
            turn.status = _sanitize_web_chat_text(status)
        if phase is not None:
            turn.phase = phase
        if interrupt_requested is not None:
            turn.interrupt_requested = interrupt_requested
        if active_agent_session_id is not None:
            turn.active_agent_session_id = active_agent_session_id
        return


def _append_web_turn_token(session_id: Optional[str], token: str) -> None:
    if not session_id or not token:
        return
    token = _sanitize_web_chat_text(token)
    if not token:
        return
    for candidate in _web_turn_candidates(session_id):
        turn = _web_active_turns.get(candidate)
        if not turn:
            continue
        turn.last_event_at = time.time()
        turn.phase = "streaming"
        turn.stream_text += token
        turn.stream_revision += 1
        return


def _clear_web_turn(session_id: str) -> None:
    for candidate in _web_turn_candidates(session_id):
        _web_active_turns.pop(candidate, None)


def _get_web_turn(session_id: str) -> tuple[Optional[str], Optional[WebActiveTurn]]:
    for candidate in _web_turn_candidates(session_id):
        turn = _web_active_turns.get(candidate)
        if turn:
            return candidate, turn
    return None, None


def _is_web_turn_active(session_id: Optional[str]) -> bool:
    if not session_id:
        return False
    return _get_web_turn(session_id)[1] is not None


def _get_web_agent_for_turn(session_id: str) -> tuple[Optional[str], Any]:
    ids = _resolve_web_turn_ids(session_id)
    candidates = [
        ids.get("latest"),
        ids.get("resolved"),
        ids.get("requested"),
    ]
    for candidate in candidates:
        if candidate and candidate in _web_agents:
            return candidate, _web_agents[candidate]
    _, turn = _get_web_turn(session_id)
    if turn and turn.active_agent_session_id and turn.active_agent_session_id in _web_agents:
        return turn.active_agent_session_id, _web_agents[turn.active_agent_session_id]
    return None, None


@asynccontextmanager
def _prefetch_update_check() -> None:
    """Run in a thread at startup to warm the update-check cache."""
    try:
        from spark_cli.banner import check_for_updates
        check_for_updates()
    except Exception:
        pass


def _prefetch_mac_update_check() -> None:
    """Warm the macOS release-update cache at startup (desktop app only)."""
    try:
        if _is_desktop_app():
            _check_mac_update(force=True)
    except Exception:
        pass


def _init_memory_store() -> None:
    """Initialize the holographic memory store on startup (non-fatal)."""
    try:
        from plugins.memory.holographic import HolographicMemoryProvider
        provider = HolographicMemoryProvider()
        # initialize() requires a session id; this boot-time call only validates
        # and warms the on-disk store, so a sentinel id is fine.
        provider.initialize(session_id="__boot__")
        _log.info("Holographic memory store initialized")
    except Exception as exc:
        _log.warning("Memory store init skipped: %s", exc)


def _prewarm_agent_stack() -> None:
    """Pay the agent import/tool-discovery cold-start cost at boot.

    Importing AIAgent pulls in the model SDKs + runs tool discovery
    (``_discover_tools()`` at import). On a frozen app this is the first time
    many .so/.dylib files are loaded from the bundle (and, on an unsigned macOS
    build, scanned by Gatekeeper), which can take seconds. Doing it here — while
    the desktop loading screen is already showing — means the first new chat
    thread doesn't pay it. Best-effort; failures are non-fatal.
    """
    try:
        import core.model_tools  # noqa: F401  (runs _discover_tools at import)
        from core.run_agent import AIAgent  # noqa: F401

        # Warm the models.dev metadata fetch now (during the desktop loading
        # screen) rather than on the first chat turn — it runs synchronously in
        # AIAgent.__init__ and can stall for seconds when models.dev is slow.
        from agent.models_dev import fetch_models_dev

        fetch_models_dev()
    except Exception:
        _log.debug("agent prewarm skipped", exc_info=True)


async def _lifespan(_app: FastAPI):
    global _web_event_loop
    _web_event_loop = asyncio.get_running_loop()
    ensure_dashboard_token_file()
    # Warm the update cache in the background so /api/status has it immediately
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _prefetch_update_check)
    loop.run_in_executor(None, _prefetch_mac_update_check)
    loop.run_in_executor(None, _init_memory_store)
    loop.run_in_executor(None, _prewarm_agent_stack)
    # Desktop app: keep the messaging gateway running in the background so
    # platforms stay reachable while the app is open. No-ops outside the
    # desktop sidecar or when disabled via config. Only stops a gateway we own.
    try:
        from spark_cli.desktop_gateway import start_desktop_gateway
        start_desktop_gateway()
    except Exception:
        _log.debug("desktop gateway autostart skipped", exc_info=True)
    try:
        yield
    finally:
        try:
            from spark_cli.desktop_gateway import stop_desktop_gateway
            await loop.run_in_executor(None, stop_desktop_gateway)
        except Exception:
            _log.debug("desktop gateway shutdown skipped", exc_info=True)
        _web_event_loop = None
        _event_subscribers.clear()
        _web_active_turns.clear()
        _web_queues.clear()


app = FastAPI(title="Spark Agent", version=__version__, lifespan=_lifespan)

# ---------------------------------------------------------------------------
# Session token for protecting sensitive endpoints (reveal).
# Generated fresh on every server start — dies when the process exits.
# Injected into the SPA HTML so only the legitimate web UI can use it.
# ---------------------------------------------------------------------------
_SERVER_INSTANCE_ID = uuid.uuid4().hex
_SESSION_TOKEN = secrets.token_urlsafe(32)

# Simple rate limiter for the reveal endpoint
_reveal_timestamps: List[float] = []
_REVEAL_MAX_PER_WINDOW = 5
_REVEAL_WINDOW_SECONDS = 30

# CORS: LAN dashboard mode uses bearer/token-file auth on API routes, so we
# allow any Origin (no cookies). For untrusted networks, keep the dashboard
# bound to a trusted interface/VPN and rotate SPARK_DASHBOARD_TOKEN.

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://[\w\-.]+(:\d+)?$|^null$",
    allow_methods=["*"],
    allow_headers=["*"],
)


class DashboardAPIAuthMiddleware(BaseHTTPMiddleware):
    """Require dashboard.token (or SPARK_DASHBOARD_TOKEN) for non-loopback API calls."""

    _PUBLIC_PATHS = frozenset({"/api/dashboard/auth/info", "/api/status"})

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if request.method == "OPTIONS":
            return await call_next(request)
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)
        if path in self._PUBLIC_PATHS:
            return await call_next(request)
        cfg = load_config()
        dash = cfg.get("dashboard") if isinstance(cfg, dict) else {}
        if not isinstance(dash, dict):
            dash = {}
        require = bool(dash.get("require_auth_nonlocal", True))
        if not require:
            return await call_next(request)
        secret = get_configured_dashboard_secret()
        if not secret:
            secret = ensure_dashboard_token_file()
        client_host = request.client.host if request.client else None
        auth_header = request.headers.get("authorization")
        qtoken = request.query_params.get("dashboard_token")
        if request.method != "GET":
            qtoken = None
        if validate_dashboard_request(
            client_host,
            auth_header,
            require_for_remote=True,
            secret=secret,
            query_token=qtoken,
        ):
            return await call_next(request)
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)


app.add_middleware(DashboardAPIAuthMiddleware)


def _json_safe(obj: Any, max_len: int = 12000) -> Any:
    """Best-effort JSON-serializable snapshot for SSE payloads."""
    try:
        s = json.dumps(obj, default=str, ensure_ascii=False)
        if len(s) > max_len:
            return {"_truncated": True, "preview": s[: max_len - 20] + "…"}
        return json.loads(s)
    except Exception:
        try:
            return {"_repr": str(obj)[:max_len]}
        except Exception:
            return {}


def _truncate_str(s: Any, max_len: int = 16000) -> str:
    if s is None:
        return ""
    t = str(s)
    return t if len(t) <= max_len else t[: max_len - 1] + "…"


def _tool_result_preview(result: Any, max_len: int = 2000) -> dict[str, Any]:
    text = _sanitize_web_chat_text("" if result is None else str(result))
    return {
        "result_preview": _truncate_str(text, max_len),
        "result_chars": len(text),
        "result_truncated": len(text) > max_len,
        "has_full_result": len(text) > max_len,
    }


def _message_for_history_response(msg: dict[str, Any], include_tool_results: bool = False) -> dict[str, Any]:
    """Return a UI-safe message copy for chat history responses.

    Tool payloads can be tens of thousands of characters and are collapsed in
    the UI by default. Sending every full tool result during a history sync
    defeats that collapse and can stall WebKit after a long tool-heavy turn.
    Keep the full result available through the per-tool result endpoint, but
    make the normal history page carry only a bounded preview.
    """
    out = dict(msg)
    if "content" in out:
        out["content"] = _sanitize_web_chat_value(out.get("content"))
    if out.get("role") != "tool" or include_tool_results:
        return _sanitize_web_chat_value(out)

    content = out.get("content") or ""
    out.update(_tool_result_preview(content))
    out["content"] = out["result_preview"]
    return _sanitize_web_chat_value(out)


def _redacted_response_preview(resp: Any, max_len: int = 600) -> str:
    """Small response preview for auth diagnostics without exposing secrets."""
    try:
        body = resp.text
    except Exception:
        body = ""
    preview = _truncate_str(body, max_len).strip()
    if not preview:
        return "(empty response)"
    preview = re.sub(
        r'(?i)("?(?:access_token|refresh_token|id_token|authorization_code|code_verifier|token)"?\s*[:=]\s*)"[^"]+"',
        r'\1"[redacted]"',
        preview,
    )
    return preview


def _publish_event(topic: str, data: dict, session_id: Optional[str] = None) -> None:
    loop = _web_event_loop
    if loop is None:
        return
    if topic.startswith("chat."):
        data = _sanitize_web_chat_value(data)
    envelope = {"topic": topic, "session_id": session_id, "ts": time.time(), "data": data}

    def _fanout() -> None:
        for q in tuple(_event_subscribers):
            try:
                q.put_nowait(envelope)
                continue
            except asyncio.QueueFull:
                if topic in _PRIORITY_EVENT_TOPICS and _make_room_for_priority_event(q):
                    try:
                        q.put_nowait(envelope)
                        continue
                    except asyncio.QueueFull:
                        pass
                _record_event_drop(topic, session_id)
            except Exception:
                _event_subscribers.discard(q)

    try:
        loop.call_soon_threadsafe(_fanout)
    except Exception:
        pass


def _record_event_drop(topic: str, session_id: Optional[str]) -> None:
    key = f"{session_id or '-'}:{topic}"
    count = _event_drop_counts.get(key, 0) + 1
    _event_drop_counts[key] = count
    if count in {1, 10, 100}:
        _log.warning(
            "Dropped web SSE event due to slow subscriber session=%s topic=%s count=%s",
            session_id,
            topic,
            count,
        )


def _make_room_for_priority_event(q: asyncio.Queue) -> bool:
    """Drop older low-value events so completion/control events can be delivered."""
    try:
        pending = q._queue  # type: ignore[attr-defined]
    except Exception:
        return False
    for env in tuple(pending):
        if isinstance(env, dict) and env.get("topic") in _DROPPABLE_EVENT_TOPICS:
            try:
                pending.remove(env)
                _record_event_drop(str(env.get("topic") or "unknown"), env.get("session_id"))
                return True
            except ValueError:
                return not q.full()
    return not q.full()


def push_job_notification(job_id: str, job_name: str, success: bool, summary: str) -> None:
    """Publish a cron job completion event to all SSE subscribers."""
    _publish_event(
        "notifications.job_complete",
        {
            "job_id": job_id,
            "job_name": job_name,
            "success": success,
            "summary": summary[:200],
        },
    )


def _topic_allowed(topic: str, prefixes: tuple[str, ...]) -> bool:
    if not prefixes:
        return True
    for p in prefixes:
        if topic == p or topic.startswith(p + "."):
            return True
    return False


def _emit_sessions_changed(
    action: str, session_id: str, session: Optional[dict] = None
) -> None:
    payload: Dict[str, Any] = {"action": action, "session_id": session_id}
    if session is not None:
        payload["session"] = session
    _publish_event("sessions.changed", payload, session_id)


def _subagent_event_name(payload: dict[str, Any]) -> str:
    raw = str(payload.get("event") or payload.get("type") or "status")
    raw = raw.split(".")[-1]
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", raw).strip("_").lower()
    return safe or "status"


def _subagent_run_from_event(session_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    event_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
    legacy_run = payload.get("run") if isinstance(payload.get("run"), dict) else {}
    subagent_id = (
        payload.get("id")
        or payload.get("run_id")
        or legacy_run.get("id")
        or payload.get("subagent_id")
        or legacy_run.get("subagent_id")
    )
    if not subagent_id:
        return None

    event_name = _subagent_event_name(payload)
    status = {
        "created": "created",
        "started": "running",
        "thinking": "running",
        "tool_started": "running",
        "tool_output": "running",
        "tool_completed": "running",
        "status": event_payload.get("status") or legacy_run.get("status") or "running",
        "completed": "completed",
        "failed": "failed",
        "interrupted": "interrupted",
    }.get(event_name, legacy_run.get("status") or "running")
    now = time.time()
    task_index = payload.get("task_index", legacy_run.get("task_index", 0))
    run: dict[str, Any] = {
        **legacy_run,
        "id": str(subagent_id),
        "parent_session_id": (
            event_payload.get("parent_session_id")
            or legacy_run.get("parent_session_id")
            or session_id
        ),
        "child_session_id": (
            payload.get("child_session_id")
            or event_payload.get("child_session_id")
            or legacy_run.get("child_session_id")
        ),
        "task_index": task_index,
        "name": payload.get("display_name") or legacy_run.get("name"),
        "status": status,
        "task": legacy_run.get("task") or payload.get("goal_preview"),
        "context_preview": legacy_run.get("context_preview"),
        "model": payload.get("model") or legacy_run.get("model"),
        "provider": event_payload.get("provider") or legacy_run.get("provider"),
        "toolsets": event_payload.get("toolsets") or legacy_run.get("toolsets") or [],
        "last_event_at": now,
        "summary": event_payload.get("summary") or legacy_run.get("summary"),
        "error": event_payload.get("error") or legacy_run.get("error"),
        "exit_reason": event_payload.get("exit_reason") or legacy_run.get("exit_reason"),
        "tokens": event_payload.get("tokens") or legacy_run.get("tokens"),
    }
    if event_payload.get("status"):
        run["status"] = event_payload.get("status")
    if event_name in {"completed", "failed", "interrupted"}:
        run["ended_at"] = now
        if event_payload.get("duration_seconds") is not None:
            run["duration_seconds"] = event_payload.get("duration_seconds")
    return run


def _persist_and_publish_subagent_event(session_id: str, payload: dict[str, Any]) -> None:
    """Persist a subagent lifecycle event and fan it out on chat.subagent.*."""
    event_name = _subagent_event_name(payload)
    event_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
    if not event_payload and isinstance(payload.get("data"), dict):
        event_payload = payload["data"]
    run_snapshot = None
    run = _subagent_run_from_event(session_id, payload)
    if run:
        try:
            from core.spark_state import SessionDB

            db = SessionDB()
            try:
                db.create_subagent_run(run)
                db.append_subagent_event(run["id"], event_name, payload)
                run_snapshot = db.get_subagent_run(run["id"])
            finally:
                db.close()
        except Exception:
            _log.debug("subagent lifecycle persistence failed", exc_info=True)

    run_data = run_snapshot or run or {}
    subagent_id = run_data.get("id") if run_data else payload.get("subagent_id")
    event_text = (
        event_payload.get("text")
        or event_payload.get("preview")
        or event_payload.get("summary")
        or event_payload.get("error")
        or event_payload.get("tool")
        or event_payload.get("line")
    )
    event = {
        "type": event_name,
        "run_id": subagent_id,
        "subagent_id": subagent_id,
        "status": run_data.get("status") if run_data else None,
        "tool_name": event_payload.get("tool") or event_payload.get("tool_name"),
        "text": _truncate_str(str(event_text), 2000) if event_text is not None else None,
        "ts": time.time(),
        "data": _json_safe(event_payload),
    }

    _publish_event(
        f"chat.subagent.{event_name}",
        {
            **_json_safe(run_data),
            "event": event,
            "event_type": event_name,
            "id": subagent_id,
            "run_id": subagent_id,
            "subagent_id": subagent_id,
            "subagent": _json_safe(run_data),
            "events": [event],
            "transcript": [event],
            "data": _json_safe(event_payload),
        },
        session_id,
    )


@app.get("/api/events")
async def sse_events_bus(request: Request, topics: str = "sessions,chat"):
    """Shared SSE bus for sessions.* and chat.* events."""
    from fastapi.responses import StreamingResponse as _StreamingResponse

    prefixes = tuple(p.strip() for p in topics.split(",") if p.strip())
    queue: asyncio.Queue = asyncio.Queue(maxsize=_EVENT_QUEUE_SIZE)
    _event_subscribers.add(queue)

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    env = await asyncio.wait_for(queue.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    yield "event: ping\ndata: {}\n\n"
                    continue
                if not _topic_allowed(env.get("topic", ""), prefixes):
                    continue
                try:
                    yield f"data: {json.dumps(env, default=str)}\n\n"
                except Exception:
                    continue
        finally:
            _event_subscribers.discard(queue)

    return _StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ---------------------------------------------------------------------------
# Config schema — auto-generated from DEFAULT_CONFIG
# ---------------------------------------------------------------------------

# Manual overrides for fields that need select options or custom types
_SCHEMA_OVERRIDES: Dict[str, Dict[str, Any]] = {
    "agent.name": {
        "type": "string",
        "description": "The name your agent uses for itself. Applies to new conversations.",
        "category": "general",
        "label": "Agent name",
    },
    "model": {
        "type": "string",
        "description": "SMART model for complex / coding tasks. Use `spark model` → Multi-model to configure SMART and FAST models together.",
        "category": "general",
    },
    "model_provider": {
        "type": "select",
        "description": "SMART model provider (for example openai-codex, openrouter, anthropic, custom).",
        "options": [
            "",
            "openai-codex",
            "openrouter",
            "anthropic",
            "qwen-oauth",
            "github-copilot",
            "copilot-acp",
            "zai",
            "kimi-for-coding",
            "deepseek",
            "alibaba",
            "minimax",
            "minimax-cn",
            "xai",
            "ollama",
            "custom",
        ],
        "category": "general",
    },
    "model_base_url": {
        "type": "string",
        "description": "Optional SMART model base URL for custom or OpenAI-compatible providers.",
        "category": "general",
    },
    "model_api_mode": {
        "type": "select",
        "description": "Optional SMART model API mode override.",
        "options": ["", "chat_completions", "responses", "codex_responses"],
        "category": "general",
    },
    "model_context_length": {
        "type": "number",
        "description": "Context window override (0 = auto-detect from model metadata)",
        "category": "general",
    },
    "smart_model_routing.enabled": {
        "description": "Enable Multi-model routing: keep the SMART model for complex work and route simple turns to the configured FAST model.",
        "category": "general",
    },
    "smart_model_routing.max_simple_chars": {
        "description": "Only route messages at or below this many characters to the FAST model.",
        "category": "general",
    },
    "smart_model_routing.max_simple_words": {
        "description": "Only route messages at or below this many words to the FAST model.",
        "category": "general",
    },
    "smart_model_routing.cheap_model.provider": {
        "type": "select",
        "description": "FAST model provider for simple requests (for example openai-codex, openrouter, anthropic, custom).",
        "options": [
            "",
            "openai-codex",
            "openrouter",
            "anthropic",
            "qwen-oauth",
            "github-copilot",
            "copilot-acp",
            "zai",
            "kimi-for-coding",
            "deepseek",
            "alibaba",
            "minimax",
            "minimax-cn",
            "xai",
            "ollama",
            "custom",
        ],
        "category": "general",
    },
    "smart_model_routing.cheap_model.model": {
        "description": "FAST model used for simple requests (for example gpt-5.4-mini).",
        "category": "general",
    },
    "smart_model_routing.cheap_model.base_url": {
        "description": "Optional FAST model base URL for custom or OpenAI-compatible providers.",
        "category": "general",
    },
    "smart_model_routing.cheap_model.api_mode": {
        "type": "select",
        "description": "Optional FAST model API mode override.",
        "options": ["", "chat_completions", "responses", "codex_responses"],
        "category": "general",
    },
    "terminal.backend": {
        "type": "select",
        "description": "Terminal execution backend",
        "options": ["local", "docker", "ssh", "modal", "daytona", "singularity"],
    },
    "terminal.modal_mode": {
        "type": "select",
        "description": "Modal sandbox mode",
        "options": ["sandbox", "function"],
    },
    "tts.provider": {
        "type": "select",
        "description": "Text-to-speech provider",
        "options": ["edge", "elevenlabs", "openai", "neutts"],
    },
    "stt.provider": {
        "type": "select",
        "description": "Speech-to-text provider",
        "options": ["local", "openai", "mistral"],
    },
    "display.skin": {
        "type": "select",
        "description": "CLI visual theme",
        "options": ["default", "ares", "mono", "slate"],
    },
    "display.resume_display": {
        "type": "select",
        "description": "How resumed sessions display history",
        "options": ["minimal", "full", "off"],
    },
    "display.busy_input_mode": {
        "type": "select",
        "description": "Input behavior while agent is running",
        "options": ["queue", "interrupt", "block"],
    },
    "memory.provider": {
        "type": "select",
        "description": "Memory provider plugin",
        "options": ["builtin", "honcho"],
    },
    "approvals.mode": {
        "type": "select",
        "description": "Dangerous command approval mode",
        "options": ["ask", "yolo", "deny"],
    },
    "context.engine": {
        "type": "select",
        "description": "Context management engine",
        "options": ["default", "custom"],
    },
    "human_delay.mode": {
        "type": "select",
        "description": "Simulated typing delay mode",
        "options": ["off", "typing", "fixed"],
    },
    "logging.level": {
        "type": "select",
        "description": "Log level for agent.log",
        "options": ["DEBUG", "INFO", "WARNING", "ERROR"],
    },
    "agent.service_tier": {
        "type": "select",
        "description": "API service tier (OpenAI/Anthropic)",
        "options": ["", "auto", "default", "flex"],
    },
    "agent.reasoning_effort": {
        "type": "select",
        "description": "Global reasoning effort for the model. Only takes effect on reasoning-capable models. Empty = model default (usually medium).",
        "options": ["", "minimal", "low", "medium", "high", "xhigh"],
        "category": "general",
    },
    "delegation.reasoning_effort": {
        "type": "select",
        "description": "Reasoning effort for delegated subagents",
        "options": ["", "low", "medium", "high"],
    },
}

# Categories with fewer fields get merged into "general" to avoid tab sprawl.
_CATEGORY_MERGE: Dict[str, str] = {
    "privacy": "security",
    "context": "agent",
    "skills": "agent",
    "cron": "agent",
    "network": "agent",
    "checkpoints": "agent",
    "desktop": "general",
    "approvals": "security",
    "human_delay": "display",
    "smart_model_routing": "general",
}

# Display order for tabs — unlisted categories sort alphabetically after these.
_CATEGORY_ORDER = [
    "general",
    "agent",
    "terminal",
    "display",
    "delegation",
    "memory",
    "compression",
    "security",
    "browser",
    "voice",
    "tts",
    "stt",
    "logging",
    "discord",
    "auxiliary",
]


def _infer_type(value: Any) -> str:
    """Infer a UI field type from a Python value."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "number"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "object"
    return "string"


def _build_schema_from_config(
    config: Dict[str, Any],
    prefix: str = "",
) -> Dict[str, Dict[str, Any]]:
    """Walk DEFAULT_CONFIG and produce a flat dot-path → field schema dict."""
    schema: Dict[str, Dict[str, Any]] = {}
    for key, value in config.items():
        full_key = f"{prefix}.{key}" if prefix else key

        # Skip internal / version keys
        if full_key in ("_config_version",):
            continue

        # Category is the first path component for nested keys, or "general"
        # for top-level scalar fields (model, toolsets, timezone, etc.).
        if prefix:
            category = prefix.split(".")[0]
        elif isinstance(value, dict):
            category = key
        else:
            category = "general"

        if isinstance(value, dict):
            # Recurse into nested dicts
            schema.update(_build_schema_from_config(value, full_key))
        else:
            entry: Dict[str, Any] = {
                "type": _infer_type(value),
                "description": full_key.replace(".", " → ").replace("_", " ").title(),
                "category": category,
            }
            # Apply manual overrides
            if full_key in _SCHEMA_OVERRIDES:
                entry.update(_SCHEMA_OVERRIDES[full_key])
            # Merge small categories
            entry["category"] = _CATEGORY_MERGE.get(
                entry["category"], entry["category"]
            )
            schema[full_key] = entry
    return schema


CONFIG_SCHEMA = _build_schema_from_config(DEFAULT_CONFIG)

# Inject virtual fields that don't live in DEFAULT_CONFIG but are surfaced
# by the normalize/denormalize cycle. Insert model-related virtual fields
# right after "model" so the frontend can render a coherent model editor.
_model_virtual_entries = [
    ("model_provider", _SCHEMA_OVERRIDES["model_provider"]),
    ("model_base_url", _SCHEMA_OVERRIDES["model_base_url"]),
    ("model_api_mode", _SCHEMA_OVERRIDES["model_api_mode"]),
    ("model_context_length", _SCHEMA_OVERRIDES["model_context_length"]),
]
_ordered_schema: Dict[str, Dict[str, Any]] = {}
for _k, _v in CONFIG_SCHEMA.items():
    _ordered_schema[_k] = _v
    if _k == "model":
        for _virtual_key, _virtual_entry in _model_virtual_entries:
            _ordered_schema[_virtual_key] = _virtual_entry
CONFIG_SCHEMA = _ordered_schema


class ConfigUpdate(BaseModel):
    config: dict


class EnvVarUpdate(BaseModel):
    key: str
    value: str


class EnvVarDelete(BaseModel):
    key: str


class EnvVarReveal(BaseModel):
    key: str


class AdminActionStart(BaseModel):
    args: Dict[str, Any] = {}
    confirm: bool = False


class GatewayControlRequest(BaseModel):
    action: str
    confirm: bool = False


class ProfileCreateRequest(BaseModel):
    name: str
    clone_from: Optional[str] = None
    clone_config: bool = False
    clone_all: bool = False
    no_alias: bool = True


class ProfileRenameRequest(BaseModel):
    new_name: str
    confirm: bool = False


class ProfileExportRequest(BaseModel):
    output_path: Optional[str] = None
    confirm: bool = False


class ProfileImportRequest(BaseModel):
    archive_path: str
    name: Optional[str] = None
    confirm: bool = False


class McpServerCreate(BaseModel):
    name: str
    url: Optional[str] = None
    command: Optional[str] = None
    args: List[str] = []
    env: Dict[str, str] = {}


class PluginActionRequest(BaseModel):
    name: str
    confirm: bool = False


class FeedbackSubmitBody(BaseModel):
    name: str = ""
    email: str = ""
    area: str = ""
    note: str


class AdminAction:
    def __init__(
        self,
        action_id: str,
        label: str,
        description: str,
        risk: str,
        command: Callable[[Dict[str, Any]], List[str]],
        *,
        requires_confirmation: bool = False,
        long_running: bool = False,
        args_schema: Optional[dict] = None,
        availability: Optional[Callable[[], tuple[bool, Optional[str]]]] = None,
    ):
        self.id = action_id
        self.label = label
        self.description = description
        self.risk = risk
        self.command = command
        self.requires_confirmation = requires_confirmation
        self.long_running = long_running
        self.args_schema = args_schema or {"type": "object", "properties": {}}
        self.availability = availability

    def to_metadata(self) -> dict:
        available = True
        reason = None
        if self.availability:
            available, reason = self.availability()
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "risk": self.risk,
            "requires_confirmation": self.requires_confirmation,
            "long_running": self.long_running,
            "args_schema": self.args_schema,
            "available": available,
            "unavailable_reason": reason,
        }


def _spark_command(*parts: str) -> List[str]:
    return [sys.executable, "-m", "spark_cli.main", *parts]


def _gateway_command(action: str) -> List[str]:
    return _spark_command("gateway", action)


def _update_command(check_only: bool) -> List[str]:
    try:
        from core.spark_constants import get_spark_home
        spark_home = get_spark_home()
        # Always clear the cache so we do a fresh git fetch, not a stale 6-hour result
        (spark_home / ".update_check").unlink(missing_ok=True)
        if not check_only:
            # Pre-write "y" so _gateway_prompt auto-accepts the "run installer?" question
            (spark_home / ".update_response").write_text("y")
    except Exception:
        pass
    if check_only:
        return _spark_command("version")
    return _spark_command("update", "--gateway")


def _debug_command(args: Dict[str, Any]) -> List[str]:
    lines = int(args.get("lines") or 200)
    lines = max(20, min(lines, 2000))
    return _spark_command("debug", "share", "--local", "--lines", str(lines))


ADMIN_ACTIONS: dict[str, AdminAction] = {
    "gateway.start": AdminAction(
        "gateway.start",
        "Start gateway",
        "Start the configured messaging gateway service.",
        "medium",
        lambda _args: _gateway_command("start"),
        requires_confirmation=True,
        long_running=True,
    ),
    "gateway.stop": AdminAction(
        "gateway.stop",
        "Stop gateway",
        "Stop the configured messaging gateway service.",
        "high",
        lambda _args: _gateway_command("stop"),
        requires_confirmation=True,
    ),
    "gateway.restart": AdminAction(
        "gateway.restart",
        "Restart gateway",
        "Restart the configured messaging gateway service.",
        "high",
        lambda _args: _gateway_command("restart"),
        requires_confirmation=True,
        long_running=True,
    ),
    "gateway.install": AdminAction(
        "gateway.install",
        "Install gateway service",
        "Install the OS service wrapper for the gateway.",
        "high",
        lambda _args: _gateway_command("install"),
        requires_confirmation=True,
        long_running=True,
    ),
    "gateway.uninstall": AdminAction(
        "gateway.uninstall",
        "Uninstall gateway service",
        "Remove the OS service wrapper for the gateway.",
        "high",
        lambda _args: _gateway_command("uninstall"),
        requires_confirmation=True,
    ),
    "gateway.status": AdminAction(
        "gateway.status",
        "Gateway service status",
        "Read foreground, runtime, and service status.",
        "low",
        lambda _args: _gateway_command("status"),
    ),
    "diagnostics.doctor": AdminAction(
        "diagnostics.doctor",
        "Run doctor",
        "Run Spark diagnostics and report configuration issues.",
        "low",
        lambda _args: _spark_command("doctor"),
    ),
    "diagnostics.doctor_fix": AdminAction(
        "diagnostics.doctor_fix",
        "Run doctor fix",
        "Run Spark doctor with repair mode where supported.",
        "medium",
        lambda _args: _spark_command("doctor", "--fix"),
        requires_confirmation=True,
    ),
    "diagnostics.debug": AdminAction(
        "diagnostics.debug",
        "Build debug report",
        "Generate a local debug preview with bounded log output.",
        "low",
        _debug_command,
        args_schema={
            "type": "object",
            "properties": {"lines": {"type": "integer", "minimum": 20, "maximum": 2000}},
        },
    ),
    "backup.quick": AdminAction(
        "backup.quick",
        "Quick backup",
        "Create a quick Spark backup.",
        "medium",
        lambda _args: _spark_command("backup", "--quick"),
        requires_confirmation=True,
        long_running=True,
    ),
    "backup.full": AdminAction(
        "backup.full",
        "Full backup",
        "Create a full Spark backup.",
        "medium",
        lambda _args: _spark_command("backup"),
        requires_confirmation=True,
        long_running=True,
    ),
    "update.check": AdminAction(
        "update.check",
        "Check for updates",
        "Check whether a Spark update is available.",
        "low",
        lambda _args: _update_command(True),
        long_running=True,
    ),
    "update.run": AdminAction(
        "update.run",
        "Run update",
        "Run Spark's update flow.",
        "high",
        lambda _args: _update_command(False),
        requires_confirmation=True,
        long_running=True,
    ),
}


def _new_admin_run(action_id: str, args: dict) -> tuple[str, thread_queue.Queue]:
    run_id = uuid.uuid4().hex
    queue: thread_queue.Queue = thread_queue.Queue(maxsize=512)
    _admin_runs[run_id] = {
        "run_id": run_id,
        "action_id": action_id,
        "args": args,
        "status": "queued",
        "started_at": None,
        "finished_at": None,
        "exit_code": None,
        "output_tail": [],
        "error": None,
    }
    _admin_run_queues[run_id] = queue
    return run_id, queue


def _queue_admin_event(run_id: str, event: dict) -> None:
    queue = _admin_run_queues.get(run_id)
    if queue is None:
        return
    try:
        queue.put_nowait(event)
    except Exception:
        pass


def _append_admin_output(run_id: str, stream: str, text: str) -> None:
    run = _admin_runs.get(run_id)
    if not run:
        return
    tail = run.setdefault("output_tail", [])
    tail.append({"stream": stream, "text": text, "ts": time.time()})
    del tail[:-200]


def _run_admin_action(run_id: str, action: AdminAction, args: dict) -> None:
    run = _admin_runs[run_id]
    run["status"] = "running"
    run["started_at"] = time.time()
    _queue_admin_event(run_id, {"type": "state", "status": "running"})
    try:
        cmd = action.command(args)
        _queue_admin_event(run_id, {"type": "output", "stream": "system", "text": " ".join(cmd)})
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        env["PYTHONUNBUFFERED"] = "1"
        proc = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        if proc.stdout is not None:
            for line in proc.stdout:
                text = line.rstrip("\n")
                _append_admin_output(run_id, "stdout", text)
                _queue_admin_event(run_id, {"type": "output", "stream": "stdout", "text": text})
        exit_code = proc.wait()
        run["exit_code"] = exit_code
        run["status"] = "done" if exit_code == 0 else "failed"
    except Exception as exc:
        run["status"] = "failed"
        run["error"] = str(exc)
        _queue_admin_event(run_id, {"type": "output", "stream": "stderr", "text": str(exc)})
    finally:
        run["finished_at"] = time.time()
        _queue_admin_event(run_id, {"type": "done", "run": run})


def _profile_info_dict(info: Any, active: str) -> dict:
    return {
        "name": info.name,
        "path": str(info.path),
        "is_default": info.is_default,
        "is_active": info.name == active,
        "gateway_running": info.gateway_running,
        "model": info.model,
        "provider": info.provider,
        "has_env": info.has_env,
        "skill_count": info.skill_count,
        "alias_path": str(info.alias_path) if info.alias_path else None,
    }


def _list_plugin_dirs() -> list[dict]:
    plugins_dir = get_spark_home() / "plugins"
    rows: list[dict] = []
    if not plugins_dir.is_dir():
        return rows
    for entry in sorted(plugins_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        manifest = entry / "plugin.json"
        data: dict = {}
        if manifest.exists():
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        rows.append(
            {
                "name": data.get("name") or entry.name,
                "id": data.get("id") or entry.name,
                "path": str(entry),
                "description": data.get("description"),
                "version": data.get("version"),
                "enabled": not (entry / ".disabled").exists(),
            }
        )
    return rows


def _configured_gateway_platforms() -> list[dict]:
    try:
        from gateway.config import load_gateway_config

        gateway_config = load_gateway_config()
        return [
            {
                "id": platform_cfg.value,
                "configured": True,
            }
            for platform_cfg in gateway_config.get_connected_platforms()
        ]
    except Exception:
        return []


@app.get("/api/status")
async def get_status():
    current_ver, latest_ver = check_config_version()

    gateway_pid = get_running_pid()
    gateway_running = gateway_pid is not None

    gateway_state = None
    gateway_platforms: dict = {}
    gateway_exit_reason = None
    gateway_updated_at = None
    configured_gateway_platforms: set[str] | None = None
    try:
        from gateway.config import load_gateway_config

        gateway_config = load_gateway_config()
        configured_gateway_platforms = {
            platform.value for platform in gateway_config.get_connected_platforms()
        }
    except Exception:
        configured_gateway_platforms = None

    runtime = read_runtime_status()
    if runtime:
        gateway_state = runtime.get("gateway_state")
        gateway_platforms = runtime.get("platforms") or {}
        if configured_gateway_platforms is not None:
            gateway_platforms = {
                key: value
                for key, value in gateway_platforms.items()
                if key in configured_gateway_platforms
            }
        gateway_exit_reason = runtime.get("exit_reason")
        gateway_updated_at = runtime.get("updated_at")
        if not gateway_running:
            gateway_state = (
                gateway_state
                if gateway_state in ("stopped", "startup_failed")
                else "stopped"
            )
            gateway_platforms = {}

    active_sessions = 0
    try:
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            sessions = db.list_sessions_rich(limit=50)
            now = time.time()
            active_sessions = sum(
                1
                for s in sessions
                if s.get("ended_at") is None
                and (now - s.get("last_active", s.get("started_at", 0))) < 300
            )
        finally:
            db.close()
    except Exception:
        pass

    spark_cfg = load_config()
    _dash = spark_cfg.get("dashboard") if isinstance(spark_cfg, dict) else {}
    if not isinstance(_dash, dict):
        _dash = {}

    # Read cached update result — never blocks (no git fetch)
    commits_behind: int | None = None
    try:
        import json as _json
        _cache = get_spark_home() / ".update_check"
        if _cache.exists():
            _data = _json.loads(_cache.read_text())
            commits_behind = _data.get("behind")
    except Exception:
        pass

    return {
        "server_instance_id": _SERVER_INSTANCE_ID,
        "version": __version__,
        "release_date": __release_date__,
        "spark_home": str(get_spark_home()),
        "config_path": str(get_config_path()),
        "env_path": str(get_env_path()),
        "config_version": current_ver,
        "latest_config_version": latest_ver,
        "gateway_running": gateway_running,
        "gateway_pid": gateway_pid,
        "gateway_state": gateway_state,
        "gateway_platforms": gateway_platforms,
        "gateway_exit_reason": gateway_exit_reason,
        "gateway_updated_at": gateway_updated_at,
        "active_sessions": active_sessions,
        "commits_behind": commits_behind,
        "update_available": bool(commits_behind and commits_behind > 0),
        "desktop": _is_desktop_app(),
        "desktop_version": _desktop_app_version(),
        "mac_update_available": bool(
            _is_desktop_app()
            and _mac_update_cache.get("result")
            and _mac_update_cache["result"].get("update_available")
        ),
        "mac_latest_version": (
            (_mac_update_cache.get("result") or {}).get("latest_version")
            if _is_desktop_app()
            else None
        ),
        "dashboard_auth": {
            "token_file": str(dashboard_token_path()),
            "require_auth_nonlocal": bool(_dash.get("require_auth_nonlocal", True)),
        },
        "dashboard_features": {
            "subagents_sidebar": bool(_dash.get("subagents_sidebar", True)),
        },
    }


@app.get("/api/update/check")
async def check_update_available():
    """Check whether a Spark update is available (commits behind origin/main)."""
    import asyncio

    try:
        from spark_cli.banner import check_for_updates

        loop = asyncio.get_event_loop()
        behind = await loop.run_in_executor(None, check_for_updates)
        return {
            "update_available": bool(behind and behind > 0),
            "commits_behind": behind,
        }
    except Exception:
        return {"update_available": False, "commits_behind": None}


# --------------------------------------------------------------------------- #
# macOS desktop app updates (separate from the webapp/code update above)       #
#                                                                              #
# The webapp/code update (`/api/update/*`, `update.run`) pulls the latest      #
# Spark source and reinstalls in place. That does NOT update the bundled       #
# macOS .app shell, which ships as a signed DMG via GitHub Releases. The mac    #
# update flow below checks GitHub Releases for a newer DMG and installs it.    #
# --------------------------------------------------------------------------- #

GITHUB_REPO = "automatedigital/spark"
_mac_update_cache: dict[str, Any] = {"checked_at": 0.0, "result": None}
MAC_APP_BUNDLE_ID = "studio.fromtheroot.spark"
MAC_APP_INSTALL_PATH = Path("/Applications/Spark.app")


def _is_desktop_app() -> bool:
    """True when running as the bundled macOS desktop sidecar."""
    return os.environ.get("SPARK_DESKTOP") == "1"


def _desktop_app_version() -> str | None:
    """Version of the running .app shell, injected by Tauri at spawn time."""
    return os.environ.get("SPARK_DESKTOP_VERSION") or None


def _parse_version(tag: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", tag or "")
    return tuple(int(n) for n in nums) if nums else (0,)


def _fetch_latest_mac_release(timeout: float = 8.0) -> dict | None:
    """Query GitHub Releases for the latest tag and its .dmg asset."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "spark-desktop"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode())
    download_url = None
    for asset in data.get("assets", []) or []:
        if str(asset.get("name", "")).lower().endswith(".dmg"):
            download_url = asset.get("browser_download_url")
            break
    return {
        "tag": data.get("tag_name") or data.get("name") or "",
        "download_url": download_url,
        "release_url": data.get("html_url"),
        # Markdown release notes, shown as the changelog in the update modal (§3.3).
        "release_notes": (data.get("body") or "").strip() or None,
        "release_name": data.get("name") or None,
        "published_at": data.get("published_at"),
    }


def _check_mac_update(force: bool = False) -> dict:
    """Compare the running app version against the latest GitHub release."""
    current = _desktop_app_version()
    result = {
        "update_available": False,
        "latest_version": None,
        "current_version": current,
        "download_url": None,
        "release_url": None,
        "release_notes": None,
        "release_name": None,
        "published_at": None,
    }
    now = time.time()
    if (
        not force
        and _mac_update_cache["result"] is not None
        and (now - _mac_update_cache["checked_at"]) < 21600
    ):
        return _mac_update_cache["result"]
    try:
        rel = _fetch_latest_mac_release()
    except Exception:
        return result
    if not rel:
        return result
    latest = rel.get("tag") or ""
    result["latest_version"] = latest.lstrip("v") or None
    result["download_url"] = rel.get("download_url")
    result["release_url"] = rel.get("release_url")
    result["release_notes"] = rel.get("release_notes")
    result["release_name"] = rel.get("release_name")
    result["published_at"] = rel.get("published_at")
    if current and result["latest_version"]:
        result["update_available"] = _parse_version(result["latest_version"]) > _parse_version(current)
    _mac_update_cache.update(checked_at=now, result=result)
    return result


def _shell_quote(value: str | Path) -> str:
    import shlex

    return shlex.quote(str(value))


def _build_mac_update_installer_script(
    *,
    dmg_path: Path,
    work_dir: Path,
    log_path: Path,
    install_path: Path = MAC_APP_INSTALL_PATH,
    bundle_id: str = MAC_APP_BUNDLE_ID,
) -> str:
    """Build a detached macOS installer script for the downloaded Spark DMG."""

    staged_app = work_dir / "Spark.app"
    mount_dir = work_dir / "mount"
    script_path = work_dir / "install-spark-update.zsh"
    tmp_install_path = install_path.with_name(f"{install_path.name}.tmp")
    backup_path = install_path.with_name(f"{install_path.name}.previous")
    privileged_install_cmd = f"{_shell_quote(script_path)} --install-only".replace("\\", "\\\\").replace('"', '\\"')

    return f"""#!/bin/zsh
set -euo pipefail

DMG={_shell_quote(dmg_path)}
WORK_DIR={_shell_quote(work_dir)}
MOUNT_DIR={_shell_quote(mount_dir)}
STAGED_APP={_shell_quote(staged_app)}
INSTALL_PATH={_shell_quote(install_path)}
LOG_PATH={_shell_quote(log_path)}
BUNDLE_ID={_shell_quote(bundle_id)}
TMP_INSTALL_PATH={_shell_quote(tmp_install_path)}
BACKUP_PATH={_shell_quote(backup_path)}

log() {{
  /bin/mkdir -p "$(/usr/bin/dirname "$LOG_PATH")"
  /bin/echo "[$(/bin/date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_PATH"
}}

cleanup() {{
  if /sbin/mount | /usr/bin/grep -q "on $MOUNT_DIR "; then
    /usr/bin/hdiutil detach "$MOUNT_DIR" -quiet || true
  fi
}}
trap cleanup EXIT

perform_install() {{
  /bin/rm -rf "$TMP_INSTALL_PATH"
  /usr/bin/ditto "$STAGED_APP" "$TMP_INSTALL_PATH"
  /bin/rm -rf "$BACKUP_PATH"

  if [ -d "$INSTALL_PATH" ]; then
    /bin/mv "$INSTALL_PATH" "$BACKUP_PATH"
  fi

  if ! /bin/mv "$TMP_INSTALL_PATH" "$INSTALL_PATH"; then
    log "Replacement move failed; restoring previous app"
    if [ -d "$BACKUP_PATH" ] && [ ! -d "$INSTALL_PATH" ]; then
      /bin/mv "$BACKUP_PATH" "$INSTALL_PATH" || true
    fi
    return 1
  fi

  /bin/rm -rf "$BACKUP_PATH"
}}

if [ "${{1:-}}" = "--install-only" ]; then
  perform_install >> "$LOG_PATH" 2>&1
  exit $?
fi

log "Starting Spark desktop update install"
/bin/mkdir -p "$MOUNT_DIR"
/usr/bin/hdiutil attach -nobrowse -readonly -mountpoint "$MOUNT_DIR" "$DMG" >> "$LOG_PATH" 2>&1

SOURCE_APP="$(/usr/bin/find "$MOUNT_DIR" -maxdepth 2 -type d -name 'Spark.app' -print -quit)"
if [ -z "$SOURCE_APP" ]; then
  log "No Spark.app found in release DMG"
  exit 2
fi

FOUND_BUNDLE_ID="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$SOURCE_APP/Contents/Info.plist" 2>/dev/null || true)"
if [ "$FOUND_BUNDLE_ID" != "$BUNDLE_ID" ]; then
  log "Unexpected bundle id: $FOUND_BUNDLE_ID"
  exit 3
fi

/bin/rm -rf "$STAGED_APP"
/usr/bin/ditto "$SOURCE_APP" "$STAGED_APP" >> "$LOG_PATH" 2>&1
cleanup

/usr/bin/osascript -e 'tell application id "{bundle_id}" to quit' >> "$LOG_PATH" 2>&1 || true
for _ in {{1..30}}; do
  if ! /usr/bin/pgrep -x Spark >/dev/null 2>&1; then
    break
  fi
  /bin/sleep 1
done

log "Installing Spark.app into Applications"
if ! perform_install >> "$LOG_PATH" 2>&1; then
  log "Direct install failed; requesting administrator privileges"
  /usr/bin/osascript -e "do shell script \\"{privileged_install_cmd}\\" with administrator privileges" >> "$LOG_PATH" 2>&1
fi

/usr/bin/xattr -cr "$INSTALL_PATH" >> "$LOG_PATH" 2>&1 || true
/usr/bin/open "$INSTALL_PATH" >> "$LOG_PATH" 2>&1 || true
log "Spark desktop update install finished"
"""


@app.get("/api/mac/update/check")
async def check_mac_update():
    """Check whether a newer macOS desktop app release is available."""
    if not _is_desktop_app():
        return {
            "update_available": False,
            "latest_version": None,
            "current_version": None,
            "download_url": None,
            "release_url": None,
        }
    return await asyncio.to_thread(_check_mac_update, True)


@app.post("/api/mac/update/run")
async def run_mac_update():
    """Download the latest macOS DMG and start a detached automatic installer."""
    if not _is_desktop_app():
        raise HTTPException(status_code=400, detail="Not running as the macOS desktop app")
    info = await asyncio.to_thread(_check_mac_update, True)
    download_url = info.get("download_url")
    if not download_url:
        raise HTTPException(status_code=400, detail="No downloadable macOS release found")

    work_dir = Path(tempfile.mkdtemp(prefix="spark-mac-update-"))
    dest = work_dir / f"Spark-{info.get('latest_version') or 'latest'}.dmg"
    script_path = work_dir / "install-spark-update.zsh"
    log_path = work_dir / "install.log"

    def _download_and_start_installer() -> None:
        urllib.request.urlretrieve(download_url, dest)
        script_path.write_text(
            _build_mac_update_installer_script(
                dmg_path=dest,
                work_dir=work_dir,
                log_path=log_path,
            )
        )
        script_path.chmod(0o700)
        with log_path.open("ab") as log_file:
            subprocess.Popen(
                ["/bin/zsh", str(script_path)],
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )

    try:
        await asyncio.to_thread(_download_and_start_installer)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to start macOS update installer: {exc}") from exc
    return {
        "ok": True,
        "path": str(dest),
        "installer_script": str(script_path),
        "log_path": str(log_path),
        "latest_version": info.get("latest_version"),
        "status": "installing",
    }


@app.get("/api/admin/actions")
async def admin_actions():
    """Return bounded admin actions available to the dashboard."""
    return {"ok": True, "actions": [a.to_metadata() for a in ADMIN_ACTIONS.values()]}


@app.post("/api/admin/actions/{action_id}")
async def start_admin_action(action_id: str, payload: AdminActionStart):
    action = ADMIN_ACTIONS.get(action_id)
    if action is None:
        raise HTTPException(status_code=404, detail=f"Unknown admin action: {action_id}")
    meta = action.to_metadata()
    if not meta["available"]:
        raise HTTPException(status_code=400, detail=meta["unavailable_reason"] or "Action unavailable")
    if action.requires_confirmation and not payload.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required")
    run_id, _queue = _new_admin_run(action_id, payload.args or {})
    threading.Thread(target=_run_admin_action, args=(run_id, action, payload.args or {}), daemon=True).start()
    return {"run_id": run_id, "status": "queued"}


@app.get("/api/admin/actions/runs/{run_id}")
async def get_admin_action_run(run_id: str):
    run = _admin_runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@app.get("/api/admin/actions/runs/{run_id}/stream")
async def stream_admin_action_run(request: Request, run_id: str):
    from fastapi.responses import StreamingResponse as _StreamingResponse

    run = _admin_runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    queue = _admin_run_queues.get(run_id)
    if queue is None:
        queue = thread_queue.Queue(maxsize=512)
        _admin_run_queues[run_id] = queue

    async def event_generator():
        yield f"data: {json.dumps({'type': 'state', 'status': run.get('status')})}\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.to_thread(queue.get, True, 20)
                except thread_queue.Empty:
                    yield "event: ping\ndata: {}\n\n"
                    if run.get("status") in ("done", "failed"):
                        break
                    continue
                yield f"data: {json.dumps(event, default=str)}\n\n"
                if event.get("type") == "done":
                    break
        finally:
            if run.get("status") in ("done", "failed"):
                _admin_run_queues.pop(run_id, None)

    return _StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/gateway/status")
async def gateway_admin_status():
    runtime = read_runtime_status() or {}
    pid = get_running_pid()
    return {
        "ok": True,
        "running": pid is not None,
        "pid": pid,
        "runtime": runtime,
        "platforms": runtime.get("platforms") or {},
        "configured_platforms": _configured_gateway_platforms(),
        "service_system": platform.system(),
        "last_error": runtime.get("last_startup_error") or runtime.get("exit_reason"),
        "state": runtime.get("gateway_state") if pid is not None else "stopped",
    }


@app.post("/api/gateway/control")
async def gateway_control(payload: GatewayControlRequest):
    action_id = f"gateway.{payload.action}"
    action = ADMIN_ACTIONS.get(action_id)
    if action is None:
        raise HTTPException(status_code=400, detail=f"Unsupported gateway action: {payload.action}")
    if action.requires_confirmation and not payload.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required")
    run_id, _queue = _new_admin_run(action_id, {})
    threading.Thread(target=_run_admin_action, args=(run_id, action, {}), daemon=True).start()
    return {"run_id": run_id, "status": "queued"}


@app.get("/api/profiles")
async def profiles_list():
    from spark_cli.profiles import get_active_profile, list_profiles

    active = get_active_profile()
    return {"ok": True, "active": active, "profiles": [_profile_info_dict(p, active) for p in list_profiles()]}


@app.post("/api/profiles")
async def profiles_create(payload: ProfileCreateRequest):
    from spark_cli.profiles import create_profile, get_active_profile, list_profiles

    try:
        path = create_profile(
            payload.name,
            clone_from=payload.clone_from,
            clone_config=payload.clone_config,
            clone_all=payload.clone_all,
            no_alias=payload.no_alias,
        )
    except (ValueError, FileExistsError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    active = get_active_profile()
    return {
        "ok": True,
        "path": str(path),
        "profiles": [_profile_info_dict(p, active) for p in list_profiles()],
    }


@app.post("/api/profiles/{name}/use")
async def profiles_use(name: str):
    from spark_cli.profiles import set_active_profile

    try:
        set_active_profile(name)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "active": name}


@app.post("/api/profiles/{name}/rename")
async def profiles_rename(name: str, payload: ProfileRenameRequest):
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required")
    from spark_cli.profiles import rename_profile

    try:
        path = rename_profile(name, payload.new_name)
    except (ValueError, FileExistsError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "path": str(path), "name": payload.new_name}


@app.delete("/api/profiles/{name}")
async def profiles_delete(name: str, confirm: bool = False):
    if not confirm:
        raise HTTPException(status_code=400, detail="Confirmation required")
    from spark_cli.profiles import delete_profile

    try:
        path = delete_profile(name, yes=True)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "path": str(path)}


@app.post("/api/profiles/{name}/export")
async def profiles_export(name: str, payload: ProfileExportRequest):
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required")
    from spark_cli.profiles import export_profile

    output = payload.output_path or str(get_spark_home() / "backups" / f"profile-{name}-{int(time.time())}.tar.gz")
    try:
        path = export_profile(name, output)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "path": str(path)}


@app.post("/api/profiles/import")
async def profiles_import(payload: ProfileImportRequest):
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required")
    from spark_cli.profiles import import_profile

    try:
        path = import_profile(payload.archive_path, payload.name)
    except (ValueError, FileExistsError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "path": str(path)}


@app.get("/api/plugins")
async def plugins_list():
    return {"ok": True, "plugins": _list_plugin_dirs()}


@app.post("/api/plugins/{action}")
async def plugins_action(action: str, payload: PluginActionRequest):
    if action not in {"install", "update", "remove", "enable", "disable"}:
        raise HTTPException(status_code=400, detail=f"Unsupported plugin action: {action}")
    if action in {"install", "update", "remove"} and not payload.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required")
    action_id = f"plugins.{action}.{uuid.uuid4().hex[:8]}"
    command = _spark_command("plugins", action, payload.name)
    run_id, _queue = _new_admin_run(action_id, {"name": payload.name})
    _admin_runs[run_id]["action_id"] = action_id
    temp_action = AdminAction(action_id, f"Plugin {action}", f"Run plugin {action}.", "medium", lambda _args: command)
    threading.Thread(target=_run_admin_action, args=(run_id, temp_action, {"name": payload.name}), daemon=True).start()
    return {"run_id": run_id, "status": "queued"}


@app.get("/api/mcp/servers")
async def mcp_servers_list():
    from spark_cli.mcp_config import _get_mcp_servers

    return {"ok": True, "servers": _get_mcp_servers()}


@app.post("/api/mcp/servers")
async def mcp_servers_create(payload: McpServerCreate):
    from spark_cli.mcp_config import _save_mcp_server

    if not payload.url and not payload.command:
        raise HTTPException(status_code=400, detail="Provide url or command")
    server: dict[str, Any] = {}
    if payload.url:
        server["url"] = payload.url
    if payload.command:
        server["command"] = payload.command
    if payload.args:
        server["args"] = payload.args
    if payload.env:
        server["env"] = payload.env
    try:
        _save_mcp_server(payload.name, server)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "name": payload.name, "server": server}


@app.delete("/api/mcp/servers/{name}")
async def mcp_servers_delete(name: str, confirm: bool = False):
    if not confirm:
        raise HTTPException(status_code=400, detail="Confirmation required")
    from spark_cli.mcp_config import _remove_mcp_server

    if not _remove_mcp_server(name):
        raise HTTPException(status_code=404, detail="MCP server not found")
    return {"ok": True}


@app.post("/api/mcp/servers/{name}/test")
async def mcp_servers_test(name: str):
    from spark_cli.mcp_config import _get_mcp_servers

    servers = _get_mcp_servers()
    if name not in servers:
        raise HTTPException(status_code=404, detail="MCP server not found")
    command = _spark_command("mcp", "test", name)
    action_id = f"mcp.test.{name}"
    run_id, _queue = _new_admin_run(action_id, {"name": name})
    temp_action = AdminAction(action_id, "Test MCP server", "Probe one MCP server.", "low", lambda _args: command)
    threading.Thread(target=_run_admin_action, args=(run_id, temp_action, {"name": name}), daemon=True).start()
    return {"run_id": run_id, "status": "queued"}


@app.get("/api/diagnostics/summary")
async def diagnostics_summary():
    cfg = load_config()
    env = load_env()
    missing_required: list[str] = []
    for key, meta in OPTIONAL_ENV_VARS.items():
        if meta.get("required") and not env.get(key):
            missing_required.append(key)
    return {
        "ok": True,
        "spark_home": str(get_spark_home()),
        "config_path": str(get_config_path()),
        "env_path": str(get_env_path()),
        "config_version": cfg.get("_config_version") if isinstance(cfg, dict) else None,
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "missing_required_env": missing_required,
        "gateway_running": get_running_pid() is not None,
        "dashboard_auth": {
            "token_file": str(dashboard_token_path()),
            "configured": bool(get_configured_dashboard_secret()),
        },
        "actions": [a.to_metadata() for a in ADMIN_ACTIONS.values()],
    }


@app.get("/api/diagnostics/webview")
async def diagnostics_webview(
    active_session_id: Optional[str] = None,
    safe_mode: Optional[bool] = None,
    recent_long_task_count: Optional[int] = None,
    connection_mode: Optional[str] = None,
):
    """Runtime diagnostics for the desktop/web chat shell.

    The browser owns safe-mode and long-task state, so callers can pass those
    values as query params when collecting a complete diagnostic snapshot.
    """
    candidates = {active_session_id} if active_session_id else set()
    if active_session_id:
        try:
            from core.spark_state import SessionDB

            db = SessionDB()
            try:
                sid = db.resolve_session_id(active_session_id)
                if sid:
                    candidates.add(sid)
                    latest = db.resolve_latest_descendant(sid)
                    if latest:
                        candidates.add(latest)
            finally:
                db.close()
        except Exception:
            _log.debug("diagnostic session resolution failed session=%s", active_session_id, exc_info=True)

    active_turn = any(_is_web_turn_active(sid) for sid in candidates if sid)
    return {
        "ok": True,
        "sidecar_pid": os.getpid(),
        "desktop": _is_desktop_app(),
        "desktop_version": _desktop_app_version(),
        "active_session_id": active_session_id,
        "active_turn": active_turn,
        "safe_mode": safe_mode,
        "recent_long_task_count": recent_long_task_count,
        "connection_mode": connection_mode,
        "activity_monitor_process_name_note": (
            "Spark desktop is a Tauri shell that navigates its main webview to "
            "the local sidecar at http://127.0.0.1:9119, so macOS may show the "
            "webview page URL rather than the Spark app name for the busy renderer."
        ),
    }


@app.get("/api/dashboard/auth/info")
async def dashboard_auth_info():
    """Public metadata for wiring LAN clients (no secrets in response body)."""
    cfg = load_config()
    dash = cfg.get("dashboard") if isinstance(cfg, dict) else {}
    if not isinstance(dash, dict):
        dash = {}
    return {
        "require_auth_nonlocal": bool(dash.get("require_auth_nonlocal", True)),
        "token_file": str(dashboard_token_path()),
        "hint": "Use Authorization: Bearer <token>, or ?dashboard_token= for SSE. "
        "Token is stored in token_file or SPARK_DASHBOARD_TOKEN.",
    }


def _reveal_authorized(request: Request) -> bool:
    auth = request.headers.get("authorization", "")
    if auth == f"Bearer {_SESSION_TOKEN}":
        return True
    secret = get_configured_dashboard_secret()
    if not secret:
        secret = ensure_dashboard_token_file()
    client_host = request.client.host if request.client else None
    qtoken = request.query_params.get("dashboard_token")
    return validate_dashboard_request(
        client_host,
        auth,
        require_for_remote=True,
        secret=secret,
        query_token=qtoken,
    )


def _secret_reveal_authorized(request: Request) -> bool:
    """Strict auth gate for endpoints that return *plaintext secrets*.

    Unlike :func:`_reveal_authorized`, this does **not** grant a loopback /
    trusted-local bypass: revealing an unredacted env var always requires the
    ephemeral per-process session token (injected into the SPA) or a valid
    configured dashboard token. A local TCP peer alone is not sufficient.
    """
    auth = request.headers.get("authorization", "")
    if _SESSION_TOKEN and auth == f"Bearer {_SESSION_TOKEN}":
        return True
    secret = get_configured_dashboard_secret()
    if not secret:
        secret = ensure_dashboard_token_file()
    if not secret:
        return False
    token = extract_bearer_token(auth) or (request.query_params.get("dashboard_token") or "").strip() or None
    return bool(token and secrets.compare_digest(token, secret))


@app.get("/api/sessions")
async def get_sessions(limit: int = 20, offset: int = 0, source: Optional[str] = None):
    try:
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            sessions = db.list_sessions_rich(
                source=source,
                limit=limit,
                offset=offset,
                include_children=False,
            )
            total = db.session_count(source=source, include_children=False)
            now = time.time()
            for s in sessions:
                s["is_active"] = (
                    s.get("ended_at") is None
                    and (now - s.get("last_active", s.get("started_at", 0))) < 300
                )
            return {
                "sessions": sessions,
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        finally:
            db.close()
    except Exception:
        _log.exception("GET /api/sessions failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/sessions/search")
async def search_sessions(q: str = "", limit: int = 20, source: Optional[str] = None):
    """Full-text search across session message content using FTS5."""
    if not q or not q.strip():
        return {"results": []}
    try:
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            # Auto-add prefix wildcards so partial words match
            # e.g. "nimb" → "nimb*" matches "nimby"
            # Preserve quoted phrases and existing wildcards as-is
            import re

            terms = []
            for token in re.findall(r'"[^"]*"|\S+', q.strip()):
                if token.startswith('"') or token.endswith("*"):
                    terms.append(token)
                else:
                    terms.append(token + "*")
            prefix_query = " ".join(terms)
            source_filter = [source] if source else None
            matches = db.search_messages(query=prefix_query, source_filter=source_filter, limit=limit)
            # Group by session_id — return unique sessions with their best snippet
            seen: dict = {}
            for m in matches:
                sid = m["session_id"]
                if sid not in seen:
                    seen[sid] = {
                        "session_id": sid,
                        "snippet": m.get("snippet", ""),
                        "role": m.get("role"),
                        "source": m.get("source"),
                        "model": m.get("model"),
                        "session_started": m.get("session_started"),
                    }
            return {"results": list(seen.values())}
        finally:
            db.close()
    except Exception:
        _log.exception("GET /api/sessions/search failed")
        raise HTTPException(status_code=500, detail="Search failed")


def _normalize_config_for_web(config: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize config for the web UI.

    Spark supports ``model`` as either a bare string (``"anthropic/claude-sonnet-4"``)
    or a dict (``{default: ..., provider: ..., base_url: ...}``).  The schema is built
    from DEFAULT_CONFIG where ``model`` is a string, but user configs often have the
    dict form.  Normalize to the string form so the frontend schema matches.

    Also surfaces ``model_context_length`` as a top-level field so the web UI can
    display and edit it.  A value of 0 means "auto-detect".
    """
    config = dict(config)  # shallow copy
    model_val = config.get("model")
    if isinstance(model_val, dict):
        # Extract context_length before flattening the dict
        ctx_len = model_val.get("context_length", 0)
        config["model"] = model_val.get("default", model_val.get("name", ""))
        config["model_provider"] = model_val.get("provider", "")
        config["model_base_url"] = model_val.get("base_url", "")
        config["model_api_mode"] = model_val.get("api_mode", "")
        config["model_context_length"] = ctx_len if isinstance(ctx_len, int) else 0
    else:
        config["model_provider"] = ""
        config["model_base_url"] = ""
        config["model_api_mode"] = ""
        config["model_context_length"] = 0
    return config


@app.get("/api/config")
async def get_config():
    config = _normalize_config_for_web(load_config())
    # Strip internal keys that the frontend shouldn't see or send back
    return {k: v for k, v in config.items() if not k.startswith("_")}


@app.get("/api/onboarding/status")
async def get_onboarding_status():
    """First-run detection for the desktop onboarding wizard.

    ``needs_onboarding`` is true when no config.yaml exists yet, or when
    ``model.provider`` is unset/empty.
    """
    config_exists = get_config_path().exists()

    config = load_config() if config_exists else {}
    model = config.get("model") if isinstance(config, dict) else {}
    if not isinstance(model, dict):
        model = {}
    provider = (model.get("provider") or "").strip()
    has_model = bool(provider)

    env_on_disk = load_env()
    has_api_key = any(
        bool(env_on_disk.get(var_name))
        for var_name in ("OPENAI_API_KEY", "GOOGLE_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY")
    )

    return {
        "needs_onboarding": (not config_exists) or (not has_model),
        "has_model": has_model,
        "has_api_key": has_api_key,
    }


# Skill names seeded for the "minimal" onboarding choice.
_MINIMAL_SKILLS = {"find-skills", "codebase-inspection", "frontend-design", "excalidraw", "claude-code"}


class OnboardingSkillsRequest(BaseModel):
    mode: str  # "recommended" | "minimal" | "none"


@app.post("/api/onboarding/skills")
async def setup_onboarding_skills(req: OnboardingSkillsRequest):
    """Seed the user's skills directory according to their onboarding choice.

    - ``recommended``: seed all bundled Spark skills.
    - ``minimal``: seed a small curated subset.
    - ``none``: seed nothing (blank slate; Spark creates skills over time).

    The choice is persisted under ``skills.onboarding_mode`` in config.
    """
    mode = (req.mode or "").strip().lower()
    if mode not in {"recommended", "minimal", "none"}:
        raise HTTPException(status_code=400, detail=f"Unknown skills mode: {mode}")

    result: dict = {"copied": [], "total_bundled": 0}
    if mode in {"recommended", "minimal"}:
        from tools.skills_sync import sync_skills

        only = _MINIMAL_SKILLS if mode == "minimal" else None
        result = await asyncio.to_thread(sync_skills, True, only)

    # Persist the choice so re-running setup / diagnostics knows the intent.
    try:
        cfg = load_config()
        if isinstance(cfg, dict):
            skills_cfg = dict(cfg.get("skills") or {})
            skills_cfg["onboarding_mode"] = mode
            cfg["skills"] = skills_cfg
            save_config(cfg)
    except Exception:
        pass

    return {
        "ok": True,
        "mode": mode,
        "seeded": len(result.get("copied", [])),
        "total_bundled": result.get("total_bundled", 0),
    }


class OpenExternalRequest(BaseModel):
    url: str


@app.post("/api/system/open-external")
async def open_external(req: OpenExternalRequest):
    """Open a URL in the user's default browser.

    Only acts when running as the local desktop sidecar (SPARK_DESKTOP=1) —
    in the Tauri webview, window.open()/<a target=_blank> are no-ops, so the
    frontend asks the backend to open the URL via the OS. Returns
    ``{opened: false}`` otherwise so the web client falls back to window.open.
    """
    url = (req.url or "").strip()
    if not (url.startswith("https://") or url.startswith("http://")):
        raise HTTPException(status_code=400, detail="Only http(s) URLs allowed")
    if not os.environ.get("SPARK_DESKTOP"):
        return {"opened": False}
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", url])
        elif sys.platform.startswith("win"):
            os.startfile(url)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", url])
        return {"opened": True}
    except Exception as exc:  # noqa: BLE001
        return {"opened": False, "error": str(exc)}


@app.get("/api/config/defaults")
async def get_defaults():
    return DEFAULT_CONFIG


@app.get("/api/config/schema")
async def get_schema():
    schema = dict(CONFIG_SCHEMA)
    try:
        from spark_cli.config import load_config
        cfg = load_config()
        model_cfg = cfg.get("model", {})
        if isinstance(model_cfg, dict):
            main_model = str(model_cfg.get("default", "") or "").strip()
            main_provider = str(model_cfg.get("provider", "") or "").strip()
            if main_model and "delegation.model" in schema:
                schema["delegation.model"] = {**schema["delegation.model"], "placeholder": main_model}
            if main_provider and "delegation.provider" in schema:
                schema["delegation.provider"] = {**schema["delegation.provider"], "placeholder": main_provider}
    except Exception:
        pass
    return {"fields": schema, "category_order": _CATEGORY_ORDER}


_EMPTY_MODEL_INFO: dict = {
    "model": "",
    "provider": "",
    "auto_context_length": 0,
    "config_context_length": 0,
    "effective_context_length": 0,
    "capabilities": {},
}


@app.get("/api/model/codex-usage")
def get_codex_usage():
    """Return Codex provider status and any captured usage-limit state.

    The ChatGPT backend ``usage_limits`` endpoint is Cloudflare-protected and
    requires browser session cookies — it cannot be called server-side with the
    Codex OAuth token.  The Codex Responses API also does not return
    x-ratelimit-* headers.  Instead, this endpoint surfaces:

    1. ``provider_connected`` — whether the provider is openai-codex and the
       user is authenticated (always available when Codex is configured).
    2. ``limit_hit`` — non-null when a ``usage_limit_reached`` error was
       detected during a recent inference turn, including reset info.
    3. ``rate_limit`` — the last x-ratelimit-* state from any active web agent,
       if the provider returned those headers (most non-Codex providers do).
    """
    try:
        cfg = load_config()
        model_cfg = cfg.get("model", "")
        if isinstance(model_cfg, dict):
            provider = str(model_cfg.get("provider", "") or "").strip()
        else:
            provider = ""

        if provider != "openai-codex":
            return {"available": False, "reason": "not_codex_provider"}

        from spark_cli.auth import get_codex_auth_status

        status = get_codex_auth_status()
        if not status.get("logged_in"):
            return {"available": False, "reason": "not_authenticated"}

        # Resolve active model name for display
        active_model = ""
        try:
            if isinstance(model_cfg, dict):
                active_model = str(model_cfg.get("default", model_cfg.get("name", "")) or "").strip()
            else:
                active_model = str(model_cfg or "").strip()
            if active_model:
                active_model = active_model.replace("-", " ").title().replace(" ", "-").replace("Gpt", "GPT")
        except Exception:
            pass

        # Fetch live usage from the wham/usage endpoint (discovered via CodexBar)
        # Requires the ChatGPT-Account-Id header extracted from the JWT claims.
        try:
            import httpx as _httpx
            import base64 as _base64

            access_token = status.get("api_key", "")
            # Extract chatgpt_account_id from JWT payload
            account_id = ""
            try:
                parts = access_token.split(".")
                if len(parts) >= 2:
                    padded = parts[1] + "=" * (-len(parts[1]) % 4)
                    jwt_claims = __import__("json").loads(_base64.urlsafe_b64decode(padded))
                    auth_ns = jwt_claims.get("https://api.openai.com/auth", {})
                    account_id = auth_ns.get("chatgpt_account_id", "")
            except Exception:
                pass

            wham_headers = {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
                "User-Agent": "Spark/1.0",
            }
            if account_id:
                wham_headers["ChatGPT-Account-Id"] = account_id

            with _httpx.Client(http2=True, timeout=10.0) as _hc:
                wham = _hc.get("https://chatgpt.com/backend-api/wham/usage", headers=wham_headers)

            if wham.status_code == 200:
                wham_data = wham.json()
                rl = wham_data.get("rate_limit", {})
                pw = rl.get("primary_window", {})    # 5-hour window
                sw = rl.get("secondary_window", {})  # weekly window
                return {
                    "available": True,
                    "provider_connected": True,
                    "active_model": active_model,
                    "plan_type": wham_data.get("plan_type"),
                    "limit_reached": rl.get("limit_reached", False),
                    "windows": [
                        {
                            "label": "5h Limit",
                            "used_percent": pw.get("used_percent", 0),
                            "reset_at": pw.get("reset_at"),
                            "reset_after_seconds": pw.get("reset_after_seconds"),
                            "window_seconds": pw.get("limit_window_seconds", 18000),
                        },
                        {
                            "label": "Weekly limit",
                            "used_percent": sw.get("used_percent", 0),
                            "reset_at": sw.get("reset_at"),
                            "reset_after_seconds": sw.get("reset_after_seconds"),
                            "window_seconds": sw.get("limit_window_seconds", 604800),
                        },
                    ],
                }
        except Exception as exc:
            _log.debug("wham/usage fetch failed: %s", exc)

        # Fallback: return connected state without usage windows
        return {
            "available": True,
            "provider_connected": True,
            "active_model": active_model,
            "windows": [],
        }
    except Exception:
        _log.exception("GET /api/model/codex-usage failed")
        return {"available": False, "reason": "internal_error"}


@app.get("/api/model/info")
def get_model_info():
    """Return resolved model metadata for the currently configured model.

    Calls the same context-length resolution chain the agent uses, so the
    frontend can display "Auto-detected: 200K" alongside the override field.
    Also returns model capabilities (vision, reasoning, tools) when available.
    """
    try:
        cfg = load_config()
        model_cfg = cfg.get("model", "")

        # Extract model name and provider from the config
        if isinstance(model_cfg, dict):
            model_name = model_cfg.get("default", model_cfg.get("name", ""))
            provider = model_cfg.get("provider", "")
            base_url = model_cfg.get("base_url", "")
            config_ctx = model_cfg.get("context_length")
        else:
            model_name = str(model_cfg) if model_cfg else ""
            provider = ""
            base_url = ""
            config_ctx = None

        if not model_name:
            return dict(_EMPTY_MODEL_INFO, provider=provider)

        # Resolve auto-detected context length (pass config_ctx=None to get
        # purely auto-detected value, then separately report the override)
        try:
            from agent.model_metadata import get_model_context_length

            auto_ctx = get_model_context_length(
                model=model_name,
                base_url=base_url,
                provider=provider,
                config_context_length=None,  # ignore override — we want auto value
            )
        except Exception:
            auto_ctx = 0

        config_ctx_int = 0
        if isinstance(config_ctx, int) and config_ctx > 0:
            config_ctx_int = config_ctx

        # Effective is what the agent actually uses
        effective_ctx = config_ctx_int if config_ctx_int > 0 else auto_ctx

        # Try to get model capabilities from models.dev
        caps = {}
        try:
            from agent.models_dev import get_model_capabilities

            mc = get_model_capabilities(provider=provider, model=model_name)
            if mc is not None:
                caps = {
                    "supports_tools": mc.supports_tools,
                    "supports_vision": mc.supports_vision,
                    "supports_reasoning": mc.supports_reasoning,
                    "context_window": mc.context_window,
                    "max_output_tokens": mc.max_output_tokens,
                    "model_family": mc.model_family,
                }
        except Exception:
            pass

        return {
            "model": model_name,
            "provider": provider,
            "auto_context_length": auto_ctx,
            "config_context_length": config_ctx_int,
            "effective_context_length": effective_ctx,
            "capabilities": caps,
        }
    except Exception:
        _log.exception("GET /api/model/info failed")
        return dict(_EMPTY_MODEL_INFO)


@app.get("/api/model/status")
def get_model_status():
    """Return all model/routing/reasoning state needed by the prompt bar."""
    try:
        cfg = load_config()
        model_cfg = cfg.get("model", "")
        if isinstance(model_cfg, dict):
            smart_model = str(model_cfg.get("default", model_cfg.get("name", "")) or "")
            smart_provider = str(model_cfg.get("provider", "") or "")
        else:
            smart_model = str(model_cfg or "")
            smart_provider = ""

        routing_cfg = cfg.get("smart_model_routing", {}) or {}
        multi_enabled = bool(routing_cfg.get("enabled", False))
        cheap = routing_cfg.get("cheap_model", {}) or {}
        fast_model = str(cheap.get("model", "") or "")
        fast_provider = str(cheap.get("provider", "") or "")

        agent_cfg = cfg.get("agent", {}) if isinstance(cfg.get("agent"), dict) else {}
        effort = str(agent_cfg.get("reasoning_effort") or "").strip().lower() or "none"

        # Reasoning support
        reasoning_supported = False
        try:
            from agent.models_dev import get_model_capabilities
            if smart_model:
                mc = get_model_capabilities(provider=smart_provider, model=smart_model)
                reasoning_supported = bool(mc and mc.supports_reasoning)
        except Exception:
            pass

        return {
            "smart_model": smart_model,
            "smart_provider": smart_provider,
            "fast_model": fast_model,
            "fast_provider": fast_provider,
            "multi_model_enabled": multi_enabled,
            "reasoning_effort": effort,
            "reasoning_supported": reasoning_supported,
        }
    except Exception:
        _log.exception("GET /api/model/status failed")
        return {
            "smart_model": "", "smart_provider": "", "fast_model": "", "fast_provider": "",
            "multi_model_enabled": False, "reasoning_effort": "none", "reasoning_supported": False,
        }


# Provider-aware model name catalogs. Used by both the quick-settings popover
# (/api/model/suggestions) and the Config editor dropdown (/api/model/available).
_PROVIDER_MODEL_SUGGESTIONS: Dict[str, list] = {
    "openai-codex": ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "o3", "o4-mini", "o3-mini"],
    "qwen-oauth": ["qwen3-coder-plus", "qwen3-coder-flash"],
    "openai": ["gpt-4.1", "gpt-4.1-mini", "gpt-4o", "gpt-4o-mini", "o3", "o4-mini"],
    "anthropic": [
        "claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5-20251001",
        "claude-opus-4-5", "claude-sonnet-4-5",
    ],
    "google": ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash"],
    "openrouter": ["anthropic/claude-sonnet-4-6", "openai/gpt-4o", "google/gemini-2.5-pro"],
    "deepseek": ["deepseek-chat", "deepseek-reasoner"],
    "xai": ["grok-3", "grok-3-mini"],
    "ollama": ["llama3.3", "qwen2.5-coder:32b", "mistral", "phi4"],
}

# Providers whose model catalog is fixed/managed (OAuth backends that only serve
# a known set), so the Config editor presents a strict dropdown. Open-ended
# providers (ollama local tags, openrouter's huge catalog, custom endpoints) keep
# a free-text field — the suggestions are only hints there.
_STRICT_MODEL_PROVIDERS = frozenset({"openai-codex", "qwen-oauth"})


def _normalize_config_provider_key(value: str) -> str:
    return str(value or "").strip().lower().replace(" ", "-")


def _models_from_provider_config(provider: str) -> tuple[list, str]:
    """Return ``(models, base_url)`` for a provider defined in config.yaml."""
    requested = _normalize_config_provider_key(provider)
    if not requested:
        return [], ""
    requested_no_custom = requested
    if requested.startswith("custom:"):
        requested_no_custom = requested.removeprefix("custom:")
    try:
        cfg = load_config()
    except Exception:
        return [], ""
    providers_cfg = cfg.get("providers")
    if not isinstance(providers_cfg, dict):
        return [], ""

    for key, entry in providers_cfg.items():
        if not isinstance(entry, dict):
            continue
        key_norm = _normalize_config_provider_key(str(key))
        display = _normalize_config_provider_key(str(entry.get("name", "") or ""))
        candidates = {key_norm, f"custom:{key_norm}"}
        if display:
            candidates.update({display, f"custom:{display}"})
        if (
            requested not in candidates
            and requested_no_custom not in {key_norm, display}
        ):
            continue

        models: list[str] = []
        default_model = str(entry.get("default_model", "") or "").strip()
        if default_model:
            models.append(default_model)
        cfg_models = entry.get("models", [])
        if isinstance(cfg_models, list):
            for model_id in cfg_models:
                model_id = str(model_id or "").strip()
                if model_id and model_id not in models:
                    models.append(model_id)
        base_url = str(
            entry.get("api") or entry.get("url") or entry.get("base_url") or ""
        ).strip()
        return models, base_url
    return [], ""


def _resolve_provider_models(provider: str, base_url: str = "") -> tuple[list, bool]:
    """Resolve the model catalog for ``provider`` (live where possible).

    Returns ``(models, live)`` where ``live`` indicates the list came from
    querying the provider directly (vs. static suggestions). For ollama,
    openrouter and OpenAI-compatible custom endpoints we query the provider so
    the dropdown reflects what's actually installed/available. Everything else
    falls back to the curated suggestion lists.
    """
    provider = (provider or "").strip()
    base_url = (base_url or "").strip()

    config_models, config_base_url = _models_from_provider_config(provider)
    if config_models:
        return config_models, False
    if not base_url and config_base_url:
        base_url = config_base_url

    if provider == "openai-codex":
        try:
            from spark_cli.codex_models import get_codex_model_ids

            return get_codex_model_ids(), False
        except Exception:
            return list(_PROVIDER_MODEL_SUGGESTIONS.get(provider, [])), False

    if provider in {"ollama", "openrouter", "custom"} or base_url:
        try:
            from agent.model_metadata import list_provider_models

            api_key = ""
            if provider == "openrouter":
                api_key = load_env().get("OPENROUTER_API_KEY", "") or ""
            live = list_provider_models(provider, base_url=base_url, api_key=api_key)
            if live:
                return live, True
        except Exception:
            _log.exception("live model fetch failed for provider=%s", provider)
        # Fall back to static hints when the provider is unreachable.
        return list(_PROVIDER_MODEL_SUGGESTIONS.get(provider, [])), False

    return list(_PROVIDER_MODEL_SUGGESTIONS.get(provider, [])), False


@app.get("/api/model/available")
def get_available_models(provider: str = "", base_url: str = ""):
    """Return the model catalog for a given provider plus whether the UI should
    enforce a strict dropdown.

    Query params:
        provider — provider id (e.g. "openai-codex"). Defaults to "".
        base_url — optional endpoint URL used to query local/custom providers
                   (ollama, OpenAI-compatible servers) for their live catalog.

    Response:
        provider — echoed provider id
        models   — list of known model names for that provider (may be empty)
        live     — True when the list was fetched live from the provider
        strict   — True when the UI should only allow choosing from `models`
                   (fixed/managed catalogs like openai-codex); False when the
                   user may type a custom name (ollama, openrouter, custom).
    """
    provider = (provider or "").strip()
    normalized_base_url = ""
    if (base_url or "").strip():
        try:
            normalized_base_url = normalize_http_base_url(
                base_url, field_name="Model base URL"
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    models, live = _resolve_provider_models(provider, normalized_base_url)
    strict = provider in _STRICT_MODEL_PROVIDERS
    return {"provider": provider, "models": models, "live": live, "strict": strict}


@app.get("/api/model/suggestions")
def get_model_suggestions():
    """Return provider-aware model name suggestions for the quick-settings popover."""
    try:
        cfg = load_config()
        model_cfg = cfg.get("model", "")
        smart_provider = ""
        smart_base_url = ""
        if isinstance(model_cfg, dict):
            smart_provider = str(model_cfg.get("provider", "") or "")
            smart_base_url = str(model_cfg.get("base_url", "") or "")

        routing_cfg = cfg.get("smart_model_routing", {}) or {}
        cheap = routing_cfg.get("cheap_model", {}) or {}
        fast_provider = str(cheap.get("provider", "") or "")
        fast_base_url = str(cheap.get("base_url", "") or "")

        smart_models, _ = _resolve_provider_models(smart_provider, smart_base_url)
        fast_models, _ = _resolve_provider_models(fast_provider, fast_base_url)

        return {
            "smart": smart_models,
            "fast": fast_models,
            "smart_provider": smart_provider,
            "fast_provider": fast_provider,
        }
    except Exception:
        _log.exception("GET /api/model/suggestions failed")
        return {"smart": [], "fast": [], "smart_provider": "", "fast_provider": ""}


@app.put("/api/model/fast")
def set_fast_model(body: Dict[str, Any]):
    """Update just the fast model name, preserving other routing config."""
    try:
        from spark_cli.config import save_config

        try:
            new_model = normalize_model_name(body.get("model"), field_name="Model name")
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        cfg = load_config()
        if "smart_model_routing" not in cfg or not isinstance(cfg["smart_model_routing"], dict):
            cfg["smart_model_routing"] = {}
        if "cheap_model" not in cfg["smart_model_routing"] or not isinstance(cfg["smart_model_routing"]["cheap_model"], dict):
            cfg["smart_model_routing"]["cheap_model"] = {}
        cfg["smart_model_routing"]["cheap_model"]["model"] = new_model
        save_config(cfg)
        return {"ok": True, "model": new_model}
    except Exception:
        _log.exception("PUT /api/model/fast failed")
        return JSONResponse({"error": "Failed to save fast model"}, status_code=500)


@app.put("/api/model/smart")
def set_smart_model(body: Dict[str, Any]):
    """Update just the smart model name, preserving provider/url/api_mode."""
    try:
        from spark_cli.config import save_config

        try:
            new_model = normalize_model_name(body.get("model"), field_name="Model name")
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        cfg = load_config()
        model_cfg = cfg.get("model", "")
        if isinstance(model_cfg, dict):
            model_cfg["default"] = new_model
            cfg["model"] = model_cfg
        else:
            cfg["model"] = new_model
        save_config(cfg)
        return {"ok": True, "model": new_model}
    except Exception:
        _log.exception("PUT /api/model/smart failed")
        return JSONResponse({"error": "Failed to save model"}, status_code=500)


@app.get("/api/model/reasoning")
def get_reasoning_effort():
    """Return current reasoning effort and whether the active model supports it."""
    try:
        cfg = load_config()
        agent_cfg = cfg.get("agent", {}) if isinstance(cfg.get("agent"), dict) else {}
        effort = str(agent_cfg.get("reasoning_effort") or "").strip().lower() or "none"

        # Check if active model supports reasoning
        supported = False
        try:
            from agent.models_dev import get_model_capabilities

            model_cfg = cfg.get("model", "")
            if isinstance(model_cfg, dict):
                model_name = model_cfg.get("default", model_cfg.get("name", ""))
                provider = model_cfg.get("provider", "")
            else:
                model_name = str(model_cfg) if model_cfg else ""
                provider = ""
            if model_name:
                mc = get_model_capabilities(provider=provider, model=model_name)
                supported = bool(mc and mc.supports_reasoning)
        except Exception:
            pass

        return {"effort": effort, "supported": supported}
    except Exception:
        _log.exception("GET /api/model/reasoning failed")
        return {"effort": "none", "supported": False}


@app.put("/api/model/reasoning")
def set_reasoning_effort(body: Dict[str, Any]):
    """Set reasoning effort level. Valid values: none, minimal, low, medium, high, xhigh."""
    try:
        from core.spark_constants import parse_reasoning_effort
        from spark_cli.config import save_config

        effort = str(body.get("effort", "none")).strip().lower()
        if effort != "none" and parse_reasoning_effort(effort) is None:
            return JSONResponse({"error": f"Invalid effort: {effort}"}, status_code=400)

        cfg = load_config()
        if "agent" not in cfg or not isinstance(cfg["agent"], dict):
            cfg["agent"] = {}
        cfg["agent"]["reasoning_effort"] = "" if effort == "none" else effort
        save_config(cfg)
        return {"effort": effort, "ok": True}
    except Exception:
        _log.exception("PUT /api/model/reasoning failed")
        return JSONResponse({"error": "Failed to save reasoning effort"}, status_code=500)


def _denormalize_config_from_web(config: Dict[str, Any]) -> Dict[str, Any]:
    """Reverse _normalize_config_for_web before saving.

    Reconstructs ``model`` as a dict by reading the current on-disk config
    to recover model subkeys (provider, base_url, api_mode, etc.) that were
    stripped from the GET response.  The frontend only sees model as a flat
    string; the rest is preserved transparently.

    Also handles ``model_context_length`` — writes it back into the model dict
    as ``context_length``.  A value of 0 or absent means "auto-detect" (omitted
    from the dict so get_model_context_length() uses its normal resolution).
    """
    config = dict(config)
    # Remove any _model_meta that might have leaked in (shouldn't happen
    # with the stripped GET response, but be defensive)
    config.pop("_model_meta", None)

    # Extract and remove model virtual fields before processing model
    model_provider = str(config.pop("model_provider", "") or "").strip()
    model_base_url = str(config.pop("model_base_url", "") or "").strip()
    if model_base_url:
        model_base_url = normalize_http_base_url(model_base_url, field_name="Model base URL")
    model_api_mode = str(config.pop("model_api_mode", "") or "").strip()
    ctx_override = config.pop("model_context_length", 0)
    if not isinstance(ctx_override, int):
        try:
            ctx_override = int(ctx_override)
        except (TypeError, ValueError):
            ctx_override = 0

    model_val = config.get("model")
    if isinstance(model_val, str) and model_val:
        def _apply_model_virtuals(model_config: Dict[str, Any]) -> Dict[str, Any]:
            model_config["default"] = model_val
            if model_provider:
                model_config["provider"] = model_provider
            else:
                model_config.pop("provider", None)
            if model_base_url:
                model_config["base_url"] = model_base_url
            else:
                model_config.pop("base_url", None)
            if model_api_mode:
                model_config["api_mode"] = model_api_mode
            else:
                model_config.pop("api_mode", None)
            if ctx_override > 0:
                model_config["context_length"] = ctx_override
            else:
                model_config.pop("context_length", None)
            return model_config

        # Read the current disk config to recover model subkeys
        try:
            disk_config = load_config()
            disk_model = disk_config.get("model")
            if isinstance(disk_model, dict):
                # Preserve all subkeys, update default with the new value
                config["model"] = _apply_model_virtuals(disk_model)
            else:
                # Model was previously a bare string — upgrade to dict if the
                # user is setting any structured model metadata.
                if ctx_override > 0 or model_provider or model_base_url or model_api_mode:
                    config["model"] = _apply_model_virtuals({})
        except Exception:
            pass  # can't read disk config — just use the string form
    return config


def _validate_config_update_from_web(config: Dict[str, Any]) -> Dict[str, Any]:
    """Validate onboarding-sensitive fields before saving web config updates."""
    model = config.get("model")
    if isinstance(model, dict):
        for key in ("default", "model", "name"):
            if model.get(key):
                model[key] = normalize_model_name(model[key], field_name="Model name")
        if model.get("base_url"):
            model["base_url"] = normalize_http_base_url(
                model["base_url"], field_name="Model base URL"
            )
    elif isinstance(model, str) and model.strip():
        config["model"] = normalize_model_name(model, field_name="Model name")
    return config


@app.put("/api/config")
async def update_config(body: ConfigUpdate):
    try:
        config = _validate_config_update_from_web(
            _denormalize_config_from_web(body.config)
        )
        save_config(config)
        for sid in list(_web_agents.keys()):
            if not _is_web_turn_active(sid):
                _close_web_agent(sid)
        return {"ok": True}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        _log.exception("PUT /api/config failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/auth/session-token")
async def get_session_token():
    """Return the ephemeral session token for this server instance.

    The token protects sensitive endpoints (reveal).  It's served to the SPA
    which stores it in memory — it's never persisted and dies when the server
    process exits.  CORS already restricts this to localhost origins.
    """
    return {"token": _SESSION_TOKEN}


@app.get("/api/env")
async def get_env_vars():
    env_on_disk = load_env()
    result = {}
    for var_name, info in OPTIONAL_ENV_VARS.items():
        value = env_on_disk.get(var_name)
        result[var_name] = {
            "is_set": bool(value),
            "redacted_value": redact_key(value) if value else None,
            "description": info.get("description", ""),
            "url": info.get("url"),
            "category": info.get("category", ""),
            "is_password": info.get("password", False),
            "tools": info.get("tools", []),
            "advanced": info.get("advanced", False),
        }
    return result


@app.put("/api/env")
async def set_env_var(body: EnvVarUpdate):
    try:
        value = validate_env_assignment(body.key, body.value)
        save_env_value(body.key, value)
        return {"ok": True, "key": body.key}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        _log.exception("PUT /api/env failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.delete("/api/env")
async def remove_env_var(body: EnvVarDelete):
    try:
        removed = remove_env_value(body.key)
        if not removed:
            raise HTTPException(status_code=404, detail=f"{body.key} not found in .env")
        return {"ok": True, "key": body.key}
    except HTTPException:
        raise
    except Exception:
        _log.exception("DELETE /api/env failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/api/env/reveal")
async def reveal_env_var(body: EnvVarReveal, request: Request):
    """Return the real (unredacted) value of a single env var.

    Protected by:
    - Ephemeral session token (generated per server start, injected into SPA)
    - Rate limiting (max 5 reveals per 30s window)
    - Audit logging
    """
    # --- Token check (strict: no loopback bypass for plaintext secrets) ---
    if not _secret_reveal_authorized(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    # --- Rate limit ---
    now = time.time()
    cutoff = now - _REVEAL_WINDOW_SECONDS
    _reveal_timestamps[:] = [t for t in _reveal_timestamps if t > cutoff]
    if len(_reveal_timestamps) >= _REVEAL_MAX_PER_WINDOW:
        raise HTTPException(
            status_code=429, detail="Too many reveal requests. Try again shortly."
        )
    _reveal_timestamps.append(now)

    # --- Reveal ---
    env_on_disk = load_env()
    value = env_on_disk.get(body.key)
    if value is None:
        raise HTTPException(status_code=404, detail=f"{body.key} not found in .env")

    _log.info("env/reveal: %s", body.key)
    return {"key": body.key, "value": value}


# ---------------------------------------------------------------------------
# OAuth provider endpoints — status + disconnect (Phase 1)
# ---------------------------------------------------------------------------
#
# Phase 1 surfaces *which OAuth providers exist* and whether each is
# connected, plus a disconnect button. The actual login flow (PKCE for
# Anthropic and device-code OAuth flows still run in the CLI for now;
# Phase 2 will add in-browser flows. For unconnected providers we return
# the canonical ``spark auth add <provider>`` command so the dashboard
# can surface a one-click copy.


def _truncate_token(value: Optional[str], visible: int = 6) -> str:
    """Return ``...XXXXXX`` (last N chars) for safe display in the UI.

    We never expose more than the trailing ``visible`` characters of an
    OAuth access token. JWT prefixes (the part before the first dot) are
    stripped first when present so the visible suffix is always part of
    the signing region rather than a meaningless header chunk.
    """
    if not value:
        return ""
    s = str(value)
    if "." in s and s.count(".") >= 2:
        # Looks like a JWT — show the trailing piece of the signature only.
        s = s.rsplit(".", 1)[-1]
    if len(s) <= visible:
        return s
    return f"…{s[-visible:]}"


def _anthropic_oauth_status() -> Dict[str, Any]:
    """Combined status across the three Anthropic credential sources we read.

    Spark resolves Anthropic creds in this order at runtime:
    1. ``~/.spark/.anthropic_oauth.json`` — Spark-managed PKCE flow
    2. ``~/.claude/.credentials.json`` — Claude Code CLI credentials (auto)
    3. ``ANTHROPIC_TOKEN`` / ``ANTHROPIC_API_KEY`` env vars
    The dashboard reports the highest-priority source that's actually present.
    """
    try:
        from agent.anthropic_adapter import (
            read_spark_oauth_credentials,
            read_claude_code_credentials,
            _SPARK_OAUTH_FILE,
        )
    except ImportError:
        read_claude_code_credentials = None  # type: ignore
        read_spark_oauth_credentials = None  # type: ignore
        _SPARK_OAUTH_FILE = None  # type: ignore

    spark_creds = None
    if read_spark_oauth_credentials:
        try:
            spark_creds = read_spark_oauth_credentials()
        except Exception:
            spark_creds = None
    if spark_creds and spark_creds.get("accessToken"):
        return {
            "logged_in": True,
            "source": "spark_pkce",
            "source_label": f"Spark PKCE ({_SPARK_OAUTH_FILE})",
            "token_preview": _truncate_token(spark_creds.get("accessToken")),
            "expires_at": spark_creds.get("expiresAt"),
            "has_refresh_token": bool(spark_creds.get("refreshToken")),
        }

    cc_creds = None
    if read_claude_code_credentials:
        try:
            cc_creds = read_claude_code_credentials()
        except Exception:
            cc_creds = None
    if cc_creds and cc_creds.get("accessToken"):
        return {
            "logged_in": True,
            "source": "claude_code",
            "source_label": "Claude Code (~/.claude/.credentials.json)",
            "token_preview": _truncate_token(cc_creds.get("accessToken")),
            "expires_at": cc_creds.get("expiresAt"),
            "has_refresh_token": bool(cc_creds.get("refreshToken")),
        }

    env_token = os.getenv("ANTHROPIC_TOKEN") or os.getenv("CLAUDE_CODE_OAUTH_TOKEN")
    if env_token:
        return {
            "logged_in": True,
            "source": "env_var",
            "source_label": "ANTHROPIC_TOKEN environment variable",
            "token_preview": _truncate_token(env_token),
            "expires_at": None,
            "has_refresh_token": False,
        }
    return {"logged_in": False, "source": None}


def _claude_code_only_status() -> Dict[str, Any]:
    """Surface Claude Code CLI credentials as their own provider entry.

    Independent of the Anthropic entry above so users can see whether their
    Claude Code subscription tokens are actively flowing into Spark even
    when they also have a separate Spark-managed PKCE login.
    """
    try:
        from agent.anthropic_adapter import read_claude_code_credentials

        creds = read_claude_code_credentials()
    except Exception:
        creds = None
    if creds and creds.get("accessToken"):
        return {
            "logged_in": True,
            "source": "claude_code_cli",
            "source_label": "~/.claude/.credentials.json",
            "token_preview": _truncate_token(creds.get("accessToken")),
            "expires_at": creds.get("expiresAt"),
            "has_refresh_token": bool(creds.get("refreshToken")),
        }
    return {"logged_in": False, "source": None}


# Provider catalog. The order matters — it's how we render the UI list.
# ``cli_command`` is what the dashboard surfaces as the copy-to-clipboard
# fallback while Phase 2 (in-browser flows) isn't built yet.
# ``flow`` describes the OAuth shape so the future modal can pick the
# right UI: ``pkce`` = open URL + paste callback code, ``device_code`` =
# show code + verification URL + poll, ``external`` = read-only (delegated
# to a third-party CLI like Claude Code or Qwen).
_OAUTH_PROVIDER_CATALOG: tuple[Dict[str, Any], ...] = (
    {
        "id": "anthropic",
        "name": "Anthropic (Claude API)",
        "flow": "pkce",
        "cli_command": "spark auth add anthropic",
        "docs_url": "https://docs.claude.com/en/api/getting-started",
        "status_fn": _anthropic_oauth_status,
    },
    {
        "id": "claude-code",
        "name": "Claude Code (subscription)",
        "flow": "external",
        "cli_command": "claude setup-token",
        "docs_url": "https://docs.claude.com/en/docs/claude-code",
        "status_fn": _claude_code_only_status,
    },
    {
        "id": "openai-codex",
        "name": "OpenAI Codex (ChatGPT)",
        "flow": "device_code",
        "cli_command": "spark auth add openai-codex",
        "docs_url": "https://platform.openai.com/docs",
        "status_fn": None,  # dispatched via auth.get_codex_auth_status
    },
    {
        "id": "qwen-oauth",
        "name": "Qwen (via Qwen CLI)",
        "flow": "external",
        "cli_command": "spark auth add qwen-oauth",
        "docs_url": "https://github.com/QwenLM/qwen-code",
        "status_fn": None,  # dispatched via auth.get_qwen_auth_status
    },
)


def _resolve_provider_status(provider_id: str, status_fn) -> Dict[str, Any]:
    """Dispatch to the right status helper for an OAuth provider entry."""
    if status_fn is not None:
        try:
            return status_fn()
        except Exception as e:
            return {"logged_in": False, "error": str(e)}
    try:
        from spark_cli import auth as hauth

        if provider_id == "openai-codex":
            raw = hauth.get_codex_auth_status()
            return {
                "logged_in": bool(raw.get("logged_in")),
                "source": raw.get("source") or "openai_codex",
                "source_label": raw.get("auth_mode") or "OpenAI Codex",
                "token_preview": _truncate_token(raw.get("api_key")),
                "expires_at": None,
                "has_refresh_token": False,
                "last_refresh": raw.get("last_refresh"),
            }
        if provider_id == "qwen-oauth":
            raw = hauth.get_qwen_auth_status()
            return {
                "logged_in": bool(raw.get("logged_in")),
                "source": "qwen_cli",
                "source_label": raw.get("auth_store_path") or "Qwen CLI",
                "token_preview": _truncate_token(raw.get("access_token")),
                "expires_at": raw.get("expires_at"),
                "has_refresh_token": bool(raw.get("has_refresh_token")),
            }
    except Exception as e:
        return {"logged_in": False, "error": str(e)}
    return {"logged_in": False}


@app.get("/api/providers/oauth")
async def list_oauth_providers():
    """Enumerate every OAuth-capable LLM provider with current status.

    Response shape (per provider):
        id              stable identifier (used in DELETE path)
        name            human label
        flow            "pkce" | "device_code" | "external"
        cli_command     fallback CLI command for users to run manually
        docs_url        external docs/portal link for the "Learn more" link
        status:
          logged_in        bool — currently has usable creds
          source           short slug ("spark_pkce", "claude_code", ...)
          source_label     human-readable origin (file path, env var name)
          token_preview    last N chars of the token, never the full token
          expires_at       ISO timestamp string or null
          has_refresh_token bool
    """
    providers = []
    for p in _OAUTH_PROVIDER_CATALOG:
        status = _resolve_provider_status(p["id"], p.get("status_fn"))
        providers.append(
            {
                "id": p["id"],
                "name": p["name"],
                "flow": p["flow"],
                "cli_command": p["cli_command"],
                "docs_url": p["docs_url"],
                "status": status,
            }
        )
    return {"providers": providers}


@app.delete("/api/providers/oauth/{provider_id}")
async def disconnect_oauth_provider(provider_id: str, request: Request):
    """Disconnect an OAuth provider. Token-protected (matches /env/reveal)."""
    # Accept either the per-process session token OR the configured dashboard
    # token (same dual-credential rule as /api/env/reveal). The desktop app and
    # remote clients authenticate with the dashboard token, so a session-only
    # check here made OAuth connect/disconnect 401 even though the rest of the
    # dashboard was authorized.
    if not _reveal_authorized(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    valid_ids = {p["id"] for p in _OAUTH_PROVIDER_CATALOG}
    if provider_id not in valid_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider: {provider_id}. "
            f"Available: {', '.join(sorted(valid_ids))}",
        )

    # Anthropic and claude-code clear the same Spark-managed PKCE file
    # AND forget the Claude Code import. We don't touch ~/.claude/* directly
    # — that's owned by the Claude Code CLI; users can re-auth there if they
    # want to undo a disconnect.
    if provider_id in ("anthropic", "claude-code"):
        try:
            from agent.anthropic_adapter import _SPARK_OAUTH_FILE

            if _SPARK_OAUTH_FILE.exists():
                _SPARK_OAUTH_FILE.unlink()
        except Exception:
            pass
        # Also clear the credential pool entry if present.
        try:
            from spark_cli.auth import clear_provider_auth

            clear_provider_auth("anthropic")
        except Exception:
            pass
        _log.info("oauth/disconnect: %s", provider_id)
        return {"ok": True, "provider": provider_id}

    try:
        from spark_cli.auth import clear_provider_auth

        cleared = clear_provider_auth(provider_id)
        _log.info("oauth/disconnect: %s (cleared=%s)", provider_id, cleared)
        return {"ok": bool(cleared), "provider": provider_id}
    except Exception as e:
        _log.exception("disconnect %s failed", provider_id)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# OAuth Phase 2 — in-browser PKCE & device-code flows
# ---------------------------------------------------------------------------
#
# Two flow shapes are supported:
#
#   PKCE (Anthropic):
#     1. POST /api/providers/oauth/anthropic/start
#          → server generates code_verifier + challenge, builds claude.ai
#            authorize URL, stashes verifier in _oauth_sessions[session_id]
#          → returns { session_id, flow: "pkce", auth_url }
#     2. UI opens auth_url in a new tab. User authorizes, copies code.
#     3. POST /api/providers/oauth/anthropic/submit { session_id, code }
#          → server exchanges (code + verifier) → tokens at console.anthropic.com
#          → persists to ~/.spark/.anthropic_oauth.json AND credential pool
#          → returns { ok: true, status: "approved" }
#
#   Device code (OpenAI Codex):
#     1. POST /api/providers/oauth/openai-codex/start
#          → server hits provider's device-auth endpoint
#          → gets { user_code, verification_url, device_code, interval, expires_in }
#          → spawns background poller thread that polls the token endpoint
#            every `interval` seconds until approved/expired
#          → stores poll status in _oauth_sessions[session_id]
#          → returns { session_id, flow: "device_code", user_code,
#                      verification_url, expires_in, poll_interval }
#     2. UI opens verification_url in a new tab and shows user_code.
#     3. UI polls GET /api/providers/oauth/{provider}/poll/{session_id}
#          every 2s until status != "pending".
#     4. On "approved" the background thread has already saved creds; UI
#        refreshes the providers list.
#
# Sessions are kept in-memory only (single-process FastAPI) and time out
# after 15 minutes. A periodic cleanup runs on each /start call to GC
# expired sessions so the dict doesn't grow without bound.

_OAUTH_SESSION_TTL_SECONDS = 15 * 60
_oauth_sessions: Dict[str, Dict[str, Any]] = {}
_oauth_sessions_lock = threading.Lock()

# Import OAuth constants from canonical source instead of duplicating.
# Guarded so spark web still starts if anthropic_adapter is unavailable;
# Phase 2 endpoints will return 501 in that case.
try:
    from agent.anthropic_adapter import (
        _OAUTH_CLIENT_ID as _ANTHROPIC_OAUTH_CLIENT_ID,
        _OAUTH_TOKEN_URL as _ANTHROPIC_OAUTH_TOKEN_URL,
        _OAUTH_REDIRECT_URI as _ANTHROPIC_OAUTH_REDIRECT_URI,
        _OAUTH_SCOPES as _ANTHROPIC_OAUTH_SCOPES,
        _generate_pkce as _generate_pkce_pair,
    )

    _ANTHROPIC_OAUTH_AVAILABLE = True
except ImportError:
    _ANTHROPIC_OAUTH_AVAILABLE = False
_ANTHROPIC_OAUTH_AUTHORIZE_URL = "https://claude.ai/oauth/authorize"


def _gc_oauth_sessions() -> None:
    """Drop expired sessions. Called opportunistically on /start."""
    cutoff = time.time() - _OAUTH_SESSION_TTL_SECONDS
    with _oauth_sessions_lock:
        stale = [
            sid for sid, sess in _oauth_sessions.items() if sess["created_at"] < cutoff
        ]
        for sid in stale:
            _oauth_sessions.pop(sid, None)


def _new_oauth_session(provider_id: str, flow: str) -> tuple[str, Dict[str, Any]]:
    """Create + register a new OAuth session, return (session_id, session_dict)."""
    sid = secrets.token_urlsafe(16)
    sess = {
        "session_id": sid,
        "provider": provider_id,
        "flow": flow,
        "created_at": time.time(),
        "status": "pending",  # pending | approved | denied | expired | error
        "error_message": None,
    }
    with _oauth_sessions_lock:
        _oauth_sessions[sid] = sess
    return sid, sess


def _save_anthropic_oauth_creds(
    access_token: str, refresh_token: str, expires_at_ms: int
) -> None:
    """Persist Anthropic PKCE creds to both Spark file AND credential pool.

    Mirrors what auth_commands.add_command does so the dashboard flow leaves
    the system in the same state as ``spark auth add anthropic``.
    """
    from agent.anthropic_adapter import _SPARK_OAUTH_FILE

    payload = {
        "accessToken": access_token,
        "refreshToken": refresh_token,
        "expiresAt": expires_at_ms,
    }
    _SPARK_OAUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    _SPARK_OAUTH_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    # Best-effort credential-pool insert. Failure here doesn't invalidate
    # the file write — pool registration only matters for the rotation
    # strategy, not for runtime credential resolution.
    try:
        from agent.credential_pool import (
            PooledCredential,
            load_pool,
            AUTH_TYPE_OAUTH,
            SOURCE_MANUAL,
        )
        import uuid

        pool = load_pool("anthropic")
        # Avoid duplicate entries: delete any prior dashboard-issued OAuth entry
        existing = [
            e
            for e in pool.entries()
            if getattr(e, "source", "").startswith(f"{SOURCE_MANUAL}:dashboard_pkce")
        ]
        for e in existing:
            try:
                pool.remove_entry(getattr(e, "id", ""))
            except Exception:
                pass
        entry = PooledCredential(
            provider="anthropic",
            id=uuid.uuid4().hex[:6],
            label="dashboard PKCE",
            auth_type=AUTH_TYPE_OAUTH,
            priority=0,
            source=f"{SOURCE_MANUAL}:dashboard_pkce",
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at_ms=expires_at_ms,
        )
        pool.add_entry(entry)
    except Exception as e:
        _log.warning("anthropic pool add (dashboard) failed: %s", e)


def _start_anthropic_pkce() -> Dict[str, Any]:
    """Begin PKCE flow. Returns the auth URL the UI should open."""
    if not _ANTHROPIC_OAUTH_AVAILABLE:
        raise HTTPException(
            status_code=501, detail="Anthropic OAuth not available (missing adapter)"
        )
    verifier, challenge = _generate_pkce_pair()
    sid, sess = _new_oauth_session("anthropic", "pkce")
    sess["verifier"] = verifier
    sess["state"] = verifier  # Anthropic round-trips verifier as state
    params = {
        "code": "true",
        "client_id": _ANTHROPIC_OAUTH_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": _ANTHROPIC_OAUTH_REDIRECT_URI,
        "scope": _ANTHROPIC_OAUTH_SCOPES,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": verifier,
    }
    auth_url = f"{_ANTHROPIC_OAUTH_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"
    return {
        "session_id": sid,
        "flow": "pkce",
        "auth_url": auth_url,
        "expires_in": _OAUTH_SESSION_TTL_SECONDS,
    }


def _submit_anthropic_pkce(session_id: str, code_input: str) -> Dict[str, Any]:
    """Exchange authorization code for tokens. Persists on success."""
    with _oauth_sessions_lock:
        sess = _oauth_sessions.get(session_id)
    if not sess or sess["provider"] != "anthropic" or sess["flow"] != "pkce":
        raise HTTPException(status_code=404, detail="Unknown or expired session")
    if sess["status"] != "pending":
        return {
            "ok": False,
            "status": sess["status"],
            "message": sess.get("error_message"),
        }

    # Anthropic's redirect callback page formats the code as `<code>#<state>`.
    # Strip the state suffix if present (we already have the verifier server-side).
    parts = code_input.strip().split("#", 1)
    code = parts[0].strip()
    if not code:
        return {"ok": False, "status": "error", "message": "No code provided"}
    state_from_callback = parts[1] if len(parts) > 1 else ""

    exchange_data = json.dumps(
        {
            "grant_type": "authorization_code",
            "client_id": _ANTHROPIC_OAUTH_CLIENT_ID,
            "code": code,
            "state": state_from_callback or sess["state"],
            "redirect_uri": _ANTHROPIC_OAUTH_REDIRECT_URI,
            "code_verifier": sess["verifier"],
        }
    ).encode()
    req = urllib.request.Request(
        _ANTHROPIC_OAUTH_TOKEN_URL,
        data=exchange_data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "spark-dashboard/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read().decode())
    except Exception as e:
        sess["status"] = "error"
        sess["error_message"] = f"Token exchange failed: {e}"
        return {"ok": False, "status": "error", "message": sess["error_message"]}

    access_token = result.get("access_token", "")
    refresh_token = result.get("refresh_token", "")
    expires_in = int(result.get("expires_in") or 3600)
    if not access_token:
        sess["status"] = "error"
        sess["error_message"] = "No access token returned"
        return {"ok": False, "status": "error", "message": sess["error_message"]}

    expires_at_ms = int(time.time() * 1000) + (expires_in * 1000)
    try:
        _save_anthropic_oauth_creds(access_token, refresh_token, expires_at_ms)
    except Exception as e:
        sess["status"] = "error"
        sess["error_message"] = f"Save failed: {e}"
        return {"ok": False, "status": "error", "message": sess["error_message"]}
    sess["status"] = "approved"
    _log.info("oauth/pkce: anthropic login completed (session=%s)", session_id)
    return {"ok": True, "status": "approved"}


async def _start_device_code_flow(provider_id: str) -> Dict[str, Any]:
    """Initiate a device-code flow (OpenAI Codex).

    Calls the provider's device-auth endpoint via the existing CLI helpers,
    then spawns a background poller. Returns the user-facing display fields
    so the UI can render the verification page link + user code.
    """
    if provider_id == "openai-codex":
        # Codex uses fixed OpenAI device-auth endpoints; reuse the helper.
        sid, _ = _new_oauth_session("openai-codex", "device_code")
        # Use the helper but in a thread because it polls inline.
        # We can't extract just the start step without refactoring auth.py,
        # so we run the full helper in a worker and proxy the user_code +
        # verification_url back via the session dict. The helper prints
        # to stdout — we capture nothing here, just status.
        threading.Thread(
            target=_codex_full_login_worker,
            args=(sid,),
            daemon=True,
            name=f"oauth-codex-{sid[:6]}",
        ).start()
        # Wait briefly for the worker to populate the user_code. OpenAI's
        # device-auth endpoint is often slow (observed 30–120 s), so we do NOT
        # block until it returns — if the code isn't ready quickly we return a
        # "starting" response and the UI polls GET /poll/{session_id} until the
        # user_code appears (the same endpoint it already polls for approval).
        deadline = time.time() + 8
        while time.time() < deadline:
            with _oauth_sessions_lock:
                s = _oauth_sessions.get(sid)
            if s and (s.get("user_code") or s["status"] != "pending"):
                break
            await asyncio.sleep(0.1)
        with _oauth_sessions_lock:
            s = _oauth_sessions.get(sid, {})
        if s.get("status") == "error":
            raise HTTPException(
                status_code=500, detail=s.get("error_message") or "device-auth failed"
            )
        # user_code may be empty here — that's expected when OpenAI is slow.
        return {
            "session_id": sid,
            "flow": "device_code",
            "status": "starting" if not s.get("user_code") else "polling",
            "user_code": s.get("user_code") or None,
            "verification_url": s.get("verification_url")
            or "https://auth.openai.com/codex/device",
            "expires_in": int(s.get("expires_in") or 900),
            "poll_interval": int(s.get("interval") or 5),
        }

    raise HTTPException(
        status_code=400,
        detail=f"Provider {provider_id} does not support device-code flow",
    )



def _codex_full_login_worker(session_id: str) -> None:
    """Run the complete OpenAI Codex device-code flow.

    Codex doesn't use the standard OAuth device-code endpoints; it has its
    own ``/api/accounts/deviceauth/usercode`` (JSON body, returns
    ``device_auth_id``) and ``/api/accounts/deviceauth/token`` (JSON body
    polled until 200). On success the response carries an
    ``authorization_code`` + ``code_verifier`` that get exchanged at
    CODEX_OAUTH_TOKEN_URL with grant_type=authorization_code.

    The flow is replicated inline (rather than calling
    _codex_device_code_login) because that helper prints/blocks/polls in a
    single function — we need to surface the user_code to the dashboard the
    moment we receive it, well before polling completes.
    """
    prefer_cli = _codex_cli_device_login_preferred()
    try:
        if prefer_cli and _codex_cli_device_login_worker(session_id):
            return

        import httpx
        from spark_cli.auth import (
            CODEX_OAUTH_CLIENT_ID,
            CODEX_OAUTH_TOKEN_URL,
            DEFAULT_CODEX_BASE_URL,
        )

        issuer = "https://auth.openai.com"

        # Step 1: request device code. OpenAI's usercode endpoint can take well
        # over a minute to respond, so use a generous read timeout (connect stays
        # short). The UI shows a "requesting code" state meanwhile.
        with httpx.Client(
            timeout=httpx.Timeout(180.0, connect=15.0)
        ) as client:
            resp = client.post(
                f"{issuer}/api/accounts/deviceauth/usercode",
                json={"client_id": CODEX_OAUTH_CLIENT_ID},
                headers={"Content-Type": "application/json"},
            )
        if resp.status_code != 200:
            detail = _redacted_response_preview(resp)
            raise RuntimeError(
                f"deviceauth/usercode returned {resp.status_code}: {detail}"
            )
        device_data = resp.json()
        user_code = device_data.get("user_code", "")
        device_auth_id = device_data.get("device_auth_id", "")
        poll_interval = max(3, int(device_data.get("interval", "5")))
        if not user_code or not device_auth_id:
            raise RuntimeError(
                "device-code response missing user_code or device_auth_id"
            )
        verification_url = f"{issuer}/codex/device"
        with _oauth_sessions_lock:
            sess = _oauth_sessions.get(session_id)
            if not sess:
                return
            sess["user_code"] = user_code
            sess["verification_url"] = verification_url
            sess["device_auth_id"] = device_auth_id
            sess["interval"] = poll_interval
            sess["expires_in"] = 15 * 60  # OpenAI's effective limit
            sess["expires_at"] = time.time() + sess["expires_in"]

        # Step 2: poll until authorized
        deadline = time.time() + sess["expires_in"]
        code_resp = None
        with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
            while time.time() < deadline:
                time.sleep(poll_interval)
                poll = client.post(
                    f"{issuer}/api/accounts/deviceauth/token",
                    json={"device_auth_id": device_auth_id, "user_code": user_code},
                    headers={"Content-Type": "application/json"},
                )
                if poll.status_code == 200:
                    code_resp = poll.json()
                    break
                if poll.status_code in (403, 404):
                    continue  # user hasn't authorized yet
                raise RuntimeError(f"deviceauth/token poll returned {poll.status_code}")

        if code_resp is None:
            with _oauth_sessions_lock:
                sess["status"] = "expired"
                sess["error_message"] = "Device code expired before approval"
            return

        # Step 3: exchange authorization_code for tokens
        authorization_code = code_resp.get("authorization_code", "")
        code_verifier = code_resp.get("code_verifier", "")
        if not authorization_code or not code_verifier:
            raise RuntimeError(
                "device-auth response missing authorization_code/code_verifier"
            )
        with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
            token_resp = client.post(
                CODEX_OAUTH_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": authorization_code,
                    "redirect_uri": f"{issuer}/deviceauth/callback",
                    "client_id": CODEX_OAUTH_CLIENT_ID,
                    "code_verifier": code_verifier,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if token_resp.status_code != 200:
            raise RuntimeError(f"token exchange returned {token_resp.status_code}")
        tokens = token_resp.json()
        access_token = tokens.get("access_token", "")
        refresh_token = tokens.get("refresh_token", "")
        id_token = tokens.get("id_token", "")
        if not access_token:
            raise RuntimeError("token exchange did not return access_token")

        _persist_codex_dashboard_credential(
            {"access_token": access_token, "refresh_token": refresh_token, "id_token": id_token},
            "dashboard device_code",
        )
        with _oauth_sessions_lock:
            sess["status"] = "approved"
        _log.info("oauth/device: openai-codex login completed (session=%s)", session_id)
    except Exception as e:
        if not prefer_cli and _codex_cli_device_login_worker(session_id, reason=str(e)):
            return
        _log.warning("codex device-code worker failed (session=%s): %s", session_id, e)
        with _oauth_sessions_lock:
            s = _oauth_sessions.get(session_id)
            if s:
                s["status"] = "error"
                s["error_message"] = str(e)


def _codex_cli_device_login_preferred() -> bool:
    if os.getenv("SPARK_CODEX_DEVICE_AUTH_IMPL", "").strip().lower() == "inline":
        return False
    return shutil.which("codex") is not None


def _persist_codex_dashboard_credential(tokens: dict[str, Any], label: str) -> None:
    """Persist Codex tokens into the credential pool for WebUI OAuth login."""
    from agent.credential_pool import (
        AUTH_TYPE_OAUTH,
        SOURCE_MANUAL,
        PooledCredential,
        load_pool,
    )
    from spark_cli.auth import DEFAULT_CODEX_BASE_URL

    pool = load_pool("openai-codex")
    base_url = (
        os.getenv("SPARK_CODEX_BASE_URL", "").strip().rstrip("/")
        or DEFAULT_CODEX_BASE_URL
    )
    entry = PooledCredential(
        provider="openai-codex",
        id=uuid.uuid4().hex[:6],
        label=label,
        auth_type=AUTH_TYPE_OAUTH,
        priority=0,
        source=f"{SOURCE_MANUAL}:dashboard_device_code",
        access_token=str(tokens.get("access_token", "") or ""),
        refresh_token=str(tokens.get("refresh_token", "") or ""),
        base_url=base_url,
        extra={"id_token": tokens.get("id_token")},
    )
    pool.add_entry(entry)


def _codex_cli_device_login_worker(session_id: str, *, reason: str = "") -> bool:
    """Run the official Codex CLI device-auth flow and import its tokens.

    Returns True when the CLI path handled the session, False when Spark should
    fall back to its built-in device flow.
    """
    if os.getenv("SPARK_CODEX_DEVICE_AUTH_IMPL", "").strip().lower() == "inline":
        return False
    codex_bin = shutil.which("codex")
    if not codex_bin:
        return False

    try:
        proc = subprocess.Popen(
            [codex_bin, "login", "--device-auth"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except Exception as exc:
        _log.debug("codex CLI device auth unavailable: %s", exc)
        return False

    if reason:
        _log.info("Falling back to Codex CLI device auth after inline flow failed: %s", reason)

    code_re = re.compile(r"\b[A-Z0-9]{4}-[A-Z0-9]{5}\b")
    url_re = re.compile(r"https://auth\.openai\.com/codex/device\b")
    output: thread_queue.Queue[str | None] = thread_queue.Queue()

    def _read_output() -> None:
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                output.put(line)
        except Exception:
            pass
        finally:
            output.put(None)

    threading.Thread(target=_read_output, daemon=True).start()

    saw_code = False
    verification_url = "https://auth.openai.com/codex/device"
    code_timeout = float(
        os.getenv("SPARK_CODEX_CLI_DEVICE_AUTH_CODE_TIMEOUT_SECONDS", "12") or "12"
    )
    code_deadline = time.time() + max(1.0, code_timeout)

    try:
        while time.time() < code_deadline:
            if proc.poll() is not None:
                break
            try:
                line = output.get(timeout=0.25)
            except thread_queue.Empty:
                continue
            if line is None:
                break
            if not saw_code:
                url_match = url_re.search(line)
                if url_match:
                    verification_url = url_match.group(0)
                code_match = code_re.search(line)
                if code_match:
                    saw_code = True
                    with _oauth_sessions_lock:
                        sess = _oauth_sessions.get(session_id)
                        if not sess:
                            proc.terminate()
                            return True
                        sess["user_code"] = code_match.group(0)
                        sess["verification_url"] = verification_url
                        sess["interval"] = 5
                        sess["expires_in"] = 15 * 60
                        sess["expires_at"] = time.time() + sess["expires_in"]
                    break

        if not saw_code:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            _log.info(
                "Codex CLI device auth did not produce a code within %.1fs; falling back to inline flow",
                code_timeout,
            )
            return False

        rc = proc.wait(timeout=15 * 60)
    except Exception as exc:
        try:
            proc.kill()
        except Exception:
            pass
        _log.debug("codex CLI device auth failed while reading output: %s", exc)
        return False

    if rc != 0:
        raise RuntimeError(f"Codex CLI device auth exited with status {rc}")

    from spark_cli.auth import _import_codex_cli_tokens

    tokens = _import_codex_cli_tokens()
    if not tokens:
        raise RuntimeError(
            "Codex CLI login completed, but Spark could not import tokens from ~/.codex/auth.json. "
            "Configure Codex CLI to use file-backed credentials or run `spark auth` in the terminal."
        )
    _persist_codex_dashboard_credential(tokens, "codex CLI device_code")
    with _oauth_sessions_lock:
        sess = _oauth_sessions.get(session_id)
        if sess:
            sess["status"] = "approved"
    return True


@app.post("/api/providers/oauth/{provider_id}/start")
async def start_oauth_login(provider_id: str, request: Request):
    """Initiate an OAuth login flow. Token-protected."""
    # Accept either the per-process session token OR the configured dashboard
    # token (same dual-credential rule as /api/env/reveal). The desktop app and
    # remote clients authenticate with the dashboard token, so a session-only
    # check here made OAuth connect/disconnect 401 even though the rest of the
    # dashboard was authorized.
    if not _reveal_authorized(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    _gc_oauth_sessions()
    valid = {p["id"] for p in _OAUTH_PROVIDER_CATALOG}
    if provider_id not in valid:
        raise HTTPException(status_code=400, detail=f"Unknown provider {provider_id}")
    catalog_entry = next(p for p in _OAUTH_PROVIDER_CATALOG if p["id"] == provider_id)
    if catalog_entry["flow"] == "external":
        raise HTTPException(
            status_code=400,
            detail=f"{provider_id} uses an external CLI; run `{catalog_entry['cli_command']}` manually",
        )
    try:
        if catalog_entry["flow"] == "pkce":
            return _start_anthropic_pkce()
        if catalog_entry["flow"] == "device_code":
            return await _start_device_code_flow(provider_id)
    except HTTPException:
        raise
    except Exception as e:
        _log.exception("oauth/start %s failed", provider_id)
        raise HTTPException(status_code=500, detail=str(e))
    raise HTTPException(status_code=400, detail="Unsupported flow")


class OAuthSubmitBody(BaseModel):
    session_id: str
    code: str


@app.post("/api/providers/oauth/{provider_id}/submit")
async def submit_oauth_code(provider_id: str, body: OAuthSubmitBody, request: Request):
    """Submit the auth code for PKCE flows. Token-protected."""
    # Accept either the per-process session token OR the configured dashboard
    # token (same dual-credential rule as /api/env/reveal). The desktop app and
    # remote clients authenticate with the dashboard token, so a session-only
    # check here made OAuth connect/disconnect 401 even though the rest of the
    # dashboard was authorized.
    if not _reveal_authorized(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    if provider_id == "anthropic":
        return await asyncio.get_event_loop().run_in_executor(
            None,
            _submit_anthropic_pkce,
            body.session_id,
            body.code,
        )
    raise HTTPException(
        status_code=400, detail=f"submit not supported for {provider_id}"
    )


@app.get("/api/providers/oauth/{provider_id}/poll/{session_id}")
async def poll_oauth_session(provider_id: str, session_id: str):
    """Poll a device-code session's status (no auth — read-only state)."""
    with _oauth_sessions_lock:
        sess = _oauth_sessions.get(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    if sess["provider"] != provider_id:
        raise HTTPException(status_code=400, detail="Provider mismatch for session")
    return {
        "session_id": session_id,
        "status": sess["status"],
        "error_message": sess.get("error_message"),
        "expires_at": sess.get("expires_at"),
        # Surfaced once the (often-slow) device-auth call returns, so a UI that
        # received a "starting" /start response can display the code on arrival.
        "user_code": sess.get("user_code") or None,
        "verification_url": sess.get("verification_url") or None,
    }


@app.delete("/api/providers/oauth/sessions/{session_id}")
async def cancel_oauth_session(session_id: str, request: Request):
    """Cancel a pending OAuth session. Token-protected."""
    # Accept either the per-process session token OR the configured dashboard
    # token (same dual-credential rule as /api/env/reveal). The desktop app and
    # remote clients authenticate with the dashboard token, so a session-only
    # check here made OAuth connect/disconnect 401 even though the rest of the
    # dashboard was authorized.
    if not _reveal_authorized(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    with _oauth_sessions_lock:
        sess = _oauth_sessions.pop(session_id, None)
    if sess is None:
        return {"ok": False, "message": "session not found"}
    return {"ok": True, "session_id": session_id}


# ---------------------------------------------------------------------------
# Session detail endpoints
# ---------------------------------------------------------------------------


@app.get("/api/sessions/{session_id}")
async def get_session_detail(session_id: str):
    from core.spark_state import SessionDB

    db = SessionDB()
    try:
        sid = db.resolve_session_id(session_id)
        session = db.get_session(sid) if sid else None
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return session
    finally:
        db.close()


@app.get("/api/sessions/{session_id}/messages")
async def get_session_messages(
    request: Request,
    session_id: str,
    limit: int = 0,
    before_id: Optional[str] = None,
    include_tool_results: bool = False,
):
    from core.spark_state import SessionDB

    db = SessionDB()
    try:
        sid = db.resolve_session_id(session_id)
        if not sid:
            raise HTTPException(status_code=404, detail="Session not found")
        # Follow the compression chain forward so the UI sees the agent's
        # current state, not the pre-compression snapshot frozen in the
        # parent session row. Forks are not followed (different end_reason).
        leaf_sid = db.resolve_latest_descendant(sid)
        messages = db.get_messages(leaf_sid)
        total = len(messages)
        indexed_messages = list(enumerate(messages))
        # Apply pagination: if limit > 0 and/or before_id specified, return a page
        if before_id:
            idx = next((i for i, m in enumerate(messages) if m.get("id") == before_id), None)
            if idx is not None:
                indexed_messages = indexed_messages[:idx]
        if limit > 0:
            indexed_messages = indexed_messages[-limit:]
        messages = [
            _message_for_history_response(
                {**m, "message_index": message_index},
                include_tool_results=include_tool_results,
            )
            for message_index, m in indexed_messages
        ]
        has_earlier = len(messages) < total
        resp: dict[str, Any] = {
            "session_id": leaf_sid,
            "messages": messages,
            "total": total,
            "has_earlier": has_earlier,
        }
        if leaf_sid != sid:
            resp["migrated_from"] = sid

        # ETag: hash of message count + last message id for cheap revalidation.
        last_id = messages[-1].get("id", "") if messages else ""
        etag_src = f"{leaf_sid}:{total}:{last_id}:{limit}:{before_id}"
        etag = f'"{hashlib.md5(etag_src.encode()).hexdigest()}"'
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers={
                "ETag": etag,
                "Cache-Control": "no-cache",
            })
        return JSONResponse(content=resp, headers={
            "ETag": etag,
            "Cache-Control": "no-cache",
        })
    finally:
        db.close()


@app.get("/api/sessions/{session_id}/tool-results/{tool_call_id}")
async def get_session_tool_result(session_id: str, tool_call_id: str):
    from core.spark_state import SessionDB

    db = SessionDB()
    try:
        sid = db.resolve_session_id(session_id)
        if not sid:
            raise HTTPException(status_code=404, detail="Session not found")
        leaf_sid = db.resolve_latest_descendant(sid)
        for msg in db.get_messages(leaf_sid):
            if msg.get("role") == "tool" and msg.get("tool_call_id") == tool_call_id:
                return {
                    "session_id": leaf_sid,
                    "tool_call_id": tool_call_id,
                    "content": _sanitize_web_chat_text(str(msg.get("content") or "")),
                    "tool_name": msg.get("tool_name"),
                }
        raise HTTPException(status_code=404, detail="Tool result not found")
    finally:
        db.close()


def _resolve_workspace_media_path(path: str) -> Path:
    """Resolve a MEDIA path for previewing, limited to Spark workspace files."""
    raw = path.strip().strip("`\"'")
    if not raw:
        raise HTTPException(status_code=400, detail="Missing media path")
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = get_spark_home() / "workspace" / candidate
    resolved = candidate.resolve()
    workspace_root = _get_workspace_root()
    try:
        resolved.relative_to(workspace_root)
    except ValueError:
        raise HTTPException(
            status_code=403,
            detail="Media previews are limited to Spark workspace files",
        )
    if not resolved.exists():
        raise HTTPException(status_code=404, detail=f"Media file not found: {path!r}")
    if resolved.is_dir():
        raise HTTPException(status_code=400, detail="Media path is a directory")
    return resolved


@app.get("/api/media")
async def get_media_file(path: str):
    """Serve MEDIA:/path attachments for web chat previews."""
    file_path = _resolve_workspace_media_path(path)
    mime, _ = mimetypes.guess_type(file_path.name)
    return FileResponse(str(file_path), media_type=mime or "application/octet-stream")


@app.patch("/api/sessions/{session_id}/title")
async def update_session_title(session_id: str, body: dict[str, Any]):
    from core.spark_state import SessionDB

    db = SessionDB()
    try:
        sid = db.resolve_session_id(session_id)
        if not sid:
            raise HTTPException(status_code=404, detail="Session not found")
        title = str(body.get("title", ""))
        try:
            updated = db.set_session_title(sid, title)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if not updated:
            raise HTTPException(status_code=404, detail="Session not found")
        row = db.get_session(sid)
        _emit_sessions_changed("updated", sid, row)
        return {"ok": True, "session_id": sid, "title": row.get("title") if row else None}
    finally:
        db.close()


@app.delete("/api/sessions/{session_id}")
async def delete_session_endpoint(session_id: str):
    from core.spark_state import SessionDB
    from tools.approval import unregister_gateway_notify

    db = SessionDB()
    try:
        if not db.delete_session(session_id):
            raise HTTPException(status_code=404, detail="Session not found")
        _close_web_agent(session_id)
        _web_queues.pop(session_id, None)
        _clear_web_turn(session_id)
        unregister_gateway_notify(session_id)
        _emit_sessions_changed("deleted", session_id)
        return {"ok": True}
    finally:
        db.close()


@app.post("/api/sessions/{session_id}/warm")
async def warm_session_agent(session_id: str):
    """Pre-create the AIAgent for a session so the first real message doesn't pay cold-start costs.

    Does not send a message or emit any chat.* SSE events.
    Returns immediately with {"ok": true, "warm": true/false} indicating
    whether the agent was already warm or was newly created.
    """
    from core.spark_state import SessionDB

    db = SessionDB()
    try:
        requested_session_id = session_id
        sid = db.resolve_session_id(session_id)
        if not sid:
            raise HTTPException(status_code=404, detail="Session not found")
        latest_sid = db.resolve_latest_descendant(sid)
        if latest_sid != sid:
            _log.info(
                "web warm resolved compression descendant requested=%s resolved=%s latest=%s",
                requested_session_id,
                sid,
                latest_sid,
            )
            sid = latest_sid
        row = db.get_session(sid)
        if not row:
            raise HTTPException(status_code=404, detail="Session not found")
    finally:
        db.close()

    # Already warm — nothing to do.
    if sid in _web_agents:
        return {"ok": True, "warm": True}

    # Resolve routing (model, provider, etc.) using an empty-string message
    # so routing heuristics use the same defaults as a real turn.
    try:
        turn_route = _resolve_web_turn_route("")
    except Exception:
        return {"ok": True, "warm": False}

    def _warm_in_thread() -> None:
        from core.spark_state import SessionDB as _DB
        _db = _DB()
        try:
            conversation_history = _db.get_messages_as_conversation(sid)
        finally:
            _db.close()
        _new_web_agent(
            session_id=sid,
            model=turn_route["model"],
            runtime=turn_route["runtime"],
            request_overrides=turn_route.get("request_overrides"),
            signature=turn_route["signature"],
            token_callback=None,
            tool_start_callback=None,
            tool_complete_callback=None,
            reasoning_callback=None,
            status_callback=None,
        )
        # Load conversation history so the system prompt is built and cached.
        agent = _web_agents.get(sid)
        if agent and conversation_history:
            agent.messages = list(conversation_history)

    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, _warm_in_thread)
    return {"ok": True, "warm": False}


# ---------------------------------------------------------------------------
# Log viewer endpoint
# ---------------------------------------------------------------------------


@app.get("/api/logs")
async def get_logs(
    file: str = "agent",
    lines: int = 100,
    level: Optional[str] = None,
    component: Optional[str] = None,
    search: Optional[str] = None,
):
    from spark_cli.logs import _read_tail, LOG_FILES

    log_name = LOG_FILES.get(file)
    if not log_name:
        raise HTTPException(status_code=400, detail=f"Unknown log file: {file}")
    log_path = get_spark_home() / "logs" / log_name
    if not log_path.exists():
        return {"file": file, "lines": []}

    try:
        from core.spark_logging import COMPONENT_PREFIXES
    except ImportError:
        COMPONENT_PREFIXES = {}

    # Normalize "ALL" / "all" / empty → no filter. _matches_filters treats an
    # empty tuple as "must match a prefix" (startswith(()) is always False),
    # so passing () instead of None silently drops every line.
    min_level = level if level and level.upper() != "ALL" else None
    if component and component.lower() != "all":
        comp_prefixes = COMPONENT_PREFIXES.get(component)
        if comp_prefixes is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown component: {component}. "
                f"Available: {', '.join(sorted(COMPONENT_PREFIXES))}",
            )
    else:
        comp_prefixes = None

    has_filters = bool(min_level or comp_prefixes or search)
    result = _read_tail(
        log_path,
        min(lines, 500) if not search else 2000,
        has_filters=has_filters,
        min_level=min_level,
        component_prefixes=comp_prefixes,
    )
    # Post-filter by search term (case-insensitive substring match).
    # _read_tail doesn't support free-text search, so we filter here and
    # trim to the requested line count afterward.
    if search:
        needle = search.lower()
        result = [l for l in result if needle in l.lower()][-min(lines, 500) :]
    return {"file": file, "lines": result}


@app.get("/api/logs/download")
async def download_log(file: str = "agent"):
    from spark_cli.logs import LOG_FILES

    log_name = LOG_FILES.get(file)
    if not log_name:
        raise HTTPException(status_code=400, detail=f"Unknown log file: {file}")
    log_path = get_spark_home() / "logs" / log_name
    if not log_path.exists():
        raise HTTPException(status_code=404, detail=f"Log file not found: {file}")
    return FileResponse(log_path, media_type="text/plain", filename=log_name)


# ---------------------------------------------------------------------------
# Cron job management endpoints
# ---------------------------------------------------------------------------


class CronJobCreate(BaseModel):
    prompt: str
    schedule: str
    name: str = ""
    deliver: str = "local"


class CronJobUpdate(BaseModel):
    updates: dict


@app.get("/api/cron/jobs")
async def list_cron_jobs():
    from cron.jobs import list_jobs

    return list_jobs(include_disabled=True)


@app.get("/api/cron/jobs/{job_id}")
async def get_cron_job(job_id: str):
    from cron.jobs import get_job

    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/api/cron/jobs")
async def create_cron_job(body: CronJobCreate):
    from cron.jobs import create_job

    try:
        job = create_job(
            prompt=body.prompt,
            schedule=body.schedule,
            name=body.name,
            deliver=body.deliver,
        )
        return job
    except Exception as e:
        _log.exception("POST /api/cron/jobs failed")
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/cron/jobs/{job_id}")
async def update_cron_job(job_id: str, body: CronJobUpdate):
    from cron.jobs import parse_schedule, update_job

    try:
        updates = dict(body.updates)
        if isinstance(updates.get("schedule"), str):
            updates["schedule"] = parse_schedule(updates["schedule"])
        job = update_job(job_id, updates)
    except Exception as e:
        _log.exception("PUT /api/cron/jobs/%s failed", job_id)
        raise HTTPException(status_code=400, detail=str(e))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/api/cron/jobs/{job_id}/pause")
async def pause_cron_job(job_id: str):
    from cron.jobs import pause_job

    job = pause_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/api/cron/jobs/{job_id}/resume")
async def resume_cron_job(job_id: str):
    from cron.jobs import resume_job

    job = resume_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/api/cron/jobs/{job_id}/trigger")
async def trigger_cron_job(job_id: str):
    from cron.jobs import trigger_job

    job = trigger_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.delete("/api/cron/jobs/{job_id}")
async def delete_cron_job(job_id: str):
    from cron.jobs import remove_job

    if not remove_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Skills & Tools endpoints
# ---------------------------------------------------------------------------


class SkillToggle(BaseModel):
    name: str
    enabled: bool


@app.get("/api/skills")
async def get_skills():
    from tools.skills_tool import _find_all_skills
    from tools.skills_sync import sync_skills
    from spark_cli.skills_config import get_disabled_skills

    try:
        sync_skills(quiet=True)
    except Exception:
        pass

    config = load_config()
    disabled = get_disabled_skills(config)
    skills = _find_all_skills(skip_disabled=True)

    usage_by_name: dict = {}
    try:
        from tools.skill_usage import all_records
        usage_by_name = all_records()
    except Exception:
        pass

    for s in skills:
        s["enabled"] = s["name"] not in disabled
        rec = usage_by_name.get(s["name"])
        if rec:
            s["use_count"] = int(rec.get("use_count") or 0)
            s["view_count"] = int(rec.get("view_count") or 0)
            s["patch_count"] = int(rec.get("patch_count") or 0)
            s["skill_state"] = rec.get("state", "active")
        else:
            s["use_count"] = 0
            s["view_count"] = 0
            s["patch_count"] = 0
            s["skill_state"] = "active"
    return skills


@app.put("/api/skills/toggle")
async def toggle_skill(body: SkillToggle):
    from spark_cli.skills_config import get_disabled_skills, save_disabled_skills

    config = load_config()
    disabled = get_disabled_skills(config)
    if body.enabled:
        disabled.discard(body.name)
    else:
        disabled.add(body.name)
    save_disabled_skills(config, disabled)
    return {"ok": True, "name": body.name, "enabled": body.enabled}


@app.get("/api/tools/toolsets")
async def get_toolsets():
    from spark_cli.tools_config import (
        _get_effective_configurable_toolsets,
        _get_platform_tools,
        _toolset_has_keys,
    )
    from core.toolsets import resolve_toolset

    config = load_config()
    enabled_toolsets = _get_platform_tools(
        config,
        "cli",
        include_default_mcp_servers=False,
    )
    result = []
    for name, label, desc in _get_effective_configurable_toolsets():
        try:
            tools = sorted(set(resolve_toolset(name)))
        except Exception:
            tools = []
        is_enabled = name in enabled_toolsets
        result.append(
            {
                "name": name,
                "label": label,
                "description": desc,
                "enabled": is_enabled,
                "available": is_enabled,
                "configured": _toolset_has_keys(name, config),
                "tools": tools,
            }
        )
    return result


# ---------------------------------------------------------------------------
# Raw YAML config endpoint
# ---------------------------------------------------------------------------


class RawConfigUpdate(BaseModel):
    yaml_text: str


@app.get("/api/config/raw")
async def get_config_raw():
    path = get_config_path()
    if not path.exists():
        return {"yaml": ""}
    return {"yaml": path.read_text(encoding="utf-8")}


@app.put("/api/config/raw")
async def update_config_raw(body: RawConfigUpdate):
    try:
        parsed = yaml.safe_load(body.yaml_text)
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=400, detail="YAML must be a mapping")
        save_config(parsed)
        for sid in list(_web_agents.keys()):
            if not _is_web_turn_active(sid):
                _close_web_agent(sid)
        return {"ok": True}
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {e}")


# ---------------------------------------------------------------------------
# Token / cost analytics endpoint
# ---------------------------------------------------------------------------


@app.get("/api/analytics/usage")
async def get_usage_analytics(days: int = 30):
    from core.spark_state import SessionDB

    db = SessionDB()
    try:
        cutoff = time.time() - (days * 86400)
        cur = db._conn.execute(
            """
            SELECT date(started_at, 'unixepoch') as day,
                   SUM(input_tokens) as input_tokens,
                   SUM(output_tokens) as output_tokens,
                   SUM(cache_read_tokens) as cache_read_tokens,
                   SUM(reasoning_tokens) as reasoning_tokens,
                   COALESCE(SUM(estimated_cost_usd), 0) as estimated_cost,
                   COALESCE(SUM(actual_cost_usd), 0) as actual_cost,
                   COUNT(*) as sessions
            FROM sessions WHERE started_at > ?
            GROUP BY day ORDER BY day
        """,
            (cutoff,),
        )
        daily = [dict(r) for r in cur.fetchall()]

        cur2 = db._conn.execute(
            """
            SELECT model,
                   SUM(input_tokens) as input_tokens,
                   SUM(output_tokens) as output_tokens,
                   COALESCE(SUM(estimated_cost_usd), 0) as estimated_cost,
                   COUNT(*) as sessions
            FROM sessions WHERE started_at > ? AND model IS NOT NULL
            GROUP BY model ORDER BY SUM(input_tokens) + SUM(output_tokens) DESC
        """,
            (cutoff,),
        )
        by_model = [dict(r) for r in cur2.fetchall()]

        cur3 = db._conn.execute(
            """
            SELECT SUM(input_tokens) as total_input,
                   SUM(output_tokens) as total_output,
                   SUM(cache_read_tokens) as total_cache_read,
                   SUM(reasoning_tokens) as total_reasoning,
                   COALESCE(SUM(estimated_cost_usd), 0) as total_estimated_cost,
                   COALESCE(SUM(actual_cost_usd), 0) as total_actual_cost,
                   COUNT(*) as total_sessions
            FROM sessions WHERE started_at > ?
        """,
            (cutoff,),
        )
        totals = dict(cur3.fetchone())

        return {
            "daily": daily,
            "by_model": by_model,
            "totals": totals,
            "period_days": days,
        }
    finally:
        db.close()


@app.get("/api/analytics/skills")
async def get_skills_analytics(limit: int = 20):
    try:
        from tools.skill_usage import top_skills, lifecycle_counts
        return {
            "top_skills": top_skills(limit=limit),
            "lifecycle_counts": lifecycle_counts(),
        }
    except Exception as e:
        return {"top_skills": [], "lifecycle_counts": {"active": 0, "stale": 0, "archived": 0}, "error": str(e)}


# ---------------------------------------------------------------------------
# Kanban board — session status management
# ---------------------------------------------------------------------------

_KANBAN_STATUSES = {"backlog", "active", "review", "done"}

# In-memory state for web chat sessions
_web_queues: Dict[str, asyncio.Queue] = {}   # session_id → token queue (active streams)
_web_agents: Dict[str, Any] = {}             # session_id → AIAgent (multi-turn context)
_web_agent_signatures: Dict[str, Any] = {}    # session_id → effective model/runtime signature


def _web_max_iterations() -> int:
    """Bound web turns so routine dashboard chats do not become runaway tool loops."""
    raw = os.getenv("SPARK_WEB_MAX_ITERATIONS", "").strip()
    if not raw:
        raw = str((load_config().get("dashboard") or {}).get("max_iterations") or "")
    if raw:
        try:
            return max(1, min(90, int(raw)))
        except (TypeError, ValueError):
            _log.warning("Invalid web max-iterations setting: %r", raw)
    return 20


# Codex usage-limit hit state — updated when a usage_limit_reached error occurs during inference.
# Shape: {"hit_at": float, "resets_at": float | None, "resets_in_seconds": int | None}
_codex_usage_limit_hit: Dict[str, Any] = {}


class KanbanUpdate(BaseModel):
    status: str


class ConversationCreate(BaseModel):
    message: str
    model: Optional[str] = None
    context_items: list = []


class ConversationMessage(BaseModel):
    message: str
    context_items: list = []


class ConversationInterrupt(BaseModel):
    message: Optional[str] = None


class ConversationModelBody(BaseModel):
    model: str


class ConversationForkBody(BaseModel):
    from_message_index: Optional[int] = None


class ConversationRetryBody(BaseModel):
    message_index: int
    message: Optional[str] = None


class ConversationApprovalBody(BaseModel):
    choice: str
    resolve_all: bool = False


def _publish_web_status(session_id: str, kind: str, message: str, *, phase: Optional[str] = None) -> None:
    text = _truncate_str(message, 2000)
    _touch_web_turn(session_id, status=text, phase=phase or str(kind or "status"))
    _publish_event(
        "chat.status",
        {"kind": kind, "message": text},
        session_id,
    )


def _make_web_chat_callbacks(
    session_id: str,
    queue: asyncio.Queue,
    loop: asyncio.AbstractEventLoop,
):
    # Mutable holder so the migrate callback can switch the channel that
    # subsequent events publish on after a compression-driven session split.
    current_session_id = [session_id]
    tool_started_monotonic: dict[str, float] = {}

    def publish_status(kind: str, message: str, *, phase: Optional[str] = None) -> None:
        _publish_web_status(current_session_id[0], kind, message, phase=phase)

    def token_callback(token: Optional[str]) -> None:
        if token is None:
            return
        token = _sanitize_web_chat_text(token)
        if not token:
            return
        _append_web_turn_token(current_session_id[0], token)
        try:
            loop.call_soon_threadsafe(queue.put_nowait, token)
        except Exception:
            pass
        _publish_event("chat.token", {"t": token}, current_session_id[0])

    def tool_start_callback(tid: str, name: str, args: Any) -> None:
        started_at = time.time()
        tool_started_monotonic[tid] = time.monotonic()
        publish_status("tool_running", f"Tool running: {name}", phase="tool")
        _publish_event(
            "chat.tool_start",
            {"id": tid, "name": name, "args": _json_safe(args), "ts": started_at, "started_at": started_at},
            current_session_id[0],
        )

    def tool_complete_callback(tid: str, name: str, args: Any, result: Any) -> None:
        ended_at = time.time()
        started = tool_started_monotonic.pop(tid, None)
        duration_seconds = max(0.0, time.monotonic() - started) if started is not None else None
        publish_status("tool_finished", f"Tool finished: {name}", phase="streaming")
        _publish_event(
            "chat.tool_end",
            {
                "id": tid,
                "name": name,
                "args": _json_safe(args),
                **_tool_result_preview(result),
                "ts": ended_at,
                "ended_at": ended_at,
                **({"duration_seconds": duration_seconds} if duration_seconds is not None else {}),
            },
            current_session_id[0],
        )

    def reasoning_callback(text: str) -> None:
        _touch_web_turn(current_session_id[0], phase="reasoning")
        _publish_event("chat.reasoning", {"text": _truncate_str(text, 8000)}, current_session_id[0])

    def status_callback(kind: str, message: str) -> None:
        publish_status(kind, message)

    def session_migrated_callback(old_id: str, new_id: str, reason: str) -> None:
        # Publish the migration event on the OLD channel so listeners pinned
        # to it receive it and update their pointer. Then switch the holder so
        # all subsequent events flow on the NEW channel — otherwise the UI
        # would update activeSessionRef to new_id and then drop every
        # following event because the filter would no longer match.
        old_key, turn = _get_web_turn(old_id)
        if old_key and turn:
            _web_active_turns.pop(old_key, None)
            turn.last_event_at = time.time()
            turn.phase = "streaming"
            turn.status = "Context compressed; continuing…"
            turn.active_agent_session_id = new_id
            _web_active_turns[new_id] = turn
        if old_id in _web_agents and new_id not in _web_agents:
            _web_agents[new_id] = _web_agents[old_id]
            _web_agent_signatures[new_id] = _web_agent_signatures.get(old_id)
        _publish_event(
            "chat.session_migrated",
            {"old_session_id": old_id, "new_session_id": new_id, "reason": reason},
            current_session_id[0],
        )
        current_session_id[0] = new_id
        publish_status("context_compression", "Context compressed; continuing…", phase="streaming")

    def subagent_event_callback(payload: dict) -> None:
        if not isinstance(payload, dict):
            payload = {"event": "status", "payload": {"preview": str(payload)}}
        _touch_web_turn(current_session_id[0], phase="subagent")
        _persist_and_publish_subagent_event(current_session_id[0], payload)

    return (
        token_callback,
        tool_start_callback,
        tool_complete_callback,
        reasoning_callback,
        status_callback,
        session_migrated_callback,
        subagent_event_callback,
    )


def _last_assistant_message_info(session_id: str) -> Dict[str, Any]:
    try:
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            for msg in reversed(db.get_messages(session_id)):
                if msg.get("role") == "assistant":
                    return {
                        "final_assistant_message_id": msg.get("id"),
                        "final_assistant_present": bool(str(msg.get("content") or "").strip()),
                    }
        finally:
            db.close()
    except Exception:
        _log.debug("last assistant lookup failed session=%s", session_id, exc_info=True)
    return {"final_assistant_message_id": None, "final_assistant_present": False}


def _turn_done_payload(
    result: Any,
    session_id: Optional[str] = None,
    *,
    interrupted: bool = False,
    migrated_session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Extract token/cost stats from a run_conversation() result for chat.turn_done."""
    payload: Dict[str, Any] = {
        "session_id": session_id,
        "message_count": _session_message_count(session_id) if session_id else 0,
        "interrupted": interrupted,
        "migrated_session_id": migrated_session_id,
        "backend_error_class": None,
    }
    if session_id:
        payload.update(_last_assistant_message_info(session_id))
    if not isinstance(result, dict):
        return payload
    payload.update(
        {
            "tokens": {
            "input": result.get("input_tokens", 0) or 0,
            "output": result.get("output_tokens", 0) or 0,
            "cache_read": result.get("cache_read_tokens", 0) or 0,
            "cache_write": result.get("cache_write_tokens", 0) or 0,
            },
            "cost_usd": result.get("estimated_cost_usd"),
            "model": result.get("model"),
            "backend_error_class": result.get("backend_error_class"),
        }
    )
    return payload


def _execute_web_slash_command(session_id: str, message: str) -> "str | None":
    """Handle a slash command from the web UI. Returns response text, or None to fall through to the agent."""
    if not message.startswith("/"):
        return None

    from spark_cli.commands import resolve_command

    raw_parts = message[1:].split(maxsplit=1)
    cmd_name = raw_parts[0].lower() if raw_parts else ""
    args = raw_parts[1] if len(raw_parts) > 1 else ""

    if not cmd_name:
        return None

    cmd_def = resolve_command(cmd_name)
    if not cmd_def:
        return None  # Unknown command — let the agent handle it

    if cmd_def.gateway_only:
        return None  # Gateway-only — agent handles naturally

    if cmd_def.cli_only and not cmd_def.web_available:
        return f"`/{cmd_def.name}` is only available in the CLI."

    canonical = cmd_def.name

    if canonical in ("new", "reset"):
        return "To start a new conversation, click **New thread** in the sidebar."

    if canonical == "help":
        return _web_cmd_help()
    if canonical == "history":
        return _web_cmd_history(session_id)
    if canonical == "memory":
        return _web_cmd_memory()
    if canonical == "learnings":
        return _web_cmd_learnings()
    if canonical == "sessions":
        return _web_cmd_sessions()
    if canonical == "config":
        return _web_cmd_config()
    if canonical == "tools":
        return _web_cmd_tools(args)
    if canonical == "toolsets":
        return _web_cmd_toolsets()
    if canonical == "computer-use":
        return _web_cmd_computer_use(args)
    if canonical == "skills":
        return _web_cmd_skills(args)
    if canonical == "cron":
        return _web_cmd_cron()
    if canonical == "plugins":
        return _web_cmd_plugins()
    if canonical == "files":
        return _web_cmd_files()
    if canonical == "save":
        return _web_cmd_save(session_id)
    if canonical == "status":
        return _web_cmd_status(session_id)

    if canonical == "feedback":
        return ""  # frontend injects form directly; return "" to prevent agent fallthrough

    return None  # Other web-available commands fall through to the agent


def _web_cmd_computer_use(args: str) -> "str | None":
    import platform

    if platform.system() != "Darwin":
        return "computer_use is only available on macOS."

    try:
        from spark_cli.tools_config import enable_computer_use_web_toolset

        enable_computer_use_web_toolset()
    except Exception as e:
        return f"Could not enable computer_use for the desktop app: {e}"

    if args.strip():
        return None

    try:
        from tools.computer_use.cua_backend import cua_driver_resolution_hint, is_available

        if not is_available():
            hint = cua_driver_resolution_hint()
            suffix = f"\n\n{hint}" if hint else ""
            return "computer_use is enabled for the desktop app, but cua-driver is not available yet." + suffix
    except Exception:
        pass

    return "Computer-use is enabled for the desktop app. Describe the desktop task in your next message."


def _web_cmd_help() -> str:
    from spark_cli.commands import COMMAND_REGISTRY
    lines = ["**Available commands**\n"]
    by_cat: dict[str, list] = {}
    for cmd in COMMAND_REGISTRY:
        if cmd.gateway_only:
            continue
        if cmd.cli_only and not cmd.web_available:
            continue
        by_cat.setdefault(cmd.category, []).append(cmd)
    for cat, cmds in by_cat.items():
        lines.append(f"**{cat}**")
        for cmd in cmds:
            hint = f" `{cmd.args_hint}`" if cmd.args_hint else ""
            lines.append(f"• `/{cmd.name}`{hint} — {cmd.description}")
        lines.append("")
    return "\n".join(lines).strip()


def _web_cmd_history(session_id: str) -> str:
    try:
        from core.spark_state import SessionDB
        db = SessionDB()
        try:
            messages = db.get_messages(session_id)
        finally:
            db.close()
    except Exception as e:
        return f"Could not load history: {e}"
    user_assistant = [m for m in messages if m.get("role") in ("user", "assistant")]
    if not user_assistant:
        return "No conversation history yet."
    lines = [f"**Conversation history** ({len(user_assistant)} messages)\n"]
    for msg in user_assistant[-40:]:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if isinstance(content, list):
            parts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
            content = " ".join(parts)
        label = "**You**" if role == "user" else "**Spark**"
        snippet = str(content)[:300].replace("\n", " ")
        if len(str(content)) > 300:
            snippet += "…"
        lines.append(f"{label}: {snippet}")
    return "\n".join(lines)


def _web_cmd_memory() -> str:
    from core.spark_constants import get_spark_home
    try:
        memories_dir = get_spark_home() / "memories"
        if not memories_dir.exists():
            return "No memories directory found. Memory is built automatically as you chat."
        sections = []
        for fname in ("MEMORY.md", "USER.md", "FEEDBACK.md"):
            fpath = memories_dir / fname
            if fpath.exists():
                content = fpath.read_text(encoding="utf-8").strip()
                if content:
                    lines = content.splitlines()
                    preview = "\n".join(lines[:40])
                    if len(lines) > 40:
                        preview += f"\n… ({len(lines) - 40} more lines)"
                    sections.append(f"**{fname}**\n```\n{preview}\n```")
        if not sections:
            return "Memory files exist but are empty — memories accumulate as you chat."
        return "\n\n".join(sections)
    except Exception as e:
        return f"Could not read memories: {e}"


def _web_cmd_learnings() -> str:
    """Read-only review of recent dreams + pending memory removals for the web UI."""
    from datetime import datetime

    try:
        from core import dream as dream_mod
        recent = dream_mod.list_recent_dreams(limit=5)
        pending = dream_mod.get_pending_removals()
    except Exception as e:
        return f"Could not read learnings: {e}"

    if not recent and not pending:
        return "No learnings yet. Run `/dream` to reflect on past sessions."

    sections = []
    if recent:
        lines = []
        for d in recent:
            try:
                when = datetime.fromtimestamp(d["modified"]).strftime("%Y-%m-%d %H:%M")
            except Exception:
                when = ""
            lines.append(f"- **{d['title']}** _({when})_")
        sections.append("**Recent dreams**\n" + "\n".join(lines))

    if pending:
        lines = [f"- `fact {it.get('fact_id')}` — {it.get('reason', '')}" for it in pending[:20]]
        if len(pending) > 20:
            lines.append(f"- … and {len(pending) - 20} more")
        sections.append(
            f"**{len(pending)} fact(s) flagged stale**\n"
            + "\n".join(lines)
            + "\n\n_Confirm removals from the CLI with `/learnings`._"
        )
    else:
        sections.append("_No memory removals awaiting review._")

    return "\n\n".join(sections)


def _web_cmd_sessions() -> str:
    try:
        from core.spark_state import SessionDB
        db = SessionDB()
        try:
            sessions = db.list_sessions_rich(limit=20)
        finally:
            db.close()
    except Exception as e:
        return f"Could not load sessions: {e}"
    if not sessions:
        return "No sessions found."
    lines = ["**Recent sessions**\n"]
    for s in sessions:
        sid = s.get("id", "")
        title = s.get("title") or "(untitled)"
        ts = s.get("updated_at") or s.get("created_at") or ""
        if ts:
            try:
                from datetime import datetime
                if isinstance(ts, (int, float)):
                    ts = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
                elif isinstance(ts, str):
                    ts = datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
            except Exception:
                ts = str(ts)
        turns = s.get("turn_count", "?")
        lines.append(f"• `{sid[:16]}…` — {title} ({turns} turns, {ts})")
    return "\n".join(lines)


def _web_cmd_config() -> str:
    try:
        import yaml
        cfg = load_config()
        data = cfg._data if hasattr(cfg, "_data") else (dict(cfg) if isinstance(cfg, dict) else {})
        safe = {}
        secret_keys = {"api_key", "token", "secret", "password", "webhook"}
        for k, v in data.items():
            safe[k] = "***" if any(s in str(k).lower() for s in secret_keys) else v
        return f"**Current configuration:**\n```yaml\n{yaml.dump(safe, default_flow_style=False).strip()}\n```"
    except Exception as e:
        return f"Could not read config: {e}"


def _web_cmd_tools(args: str) -> str:
    import shlex
    try:
        tokens = shlex.split(args) if args else []
    except ValueError:
        tokens = args.split() if args else []
    subcommand = tokens[0] if tokens else ""
    if subcommand in ("disable", "enable"):
        names = tokens[1:]
        if not names:
            return f"Usage: `/tools {subcommand} <name> [name …]`"
        try:
            import io, sys
            from argparse import Namespace
            from spark_cli.tools_config import tools_disable_enable_command
            buf = io.StringIO()
            old_stdout, sys.stdout = sys.stdout, buf
            try:
                tools_disable_enable_command(Namespace(tools_action=subcommand, names=names, platform="web"))
            finally:
                sys.stdout = old_stdout
            return buf.getvalue().strip() or f"Tools {subcommand}d: {', '.join(names)}"
        except Exception as e:
            return f"Failed to {subcommand} tools: {e}"
    try:
        from core.model_tools import get_tool_definitions
        tools = get_tool_definitions(quiet_mode=True)
        if not tools:
            return "No tools currently loaded."
        lines = [f"**Active tools** ({len(tools)} total)\n"]
        for t in sorted(tools, key=lambda x: x.get("function", {}).get("name", "")):
            name = t.get("function", {}).get("name", "?")
            desc = t.get("function", {}).get("description", "")
            lines.append(f"• `{name}` — {desc.split('.')[0][:80] if desc else ''}")
        lines.append("\nUse `/tools disable <name>` or `/tools enable <name>` to toggle.")
        return "\n".join(lines)
    except Exception as e:
        return f"Could not list tools: {e}"


def _web_cmd_toolsets() -> str:
    try:
        from tools.toolsets import get_all_toolsets, get_toolset_info
        from spark_cli.tools_config import _get_platform_tools
        cfg = load_config()
        enabled = set(_get_platform_tools(cfg, "web") or [])
        all_toolsets = get_all_toolsets()
        if not all_toolsets:
            return "No toolsets found."
        lines = ["**Available toolsets**\n"]
        for name in sorted(all_toolsets.keys()):
            info = get_toolset_info(name)
            if info:
                count = info.get("tool_count", "?")
                desc = info.get("description", "")
                marker = "✓" if name in enabled else "○"
                lines.append(f"{marker} **{name}** [{count} tools] — {desc}")
        lines.append("\n✓ = currently enabled")
        return "\n".join(lines)
    except Exception as e:
        return f"Could not list toolsets: {e}"


def _web_cmd_skills(args: str) -> str:
    parts = args.split(maxsplit=1)
    subcommand = parts[0].lower() if parts else ""
    query = parts[1] if len(parts) > 1 else ""
    try:
        from agent.skill_commands import get_skill_commands
        skill_cmds = get_skill_commands()
    except Exception as e:
        return f"Could not load skills: {e}"
    if not skill_cmds:
        return "No skills installed."
    if subcommand == "search" and query:
        q = query.lower()
        matches = {k: v for k, v in skill_cmds.items()
                   if q in k.lower() or q in v.get("description", "").lower()}
        if not matches:
            return f"No skills matching `{query}`."
        lines = [f"**Skills matching '{query}':**\n"]
    else:
        matches = skill_cmds
        lines = [f"**Installed skills** ({len(matches)} total)\n"]
    for cmd_key in sorted(matches.keys()):
        info = matches[cmd_key]
        desc = info.get("description", "")
        lines.append(f"• `{cmd_key}` — {desc.split(chr(10))[0][:80] if desc else ''}")
    lines.append("\nType the skill command directly to invoke it.")
    return "\n".join(lines)


def _web_cmd_cron() -> str:
    try:
        import json
        from tools.cronjob_tools import cronjob as cronjob_tool
        result = json.loads(cronjob_tool(action="list"))
        jobs = result.get("jobs", []) if isinstance(result, dict) else []
        if not jobs:
            return "No scheduled tasks."
        lines = [f"**Scheduled tasks** ({len(jobs)} total)\n"]
        for job in jobs:
            name = job.get("name") or job.get("id", "?")
            schedule = job.get("schedule", "?")
            status = job.get("status", "active")
            prompt = job.get("prompt", "")
            short_prompt = prompt[:60] + ("…" if len(prompt) > 60 else "") if prompt else ""
            lines.append(f"• **{name}** `{schedule}` [{status}]{' — ' + short_prompt if short_prompt else ''}")
        return "\n".join(lines)
    except Exception as e:
        return f"Could not list cron tasks: {e}"


def _web_cmd_plugins() -> str:
    try:
        from spark_cli.plugins import get_plugin_manager
        mgr = get_plugin_manager()
        plugins = mgr.list_plugins()
        if not plugins:
            from core.spark_constants import display_spark_home
            return f"No plugins installed.\nDrop plugin directories into `{display_spark_home()}/plugins/` to get started."
        lines = [f"**Installed plugins** ({len(plugins)} total)\n"]
        for p in plugins:
            status = "✓" if p.get("enabled") else "✗"
            name = p.get("name", "?")
            version = f" v{p['version']}" if p.get("version") else ""
            tools = f"{p['tools']} tools" if p.get("tools") else ""
            hooks = f"{p['hooks']} hooks" if p.get("hooks") else ""
            detail_parts = [x for x in [tools, hooks] if x]
            detail = f" ({', '.join(detail_parts)})" if detail_parts else ""
            error = f" — ⚠ {p['error']}" if p.get("error") else ""
            lines.append(f"{status} **{name}**{version}{detail}{error}")
        return "\n".join(lines)
    except Exception as e:
        return f"Plugin system error: {e}"


def _web_cmd_files() -> str:
    import glob
    import os
    try:
        cwd = os.environ.get("TERMINAL_CWD", os.getcwd())
        files = sorted(glob.glob("**/*", recursive=True, root_dir=cwd))
        files = [f for f in files if os.path.isfile(os.path.join(cwd, f)) and not any(
            seg.startswith(".") or seg in ("__pycache__", "node_modules", ".git")
            for seg in f.split(os.sep)
        )][:100]
        if not files:
            return f"No files found in workspace: `{cwd}`"
        lines = [f"**Workspace files** in `{cwd}` ({len(files)} shown)\n"]
        lines.extend(f"• `{f}`" for f in files[:50])
        if len(files) > 50:
            lines.append(f"… and {len(files) - 50} more")
        lines.append("\nReference files in your message with `@path/to/file`.")
        return "\n".join(lines)
    except Exception as e:
        return f"Could not list files: {e}"


def _web_cmd_save(session_id: str) -> str:
    import json
    from datetime import datetime
    from core.spark_constants import get_spark_home
    try:
        from core.spark_state import SessionDB
        db = SessionDB()
        try:
            history = db.get_messages(session_id)
        finally:
            db.close()
    except Exception as e:
        return f"Could not load conversation: {e}"
    if not history:
        return "Nothing to save — conversation is empty."
    try:
        save_dir = get_spark_home() / "saved_conversations"
        save_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"conversation_{ts}_{session_id[:8]}.json"
        path = save_dir / filename
        path.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")
        return f"✓ Conversation saved to `{path}`"
    except Exception as e:
        return f"Could not save conversation: {e}"


def _web_cmd_status(session_id: str) -> str:
    try:
        from core.spark_state import SessionDB
        db = SessionDB()
        try:
            row = db.get_session(session_id)
            messages = db.get_messages(session_id)
        finally:
            db.close()
    except Exception as e:
        return f"Could not load session: {e}"
    if not row:
        return f"Session `{session_id}` not found."
    title = row.get("title") or "(untitled)"
    model = row.get("model") or "unknown"
    source = row.get("source") or "web"
    turn_count = sum(1 for m in messages if m.get("role") == "user")
    lines = [
        "**Session status**\n",
        f"• **ID:** `{session_id}`",
        f"• **Title:** {title}",
        f"• **Model:** {model}",
        f"• **Source:** {source}",
        f"• **Turns:** {turn_count}",
        f"• **Messages:** {len(messages)}",
    ]
    return "\n".join(lines)


def _get_workspace_root(slug: Optional[str] = None) -> "Path":
    """Return the resolved workspace root, optionally scoped to a project slug."""
    base = (get_spark_home() / "workspace").resolve()
    if slug:
        return (base / slug).resolve()
    return base


def _resolve_context_item_content(item: Any, workspace_root: "Path") -> Optional[str]:
    """Return the text to inject for a context item, or None if nothing to inject."""
    from spark_cli.context_models import InclusionMode

    mode = item.get("inclusion_mode", "full")
    source_path = item.get("source_path")
    content = item.get("content")

    if content:
        return content

    if not source_path:
        return None

    try:
        resolved = (workspace_root / source_path.lstrip("/")).resolve()
        resolved.relative_to(workspace_root.resolve())
    except (ValueError, Exception):
        return None

    if mode == InclusionMode.path_only:
        return None

    if not resolved.exists() or not resolved.is_file():
        return None

    try:
        if mode == InclusionMode.full:
            return resolved.read_text(errors="replace")

        if mode == InclusionMode.excerpt:
            import json as _json
            excerpt_range = item.get("excerpt_range")
            lines = resolved.read_text(errors="replace").splitlines()
            if excerpt_range:
                try:
                    start, end = _json.loads(excerpt_range) if isinstance(excerpt_range, str) else excerpt_range
                    return "\n".join(lines[max(0, start - 1):end])
                except Exception:
                    pass
            return "\n".join(lines[:100])

        if mode == InclusionMode.search:
            import re as _re
            query = item.get("search_query", "")
            if not query:
                return None
            text = resolved.read_text(errors="replace")
            lines = text.splitlines()
            pattern = _re.compile(_re.escape(query), _re.IGNORECASE)
            snippets = []
            for i, line in enumerate(lines):
                if pattern.search(line):
                    ctx_start = max(0, i - 3)
                    ctx_end = min(len(lines), i + 4)
                    snippets.append("\n".join(lines[ctx_start:ctx_end]))
                    if len(snippets) >= 5:
                        break
            return "\n---\n".join(snippets) if snippets else None

        if mode == "diff":
            import subprocess as _sub
            try:
                result = _sub.run(
                    ["git", "diff", "HEAD", "--", str(resolved)],
                    capture_output=True,
                    text=True,
                    cwd=str(resolved.parent),
                    timeout=10,
                )
                diff_text = result.stdout.strip()
                if diff_text:
                    return diff_text
                # No unstaged diff — try staged
                result2 = _sub.run(
                    ["git", "diff", "--cached", "--", str(resolved)],
                    capture_output=True,
                    text=True,
                    cwd=str(resolved.parent),
                    timeout=10,
                )
                return result2.stdout.strip() or None
            except Exception:
                return None

    except Exception:
        return None

    return None


def _build_context_augmented_message(session_id: str, user_message: str, context_items: list) -> str:
    """Prepend resolved context item content to the user message."""
    if not context_items:
        return user_message

    workspace_root = _get_workspace_root()

    parts: list[str] = []
    for item in context_items:
        source_path = item.get("source_path")
        label = item.get("label") or (source_path.split("/")[-1] if source_path else "context")
        mode = item.get("inclusion_mode", "full")
        content = _resolve_context_item_content(item, workspace_root)

        if mode == "path_only" and source_path:
            parts.append(f"[Context file: {source_path}]")
        elif content:
            parts.append(f"[Context: {label}]\n{content}\n[/Context]")

    if not parts:
        return user_message

    context_block = "\n\n".join(parts)
    return f"{context_block}\n\n---\n\n{user_message}"


def _inject_brief_if_present(session_id: str, user_message: str) -> str:
    """Prepend the session brief (if any) as a labelled context block."""
    try:
        from core.spark_state import SessionDB
        db = SessionDB()
        try:
            brief = db.get_brief(session_id)
        finally:
            db.close()
        if brief and brief.strip():
            return f"[Session Brief]\n{brief.strip()}\n[/Session Brief]\n\n---\n\n{user_message}"
    except Exception:
        pass
    return user_message


def _refresh_web_agent_for_computer_use(agent: Any, user_message: str) -> None:
    if not isinstance(user_message, str):
        return

    import re

    match = re.search(r"(?m)^/(computer-use|cu|desktop-use)(?:\s|$)", user_message)
    cmd_name = match.group(1).lower() if match else ""
    if cmd_name not in {"computer-use", "cu", "desktop-use"}:
        return

    try:
        from core.model_tools import get_tool_definitions
        from spark_cli.config import load_config
        from spark_cli.tools_config import _get_platform_tools

        enabled_toolsets = _get_platform_tools(load_config(), "cli")
        disabled_toolsets = getattr(agent, "disabled_toolsets", None)
        tool_defs = get_tool_definitions(
            enabled_toolsets=enabled_toolsets,
            disabled_toolsets=disabled_toolsets,
            quiet_mode=True,
        )
        agent.enabled_toolsets = enabled_toolsets
        agent.tools = tool_defs
        agent.valid_tool_names = (
            {t["function"]["name"] for t in tool_defs}
            if tool_defs
            else set()
        )
        if hasattr(agent, "_invalidate_system_prompt"):
            agent._invalidate_system_prompt()
    except Exception:
        _log.debug("computer_use web tool refresh failed", exc_info=True)


def _run_web_agent_turn(
    agent: Any,
    user_message: str,
    conversation_history: Optional[list[dict[str, Any]]] = None,
    context_items: Optional[list] = None,
) -> Any:
    from tools.approval import reset_current_session_key, set_current_session_key

    if context_items:
        user_message = _build_context_augmented_message(agent.session_id, user_message, context_items)

    _refresh_web_agent_for_computer_use(agent, user_message)

    user_message = _inject_brief_if_present(agent.session_id, user_message)
    user_message = _with_long_document_delivery_instruction(user_message)

    tok = set_current_session_key(agent.session_id)
    try:
        if conversation_history is not None:
            result = agent.run_conversation(user_message, conversation_history=conversation_history)
        else:
            result = agent.run_conversation(user_message)
        _maybe_capture_codex_usage_limit(agent, result)
        return result
    finally:
        reset_current_session_key(tok)


def _maybe_capture_codex_usage_limit(agent: Any, result: Any) -> None:
    """Detect usage_limit_reached signals and store them in _codex_usage_limit_hit."""
    global _codex_usage_limit_hit
    try:
        provider = str(getattr(agent, "provider", "") or "").lower()
        if "codex" not in provider and "chatgpt" not in str(getattr(agent, "base_url", "") or "").lower():
            return
        # Check if the result text contains a usage limit message
        final_text = ""
        if isinstance(result, dict):
            final_text = str(result.get("final_response", "") or "")
        elif isinstance(result, str):
            final_text = result
        usage_limit_signals = [
            "usage limit", "usage_limit_reached", "rate limit reached",
            "resets in", "try again later",
        ]
        if not any(sig in final_text.lower() for sig in usage_limit_signals):
            return
        # Try to parse resets_in from the text or agent error state
        resets_in = None
        try:
            import re
            m = re.search(r"resets? in[^\d]*(\d+)\s*h", final_text, re.IGNORECASE)
            if m:
                resets_in = int(m.group(1)) * 3600
        except Exception:
            pass
        _codex_usage_limit_hit = {
            "hit_at": time.time(),
            "resets_in_seconds": resets_in,
            "resets_at": (time.time() + resets_in) if resets_in else None,
        }
    except Exception:
        pass


def _close_web_agent(session_id: str) -> None:
    agent = _web_agents.pop(session_id, None)
    _web_agent_signatures.pop(session_id, None)
    db = getattr(agent, "_session_db", None)
    close = getattr(db, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


def _default_web_chat_model() -> str:
    from spark_cli.model_config import read_global_model_config

    return read_global_model_config().model


def _resolve_web_turn_route(user_message: str) -> Dict[str, Any]:
    """Resolve the effective global model/runtime for one web chat turn."""
    from agent.smart_model_routing import resolve_turn_route
    from spark_cli.model_config import read_global_model_config
    from spark_cli.runtime_provider import resolve_runtime_provider

    cfg = load_config()
    model_cfg = read_global_model_config(cfg)
    runtime = resolve_runtime_provider(requested=None)
    model = model_cfg.model
    if not model and runtime.get("provider"):
        try:
            from spark_cli.models import get_default_model_for_provider

            model = get_default_model_for_provider(runtime["provider"])
        except Exception:
            pass

    primary = {
        "model": model,
        "api_key": runtime.get("api_key"),
        "base_url": runtime.get("base_url"),
        "provider": runtime.get("provider"),
        "api_mode": runtime.get("api_mode"),
        "command": runtime.get("command"),
        "args": list(runtime.get("args") or []),
        "credential_pool": runtime.get("credential_pool"),
    }
    route = resolve_turn_route(
        user_message,
        cfg.get("smart_model_routing", {}) or {},
        primary,
    )
    route["request_overrides"] = None
    return route


def _update_web_session_model(session_id: str, model: str) -> None:
    try:
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            db._conn.execute(
                "UPDATE sessions SET model = ? WHERE id = ?",
                (model, session_id),
            )
            db._conn.commit()
        finally:
            db.close()
    except Exception:
        _log.debug("session model update failed session=%s", session_id, exc_info=True)


def _new_web_agent(
    *,
    session_id: str,
    model: str,
    runtime: Optional[dict[str, Any]] = None,
    request_overrides: Optional[dict[str, Any]] = None,
    signature: Any = None,
    token_callback: Any,
    tool_start_callback: Any,
    tool_complete_callback: Any,
    reasoning_callback: Any,
    status_callback: Any,
    session_migrated_callback: Any = None,
    subagent_event_callback: Any = None,
    working_dir: Optional[str] = None,
) -> Any:
    from core.run_agent import AIAgent
    from core.spark_state import SessionDB

    _close_web_agent(session_id)
    runtime = runtime or {}
    agent = AIAgent(
        session_id=session_id,
        model=model,
        max_iterations=_web_max_iterations(),
        api_key=runtime.get("api_key"),
        base_url=runtime.get("base_url"),
        provider=runtime.get("provider"),
        api_mode=runtime.get("api_mode"),
        command=runtime.get("command"),
        args=list(runtime.get("args") or []),
        credential_pool=runtime.get("credential_pool"),
        request_overrides=request_overrides,
        stream_delta_callback=token_callback,
        tool_start_callback=tool_start_callback,
        tool_complete_callback=tool_complete_callback,
        reasoning_callback=reasoning_callback,
        status_callback=status_callback,
        session_migrated_callback=session_migrated_callback,
        subagent_event_callback=subagent_event_callback,
        quiet_mode=True,
        platform="web",
        session_db=SessionDB(),
        working_dir=working_dir,
    )
    _web_agents[session_id] = agent
    _web_agent_signatures[session_id] = signature
    return agent


def _emit_web_session_updated(session_id: str) -> None:
    try:
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            row = db.get_session(session_id)
            if row:
                _emit_sessions_changed("updated", session_id, row)
        finally:
            db.close()
    except Exception:
        _log.debug("session update emit failed session=%s", session_id, exc_info=True)


def _maybe_auto_title_web(
    agent: Any, session_id: str, user_message: str, result: Any
) -> None:
    """Auto-generate a session title after the first web exchange.

    Mirrors the CLI/gateway behaviour. Title generation runs in a background
    thread; when a title is set we broadcast ``sessions.changed`` so the open
    web client updates the thread name live (no reload required).
    """
    try:
        final = _extract_final_response(result)
        if not final:
            return
        session_db = getattr(agent, "_session_db", None)
        if session_db is None:
            return
        messages = result.get("messages", []) if isinstance(result, dict) else []

        from agent.title_generator import maybe_auto_title

        maybe_auto_title(
            session_db,
            session_id,
            user_message,
            final,
            messages,
            on_titled=lambda _title: _emit_web_session_updated(session_id),
        )
    except Exception:
        _log.debug("web auto-title failed session=%s", session_id, exc_info=True)


def _extract_final_response(result: Any) -> str:
    if isinstance(result, dict):
        final = result.get("final_response")
        return _sanitize_web_chat_text(final) if isinstance(final, str) else ""
    return ""


_LONG_ASSISTANT_ARTIFACT_CHARS = 20_000
_REPORT_ARTIFACT_CHARS = 6_000
_LONG_DOCUMENT_REQUEST_RE = re.compile(
    r"\b("
    r"markdown\s+report|comprehensive\s+(?:markdown\s+)?report|"
    r"long\s+and\s+structured|white\s*paper|whitepaper|"
    r"write\s+(?:a\s+)?(?:comprehensive\s+|long\s+)?(?:report|document|guide)|"
    r"generate\s+(?:a\s+)?(?:comprehensive\s+|long\s+)?(?:report|document|guide)"
    r")\b",
    re.IGNORECASE,
)


def _looks_like_long_document_request(message: str) -> bool:
    return bool(_LONG_DOCUMENT_REQUEST_RE.search(message or ""))


def _with_long_document_delivery_instruction(message: str) -> str:
    """Nudge report-like web turns toward file artifacts instead of huge chat rows."""
    if not _looks_like_long_document_request(message):
        return message
    if "Spark delivery instruction" in message:
        return message
    return (
        f"{message}\n\n"
        "[Spark delivery instruction: If this request needs a long markdown report, "
        "document, guide, or other large structured output, do not stream the full "
        "document inline in chat. Keep the chat response brief, create the full "
        "markdown as a workspace file using available file-writing tools, and give "
        "the user the file path/link. The chat response should summarize what was "
        "created rather than contain the entire report.]"
    )


def _safe_artifact_filename(text: str, fallback: str = "assistant-response") -> str:
    title = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            break
    if not title:
        title = text.strip().splitlines()[0] if text.strip() else fallback
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title.lower()).strip("-")
    return (slug or fallback)[:72].strip("-") or fallback


def _write_chat_markdown_artifact(session_id: str, content: str) -> tuple[Path, str, str]:
    workspace_root = get_spark_home() / "workspace"
    safe_session = re.sub(r"[^a-zA-Z0-9_.-]+", "-", session_id).strip("-") or "session"
    artifact_dir = workspace_root / "chat-artifacts" / safe_session
    artifact_dir.mkdir(parents=True, exist_ok=True)

    base = _safe_artifact_filename(content)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = artifact_dir / f"{stamp}-{base}.md"
    counter = 2
    while path.exists():
        path = artifact_dir / f"{stamp}-{base}-{counter}.md"
        counter += 1
    path.write_text(content, encoding="utf-8")

    rel_path = path.relative_to(workspace_root).as_posix()
    media_url = f"/api/media?path={urllib.parse.quote(str(path))}"
    return path, rel_path, media_url


def _assistant_artifact_card(content: str, rel_path: str, media_url: str) -> str:
    return (
        "I created the full markdown response as a file instead of placing a very "
        "large document inline in chat.\n\n"
        f"[Open the markdown file]({media_url})\n\n"
        f"`{rel_path}`\n\n"
        f"Saved {len(content):,} characters to the file. No content was hidden or discarded."
    )


def _maybe_materialize_large_assistant_response(
    session_id: str,
    user_message: str,
    final_response: str,
) -> str:
    if not final_response:
        return final_response
    should_artifact = len(final_response) >= _LONG_ASSISTANT_ARTIFACT_CHARS
    if not should_artifact and _looks_like_long_document_request(user_message):
        should_artifact = len(final_response) >= _REPORT_ARTIFACT_CHARS
    if not should_artifact:
        return final_response
    try:
        _path, rel_path, media_url = _write_chat_markdown_artifact(session_id, final_response)
        return _assistant_artifact_card(final_response, rel_path, media_url)
    except Exception:
        _log.debug("assistant artifact materialization failed session=%s", session_id, exc_info=True)
        return final_response


def _replace_message_content(message_id: Any, content: str, db: Any = None) -> None:
    try:
        if db is not None:
            db._conn.execute("UPDATE messages SET content = ? WHERE id = ?", (content, message_id))
            db._conn.commit()
            return
        from core.spark_state import SessionDB

        owned_db = SessionDB()
        try:
            owned_db._conn.execute("UPDATE messages SET content = ? WHERE id = ?", (content, message_id))
            owned_db._conn.commit()
        finally:
            owned_db.close()
    except Exception:
        _log.debug("assistant message replacement failed message_id=%s", message_id, exc_info=True)


def _strip_user_message_prefix(session_id: str, prefix: str, raw_message: str) -> None:
    """After the agent saves a user message with a context prefix, replace it with the clean version."""
    try:
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            db._conn.execute(
                "UPDATE messages SET content = ? WHERE session_id = ? AND role = 'user' AND content = ?",
                (raw_message, session_id, prefix + raw_message),
            )
            db._conn.commit()
        finally:
            db.close()
    except Exception:
        _log.debug("strip user message prefix failed session=%s", session_id, exc_info=True)


def _persist_web_turn_if_missing(
    session_id: str,
    user_message: str,
    result: Any,
    before_message_count: int,
) -> None:
    """Persist any missing pieces of a web turn.

    The agent may flush the current user message before the final assistant
    response is available. Treating any new row as a fully persisted turn makes
    the web UI lose the streamed answer when it reloads from SQLite.
    """
    try:
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            messages = db.get_messages(session_id)
            final_response = _extract_final_response(result)

            display_response = (
                _maybe_materialize_large_assistant_response(
                    session_id,
                    user_message,
                    final_response,
                )
                if final_response.strip()
                else ""
            )

            new_messages = messages[before_message_count:]
            user_messages = [m for m in new_messages if m.get("role") == "user"]
            delivery_instruction_user_messages = [
                m
                for m in user_messages
                if "Spark delivery instruction" in str(m.get("content") or "")
                and user_message in str(m.get("content") or "")
            ]
            has_user = any(m.get("content") == user_message for m in user_messages) or bool(
                delivery_instruction_user_messages
            )
            for message in delivery_instruction_user_messages:
                _replace_message_content(message.get("id"), user_message, db)

            assistant_messages = [
                m
                for m in new_messages
                if m.get("role") == "assistant" and str(m.get("content") or "").strip()
            ]
            has_assistant = bool(assistant_messages)

            if display_response and display_response != final_response and assistant_messages:
                latest = assistant_messages[-1]
                current = str(latest.get("content") or "").strip()
                if (
                    current == final_response
                    or current == final_response.strip()
                    or len(current) >= _REPORT_ARTIFACT_CHARS
                ):
                    _replace_message_content(latest.get("id"), display_response, db)

            if not has_user:
                db.append_message(session_id, "user", content=user_message)
            if display_response:
                if not has_assistant:
                    db.append_message(session_id, "assistant", content=display_response)
        finally:
            db.close()
    except Exception:
        _log.debug("web turn fallback persist failed session=%s", session_id, exc_info=True)


def _session_message_count(session_id: str) -> int:
    try:
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            return len(db.get_messages(session_id))
        finally:
            db.close()
    except Exception:
        _log.debug("session message count failed session=%s", session_id, exc_info=True)
        return 0


def _message_content_hash(message: dict[str, Any]) -> str:
    content = str(message.get("content") or "")
    return hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _conversation_signature(messages: list[dict[str, Any]]) -> dict[str, Any]:
    last_user = next((m for m in reversed(messages) if m.get("role") == "user"), None)
    last_assistant = next((m for m in reversed(messages) if m.get("role") == "assistant"), None)
    approx_tokens = sum(max(1, len(str(m.get("content") or "")) // 4) for m in messages)
    return {
        "count": len(messages),
        "last_role": messages[-1].get("role") if messages else None,
        "last_roles": [m.get("role") for m in messages[-5:]],
        "last_user_hash": _message_content_hash(last_user) if last_user else None,
        "last_assistant_present": bool(
            last_assistant and str(last_assistant.get("content") or "").strip()
        ),
        "approx_tokens": approx_tokens,
    }


def _agent_history_snapshot(agent: Any) -> list[dict[str, Any]]:
    session_messages = getattr(agent, "_session_messages", None)
    if isinstance(session_messages, list) and session_messages:
        return list(session_messages)
    warm_messages = getattr(agent, "messages", None)
    if isinstance(warm_messages, list) and warm_messages:
        return list(warm_messages)
    return []


def _web_history_flags(session_id: str) -> dict[str, bool]:
    flags = {"prior_interrupted": False, "migrated": False}
    try:
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            resolved = db.resolve_session_id(session_id)
            latest = db.resolve_latest_descendant(resolved or session_id)
            flags["migrated"] = bool(latest and resolved and latest != resolved)
            messages = db.get_messages(resolved or session_id)
            flags["prior_interrupted"] = bool(
                messages and messages[-1].get("finish_reason") == "interrupted"
            )
        finally:
            db.close()
    except Exception:
        _log.debug("web history flag lookup failed session=%s", session_id, exc_info=True)
    return flags


def _cached_web_agent_matches_history(
    session_id: str,
    agent: Any,
    db_history: list[dict[str, Any]],
) -> bool:
    cached_history = _agent_history_snapshot(agent)
    db_sig = _conversation_signature(db_history)
    cached_sig = _conversation_signature(cached_history)
    matches = (
        db_sig["count"] == cached_sig["count"]
        and db_sig["last_role"] == cached_sig["last_role"]
        and db_sig["last_user_hash"] == cached_sig["last_user_hash"]
        and db_sig["last_assistant_present"] == cached_sig["last_assistant_present"]
    )
    flags = _web_history_flags(session_id)
    _log.debug(
        "web context validation session=%s source=%s db_count=%s cached_count=%s db_last=%s cached_last=%s db_roles=%s cached_roles=%s db_tokens~%s cached_tokens~%s prior_interrupted=%s migrated=%s match=%s",
        session_id,
        "cached_agent" if cached_history else "empty_cached_agent",
        db_sig["count"],
        cached_sig["count"],
        db_sig["last_role"],
        cached_sig["last_role"],
        db_sig["last_roles"],
        cached_sig["last_roles"],
        db_sig["approx_tokens"],
        cached_sig["approx_tokens"],
        flags["prior_interrupted"],
        flags["migrated"],
        matches,
    )
    return matches


def _persist_interrupted_turn_boundary(session_id: str, message: Optional[str] = None) -> None:
    """Persist a small assistant boundary if interruption leaves a dangling user row."""
    try:
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            sid = db.resolve_session_id(session_id) or session_id
            messages = db.get_messages(sid)
            if not messages or messages[-1].get("role") != "user":
                return
            note = "Turn interrupted before a complete assistant response was saved."
            if message:
                note += " A redirect message was submitted for the next turn."
            db.append_message(sid, "assistant", content=note, finish_reason="interrupted")
        finally:
            db.close()
    except Exception:
        _log.debug("interrupted boundary persist failed session=%s", session_id, exc_info=True)


_MAX_CONTEXT_ITEMS = 20
_MAX_CONTEXT_ITEM_BYTES = 500 * 1024  # 500 KB per item in full mode


def _validate_context_items(raw_items: list, workspace_slug: Optional[str] = None) -> list:
    """Validate incoming context items. Returns validated list or raises HTTPException."""
    if not raw_items:
        return []
    if len(raw_items) > _MAX_CONTEXT_ITEMS:
        raise HTTPException(
            status_code=400,
            detail=f"Too many context items: max {_MAX_CONTEXT_ITEMS}, got {len(raw_items)}",
        )
    from spark_cli.context_models import ContextItem, InclusionMode

    workspace_root = _get_workspace_root()
    project_root = _get_workspace_root(workspace_slug) if workspace_slug else workspace_root

    validated = []
    for raw in raw_items:
        try:
            item = ContextItem.model_validate(raw)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid context item: {exc}") from exc

        if item.source_path:
            try:
                resolved = (project_root / item.source_path.lstrip("/")).resolve()
                resolved.relative_to(project_root)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Path traversal detected in context item: {item.source_path!r}",
                )

        if item.inclusion_mode == InclusionMode.full and item.size_bytes > _MAX_CONTEXT_ITEM_BYTES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Context item {item.id!r} exceeds size limit "
                    f"({item.size_bytes} > {_MAX_CONTEXT_ITEM_BYTES} bytes)"
                ),
            )

        validated.append(item.model_dump())
    return validated


def _persist_context_items(session_id: str, raw_items: list) -> None:
    if not raw_items:
        return
    try:
        import json as _json
        import time as _time
        from spark_cli.context_models import ContextItem
        from core.spark_state import SessionDB

        items = [ContextItem.model_validate(i) for i in raw_items]
        db = SessionDB()
        try:
            now = _time.time()
            db._conn.executemany(
                "INSERT OR REPLACE INTO context_items "
                "(id, session_id, type, source_path, inclusion_mode, scope, content, "
                "content_ref, size_bytes, excerpt_range, search_query, label, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        item.id,
                        session_id,
                        item.type,
                        item.source_path,
                        item.inclusion_mode,
                        item.scope,
                        item.content,
                        item.content_ref,
                        item.size_bytes,
                        _json.dumps(item.excerpt_range) if item.excerpt_range else None,
                        item.search_query,
                        item.label,
                        now,
                    )
                    for item in items
                ],
            )
            db._conn.commit()
        finally:
            db.close()
    except Exception:
        _log.debug("context items persist failed session=%s", session_id, exc_info=True)


def _count_tokens_fast(text: str) -> int:
    """Count tokens using tiktoken cl100k_base, falling back to char/4."""
    if not text:
        return 0
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return len(text) // 4


class TokenEstimateRequest(BaseModel):
    prompt: str = ""
    context_items: list = []
    brief: str = ""
    session_id: Optional[str] = None
    history_message_count: int = 0
    model: Optional[str] = None


@app.post("/api/estimate-tokens")
async def estimate_tokens(body: TokenEstimateRequest):
    from spark_cli.context_models import ContextBucket, ContextEstimate

    prompt_tokens = _count_tokens_fast(body.prompt)

    # Count attached context item tokens
    attached_tokens = 0
    item_buckets: list[ContextBucket] = []
    if body.context_items:
        workspace_root: Optional[Path] = None
        for raw in body.context_items:
            item = raw if isinstance(raw, dict) else (raw.model_dump() if hasattr(raw, "model_dump") else {})
            label = item.get("label") or item.get("source_path") or item.get("id", "item")
            mode = item.get("inclusion_mode", "full")
            if mode == "path_only":
                t = _count_tokens_fast(item.get("source_path", ""))
            else:
                content = item.get("content") or ""
                if not content and item.get("source_path") and workspace_root is None:
                    # Try to resolve workspace root from session
                    if body.session_id:
                        try:
                            from core.spark_state import SessionDB
                            db = SessionDB()
                            sess = db.get_session(body.session_id)
                            if sess and sess.get("workspace_slug"):
                                slug = sess["workspace_slug"]
                                workspace_root = _get_workspace_root(slug)
                        except Exception:
                            pass
                if not content and item.get("source_path") and workspace_root:
                    content = _resolve_context_item_content(item, workspace_root) or ""
                t = _count_tokens_fast(content)
            attached_tokens += t
            item_buckets.append(ContextBucket(label=label, tokens=t))

    pinned_tokens = _count_tokens_fast(body.brief)

    # Estimate history tokens from DB if session_id provided
    history_tokens = 0
    if body.session_id and body.history_message_count > 0:
        try:
            from core.spark_state import SessionDB
            db = SessionDB()
            messages = db.get_messages(body.session_id)
            db.close()
            # Take the most recent history_message_count messages
            recent = messages[-body.history_message_count:]
            for m in recent:
                history_tokens += _count_tokens_fast(m.get("content") or "")
        except Exception:
            pass

    total = prompt_tokens + attached_tokens + pinned_tokens + history_tokens

    # Determine context window from model capabilities
    context_window = 200_000
    if body.model:
        try:
            from agent.models_dev import get_model_capabilities
            mc = get_model_capabilities(model=body.model)
            if mc and mc.context_window > 0:
                context_window = mc.context_window
        except Exception:
            pass

    utilization = total / context_window if context_window > 0 else 0.0
    warning = None
    if utilization >= 0.95:
        warning = "limit_exceeded"
    elif utilization >= 0.80:
        warning = "compression_likely"

    buckets = [
        ContextBucket(label="Prompt", tokens=prompt_tokens),
        ContextBucket(label="Attached", tokens=attached_tokens, items=[b.label for b in item_buckets]),
        ContextBucket(label="Brief", tokens=pinned_tokens),
        ContextBucket(label="History", tokens=history_tokens),
    ]

    return ContextEstimate(
        prompt_tokens=prompt_tokens,
        attached_tokens=attached_tokens,
        pinned_tokens=pinned_tokens,
        history_tokens=history_tokens,
        total_tokens=total,
        context_window=context_window,
        utilization=utilization,
        warning=warning,
        buckets=buckets,
    )


@app.patch("/api/sessions/{session_id}/kanban")
async def update_session_kanban(session_id: str, body: KanbanUpdate):
    if body.status not in _KANBAN_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {', '.join(sorted(_KANBAN_STATUSES))}",
        )
    try:
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            db._conn.execute(
                "UPDATE sessions SET kanban_status = ? WHERE id = ?",
                (body.status, session_id),
            )
            db._conn.commit()
            changes = db._conn.execute("SELECT changes()").fetchone()[0]
            if changes == 0:
                raise HTTPException(status_code=404, detail="Session not found")
            row = db.get_session(session_id)
            _emit_sessions_changed("updated", session_id, row)
            return {"ok": True, "session_id": session_id, "status": body.status}
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception:
        _log.exception("PATCH /api/sessions/%s/kanban failed", session_id)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# Web chat — conversation endpoints with SSE streaming
# ---------------------------------------------------------------------------


@app.get("/api/commands")
async def get_slash_commands():
    """Return all web-available slash commands and installed skills for the command palette."""
    from spark_cli.commands import COMMAND_REGISTRY

    out = []
    for cmd in COMMAND_REGISTRY:
        if cmd.cli_only and not cmd.web_available:
            continue
        if cmd.gateway_only:
            continue
        out.append(
            {
                "name": cmd.name,
                "description": cmd.description,
                "category": cmd.category,
                "aliases": list(cmd.aliases) if cmd.aliases else [],
                "args_hint": cmd.args_hint or "",
            }
        )

    # Append installed skills so they show up in the slash command menu
    try:
        from agent.skill_commands import get_skill_commands
        skill_cmds = get_skill_commands()
        for cmd_key, info in sorted(skill_cmds.items()):
            name = cmd_key.lstrip("/")
            out.append(
                {
                    "name": name,
                    "description": info.get("description", "Skill"),
                    "category": "Skills",
                    "aliases": [],
                    "args_hint": info.get("args_hint", "") or "",
                }
            )
    except Exception:
        pass

    return out


@app.get("/api/conversations/config")
async def get_conversation_config():
    """Return the default model for web chat conversations."""
    from spark_cli.model_config import read_global_model_config

    model_cfg = read_global_model_config()
    return {"default_model": model_cfg.model, "provider": model_cfg.provider}


@app.get("/api/conversations/models")
async def get_conversation_models():
    """Curated model ids for the web UI picker (OpenRouter-style)."""
    curated = [
        ("anthropic/claude-sonnet-4.6", "Fast, strong generalist"),
        ("anthropic/claude-opus-4.6", "Highest quality"),
        ("openai/gpt-5.2", "OpenAI flagship"),
        ("google/gemini-3-pro-preview", "Long context"),
        ("deepseek/deepseek-r1", "Reasoning"),
    ]
    return {"models": [{"id": mid, "hint": h} for mid, h in curated]}


class CanvasChatBody(BaseModel):
    message: str
    history: list[dict] = []
    model: Optional[str] = None
    slug: Optional[str] = None


@app.post("/api/canvas/chat")
async def canvas_chat(body: CanvasChatBody):
    """Run a single, *stateless* agent turn for a Canvas chat node.

    Unlike /api/conversations this never creates a persisted SessionDB session, so
    canvas chats stay canvas-local and do not appear in the Chat tab. Prior turns are
    replayed via ``prefill_messages`` so each node keeps its own conversation context.
    For a project-scoped canvas, ``slug`` sets the agent's working directory.
    """
    from core.run_agent import AIAgent

    turn_route = _resolve_web_turn_route(body.message)
    runtime = turn_route.get("runtime") or {}

    working_dir = None
    if body.slug:
        from spark_cli.workspace_routes import _project_dir

        working_dir = str(_project_dir(body.slug))

    prefill = [
        {"role": m.get("role", "user"), "content": str(m.get("content", ""))}
        for m in (body.history or [])
        if m.get("content")
    ]

    def _run() -> str:
        agent = AIAgent(
            session_id="canvas_" + uuid.uuid4().hex[:12],
            model=turn_route["model"],
            max_iterations=_web_max_iterations(),
            api_key=runtime.get("api_key"),
            base_url=runtime.get("base_url"),
            provider=runtime.get("provider"),
            api_mode=runtime.get("api_mode"),
            command=runtime.get("command"),
            args=list(runtime.get("args") or []),
            credential_pool=runtime.get("credential_pool"),
            request_overrides=turn_route.get("request_overrides"),
            prefill_messages=prefill,
            quiet_mode=True,
            platform="web",
            session_db=None,
            working_dir=working_dir,
        )
        return agent.chat(body.message)

    loop = asyncio.get_running_loop()
    try:
        reply = await loop.run_in_executor(None, _run)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "reply": reply, "model": turn_route["model"]}


@app.post("/api/conversations")
async def create_conversation(body: ConversationCreate):
    """Start a new web chat session. Spawns AIAgent in a thread, returns session_id."""
    import uuid
    from datetime import datetime

    try:
        from tools.approval import register_gateway_notify, unregister_gateway_notify
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Agent module unavailable: {e}")

    session_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    queue: asyncio.Queue = asyncio.Queue()
    _web_queues[session_id] = queue

    loop = asyncio.get_running_loop()
    (
        token_callback,
        tool_start_callback,
        tool_complete_callback,
        reasoning_callback,
        status_callback,
        session_migrated_callback,
        subagent_event_callback,
    ) = _make_web_chat_callbacks(session_id, queue, loop)

    if body.model:
        from spark_cli.model_config import write_global_model_config

        write_global_model_config(model=body.model)
    turn_route = _resolve_web_turn_route(body.message)
    model = turn_route["model"]

    try:
        # Build the agent off the event loop: constructing AIAgent triggers
        # heavy imports + (on a frozen app) dylib loads that can take seconds on
        # first use. Running it inline would block the loop and freeze the whole
        # UI (SSE pings, session list, animations) while a new thread spins up.
        agent = await loop.run_in_executor(
            None,
            lambda: _new_web_agent(
                session_id=session_id,
                model=model,
                runtime=turn_route["runtime"],
                request_overrides=turn_route.get("request_overrides"),
                signature=turn_route["signature"],
                token_callback=token_callback,
                tool_start_callback=tool_start_callback,
                tool_complete_callback=tool_complete_callback,
                reasoning_callback=reasoning_callback,
                status_callback=status_callback,
                session_migrated_callback=session_migrated_callback,
                subagent_event_callback=subagent_event_callback,
            ),
        )
    except (ValueError, Exception) as e:
        _web_queues.pop(session_id, None)
        raise HTTPException(status_code=400, detail=str(e))

    try:
        from core.spark_state import SessionDB as _SessionDB

        _db = _SessionDB()
        try:
            _db._conn.execute(
                "INSERT OR IGNORE INTO sessions (id, source, model, started_at, kanban_status) "
                "VALUES (?, 'web', ?, ?, 'active')",
                (session_id, model, time.time()),
            )
            _db._conn.commit()
            row = _db.get_session(session_id)
            if row:
                _emit_sessions_changed("created", session_id, row)
        finally:
            _db.close()
    except Exception:
        _log.debug("session create emit failed", exc_info=True)

    message = body.message
    validated_items = _validate_context_items(body.context_items)
    _persist_context_items(session_id, validated_items)

    def _gw_notify(data: dict) -> None:
        _publish_web_status(session_id, "waiting_for_approval", "Waiting for approval…", phase="approval")
        _publish_event("chat.approval_requested", {"approval": _json_safe(data)}, session_id)

    async def run_agent_task() -> None:
        register_gateway_notify(session_id, _gw_notify)
        _touch_web_turn(session_id, status="Running…", phase="streaming", active_agent_session_id=getattr(agent, "session_id", session_id))
        before_message_count = _session_message_count(session_id)
        result = None
        try:
            slash_text = _execute_web_slash_command(session_id, message)
            if slash_text is not None:
                _publish_web_status(session_id, "slash_command", "Running slash command…", phase="streaming")
                _publish_event("chat.token", {"t": slash_text}, session_id)
                result = {"final_response": slash_text}
            else:
                _items = validated_items
                _publish_web_status(session_id, "api_call_started", "Calling model…", phase="api")
                result = await loop.run_in_executor(
                    None, lambda: _run_web_agent_turn(agent, message, None, _items)
                )
        except Exception as exc:
            _log.exception("Web chat agent error session=%s", session_id)
            result = {"backend_error_class": type(exc).__name__}
        finally:
            unregister_gateway_notify(session_id)
            _persist_web_turn_if_missing(session_id, message, result, before_message_count)
            _emit_web_session_updated(session_id)
            _maybe_auto_title_web(agent, session_id, message, result)
            loop.call_soon_threadsafe(queue.put_nowait, None)
            _publish_event("chat.turn_done", _turn_done_payload(result, session_id), session_id)
            _clear_web_turn(session_id)

    _mark_web_turn_active(session_id, status="Starting…", phase="starting", active_agent_session_id=getattr(agent, "session_id", session_id))
    asyncio.create_task(run_agent_task())
    return {"session_id": session_id, "ok": True}


@app.get("/api/conversations/{session_id}/subagents")
async def list_conversation_subagents(session_id: str, limit: int = 50):
    """Return bounded subagent run snapshots for a conversation."""
    from core.spark_state import SessionDB

    limit = max(1, min(int(limit or 50), 200))
    db = SessionDB()
    try:
        sid = db.resolve_session_id(session_id)
        if not sid:
            raise HTTPException(status_code=404, detail="Session not found")
        latest_sid = db.resolve_latest_descendant(sid)
        runs = db.list_subagent_runs(sid)
        return _sanitize_web_chat_value({
            "session_id": latest_sid or sid,
            "requested_session_id": session_id,
            "subagents": runs[:limit],
            "total": len(runs),
            "limit": limit,
        })
    finally:
        db.close()


@app.get("/api/conversations/{session_id}/subagents/{subagent_id}")
async def get_conversation_subagent(
    session_id: str,
    subagent_id: str,
    event_limit: int = 200,
):
    """Return one subagent run plus a bounded ordered event history."""
    from core.spark_state import SessionDB

    event_limit = max(1, min(int(event_limit or 200), 1000))
    db = SessionDB()
    try:
        sid = db.resolve_session_id(session_id)
        if not sid:
            raise HTTPException(status_code=404, detail="Session not found")
        latest_sid = db.resolve_latest_descendant(sid)
        allowed_session_ids = set(db.resolve_compression_chain(sid))
        run = db.get_subagent_run(subagent_id)
        if not run or run.get("parent_session_id") not in allowed_session_ids:
            raise HTTPException(status_code=404, detail="Subagent not found")
        events = db.get_subagent_events(subagent_id, limit=event_limit)
        run = {**run, "events": events, "transcript": events}
        return _sanitize_web_chat_value({
            "session_id": latest_sid or sid,
            "requested_session_id": session_id,
            "subagent": run,
            "events": events,
            "event_limit": event_limit,
        })
    finally:
        db.close()


@app.get("/api/conversations/{session_id}/subagents/{subagent_id}/messages")
async def get_conversation_subagent_messages(
    session_id: str,
    subagent_id: str,
    limit: int = 200,
    include_tool_results: bool = False,
):
    """Return bounded child-session messages for a subagent transcript view."""
    from core.spark_state import SessionDB

    limit = max(1, min(int(limit or 200), 1000))
    db = SessionDB()
    try:
        sid = db.resolve_session_id(session_id)
        if not sid:
            raise HTTPException(status_code=404, detail="Session not found")
        latest_sid = db.resolve_latest_descendant(sid)
        allowed_session_ids = set(db.resolve_compression_chain(sid))
        run = db.get_subagent_run(subagent_id)
        if not run or run.get("parent_session_id") not in allowed_session_ids:
            raise HTTPException(status_code=404, detail="Subagent not found")

        child_session_id = run.get("child_session_id")
        if not child_session_id:
            return {
                "session_id": latest_sid or sid,
                "requested_session_id": session_id,
                "subagent_id": subagent_id,
                "child_session_id": None,
                "messages": [],
                "total": 0,
                "limit": limit,
            }
        if not db.get_session(str(child_session_id)):
            return {
                "session_id": latest_sid or sid,
                "requested_session_id": session_id,
                "subagent_id": subagent_id,
                "child_session_id": child_session_id,
                "messages": [],
                "total": 0,
                "limit": limit,
            }

        all_messages = db.get_messages(str(child_session_id))
        total = len(all_messages)
        offset = max(0, total - limit)
        messages = [
            {
                **_message_for_history_response(msg, include_tool_results=include_tool_results),
                "message_index": offset + idx,
            }
            for idx, msg in enumerate(all_messages[offset:])
        ]
        return {
            "session_id": latest_sid or sid,
            "requested_session_id": session_id,
            "subagent_id": subagent_id,
            "child_session_id": child_session_id,
            "messages": messages,
            "total": total,
            "limit": limit,
            "offset": offset,
            "include_tool_results": include_tool_results,
        }
    finally:
        db.close()


@app.post("/api/conversations/{session_id}/subagents/{subagent_id}/interrupt")
async def interrupt_conversation_subagent(
    session_id: str,
    subagent_id: str,
    body: ConversationInterrupt,
):
    """Interrupt one live child agent when it is still tracked by the parent turn."""
    from core.spark_state import SessionDB

    db = SessionDB()
    try:
        sid = db.resolve_session_id(session_id)
        if not sid:
            raise HTTPException(status_code=404, detail="Session not found")
        latest_sid = db.resolve_latest_descendant(sid)
        allowed_session_ids = set(db.resolve_compression_chain(sid))
        run = db.get_subagent_run(subagent_id)
        if not run or run.get("parent_session_id") not in allowed_session_ids:
            raise HTTPException(status_code=404, detail="Subagent not found")
    finally:
        db.close()

    agent_session_id, parent_agent = _get_web_agent_for_turn(session_id)
    if not parent_agent:
        raise HTTPException(
            status_code=409,
            detail="Subagent interrupt is only available while the parent turn is active.",
        )

    child_session_id = run.get("child_session_id")
    active_children = list(getattr(parent_agent, "_active_children", []) or [])
    target_child = None
    for child in active_children:
        if child_session_id and getattr(child, "session_id", None) == child_session_id:
            target_child = child
            break
    if target_child is None:
        raise HTTPException(
            status_code=409,
            detail="Subagent is not running in the active parent turn; interrupt the parent conversation instead.",
        )

    try:
        target_child.interrupt(body.message)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    status = "stopping"
    payload = {
        "schema": "spark.subagent.lifecycle.v1",
        "type": "subagent.status",
        "event": "status",
        "id": subagent_id,
        "run_id": subagent_id,
        "subagent_id": subagent_id,
        "child_session_id": child_session_id,
        "task_index": run.get("task_index") or 0,
        "task_number": int(run.get("task_index") or 0) + 1,
        "task_count": run.get("task_count") or 1,
        "display_name": run.get("name"),
        "goal_preview": run.get("task"),
        "payload": {
            "parent_session_id": run.get("parent_session_id"),
            "child_session_id": child_session_id,
            "status": status,
            "preview": "Interrupt requested",
        },
        "subagent_run": {**run, "status": status},
    }
    _persist_and_publish_subagent_event(latest_sid or sid, payload)
    return {
        "ok": True,
        "session_id": agent_session_id or latest_sid or sid,
        "subagent_id": subagent_id,
        "child_session_id": child_session_id,
        "status": status,
    }


@app.post("/api/conversations/{session_id}/messages")
async def send_conversation_message(session_id: str, body: ConversationMessage):
    """Send a follow-up message to an existing web chat session."""
    from tools.approval import register_gateway_notify, unregister_gateway_notify

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    (
        token_callback,
        tool_start_callback,
        tool_complete_callback,
        reasoning_callback,
        status_callback,
        session_migrated_callback,
        subagent_event_callback,
    ) = _make_web_chat_callbacks(session_id, queue, loop)

    from core.spark_state import SessionDB

    conversation_history: Optional[list[dict[str, Any]]] = None
    db = SessionDB()
    try:
        requested_session_id = session_id
        sid = db.resolve_session_id(session_id)
        if not sid:
            raise HTTPException(status_code=404, detail="Session not found")
        latest_sid = db.resolve_latest_descendant(sid)
        if latest_sid != sid:
            _log.info(
                "web follow-up resolved compression descendant requested=%s resolved=%s latest=%s",
                requested_session_id,
                sid,
                latest_sid,
            )
            sid = latest_sid
        row = db.get_session(sid)
        if not row:
            raise HTTPException(status_code=404, detail="Session not found")
        session_id = sid
        (
            token_callback,
            tool_start_callback,
            tool_complete_callback,
            reasoning_callback,
            status_callback,
            session_migrated_callback,
            subagent_event_callback,
        ) = _make_web_chat_callbacks(session_id, queue, loop)
        _web_queues[session_id] = queue
        turn_route = _resolve_web_turn_route(body.message)
        agent = _web_agents.get(session_id)
        conversation_history = db.get_messages_as_conversation(session_id)
        history_count = len(conversation_history)
        cached_signature_matches = (
            agent is not None
            and _web_agent_signatures.get(session_id) == turn_route["signature"]
        )
        _log.info(
            "web follow-up hydrated requested=%s session=%s history_count=%s cached_agent=%s signature_match=%s",
            requested_session_id,
            session_id,
            history_count,
            bool(agent),
            cached_signature_matches,
        )
        if (
            agent
            and cached_signature_matches
            and _cached_web_agent_matches_history(session_id, agent, conversation_history)
        ):
            agent.stream_delta_callback = token_callback
            agent.tool_start_callback = tool_start_callback
            agent.tool_complete_callback = tool_complete_callback
            agent.reasoning_callback = reasoning_callback
            agent.status_callback = status_callback
            agent.session_migrated_callback = session_migrated_callback
            agent.subagent_event_callback = subagent_event_callback
            agent.request_overrides = turn_route.get("request_overrides")
            conversation_history = None
        else:
            agent = _new_web_agent(
                session_id=session_id,
                model=turn_route["model"],
                runtime=turn_route["runtime"],
                request_overrides=turn_route.get("request_overrides"),
                signature=turn_route["signature"],
                token_callback=token_callback,
                tool_start_callback=tool_start_callback,
                tool_complete_callback=tool_complete_callback,
                reasoning_callback=reasoning_callback,
                status_callback=status_callback,
                session_migrated_callback=session_migrated_callback,
                subagent_event_callback=subagent_event_callback,
            )
        _update_web_session_model(session_id, turn_route["model"])
        try:
            db.reopen_session(session_id)
        except Exception:
            pass
    finally:
        db.close()

    message = body.message
    validated_items = _validate_context_items(body.context_items)
    _persist_context_items(session_id, validated_items)

    def _gw_notify(data: dict) -> None:
        _publish_web_status(session_id, "waiting_for_approval", "Waiting for approval…", phase="approval")
        _publish_event("chat.approval_requested", {"approval": _json_safe(data)}, session_id)

    async def run_agent_task() -> None:
        register_gateway_notify(session_id, _gw_notify)
        _touch_web_turn(session_id, status="Running…", phase="streaming", active_agent_session_id=getattr(agent, "session_id", session_id))
        before_message_count = _session_message_count(session_id)
        result = None
        try:
            slash_text = _execute_web_slash_command(session_id, message)
            if slash_text is not None:
                _publish_web_status(session_id, "slash_command", "Running slash command…", phase="streaming")
                _publish_event("chat.token", {"t": slash_text}, session_id)
                result = {"final_response": slash_text}
            else:
                _items = validated_items
                _publish_web_status(session_id, "api_call_started", "Calling model…", phase="api")
                result = await loop.run_in_executor(
                    None, lambda: _run_web_agent_turn(agent, message, conversation_history, _items)
                )
        except Exception as exc:
            _log.exception("Web chat follow-up error session=%s", session_id)
            result = {"backend_error_class": type(exc).__name__}
        finally:
            unregister_gateway_notify(session_id)
            _persist_web_turn_if_missing(session_id, message, result, before_message_count)
            _emit_web_session_updated(session_id)
            _maybe_auto_title_web(agent, session_id, message, result)
            loop.call_soon_threadsafe(queue.put_nowait, None)
            _publish_event("chat.turn_done", _turn_done_payload(result, session_id), session_id)
            _clear_web_turn(session_id)

    _mark_web_turn_active(session_id, status="Starting…", phase="starting", active_agent_session_id=getattr(agent, "session_id", session_id))
    asyncio.create_task(run_agent_task())
    return {"session_id": session_id, "ok": True}


@app.post("/api/conversations/{session_id}/interrupt")
async def interrupt_conversation(session_id: str, body: ConversationInterrupt):
    agent_session_id, agent = _get_web_agent_for_turn(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Session not in active memory.")
    try:
        phase = "redirecting" if body.message else "stopping"
        status = "Redirecting…" if body.message else "Stopping…"
        _touch_web_turn(
            agent_session_id or session_id,
            status=status,
            phase=phase,
            interrupt_requested=True,
            active_agent_session_id=agent_session_id,
        )
        agent.interrupt(body.message)
        _persist_interrupted_turn_boundary(agent_session_id or session_id, body.message)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    _publish_event(
        "chat.status",
        {"kind": "interrupt_requested", "message": status},
        agent_session_id or session_id,
    )
    _publish_event(
        "chat.interrupted",
        {"message": body.message or "", "interrupt_requested": True, "phase": phase},
        agent_session_id or session_id,
    )
    return {"ok": True, "session_id": agent_session_id or session_id}


@app.post("/api/conversations/{session_id}/model")
async def switch_conversation_model(session_id: str, body: ConversationModelBody):
    if _is_web_turn_active(session_id):
        raise HTTPException(
            status_code=409, detail="Cannot switch model while a turn is running."
        )
    from spark_cli.config import get_compatible_custom_providers
    from spark_cli.model_config import read_global_model_config, write_model_switch_result
    from spark_cli.model_switch import switch_model

    cfg = load_config()
    current = read_global_model_config(cfg)
    result = switch_model(
        raw_input=body.model,
        current_provider=current.provider,
        current_model=current.model,
        current_base_url=current.base_url,
        current_api_key="",
        is_global=True,
        user_providers=cfg.get("providers"),
        custom_providers=get_compatible_custom_providers(cfg),
    )
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error_message)

    write_model_switch_result(result)
    for sid in list(_web_agents.keys()):
        if not _is_web_turn_active(sid):
            _close_web_agent(sid)
    _update_web_session_model(session_id, result.new_model)
    _publish_event("chat.model_changed", {"model": result.new_model}, session_id)
    return {"ok": True, "session_id": session_id, "model": result.new_model}


@app.post("/api/conversations/{session_id}/fork")
async def fork_conversation(session_id: str, body: ConversationForkBody):
    import uuid
    from datetime import datetime

    from core.spark_state import SessionDB

    db = SessionDB()
    try:
        sid = db.resolve_session_id(session_id)
        if not sid:
            raise HTTPException(status_code=404, detail="Session not found")
        src = db.get_session(sid)
        if not src:
            raise HTTPException(status_code=404, detail="Session not found")
        msgs = db.get_messages(sid)
        if body.from_message_index is not None:
            n = body.from_message_index
            if n < 0 or n > len(msgs):
                raise HTTPException(status_code=400, detail="Invalid from_message_index")
            msgs = msgs[:n]
        new_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
        db.create_session(
            new_id,
            source="web",
            model=src.get("model"),
            parent_session_id=sid,
        )
        for m in msgs:
            db.append_message(
                new_id,
                m["role"],
                content=m.get("content"),
                tool_name=m.get("tool_name"),
                tool_calls=m.get("tool_calls"),
                tool_call_id=m.get("tool_call_id"),
                reasoning=m.get("reasoning"),
                reasoning_details=m.get("reasoning_details"),
                codex_reasoning_items=m.get("codex_reasoning_items"),
            )
        row = db.get_session(new_id)
        if row:
            _emit_sessions_changed("created", new_id, row)
    finally:
        db.close()
    return {"ok": True, "session_id": new_id, "source_session_id": sid}


@app.get("/api/sessions/{session_id}/forks")
async def get_session_forks(session_id: str):
    """Return sessions forked from this session and the parent session title (if any)."""
    from core.spark_state import SessionDB
    db = SessionDB()
    try:
        session = db.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        forks = db.get_session_forks(session_id)
        parent_id = session.get("parent_session_id")
        parent = db.get_session(parent_id) if parent_id else None
        return {
            "forks": [{"id": f["id"], "title": f.get("title") or f["id"]} for f in forks],
            "fork_count": len(forks),
            "parent_session_id": parent_id,
            "parent_title": (parent.get("title") or parent_id) if parent else None,
        }
    finally:
        db.close()


class BriefUpdate(BaseModel):
    text: str


@app.get("/api/sessions/{session_id}/brief")
async def get_session_brief(session_id: str):
    from core.spark_state import SessionDB
    db = SessionDB()
    try:
        session = db.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        text = db.get_brief(session_id) or ""
        return {"session_id": session_id, "text": text}
    finally:
        db.close()


@app.put("/api/sessions/{session_id}/brief")
async def update_session_brief(session_id: str, body: BriefUpdate):
    from core.spark_state import SessionDB
    db = SessionDB()
    try:
        session = db.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        db.set_brief(session_id, body.text)
        return {"session_id": session_id, "text": body.text}
    finally:
        db.close()


class ManifestUpdate(BaseModel):
    data: dict = {}


@app.get("/api/workspace/projects/{slug}/manifest")
async def get_workspace_manifest(slug: str):
    from core.spark_state import SessionDB
    db = SessionDB()
    try:
        data = db.get_manifest(slug)
        return {"workspace_slug": slug, "data": data}
    finally:
        db.close()


@app.put("/api/workspace/projects/{slug}/manifest")
async def update_workspace_manifest(slug: str, body: ManifestUpdate):
    from core.spark_state import SessionDB
    db = SessionDB()
    try:
        db.set_manifest(slug, body.data)
        return {"workspace_slug": slug, "data": body.data}
    finally:
        db.close()


_BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".svg",
    ".pdf", ".zip", ".gz", ".tar", ".rar", ".7z", ".exe", ".dll", ".so",
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".mkv", ".woff", ".woff2",
    ".ttf", ".otf", ".pyc", ".class", ".o", ".a", ".db", ".sqlite",
}
_SUMMARIZE_MAX_BYTES = 2 * 1024 * 1024  # 2 MB


class SummarizeFileRequest(BaseModel):
    path: str
    workspace_slug: Optional[str] = None


async def _generate_summary(text: str, filename: str) -> str:
    """Generate a summary via the configured LLM."""
    from spark_cli.model_config import read_global_model_config
    from spark_cli.runtime_provider import resolve_runtime_provider
    import openai as _openai

    runtime = resolve_runtime_provider(requested=None)
    model_cfg = read_global_model_config()
    model = model_cfg.model or "gpt-4o-mini"
    api_key = runtime.get("api_key")
    base_url = runtime.get("base_url")

    client = _openai.OpenAI(api_key=api_key, base_url=base_url)
    max_chars = 40_000
    excerpt = text[:max_chars] + ("…[truncated]" if len(text) > max_chars else "")
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Summarize the following file ({filename}) in 3-5 sentences. "
                    f"Focus on its purpose, key concepts, and main structure.\n\n{excerpt}"
                ),
            }
        ],
        max_tokens=300,
    )
    return response.choices[0].message.content or ""


@app.post("/api/summarize-file")
async def summarize_file(body: SummarizeFileRequest):
    from core.spark_state import SessionDB

    workspace_root = _get_workspace_root(body.workspace_slug or None)

    # Safety: resolve and check path stays within workspace
    try:
        resolved = (workspace_root / body.path.lstrip("/")).resolve()
        resolved.relative_to(workspace_root)
    except (ValueError, Exception):
        raise HTTPException(status_code=400, detail="Path traversal not allowed")

    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    # Reject binary files
    if resolved.suffix.lower() in _BINARY_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Binary files cannot be summarized")

    stat = resolved.stat()
    if stat.st_size > _SUMMARIZE_MAX_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"File too large ({stat.st_size // 1024}KB). Max: {_SUMMARIZE_MAX_BYTES // 1024}KB",
        )

    db = SessionDB()
    try:
        # Check cache freshness
        is_fresh, cached = db.is_summary_fresh(str(resolved))
        if is_fresh and cached:
            return {"path": body.path, "summary": cached, "cached": True, "stale": False}

        # Generate new summary
        text = resolved.read_text(errors="replace")
        summary = await _generate_summary(text, resolved.name)
        db.set_summary(str(resolved), stat.st_size, stat.st_mtime, summary)
        return {"path": body.path, "summary": summary, "cached": False, "stale": False}
    finally:
        db.close()


@app.post("/api/conversations/{session_id}/retry")
async def retry_conversation(session_id: str, body: ConversationRetryBody):
    from tools.approval import register_gateway_notify, unregister_gateway_notify

    agent_session_id, agent = _get_web_agent_for_turn(session_id)
    if _is_web_turn_active(session_id):
        raise HTTPException(status_code=409, detail="A turn is already running.")

    from core.spark_state import SessionDB

    db = SessionDB()
    try:
        sid = db.resolve_session_id(session_id)
        if not sid:
            raise HTTPException(status_code=404, detail="Session not found")
        sid = db.resolve_latest_descendant(sid)
        session_id = sid
        msgs = db.get_messages(sid)
        idx = body.message_index
        if idx < 0 or idx >= len(msgs):
            raise HTTPException(status_code=400, detail="Invalid message_index")
        pivot = msgs[idx]
        if pivot.get("role") != "user":
            raise HTTPException(status_code=400, detail="message_index must reference a user message")
        ids_drop = [m["id"] for m in msgs[idx + 1 :]]
        if ids_drop:

            def _del(conn):
                q_marks = ",".join("?" * len(ids_drop))
                conn.execute(
                    f"DELETE FROM messages WHERE session_id = ? AND id IN ({q_marks})",
                    (sid, *ids_drop),
                )
                conn.execute(
                    """UPDATE sessions SET message_count = (
                        SELECT COUNT(*) FROM messages WHERE session_id = ?
                    ) WHERE id = ?""",
                    (sid, sid),
                )

            db._execute_write(_del)
        new_content = body.message
        if new_content is not None:

            def _upd(conn):
                conn.execute(
                    "UPDATE messages SET content = ? WHERE id = ?",
                    (new_content, pivot["id"]),
                )

            db._execute_write(_upd)
    finally:
        db.close()

    conv = SessionDB()
    try:
        hist = conv.get_messages_as_conversation(sid)
    finally:
        conv.close()
    if not hist or hist[-1].get("role") != "user":
        raise HTTPException(status_code=500, detail="Could not load history for retry")
    user_msg = hist[-1].get("content") or ""
    conv_hist = hist[:-1]

    queue: asyncio.Queue = asyncio.Queue()
    _web_queues[session_id] = queue
    loop = asyncio.get_running_loop()
    (
        token_callback,
        tool_start_callback,
        tool_complete_callback,
        reasoning_callback,
        status_callback,
        session_migrated_callback,
        subagent_event_callback,
    ) = _make_web_chat_callbacks(session_id, queue, loop)
    turn_route = _resolve_web_turn_route(user_msg)
    if agent and _web_agent_signatures.get(agent_session_id or session_id) == turn_route["signature"]:
        agent.stream_delta_callback = token_callback
        agent.tool_start_callback = tool_start_callback
        agent.tool_complete_callback = tool_complete_callback
        agent.reasoning_callback = reasoning_callback
        agent.status_callback = status_callback
        agent.session_migrated_callback = session_migrated_callback
        agent.subagent_event_callback = subagent_event_callback
        agent.request_overrides = turn_route.get("request_overrides")
    else:
        agent = _new_web_agent(
            session_id=session_id,
            model=turn_route["model"],
            runtime=turn_route["runtime"],
            request_overrides=turn_route.get("request_overrides"),
            signature=turn_route["signature"],
            token_callback=token_callback,
            tool_start_callback=tool_start_callback,
            tool_complete_callback=tool_complete_callback,
            reasoning_callback=reasoning_callback,
            status_callback=status_callback,
            session_migrated_callback=session_migrated_callback,
            subagent_event_callback=subagent_event_callback,
        )
    _update_web_session_model(session_id, turn_route["model"])

    def _gw_notify(data: dict) -> None:
        _publish_web_status(session_id, "waiting_for_approval", "Waiting for approval…", phase="approval")
        _publish_event("chat.approval_requested", {"approval": _json_safe(data)}, session_id)

    async def run_agent_task() -> None:
        register_gateway_notify(session_id, _gw_notify)
        _touch_web_turn(session_id, status="Retrying…", phase="streaming", active_agent_session_id=getattr(agent, "session_id", session_id))
        result = None
        try:
            _publish_web_status(session_id, "api_call_started", "Retrying model call…", phase="api")
            result = await loop.run_in_executor(
                None,
                lambda: _run_web_agent_turn(agent, user_msg, conv_hist),
            )
        except Exception as exc:
            _log.exception("Web chat retry error session=%s", session_id)
            result = {"backend_error_class": type(exc).__name__}
        finally:
            unregister_gateway_notify(session_id)
            loop.call_soon_threadsafe(queue.put_nowait, None)
            _publish_event("chat.turn_done", _turn_done_payload(result, session_id), session_id)
            _clear_web_turn(session_id)

    _mark_web_turn_active(session_id, status="Retrying…", phase="starting", active_agent_session_id=getattr(agent, "session_id", session_id))
    asyncio.create_task(run_agent_task())
    return {"ok": True, "session_id": session_id}


@app.post("/api/conversations/{session_id}/approval")
async def conversation_approval(session_id: str, body: ConversationApprovalBody):
    from tools import approval as approval_mod

    choice = body.choice
    if choice not in ("once", "session", "always", "deny"):
        raise HTTPException(status_code=400, detail="Invalid choice")
    n = approval_mod.resolve_gateway_approval(
        session_id, choice, resolve_all=body.resolve_all
    )
    if n == 0:
        raise HTTPException(status_code=404, detail="No pending approval for this session")
    _publish_event(
        "chat.approval_resolved",
        {"choice": choice, "resolved": n},
        session_id,
    )
    return {"ok": True, "session_id": session_id, "resolved": n}


@app.post("/api/conversations/{session_id}/feedback")
async def conversation_feedback(session_id: str, body: FeedbackSubmitBody):
    import httpx as _httpx

    payload = {"name": body.name, "email": body.email, "area": body.area, "note": body.note}
    try:
        async with _httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://n8n.automatedigital.ai/webhook/spark-feedback",
                json=payload,
            )
            resp.raise_for_status()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to submit feedback: {exc}")

    _publish_event("chat.feedback_submitted", {}, session_id)
    return {"ok": True}


@app.get("/api/conversations/{session_id}/turn-status")
async def conversation_turn_status(session_id: str):
    """Report whether an agent turn is currently active for this session.

    Lightweight source of truth the UI can poll to recover from a lost
    ``chat.turn_done`` event (e.g. the SSE bus dropped mid-turn).
    """
    ids = _resolve_web_turn_ids(session_id)
    active_key, turn = _get_web_turn(session_id)
    payload: dict[str, Any] = {
        "session_id": ids.get("requested") or session_id,
        "resolved_session_id": ids.get("resolved") or session_id,
        "latest_session_id": ids.get("latest") or ids.get("resolved") or session_id,
        "active_turn_session_id": active_key,
        "turn_active": turn is not None,
        "status": None,
        "phase": "idle",
        "started_at": None,
        "last_event_at": None,
        "interrupt_requested": False,
        "active_agent_session_id": None,
    }
    if turn:
        payload.update(
            {
                "started_at": turn.started_at,
                "last_event_at": turn.last_event_at,
                "status": turn.status,
                "interrupt_requested": turn.interrupt_requested,
                "active_agent_session_id": turn.active_agent_session_id,
                "phase": turn.phase,
                "stream_revision": turn.stream_revision,
                "stream_text_chars": len(turn.stream_text),
            }
        )
    return payload


@app.get("/api/conversations/{session_id}/stream-snapshot")
async def conversation_stream_snapshot(session_id: str):
    """Return the accumulated in-flight assistant text for recovery.

    Token SSE events are intentionally droppable under backpressure.  The UI
    calls this heavier endpoint only during stall/reconnect recovery so it can
    patch a partial assistant bubble without waiting for final persistence.
    """
    ids = _resolve_web_turn_ids(session_id)
    active_key, turn = _get_web_turn(session_id)
    return {
        "session_id": ids.get("requested") or session_id,
        "resolved_session_id": ids.get("resolved") or session_id,
        "latest_session_id": ids.get("latest") or ids.get("resolved") or session_id,
        "active_turn_session_id": active_key,
        "turn_active": turn is not None,
        "stream_text": turn.stream_text if turn else "",
        "stream_revision": turn.stream_revision if turn else 0,
        "stream_text_chars": len(turn.stream_text) if turn else 0,
    }


@app.get("/api/conversations/{session_id}/stream")
async def stream_conversation(session_id: str):
    """SSE endpoint streaming agent response tokens for a web chat session."""
    from fastapi.responses import StreamingResponse as _StreamingResponse

    queue = _web_queues.get(session_id)
    if queue is None:
        raise HTTPException(status_code=404, detail="No active stream for this session")

    async def event_generator():
        try:
            while True:
                try:
                    token = await asyncio.wait_for(queue.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    yield "event: ping\ndata: {}\n\n"
                    continue
                if token is None:
                    yield "event: done\ndata: {}\n\n"
                    break
                yield f"data: {json.dumps({'t': token})}\n\n"
        except Exception:
            yield "event: done\ndata: {}\n\n"
        finally:
            _web_queues.pop(session_id, None)

    return _StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def mount_spa(application: FastAPI):
    """Mount the built SPA. Falls back to index.html for client-side routing."""
    if not WEB_DIST.exists():

        @application.get("/{full_path:path}")
        async def no_frontend(full_path: str):
            return JSONResponse(
                {"error": "Frontend not built. Run: cd web && npm run build"},
                status_code=404,
            )

        return

    application.mount(
        "/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets"
    )

    @application.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        file_path = WEB_DIST / full_path
        # Prevent path traversal via url-encoded sequences (%2e%2e/)
        if (
            full_path
            and file_path.resolve().is_relative_to(WEB_DIST.resolve())
            and file_path.exists()
            and file_path.is_file()
        ):
            return FileResponse(file_path)
        return FileResponse(
            WEB_DIST / "index.html",
            headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
        )


register_kanban_routes(app)
register_workspace_routes(app)
register_connectors_routes(app)
register_canvas_routes(app)
from spark_cli.memory_routes import register_memory_routes
register_memory_routes(app)
register_workflow_routes(app)
from spark_cli.artifacts_routes import register_artifacts_routes
from spark_cli.messaging_routes import register_messaging_routes
register_messaging_routes(app)
register_artifacts_routes(app)


# ── Workspace conversation endpoints ─────────────────────────────────────────


class WorkspaceConvCreate(BaseModel):
    message: str
    model: Optional[str] = None
    context_items: list = []


@app.post("/api/workspace/projects/{slug}/conversations")
async def start_workspace_conversation(slug: str, body: WorkspaceConvCreate):
    """Start a Spark agent conversation scoped to a workspace project."""
    from datetime import datetime

    try:
        from tools.approval import register_gateway_notify, unregister_gateway_notify
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Agent module unavailable: {e}")

    from spark_cli.workspace_routes import _project_dir

    project_dir = _project_dir(slug)
    source = f"workspace:{slug}"

    session_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    queue: asyncio.Queue = asyncio.Queue()
    _web_queues[session_id] = queue

    loop = asyncio.get_running_loop()
    (
        token_callback,
        tool_start_callback,
        tool_complete_callback,
        reasoning_callback,
        status_callback,
        session_migrated_callback,
        subagent_event_callback,
    ) = _make_web_chat_callbacks(session_id, queue, loop)

    if body.model:
        from spark_cli.model_config import write_global_model_config

        write_global_model_config(model=body.model)
    turn_route = _resolve_web_turn_route(body.message)
    model = turn_route["model"]

    # Pre-insert the session with the correct workspace source BEFORE creating the
    # agent. AIAgent.__init__ calls create_session(source="web") via INSERT OR IGNORE,
    # so we must claim the row first to ensure list_workspace_conversations can find it.
    try:
        from core.spark_state import SessionDB as _SessionDB

        _db = _SessionDB()
        try:
            raw_title = body.message.strip()
            title = raw_title[:60] + ("…" if len(raw_title) > 60 else "")
            _db._conn.execute(
                "INSERT OR IGNORE INTO sessions (id, source, model, started_at, kanban_status, title) "
                "VALUES (?, ?, ?, ?, 'active', ?)",
                (session_id, source, model, time.time(), title),
            )
            _db._conn.commit()
        finally:
            _db.close()
    except Exception:
        _log.debug("workspace session pre-insert failed", exc_info=True)

    try:
        agent = _new_web_agent(
            session_id=session_id,
            model=model,
            runtime=turn_route["runtime"],
            request_overrides=turn_route.get("request_overrides"),
            signature=turn_route["signature"],
            token_callback=token_callback,
            tool_start_callback=tool_start_callback,
            tool_complete_callback=tool_complete_callback,
            reasoning_callback=reasoning_callback,
            status_callback=status_callback,
            session_migrated_callback=session_migrated_callback,
            subagent_event_callback=subagent_event_callback,
            working_dir=str(project_dir),
        )
        agent.ephemeral_system_prompt = (
            f"You are working in the '{slug}' workspace project.\n"
            f"Working directory: {project_dir}\n"
            "IMPORTANT: All file operations, terminal commands, and searches MUST stay within "
            f"this directory ({project_dir}). Do NOT read from or write to any other project "
            "directory. If the user asks you to build or edit something, create or modify files "
            f"only under {project_dir}.\n"
            "If this project is a webapp and you need to verify UI behavior, use the "
            f"workspace preview tools with slug '{slug}' after making changes. Start with "
            "preview_open, then inspect preview_snapshot and preview_console; use "
            "preview_screenshot or preview click/type/evaluate actions when visual or "
            "interactive verification matters."
        )
    except (ValueError, Exception) as e:
        _web_queues.pop(session_id, None)
        raise HTTPException(status_code=400, detail=str(e))

    try:
        from core.spark_state import SessionDB as _SessionDB

        _db = _SessionDB()
        try:
            row = _db.get_session(session_id)
            if row:
                _emit_sessions_changed("created", session_id, row)
        finally:
            _db.close()
    except Exception:
        _log.debug("workspace session create emit failed", exc_info=True)

    context_prefix = f"[Project: {slug} | Path: {project_dir}]\n\n"
    message = context_prefix + body.message
    validated_items = _validate_context_items(body.context_items, workspace_slug=slug)
    _persist_context_items(session_id, validated_items)

    def _gw_notify(data: dict) -> None:
        _publish_web_status(session_id, "waiting_for_approval", "Waiting for approval…", phase="approval")
        _publish_event("chat.approval_requested", {"approval": _json_safe(data)}, session_id)

    raw_message = body.message

    async def run_agent_task() -> None:
        register_gateway_notify(session_id, _gw_notify)
        _touch_web_turn(session_id, status="Running…", phase="streaming", active_agent_session_id=getattr(agent, "session_id", session_id))
        before_message_count = _session_message_count(session_id)
        result = None
        slash_text = None
        try:
            slash_text = _execute_web_slash_command(session_id, raw_message)
            if slash_text is not None:
                _publish_web_status(session_id, "slash_command", "Running slash command…", phase="streaming")
                _publish_event("chat.token", {"t": slash_text}, session_id)
                result = {"final_response": slash_text}
            else:
                _items = validated_items
                _publish_web_status(session_id, "api_call_started", "Calling model…", phase="api")
                result = await loop.run_in_executor(
                    None, lambda: _run_web_agent_turn(agent, message, None, _items)
                )
        except Exception as exc:
            _log.exception("Workspace chat agent error session=%s slug=%s", session_id, slug)
            result = {"backend_error_class": type(exc).__name__}
        finally:
            unregister_gateway_notify(session_id)
            _strip_user_message_prefix(session_id, context_prefix, raw_message)
            _persist_web_turn_if_missing(session_id, raw_message, result, before_message_count)
            _emit_web_session_updated(session_id)
            _maybe_auto_title_web(agent, session_id, raw_message, result)
            try:
                from spark_cli.workspace_routes import start_preview

                start_preview(slug, None)
            except Exception:
                _log.debug("workspace preview auto-start skipped slug=%s", slug, exc_info=True)
            loop.call_soon_threadsafe(queue.put_nowait, None)
            _publish_event("chat.turn_done", _turn_done_payload(result, session_id), session_id)
            _clear_web_turn(session_id)

    _mark_web_turn_active(session_id, status="Starting…", phase="starting", active_agent_session_id=getattr(agent, "session_id", session_id))
    asyncio.create_task(run_agent_task())
    return {"session_id": session_id, "ok": True, "source": source}


@app.get("/api/workspace/projects/{slug}/conversations")
async def list_workspace_conversations(slug: str, limit: int = 30, offset: int = 0):
    """List chat sessions for a workspace project."""
    from core.spark_state import SessionDB

    source = f"workspace:{slug}"
    db = SessionDB()
    try:
        sessions = db.list_sessions_rich(limit=limit, offset=offset, source=source)
        total = db.session_count(source=source)
        now = time.time()
        for s in sessions:
            s["is_active"] = (
                s.get("ended_at") is None
                and (now - s.get("last_active", s.get("started_at", 0))) < 300
            )
    finally:
        db.close()
    return {"sessions": sessions, "total": total, "limit": limit, "offset": offset}


mount_spa(app)


def start_server(host: str = "127.0.0.1", port: int = 9119, open_browser: bool = True):
    """Start the web UI server."""
    import uvicorn
    from core.spark_constants import get_public_base_url, is_server_environment

    ensure_dashboard_token_file()
    _set_connectors_port(port)
    # Activate the Google→gws CLI bridge for this process if already connected,
    # so the agent's gws-* skills authenticate from the stored connection.
    try:
        from spark_cli.google_connector import apply_process_env as _apply_gws_env
        _apply_gws_env()
    except Exception:
        pass
    public_url = get_public_base_url(host, port)

    _LOOPBACK = {"127.0.0.1", "::1", "localhost"}
    if host not in _LOOPBACK:
        import logging

        logging.warning(
            "Binding to %s — enable dashboard.require_auth_nonlocal (default) and use %s "
            "or SPARK_DASHBOARD_TOKEN for API access from other machines.",
            host,
            dashboard_token_path(),
        )

    if open_browser and not is_server_environment():
        import threading
        import webbrowser

        def _open():
            import time as _t

            _t.sleep(1.0)
            webbrowser.open(public_url)

        threading.Thread(target=_open, daemon=True).start()

    print(f"  Spark Web UI → {public_url} (bind {host}:{port})")
    uvicorn.run(app, host=host, port=port, log_level="warning")
