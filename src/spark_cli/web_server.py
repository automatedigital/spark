"""
Spark Agent — Web UI server.

Provides a FastAPI backend serving the Vite/React frontend and REST API
endpoints for managing configuration, environment variables, and sessions.

Usage:
    python -m spark_cli.main dashboard    # Start with dashboard.* config
    python -m spark_cli.main dashboard --port 8080
"""

import asyncio
import json
import logging
import os
import platform
import queue as thread_queue
import secrets
import subprocess
import sys
import threading
import time
import uuid
import urllib.parse
import urllib.request
from contextlib import asynccontextmanager
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
from gateway.status import get_running_pid, read_runtime_status
from spark_cli.dashboard_auth import (
    dashboard_token_path,
    ensure_dashboard_token_file,
    get_configured_dashboard_secret,
    validate_dashboard_request,
)
from spark_cli.kanban_routes import register_kanban_routes
from spark_cli.workspace_routes import register_workspace_routes

try:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, JSONResponse
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
_web_streaming: set = set()  # session_id strings with an active agent turn
_admin_runs: dict[str, dict[str, Any]] = {}
_admin_run_queues: dict[str, thread_queue.Queue] = {}


@asynccontextmanager
def _prefetch_update_check() -> None:
    """Run in a thread at startup to warm the update-check cache."""
    try:
        from spark_cli.banner import check_for_updates
        check_for_updates()
    except Exception:
        pass


def _init_memory_store() -> None:
    """Initialize the holographic memory store on startup (non-fatal)."""
    try:
        from plugins.memory.holographic import HolographicMemoryProvider
        provider = HolographicMemoryProvider()
        provider.initialize()
        _log.info("Holographic memory store initialized")
    except Exception as exc:
        _log.warning("Memory store init skipped: %s", exc)


async def _lifespan(_app: FastAPI):
    global _web_event_loop
    _web_event_loop = asyncio.get_running_loop()
    ensure_dashboard_token_file()
    # Warm the update cache in the background so /api/status has it immediately
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _prefetch_update_check)
    loop.run_in_executor(None, _init_memory_store)
    try:
        yield
    finally:
        _web_event_loop = None
        _event_subscribers.clear()
        _web_streaming.clear()
        _web_queues.clear()


app = FastAPI(title="Spark Agent", version=__version__, lifespan=_lifespan)

# ---------------------------------------------------------------------------
# Session token for protecting sensitive endpoints (reveal).
# Generated fresh on every server start — dies when the process exits.
# Injected into the SPA HTML so only the legitimate web UI can use it.
# ---------------------------------------------------------------------------
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


def _publish_event(topic: str, data: dict, session_id: Optional[str] = None) -> None:
    loop = _web_event_loop
    if loop is None:
        return
    envelope = {"topic": topic, "session_id": session_id, "ts": time.time(), "data": data}

    def _fanout() -> None:
        for q in tuple(_event_subscribers):
            try:
                q.put_nowait(envelope)
            except Exception:
                _event_subscribers.discard(q)

    try:
        loop.call_soon_threadsafe(_fanout)
    except Exception:
        pass


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


@app.get("/api/events")
async def sse_events_bus(request: Request, topics: str = "sessions,chat"):
    """Shared SSE bus for sessions.* and chat.* events."""
    from fastapi.responses import StreamingResponse as _StreamingResponse

    prefixes = tuple(p.strip() for p in topics.split(",") if p.strip())
    queue: asyncio.Queue = asyncio.Queue(maxsize=512)
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
    "model": {
        "type": "string",
        "description": "SMART model for complex / coding tasks. Use `spark model` → Multi-model to configure SMART and FAST models together.",
        "category": "general",
    },
    "model_provider": {
        "type": "string",
        "description": "SMART model provider (for example openai-codex, openrouter, nous, anthropic, custom).",
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
        "description": "FAST model provider for simple requests (for example openai-codex, openrouter, nous, anthropic, custom).",
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
        "dashboard_auth": {
            "token_file": str(dashboard_token_path()),
            "require_auth_nonlocal": bool(_dash.get("require_auth_nonlocal", True)),
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
        return False
    from spark_cli.dashboard_auth import extract_bearer_token

    tok = extract_bearer_token(auth)
    if tok and secrets.compare_digest(tok, secret):
        return True
    return False


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
                include_children=(source == "web"),
            )
            total = db.session_count(source=source)
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


@app.get("/api/config/defaults")
async def get_defaults():
    return DEFAULT_CONFIG


@app.get("/api/config/schema")
async def get_schema():
    return {"fields": CONFIG_SCHEMA, "category_order": _CATEGORY_ORDER}


_EMPTY_MODEL_INFO: dict = {
    "model": "",
    "provider": "",
    "auto_context_length": 0,
    "config_context_length": 0,
    "effective_context_length": 0,
    "capabilities": {},
}


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


@app.put("/api/config")
async def update_config(body: ConfigUpdate):
    try:
        save_config(_denormalize_config_from_web(body.config))
        for sid in list(_web_agents.keys()):
            if sid not in _web_streaming:
                _close_web_agent(sid)
        return {"ok": True}
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
        save_env_value(body.key, body.value)
        return {"ok": True, "key": body.key}
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
    # --- Token check ---
    if not _reveal_authorized(request):
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
# Anthropic, device-code for Spark Portal/Codex) still runs in the CLI for now;
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
    auth = request.headers.get("authorization", "")
    if auth != f"Bearer {_SESSION_TOKEN}":
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
        # Block briefly until the worker has populated the user_code, OR error.
        deadline = time.time() + 10
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
        if not s.get("user_code"):
            raise HTTPException(
                status_code=504,
                detail="device-auth timed out before returning a user code",
            )
        return {
            "session_id": sid,
            "flow": "device_code",
            "user_code": s["user_code"],
            "verification_url": s["verification_url"],
            "expires_in": int(s.get("expires_in") or 900),
            "poll_interval": int(s.get("interval") or 5),
        }

    raise HTTPException(
        status_code=400,
        detail=f"Provider {provider_id} does not support device-code flow",
    )


def _nous_poller(session_id: str) -> None:
    """Background poller that drives a Spark Portal device-code flow to completion."""
    from spark_cli.auth import _poll_for_token, refresh_nous_oauth_from_state
    from datetime import datetime, timezone
    import httpx

    with _oauth_sessions_lock:
        sess = _oauth_sessions.get(session_id)
    if not sess:
        return
    portal_base_url = sess["portal_base_url"]
    client_id = sess["client_id"]
    device_code = sess["device_code"]
    interval = sess["interval"]
    expires_in = max(60, int(sess["expires_at"] - time.time()))
    try:
        with httpx.Client(
            timeout=httpx.Timeout(15.0), headers={"Accept": "application/json"}
        ) as client:
            token_data = _poll_for_token(
                client=client,
                portal_base_url=portal_base_url,
                client_id=client_id,
                device_code=device_code,
                expires_in=expires_in,
                poll_interval=interval,
            )
        # Same post-processing as _nous_device_code_login (mint agent key)
        now = datetime.now(timezone.utc)
        token_ttl = int(token_data.get("expires_in") or 0)
        auth_state = {
            "portal_base_url": portal_base_url,
            "inference_base_url": token_data.get("inference_base_url"),
            "client_id": client_id,
            "scope": token_data.get("scope"),
            "token_type": token_data.get("token_type", "Bearer"),
            "access_token": token_data["access_token"],
            "refresh_token": token_data.get("refresh_token"),
            "obtained_at": now.isoformat(),
            "expires_at": (
                datetime.fromtimestamp(
                    now.timestamp() + token_ttl, tz=timezone.utc
                ).isoformat()
                if token_ttl
                else None
            ),
            "expires_in": token_ttl,
        }
        full_state = refresh_nous_oauth_from_state(
            auth_state,
            min_key_ttl_seconds=300,
            timeout_seconds=15.0,
            force_refresh=False,
            force_mint=True,
        )
        # Save into credential pool same as auth_commands.py does
        from agent.credential_pool import (
            PooledCredential,
            load_pool,
            AUTH_TYPE_OAUTH,
            SOURCE_MANUAL,
        )

        pool = load_pool("nous")
        entry = PooledCredential.from_dict(
            "nous",
            {
                **full_state,
                "label": "dashboard device_code",
                "auth_type": AUTH_TYPE_OAUTH,
                "source": f"{SOURCE_MANUAL}:dashboard_device_code",
                "base_url": full_state.get("inference_base_url"),
            },
        )
        pool.add_entry(entry)
        # Also persist to auth store so get_nous_auth_status() sees it
        # (matches what _login_nous in auth.py does for the CLI flow).
        try:
            from spark_cli.auth import (
                _load_auth_store,
                _save_provider_state,
                _save_auth_store,
                _auth_store_lock,
            )

            with _auth_store_lock():
                auth_store = _load_auth_store()
                _save_provider_state(auth_store, "nous", full_state)
                _save_auth_store(auth_store)
        except Exception as store_exc:
            _log.warning(
                "oauth/device: credential pool saved but auth store write failed "
                "(session=%s): %s",
                session_id,
                store_exc,
            )
        with _oauth_sessions_lock:
            sess["status"] = "approved"
        _log.info("oauth/device: nous login completed (session=%s)", session_id)
    except Exception as e:
        _log.warning("nous device-code poll failed (session=%s): %s", session_id, e)
        with _oauth_sessions_lock:
            sess["status"] = "error"
            sess["error_message"] = str(e)


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
    try:
        import httpx
        from spark_cli.auth import (
            CODEX_OAUTH_CLIENT_ID,
            CODEX_OAUTH_TOKEN_URL,
            DEFAULT_CODEX_BASE_URL,
        )

        issuer = "https://auth.openai.com"

        # Step 1: request device code
        with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
            resp = client.post(
                f"{issuer}/api/accounts/deviceauth/usercode",
                json={"client_id": CODEX_OAUTH_CLIENT_ID},
                headers={"Content-Type": "application/json"},
            )
        if resp.status_code != 200:
            raise RuntimeError(f"deviceauth/usercode returned {resp.status_code}")
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
        if not access_token:
            raise RuntimeError("token exchange did not return access_token")

        # Persist via credential pool — same shape as auth_commands.add_command
        from agent.credential_pool import (
            PooledCredential,
            load_pool,
            AUTH_TYPE_OAUTH,
            SOURCE_MANUAL,
        )
        import uuid as _uuid

        pool = load_pool("openai-codex")
        base_url = (
            os.getenv("SPARK_CODEX_BASE_URL", "").strip().rstrip("/")
            or DEFAULT_CODEX_BASE_URL
        )
        entry = PooledCredential(
            provider="openai-codex",
            id=_uuid.uuid4().hex[:6],
            label="dashboard device_code",
            auth_type=AUTH_TYPE_OAUTH,
            priority=0,
            source=f"{SOURCE_MANUAL}:dashboard_device_code",
            access_token=access_token,
            refresh_token=refresh_token,
            base_url=base_url,
        )
        pool.add_entry(entry)
        with _oauth_sessions_lock:
            sess["status"] = "approved"
        _log.info("oauth/device: openai-codex login completed (session=%s)", session_id)
    except Exception as e:
        _log.warning("codex device-code worker failed (session=%s): %s", session_id, e)
        with _oauth_sessions_lock:
            s = _oauth_sessions.get(session_id)
            if s:
                s["status"] = "error"
                s["error_message"] = str(e)


@app.post("/api/providers/oauth/{provider_id}/start")
async def start_oauth_login(provider_id: str, request: Request):
    """Initiate an OAuth login flow. Token-protected."""
    auth = request.headers.get("authorization", "")
    if auth != f"Bearer {_SESSION_TOKEN}":
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
    auth = request.headers.get("authorization", "")
    if auth != f"Bearer {_SESSION_TOKEN}":
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
    }


@app.delete("/api/providers/oauth/sessions/{session_id}")
async def cancel_oauth_session(session_id: str, request: Request):
    """Cancel a pending OAuth session. Token-protected."""
    auth = request.headers.get("authorization", "")
    if auth != f"Bearer {_SESSION_TOKEN}":
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
async def get_session_messages(session_id: str):
    from core.spark_state import SessionDB

    db = SessionDB()
    try:
        sid = db.resolve_session_id(session_id)
        if not sid:
            raise HTTPException(status_code=404, detail="Session not found")
        messages = db.get_messages(sid)
        return {"session_id": sid, "messages": messages}
    finally:
        db.close()


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
        _web_streaming.discard(session_id)
        unregister_gateway_notify(session_id)
        _emit_sessions_changed("deleted", session_id)
        return {"ok": True}
    finally:
        db.close()


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
    from cron.jobs import update_job

    job = update_job(job_id, body.updates)
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
            if sid not in _web_streaming:
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


class KanbanUpdate(BaseModel):
    status: str


class ConversationCreate(BaseModel):
    message: str
    model: Optional[str] = None


class ConversationMessage(BaseModel):
    message: str


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


def _make_web_chat_callbacks(
    session_id: str,
    queue: asyncio.Queue,
    loop: asyncio.AbstractEventLoop,
):
    def token_callback(token: Optional[str]) -> None:
        if token is None:
            return
        try:
            loop.call_soon_threadsafe(queue.put_nowait, token)
        except Exception:
            pass
        _publish_event("chat.token", {"t": token}, session_id)

    def tool_start_callback(tid: str, name: str, args: Any) -> None:
        _publish_event(
            "chat.tool_start",
            {"id": tid, "name": name, "args": _json_safe(args), "ts": time.time()},
            session_id,
        )

    def tool_complete_callback(tid: str, name: str, args: Any, result: Any) -> None:
        _publish_event(
            "chat.tool_end",
            {
                "id": tid,
                "name": name,
                "args": _json_safe(args),
                "result": _truncate_str(result),
                "ts": time.time(),
            },
            session_id,
        )

    def reasoning_callback(text: str) -> None:
        _publish_event("chat.reasoning", {"text": _truncate_str(text, 8000)}, session_id)

    def status_callback(kind: str, message: str) -> None:
        _publish_event(
            "chat.status",
            {"kind": kind, "message": _truncate_str(message, 2000)},
            session_id,
        )

    return (
        token_callback,
        tool_start_callback,
        tool_complete_callback,
        reasoning_callback,
        status_callback,
    )


def _turn_done_payload(result: Any) -> Dict[str, Any]:
    """Extract token/cost stats from a run_conversation() result for chat.turn_done."""
    if not isinstance(result, dict):
        return {}
    return {
        "tokens": {
            "input": result.get("input_tokens", 0) or 0,
            "output": result.get("output_tokens", 0) or 0,
            "cache_read": result.get("cache_read_tokens", 0) or 0,
        },
        "cost_usd": result.get("estimated_cost_usd"),
        "model": result.get("model"),
    }


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
    if canonical == "sessions":
        return _web_cmd_sessions()
    if canonical == "config":
        return _web_cmd_config()
    if canonical == "tools":
        return _web_cmd_tools(args)
    if canonical == "toolsets":
        return _web_cmd_toolsets()
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

    return None  # Other web-available commands fall through to the agent


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
        f"**Session status**\n",
        f"• **ID:** `{session_id}`",
        f"• **Title:** {title}",
        f"• **Model:** {model}",
        f"• **Source:** {source}",
        f"• **Turns:** {turn_count}",
        f"• **Messages:** {len(messages)}",
    ]
    return "\n".join(lines)


def _run_web_agent_turn(
    agent: Any,
    user_message: str,
    conversation_history: Optional[list[dict[str, Any]]] = None,
) -> Any:
    from tools.approval import reset_current_session_key, set_current_session_key

    tok = set_current_session_key(agent.session_id)
    try:
        if conversation_history is not None:
            return agent.run_conversation(user_message, conversation_history=conversation_history)
        return agent.run_conversation(user_message)
    finally:
        reset_current_session_key(tok)


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
    working_dir: Optional[str] = None,
) -> Any:
    from core.run_agent import AIAgent
    from core.spark_state import SessionDB

    _close_web_agent(session_id)
    runtime = runtime or {}
    agent = AIAgent(
        session_id=session_id,
        model=model,
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


def _extract_final_response(result: Any) -> str:
    if isinstance(result, dict):
        final = result.get("final_response")
        return final if isinstance(final, str) else ""
    return ""


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
    """Persist a web turn if the agent did not write it to SQLite itself."""
    try:
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            messages = db.get_messages(session_id)
            if len(messages) > before_message_count:
                return
            db.append_message(session_id, "user", content=user_message)
            final_response = _extract_final_response(result).strip()
            if final_response:
                db.append_message(session_id, "assistant", content=final_response)
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
    ) = _make_web_chat_callbacks(session_id, queue, loop)

    if body.model:
        from spark_cli.model_config import write_global_model_config

        write_global_model_config(model=body.model)
    turn_route = _resolve_web_turn_route(body.message)
    model = turn_route["model"]

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

    def _gw_notify(data: dict) -> None:
        _publish_event("chat.approval_requested", {"approval": _json_safe(data)}, session_id)

    async def run_agent_task() -> None:
        register_gateway_notify(session_id, _gw_notify)
        _web_streaming.add(session_id)
        before_message_count = _session_message_count(session_id)
        result = None
        try:
            slash_text = _execute_web_slash_command(session_id, message)
            if slash_text is not None:
                _publish_event("chat.token", {"t": slash_text}, session_id)
                result = {"final_response": slash_text}
            else:
                result = await loop.run_in_executor(
                    None, lambda: _run_web_agent_turn(agent, message, None)
                )
        except Exception:
            _log.exception("Web chat agent error session=%s", session_id)
        finally:
            _web_streaming.discard(session_id)
            unregister_gateway_notify(session_id)
            _persist_web_turn_if_missing(session_id, message, result, before_message_count)
            _emit_web_session_updated(session_id)
            loop.call_soon_threadsafe(queue.put_nowait, None)
            _publish_event("chat.turn_done", _turn_done_payload(result), session_id)

    asyncio.create_task(run_agent_task())
    return {"session_id": session_id, "ok": True}


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
    ) = _make_web_chat_callbacks(session_id, queue, loop)

    from core.spark_state import SessionDB

    conversation_history: Optional[list[dict[str, Any]]] = None
    db = SessionDB()
    try:
        sid = db.resolve_session_id(session_id)
        if not sid:
            raise HTTPException(status_code=404, detail="Session not found")
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
        ) = _make_web_chat_callbacks(session_id, queue, loop)
        _web_queues[session_id] = queue
        turn_route = _resolve_web_turn_route(body.message)
        agent = _web_agents.get(session_id)
        if agent and _web_agent_signatures.get(session_id) == turn_route["signature"]:
            agent.stream_delta_callback = token_callback
            agent.tool_start_callback = tool_start_callback
            agent.tool_complete_callback = tool_complete_callback
            agent.reasoning_callback = reasoning_callback
            agent.status_callback = status_callback
            agent.request_overrides = turn_route.get("request_overrides")
        else:
            conversation_history = db.get_messages_as_conversation(session_id)
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
            )
        _update_web_session_model(session_id, turn_route["model"])
        try:
            db.reopen_session(session_id)
        except Exception:
            pass
    finally:
        db.close()

    message = body.message

    def _gw_notify(data: dict) -> None:
        _publish_event("chat.approval_requested", {"approval": _json_safe(data)}, session_id)

    async def run_agent_task() -> None:
        register_gateway_notify(session_id, _gw_notify)
        _web_streaming.add(session_id)
        before_message_count = _session_message_count(session_id)
        result = None
        try:
            slash_text = _execute_web_slash_command(session_id, message)
            if slash_text is not None:
                _publish_event("chat.token", {"t": slash_text}, session_id)
                result = {"final_response": slash_text}
            else:
                result = await loop.run_in_executor(
                    None, lambda: _run_web_agent_turn(agent, message, conversation_history)
                )
        except Exception:
            _log.exception("Web chat follow-up error session=%s", session_id)
        finally:
            _web_streaming.discard(session_id)
            unregister_gateway_notify(session_id)
            _persist_web_turn_if_missing(session_id, message, result, before_message_count)
            _emit_web_session_updated(session_id)
            loop.call_soon_threadsafe(queue.put_nowait, None)
            _publish_event("chat.turn_done", _turn_done_payload(result), session_id)

    asyncio.create_task(run_agent_task())
    return {"session_id": session_id, "ok": True}


@app.post("/api/conversations/{session_id}/interrupt")
async def interrupt_conversation(session_id: str, body: ConversationInterrupt):
    agent = _web_agents.get(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Session not in active memory.")
    try:
        agent.interrupt(body.message)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    _publish_event(
        "chat.interrupted",
        {"message": body.message or ""},
        session_id,
    )
    return {"ok": True, "session_id": session_id}


@app.post("/api/conversations/{session_id}/model")
async def switch_conversation_model(session_id: str, body: ConversationModelBody):
    if session_id in _web_streaming:
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
        if sid not in _web_streaming:
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


@app.post("/api/conversations/{session_id}/retry")
async def retry_conversation(session_id: str, body: ConversationRetryBody):
    from tools.approval import register_gateway_notify, unregister_gateway_notify

    agent = _web_agents.get(session_id)
    if session_id in _web_streaming:
        raise HTTPException(status_code=409, detail="A turn is already running.")

    from core.spark_state import SessionDB

    db = SessionDB()
    try:
        sid = db.resolve_session_id(session_id)
        if not sid:
            raise HTTPException(status_code=404, detail="Session not found")
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
    ) = _make_web_chat_callbacks(session_id, queue, loop)
    turn_route = _resolve_web_turn_route(user_msg)
    if agent and _web_agent_signatures.get(session_id) == turn_route["signature"]:
        agent.stream_delta_callback = token_callback
        agent.tool_start_callback = tool_start_callback
        agent.tool_complete_callback = tool_complete_callback
        agent.reasoning_callback = reasoning_callback
        agent.status_callback = status_callback
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
        )
    _update_web_session_model(session_id, turn_route["model"])

    def _gw_notify(data: dict) -> None:
        _publish_event("chat.approval_requested", {"approval": _json_safe(data)}, session_id)

    async def run_agent_task() -> None:
        register_gateway_notify(session_id, _gw_notify)
        _web_streaming.add(session_id)
        try:
            await loop.run_in_executor(
                None,
                lambda: _run_web_agent_turn(agent, user_msg, conv_hist),
            )
        except Exception:
            _log.exception("Web chat retry error session=%s", session_id)
        finally:
            _web_streaming.discard(session_id)
            unregister_gateway_notify(session_id)
            loop.call_soon_threadsafe(queue.put_nowait, None)
            _publish_event("chat.turn_done", {}, session_id)  # retry — result not captured

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


# ── Workspace conversation endpoints ─────────────────────────────────────────


class WorkspaceConvCreate(BaseModel):
    message: str
    model: Optional[str] = None


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
            working_dir=str(project_dir),
        )
        agent.ephemeral_system_prompt = (
            f"You are working in the '{slug}' workspace project.\n"
            f"Working directory: {project_dir}\n"
            "IMPORTANT: All file operations, terminal commands, and searches MUST stay within "
            f"this directory ({project_dir}). Do NOT read from or write to any other project "
            "directory. If the user asks you to build or edit something, create or modify files "
            f"only under {project_dir}."
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

    def _gw_notify(data: dict) -> None:
        _publish_event("chat.approval_requested", {"approval": _json_safe(data)}, session_id)

    raw_message = body.message

    async def run_agent_task() -> None:
        register_gateway_notify(session_id, _gw_notify)
        _web_streaming.add(session_id)
        before_message_count = _session_message_count(session_id)
        result = None
        slash_text = None
        try:
            slash_text = _execute_web_slash_command(session_id, raw_message)
            if slash_text is not None:
                _publish_event("chat.token", {"t": slash_text}, session_id)
                result = {"final_response": slash_text}
            else:
                result = await loop.run_in_executor(
                    None, lambda: _run_web_agent_turn(agent, message, None)
                )
        except Exception:
            _log.exception("Workspace chat agent error session=%s slug=%s", session_id, slug)
        finally:
            _web_streaming.discard(session_id)
            unregister_gateway_notify(session_id)
            _strip_user_message_prefix(session_id, context_prefix, raw_message)
            _persist_web_turn_if_missing(session_id, raw_message, result, before_message_count)
            _emit_web_session_updated(session_id)
            loop.call_soon_threadsafe(queue.put_nowait, None)
            _publish_event("chat.turn_done", _turn_done_payload(result), session_id)

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

    ensure_dashboard_token_file()
    browse_host = "127.0.0.1" if host in ("0.0.0.0", "::", "[::]") else host
    if host not in ("127.0.0.1", "localhost", "::1"):
        import logging

        logging.warning(
            "Binding to %s — enable dashboard.require_auth_nonlocal (default) and use %s "
            "or SPARK_DASHBOARD_TOKEN for API access from other machines.",
            host,
            dashboard_token_path(),
        )

    if open_browser:
        import threading
        import webbrowser

        def _open():
            import time as _t

            _t.sleep(1.0)
            webbrowser.open(f"http://{browse_host}:{port}")

        threading.Thread(target=_open, daemon=True).start()

    print(f"  Spark Web UI → http://{browse_host}:{port} (bind {host}:{port})")
    uvicorn.run(app, host=host, port=port, log_level="warning")
