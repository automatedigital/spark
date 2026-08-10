"""FastAPI routes for the providers API.

Extracted from web_server.py, which declared these directly on the app.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import queue as thread_queue
import re
import secrets
import shutil
import subprocess
import threading
import time
import urllib
import uuid
from typing import Any, cast

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from spark_cli.env_routes import _reveal_authorized
from spark_cli.web_runtime import _run_blocking

# Import OAuth constants from canonical source instead of duplicating.
# Guarded so spark web still starts if anthropic_adapter is unavailable;
# Phase 2 endpoints will return 501 in that case.
try:
    from agent.anthropic_adapter import (
        _OAUTH_CLIENT_ID as _ANTHROPIC_OAUTH_CLIENT_ID,
    )
    from agent.anthropic_adapter import (
        _OAUTH_REDIRECT_URI as _ANTHROPIC_OAUTH_REDIRECT_URI,
    )
    from agent.anthropic_adapter import (
        _OAUTH_SCOPES as _ANTHROPIC_OAUTH_SCOPES,
    )
    from agent.anthropic_adapter import (
        _OAUTH_TOKEN_URL as _ANTHROPIC_OAUTH_TOKEN_URL,
    )
    from agent.anthropic_adapter import (
        _generate_pkce as _generate_pkce_pair,
    )

    _ANTHROPIC_OAUTH_AVAILABLE = True
except ImportError:
    _ANTHROPIC_OAUTH_AVAILABLE = False


_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/providers", tags=["providers"])


def _truncate_str(s: Any, max_len: int = 16000) -> str:
    if s is None:
        return ""
    t = str(s)
    return t if len(t) <= max_len else t[: max_len - 1] + "…"


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
            _log.debug("Ignoring error in _read_output()", exc_info=True)
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
                    _log.debug("Ignoring error in _codex_cli_device_login_worker()", exc_info=True)
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
            _log.debug("Ignoring error in _codex_cli_device_login_worker()", exc_info=True)
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


def _truncate_token(value: str | None, visible: int = 6) -> str:
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


def _anthropic_oauth_status() -> dict[str, Any]:
    """Combined status across the three Anthropic credential sources we read.

    Spark resolves Anthropic creds in this order at runtime:
    1. ``~/.spark/.anthropic_oauth.json`` — Spark-managed PKCE flow
    2. ``~/.claude/.credentials.json`` — Claude Code CLI credentials (auto)
    3. ``ANTHROPIC_TOKEN`` / ``ANTHROPIC_API_KEY`` env vars
    The dashboard reports the highest-priority source that's actually present.
    """
    try:
        from agent.anthropic_adapter import (
            _SPARK_OAUTH_FILE,
            read_claude_code_credentials,
            read_spark_oauth_credentials,
        )
    except ImportError:
        read_claude_code_credentials = None  # type: ignore
        read_spark_oauth_credentials = None  # type: ignore
        _SPARK_OAUTH_FILE = None  # type: ignore

    spark_creds = None
    if read_spark_oauth_credentials is not None:
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
    if read_claude_code_credentials is not None:
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


def _claude_code_only_status() -> dict[str, Any]:
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


_OAUTH_SESSION_TTL_SECONDS = 15 * 60


_ANTHROPIC_OAUTH_AUTHORIZE_URL = "https://claude.ai/oauth/authorize"


def _new_oauth_session(provider_id: str, flow: str) -> tuple[str, dict[str, Any]]:
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
        import uuid

        from agent.credential_pool import (
            AUTH_TYPE_OAUTH,
            SOURCE_MANUAL,
            PooledCredential,
            load_pool,
        )

        pool = load_pool("anthropic")
        # Avoid duplicate entries: delete any prior dashboard-issued OAuth entry
        # remove_index is 1-based and renumbers what follows, so walk the
        # matches from the end.  This previously called a remove_entry() that
        # CredentialPool has never had: every call raised AttributeError, was
        # swallowed by the except below, and duplicate dashboard entries piled
        # up instead of being replaced.
        stale = [
            index
            for index, entry in enumerate(pool.entries(), start=1)
            if getattr(entry, "source", "").startswith(f"{SOURCE_MANUAL}:dashboard_pkce")
        ]
        for index in reversed(stale):
            try:
                pool.remove_index(index)
            except Exception:
                _log.debug("Ignoring error in _save_anthropic_oauth_creds()", exc_info=True)
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


_OAUTH_PROVIDER_CATALOG: tuple[dict[str, Any], ...] = (
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


def _resolve_provider_status(provider_id: str, status_fn) -> dict[str, Any]:
    """Dispatch to the right status helper for an OAuth provider entry."""
    if status_fn is not None:
        try:
            return cast("dict[str, Any]", status_fn())
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


_oauth_sessions: dict[str, dict[str, Any]] = {}


_oauth_sessions_lock = threading.Lock()


def _gc_oauth_sessions() -> None:
    """Drop expired sessions. Called opportunistically on /start."""
    cutoff = time.time() - _OAUTH_SESSION_TTL_SECONDS
    with _oauth_sessions_lock:
        stale = [
            sid for sid, sess in _oauth_sessions.items() if sess["created_at"] < cutoff
        ]
        for sid in stale:
            _oauth_sessions.pop(sid, None)


def _start_anthropic_pkce() -> dict[str, Any]:
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


def _submit_anthropic_pkce(session_id: str, code_input: str) -> dict[str, Any]:
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


async def _start_device_code_flow(provider_id: str) -> dict[str, Any]:
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


class OAuthSubmitBody(BaseModel):
    session_id: str
    code: str


@router.get("/oauth")
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


@router.delete("/oauth/{provider_id}")
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
            _log.debug("Ignoring error in disconnect_oauth_provider()", exc_info=True)
        # Also clear the credential pool entry if present.
        try:
            from spark_cli.auth import clear_provider_auth

            clear_provider_auth("anthropic")
        except Exception:
            _log.debug("Ignoring error in disconnect_oauth_provider()", exc_info=True)
        _log.info("oauth/disconnect: %s", provider_id)
        return {"ok": True, "provider": provider_id}

    try:
        from spark_cli.auth import clear_provider_auth

        cleared = clear_provider_auth(provider_id)
        _log.info("oauth/disconnect: %s (cleared=%s)", provider_id, cleared)
        return {"ok": bool(cleared), "provider": provider_id}
    except Exception as e:
        _log.exception("disconnect %s failed", provider_id)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/oauth/{provider_id}/start")
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
        raise HTTPException(status_code=500, detail=str(e)) from e
    raise HTTPException(status_code=400, detail="Unsupported flow")


@router.post("/oauth/{provider_id}/submit")
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
        return await _run_blocking(
            _submit_anthropic_pkce, body.session_id, body.code
        )
    raise HTTPException(
        status_code=400, detail=f"submit not supported for {provider_id}"
    )


@router.get("/oauth/{provider_id}/poll/{session_id}")
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


@router.delete("/oauth/sessions/{session_id}")
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


def register_providers_routes(app) -> None:
    app.include_router(router)
