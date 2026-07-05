"""
Connectors API routes — handles OAuth flows for third-party services.

Currently supports: Google Workspace plus catalog-backed CLI/skill connectors.

OAuth flow:
  1. POST /api/connectors/google/connect  → returns {auth_url}
  2. Frontend opens auth_url in a popup window
  3. User consents → Google redirects to GET /oauth/google/callback
  4. Server exchanges code for tokens, saves them
  5. Frontend polls GET /api/connectors/google/status → {connected: true}
"""

from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_server_port: int = 9119
_pending_states: dict[str, str] = {}  # state → code_verifier (Google)
_pending_oauth_states: dict[str, tuple[str, str]] = {}  # state → (provider_id, code_verifier)
_pending_device_states: dict[str, dict] = {}  # state → device flow metadata


class GmailImapConnectRequest(BaseModel):
    email: str
    app_password: str


class ApiKeyRequest(BaseModel):
    api_key: str
    env_var: str = ""  # optional override; must be one of the connector's env vars


def _connector_kind(connector) -> str:
    """Coarse connect-flow kind for the UI: mcp / oauth / cli / api_key."""
    from tools.connectors import Transport

    if connector.transport is Transport.MCP:
        return "mcp"
    spec = getattr(connector, "spec", None)
    auth_type = getattr(spec, "auth_type", "") if spec is not None else ""
    if auth_type == "cli":
        return "cli"
    if auth_type == "oauth":
        return "oauth"
    return "api_key"


def _connector_payload(connector, status) -> dict:
    """Single-payload description + live state for one connector."""
    from spark_cli.connector_skills import grant_for

    spec = getattr(connector, "spec", None)
    mapping = grant_for(connector.id, connector.skills)
    return {
        **connector.describe(),
        "icon": connector.id,
        "kind": _connector_kind(connector),
        "connected": status.connected,
        "configured": status.state.value != "not_installed",
        "state": status.state.value,
        "detail": status.detail,
        "account": status.account,
        "api_key_url": getattr(spec, "api_key_url", "") if spec is not None else "",
        "primary_env_var": getattr(spec, "primary_env_var", "") if spec is not None else "",
        "env_vars": list(getattr(spec, "env_vars", ()) or ()) if spec is not None else [],
        "setup_steps": list(getattr(spec, "setup_steps", ()) or ()) if spec is not None else [],
        "skills": mapping["skills"],
        "toolsets": mapping["toolsets"],
        "status": status.to_dict(),
    }


def set_server_port(port: int) -> None:
    """Called by web_server.py at startup so we know our callback URL."""
    global _server_port
    _server_port = port


def _redirect_uri(provider: str = "google") -> str:
    """OAuth callback URL Google should redirect back to after consent.

    Resolution order:

    1. ``connectors.oauth_redirect_base`` in ``config.yaml`` — an explicit base
       (e.g. ``https://spark.example.com``) for deployments behind a proxy or
       with a custom domain. The provider console must allow this exact URI.
    2. Server environment / ``dashboard.public_url`` → derive a reachable base
       via ``get_public_base_url`` so a remote browser is redirected back to a
       host it can actually reach (not ``localhost``).
    3. Desktop / local default → ``http://localhost:{port}``.

    OAuth providers require the redirect URI to be pre-registered, so we keep
    ``localhost`` as the default and only diverge when the deployment clearly
    isn't local.
    """
    path = f"/oauth/{provider}/callback"

    # 1. Explicit override
    try:
        import yaml  # type: ignore[import-untyped]

        from spark_cli.config import get_spark_home

        cfg_path = get_spark_home() / "config.yaml"
        if cfg_path.exists():
            with open(cfg_path) as fh:
                cfg = yaml.safe_load(fh) or {}
            base = ((cfg.get("connectors") or {}).get("oauth_redirect_base") or "").strip()
            if base:
                return f"{base.rstrip('/')}{path}"
    except Exception:
        pass

    # 2. Server / public deployment → reachable host
    try:
        from core.spark_constants import get_public_base_url, is_server_environment

        if is_server_environment():
            base = get_public_base_url("0.0.0.0", _server_port).rstrip("/")
            return f"{base}{path}"
    except Exception:
        pass

    # 3. Local default
    return f"http://localhost:{_server_port}{path}"


# ---------------------------------------------------------------------------
# GET /api/connectors — list all connectors
# ---------------------------------------------------------------------------

@router.get("/api/connectors")
async def list_connectors():
    from spark_cli.connector_skills import grant_for
    from tools.connectors import list_connectors as list_registered_connectors

    items = []
    for connector in list_registered_connectors():
        if connector.id == "google":
            continue
        status = connector.status()
        items.append(_connector_payload(connector, status))

    try:
        from spark_cli.google_connector import get_connection_status_async
        google_status = await get_connection_status_async()
    except Exception as exc:
        logger.warning("Error getting Google connector status: %s", exc)
        google_status = {"connected": False, "configured": False, "error": str(exc)}

    return JSONResponse(
        [
            {
                "id": "google",
                "name": "Google Workspace",
                "description": "Gmail, Google Calendar",
                "icon": "google",
                "kind": "oauth",
                "transport": "cli",
                "state": "connected" if google_status.get("connected") else "disconnected",
                "detail": (
                    f"Connected as {google_status.get('email')}"
                    if google_status.get("connected") and google_status.get("email")
                    else "Use OAuth sign-in and optional Gmail IMAP app password."
                ),
                "skills": grant_for("google")["skills"],
                "toolsets": grant_for("google")["toolsets"],
                "docs_url": "https://developers.google.com/workspace",
                "status": {
                    "state": "connected" if google_status.get("connected") else "disconnected",
                    "detail": "Google Workspace OAuth connector",
                    "account": google_status.get("email"),
                    "extra": {
                        "auth_type": "oauth",
                        "auth_url": "/api/connectors/google/connect",
                    },
                },
                **google_status,
            },
            *items,
        ]
    )


# ---------------------------------------------------------------------------
# GET /api/connectors/cli-tools — detect CLI-backed coding agents on PATH
# ---------------------------------------------------------------------------

# (connector id, display name, binary, install hint)
_CLI_TOOLS: tuple[tuple[str, str, str, str], ...] = (
    ("claude-code", "Claude Code", "claude", "npm install -g @anthropic-ai/claude-code"),
    ("codex", "OpenAI Codex", "codex", "npm install -g @openai/codex"),
    ("opencode", "OpenCode", "opencode", "npm install -g opencode-ai"),
)


@router.get("/api/connectors/cli-tools")
async def connector_cli_tools():
    """Detected/not-detected state for CLI coding agents (binary on PATH)."""
    from tools.connectors.generic import _command_path

    items = []
    for connector_id, name, binary, install_hint in _CLI_TOOLS:
        path = _command_path(binary)
        items.append(
            {
                "id": connector_id,
                "name": name,
                "cli": binary,
                "detected": bool(path),
                "path": path,
                "install_hint": install_hint,
            }
        )
    return JSONResponse(items)


# ---------------------------------------------------------------------------
# POST /api/connectors/{id}/skills/enable — auto-enable mapped skills/toolsets
# ---------------------------------------------------------------------------

@router.post("/api/connectors/{connector_id}/skills/enable")
async def connector_enable_skills(connector_id: str):
    """Enable the skills/toolsets mapped to this connector (used after connect)."""
    try:
        from spark_cli.connector_skills import enable_connector_skills
        from tools.connectors import get_connector

        connector = get_connector(connector_id)
        if connector is None:
            return JSONResponse({"error": "unknown_connector"}, status_code=404)
        result = enable_connector_skills(connector_id, connector.skills)
        return JSONResponse({"ok": True, **result})
    except Exception as exc:
        logger.warning("connector_enable_skills error for %s: %s", connector_id, exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# POST /api/connectors/{id}/api-key — guided key paste (persists to profile .env)
# ---------------------------------------------------------------------------

@router.post("/api/connectors/{connector_id}/api-key")
async def connector_save_api_key(connector_id: str, payload: ApiKeyRequest):
    """Persist a pasted API key to the active profile's .env and re-probe status.

    The key is written via `save_env_value` (atomic write, 0600, under
    `get_spark_home()`), never a hardcoded path.
    """
    try:
        from tools.connectors import get_connector

        connector = get_connector(connector_id)
        if connector is None:
            return JSONResponse({"error": "unknown_connector"}, status_code=404)
        spec = getattr(connector, "spec", None)
        env_vars = list(getattr(spec, "env_vars", ()) or ()) if spec is not None else []
        if not env_vars:
            return JSONResponse(
                {"error": "no_api_key", "message": "This connector does not use an API key."},
                status_code=400,
            )
        env_var = (payload.env_var or "").strip() or (
            getattr(spec, "primary_env_var", "") or env_vars[0]
        )
        if env_var not in env_vars:
            return JSONResponse(
                {"error": "invalid_env_var", "message": f"Expected one of: {', '.join(env_vars)}"},
                status_code=400,
            )
        api_key = payload.api_key.strip()
        if not api_key or any(ch in api_key for ch in "\r\n"):
            return JSONResponse(
                {"error": "invalid_api_key", "message": "Paste a single-line API key."},
                status_code=400,
            )

        from spark_cli.config import save_env_value

        save_env_value(env_var, api_key)

        status = connector.status()
        if status.connected:
            try:
                from spark_cli.connector_skills import enable_connector_skills

                enable_connector_skills(connector_id, connector.skills)
            except Exception as exc:
                logger.warning("Could not enable skills for %s: %s", connector_id, exc)
        if status.state.value == "error":
            # Validation failed — roll back so a bad key isn't left in .env.
            try:
                from spark_cli.config import remove_env_value

                remove_env_value(env_var)
            except Exception:
                pass
            return JSONResponse(
                {"error": "validation_failed", "message": status.detail},
                status_code=400,
            )
        return JSONResponse({"saved": True, "env_var": env_var,
                             **_connector_payload(connector, status)})
    except Exception as exc:
        logger.warning("connector_save_api_key error for %s: %s", connector_id, exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# GET /api/connectors/{id}/connect/status — poll a pending (MCP OAuth) connect
# ---------------------------------------------------------------------------

@router.get("/api/connectors/{connector_id}/connect/status")
async def connector_connect_status(connector_id: str):
    try:
        from tools.connectors import get_connector

        connector = get_connector(connector_id)
        if connector is None:
            return JSONResponse({"error": "unknown_connector"}, status_code=404)
        status = connector.status()
        extra = status.extra or {}
        return JSONResponse({
            "connected": status.connected,
            "state": status.state.value,
            "detail": status.detail,
            "connect_state": extra.get("connect_state", ""),
            "connect_error": extra.get("connect_error", ""),
        })
    except Exception as exc:
        logger.warning("connector_connect_status error for %s: %s", connector_id, exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.get("/api/connectors/{connector_id}/status")
async def connector_status(connector_id: str):
    if connector_id == "google":
        return await google_status()
    try:
        from tools.connectors import get_connector

        connector = get_connector(connector_id)
        if connector is None:
            return JSONResponse({"error": "unknown_connector"}, status_code=404)
        status = connector.status()
        return JSONResponse({
            **connector.describe(),
            "icon": connector.id,
            "connected": status.connected,
            "configured": status.state.value != "not_installed",
            "state": status.state.value,
            "detail": status.detail,
            "account": status.account,
            "status": status.to_dict(),
        })
    except Exception as exc:
        logger.warning("Error getting %s connector status: %s", connector_id, exc)
        return JSONResponse({"connected": False, "configured": False, "error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# GET /api/connectors/google/setup — BYO-client setup helper info
# ---------------------------------------------------------------------------

@router.get("/api/connectors/google/setup")
async def google_setup_info():
    """Info for the in-app BYO-client setup helper.

    Returns the exact redirect URI the user must register in their own Google
    OAuth client, the scopes Spark requests, and whether a client is configured.
    Lets the Connectors UI turn 'figure out your VPS redirect' into one copy-paste.
    """
    try:
        from spark_cli.google_connector import get_scopes, is_configured
        redirect_uri = _redirect_uri()
        return JSONResponse({
            "redirect_uri": redirect_uri,
            "scopes": get_scopes(),
            "configured": is_configured(),
            "config_keys": {
                "client_id": "connectors.google.client_id",
                "client_secret": "connectors.google.client_secret",
            },
            "console_url": "https://console.cloud.google.com/apis/credentials",
            "client_type": "Web application",
        })
    except Exception as exc:
        logger.warning("google_setup_info error: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# GET /api/connectors/google/status
# ---------------------------------------------------------------------------

@router.get("/api/connectors/google/status")
async def google_status():
    try:
        from spark_cli.google_connector import get_connection_status_async
        return JSONResponse(await get_connection_status_async())
    except Exception as exc:
        logger.warning("Error getting Google status: %s", exc)
        return JSONResponse({"connected": False, "configured": False, "error": str(exc)})


# ---------------------------------------------------------------------------
# POST /api/connectors/google/gmail-imap — connect Gmail read via App Password
# ---------------------------------------------------------------------------

@router.post("/api/connectors/google/gmail-imap")
async def google_gmail_imap_connect(payload: GmailImapConnectRequest):
    try:
        from spark_cli.google_connector import save_imap_credentials

        save_imap_credentials(payload.email, payload.app_password)
        return JSONResponse({"connected": True, "email": payload.email.strip()})
    except Exception as exc:
        logger.warning("Error saving Gmail IMAP credentials: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=400)


@router.delete("/api/connectors/google/gmail-imap")
async def google_gmail_imap_disconnect():
    try:
        from spark_cli.google_connector import clear_imap_credentials

        clear_imap_credentials()
        return JSONResponse({"disconnected": True})
    except Exception as exc:
        logger.warning("Error clearing Gmail IMAP credentials: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# POST /api/connectors/google/connect — start OAuth flow
# ---------------------------------------------------------------------------

@router.post("/api/connectors/google/connect")
async def google_connect():
    from spark_cli.google_connector import (
        build_auth_url,
        generate_pkce_pair,
        get_relay_url,
        is_configured,
    )

    if not is_configured():
        return JSONResponse(
            {
                "error": "not_configured",
                "message": (
                    "Google OAuth is not configured. Add your client_id and "
                    "client_secret to config.yaml under connectors.google, "
                    "or set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET "
                    "environment variables."
                ),
            },
            status_code=400,
        )

    # Relay mode (one-click shared client): the relay owns the registered redirect
    # and PKCE; we just ask it to start a session pointed at our own callback.
    relay = get_relay_url()
    if relay:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{relay}/session",
                    json={"instance_callback": _redirect_uri()},
                )
                resp.raise_for_status()
                return JSONResponse({"auth_url": resp.json()["auth_url"]})
        except Exception as exc:
            logger.warning("relay /session failed: %s", exc)
            return JSONResponse(
                {"error": "relay_unavailable", "message": str(exc)}, status_code=502
            )

    state = secrets.token_urlsafe(32)
    code_verifier, code_challenge = generate_pkce_pair()
    _pending_states[state] = code_verifier

    auth_url = build_auth_url(
        state=state,
        code_challenge=code_challenge,
        redirect_uri=_redirect_uri(),
    )

    return JSONResponse({"auth_url": auth_url})


@router.post("/api/connectors/{connector_id}/connect")
async def connector_connect(connector_id: str):
    if connector_id == "google":
        return await google_connect()
    try:
        from spark_cli.oauth_connectors import (
            OAUTH_PROVIDERS,
            build_auth_url,
            generate_pkce_pair,
            is_configured,
        )
        from tools.connectors import get_connector

        connector = get_connector(connector_id)
        if connector is None:
            return JSONResponse({"error": "unknown_connector"}, status_code=404)

        # MCP preset connectors: connect() writes the mcp_servers entry and
        # launches the browser OAuth flow in the background; the UI polls
        # GET /api/connectors/{id}/connect/status until connected.
        from tools.connectors import Transport

        if connector.transport is Transport.MCP:
            status = connector.connect()
            try:
                from spark_cli.connector_skills import enable_connector_skills

                enable_connector_skills(connector_id, connector.skills)
            except Exception as exc:
                logger.warning("Could not enable skills for %s: %s", connector_id, exc)
            extra = status.extra or {}
            return JSONResponse({
                "flow": "mcp_oauth" if extra.get("auth_type") == "mcp_oauth" else "mcp",
                "connected": status.connected,
                "state": status.state.value,
                "detail": status.detail,
                "connect_state": extra.get("connect_state", ""),
                "poll_url": f"/api/connectors/{connector_id}/connect/status",
            })

        if connector_id not in OAUTH_PROVIDERS:
            return JSONResponse(
                {
                    "error": "oauth_unavailable",
                    "message": "This connector uses API-key or CLI setup.",
                },
                status_code=400,
            )
        if not is_configured(connector_id):
            return JSONResponse(
                {
                    "error": "not_configured",
                    "message": (
                        f"{connector.name} OAuth is not configured for this Spark install. "
                        "Use the API key setup now, or add OAuth client credentials under "
                        f"connectors.{connector_id}.oauth in config.yaml."
                    ),
                },
                status_code=400,
            )
        if connector_id == "github":
            from spark_cli.oauth_connectors import request_device_code

            device = request_device_code(connector_id)
            state = secrets.token_urlsafe(24)
            _pending_device_states[state] = {
                "connector_id": connector_id,
                "device_code": device["device_code"],
                "expires_at": __import__("time").time() + int(device.get("expires_in", 900)),
                "interval": int(device.get("interval", 5)),
            }
            return JSONResponse({
                "flow": "device_code",
                "device_state": state,
                "user_code": device.get("user_code"),
                "verification_uri": device.get("verification_uri"),
                "expires_in": device.get("expires_in", 900),
                "interval": device.get("interval", 5),
                "auth_url": device.get("verification_uri"),
            })
        state = secrets.token_urlsafe(32)
        code_verifier, code_challenge = generate_pkce_pair()
        _pending_oauth_states[state] = (connector_id, code_verifier)
        return JSONResponse({
            "auth_url": build_auth_url(
                connector_id,
                state=state,
                code_challenge=code_challenge,
                redirect_uri=_redirect_uri(connector_id),
            )
        })
    except Exception as exc:
        logger.warning("connector_connect error for %s: %s", connector_id, exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.post("/api/connectors/{connector_id}/device/poll")
async def connector_device_poll(connector_id: str, request: Request):
    try:
        import time

        from spark_cli.oauth_connectors import enrich_token, poll_device_code, save_token

        body = await request.json()
        state = str(body.get("device_state") or "")
        pending = _pending_device_states.get(state)
        if not pending or pending.get("connector_id") != connector_id:
            return JSONResponse({"error": "invalid_device_state"}, status_code=400)
        if time.time() > float(pending.get("expires_at", 0)):
            _pending_device_states.pop(state, None)
            return JSONResponse({"error": "expired_token"}, status_code=400)
        token = poll_device_code(connector_id, str(pending["device_code"]))
        error = token.get("error")
        if error in {"authorization_pending", "slow_down"}:
            return JSONResponse({
                "connected": False,
                "pending": True,
                "error": error,
                "interval": pending.get("interval", 5) + (5 if error == "slow_down" else 0),
            })
        if error:
            _pending_device_states.pop(state, None)
            return JSONResponse({"connected": False, "error": error}, status_code=400)
        token = enrich_token(connector_id, token)
        save_token(connector_id, token)
        _pending_device_states.pop(state, None)
        return JSONResponse({
            "connected": True,
            "account": token.get("account"),
        })
    except Exception as exc:
        logger.warning("connector_device_poll error for %s: %s", connector_id, exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# GET /oauth/google/callback — Google redirects here after consent
# ---------------------------------------------------------------------------

_CALLBACK_SUCCESS_HTML = """<!DOCTYPE html>
<html>
<head>
  <title>Google Connected</title>
  <style>
    body {{ font-family: system-ui, sans-serif; display: flex; align-items: center;
            justify-content: center; height: 100vh; margin: 0; background: #0a0a0a; color: #fff; }}
    .card {{ text-align: center; padding: 2rem; }}
    .icon {{ font-size: 3rem; margin-bottom: 1rem; }}
    h1 {{ font-size: 1.25rem; margin: 0 0 0.5rem; }}
    p {{ color: #888; font-size: 0.875rem; margin: 0; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">✓</div>
    <h1>Google Connected</h1>
    <p>You can close this window and return to Spark.</p>
    <script>
      setTimeout(() => {{ try {{ window.close(); }} catch(e) {{}} }}, 1500);
    </script>
  </div>
</body>
</html>"""

_CALLBACK_ERROR_HTML = """<!DOCTYPE html>
<html>
<head>
  <title>Connection Failed</title>
  <style>
    body {{ font-family: system-ui, sans-serif; display: flex; align-items: center;
            justify-content: center; height: 100vh; margin: 0; background: #0a0a0a; color: #fff; }}
    .card {{ text-align: center; padding: 2rem; }}
    .icon {{ font-size: 3rem; margin-bottom: 1rem; }}
    h1 {{ font-size: 1.25rem; margin: 0 0 0.5rem; }}
    p {{ color: #f87171; font-size: 0.875rem; margin: 0; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">✗</div>
    <h1>Connection Failed</h1>
    <p>{error}</p>
  </div>
</body>
</html>"""


@router.get("/oauth/google/callback")
async def google_oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    ticket: str | None = None,
):
    if error:
        logger.warning("Google OAuth error: %s", error)
        return HTMLResponse(_CALLBACK_ERROR_HTML.format(error=error))

    # Relay mode: the relay redirected here with a one-time ticket. Redeem it for
    # tokens (the relay already exchanged the code) and save the connection.
    if ticket:
        try:
            from spark_cli.google_connector import (
                claim_relay_tokens,
                get_user_info,
                save_token,
            )
            token = claim_relay_tokens(ticket)
            try:
                info = get_user_info(token["access_token"])
                token["email"] = info.get("email")
                token["name"] = info.get("name")
                token["picture"] = info.get("picture")
            except Exception as exc:
                logger.warning("Could not fetch user info after relay connect: %s", exc)
            save_token(token)
            logger.info("Google connected via relay: %s", token.get("email", "unknown"))
            return HTMLResponse(_CALLBACK_SUCCESS_HTML)
        except Exception as exc:
            logger.exception("Relay ticket claim failed: %s", exc)
            return HTMLResponse(_CALLBACK_ERROR_HTML.format(error=f"Relay claim failed: {exc}"))

    if not code or not state:
        return HTMLResponse(_CALLBACK_ERROR_HTML.format(error="Missing code or state parameter"))

    code_verifier = _pending_states.pop(state, None)
    if not code_verifier:
        return HTMLResponse(_CALLBACK_ERROR_HTML.format(error="Invalid or expired state. Please try connecting again."))

    try:
        from spark_cli.google_connector import (
            exchange_code,
            get_user_info,
            save_token,
        )

        token = exchange_code(
            code=code,
            code_verifier=code_verifier,
            redirect_uri=_redirect_uri(),
        )

        # Fetch and cache profile info immediately
        try:
            info = get_user_info(token["access_token"])
            token["email"] = info.get("email")
            token["name"] = info.get("name")
            token["picture"] = info.get("picture")
        except Exception as exc:
            logger.warning("Could not fetch user info after connect: %s", exc)

        save_token(token)
        logger.info("Google Workspace connected: %s", token.get("email", "unknown"))
        return HTMLResponse(_CALLBACK_SUCCESS_HTML)

    except Exception as exc:
        logger.exception("Google OAuth token exchange failed: %s", exc)
        return HTMLResponse(_CALLBACK_ERROR_HTML.format(error=f"Token exchange failed: {exc}"))


@router.get("/oauth/{connector_id}/callback")
async def connector_oauth_callback(
    connector_id: str,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    if connector_id == "google":
        return await google_oauth_callback(code=code, state=state, error=error)
    if error:
        logger.warning("%s OAuth error: %s", connector_id, error)
        return HTMLResponse(_CALLBACK_ERROR_HTML.format(error=error))
    if not code or not state:
        return HTMLResponse(_CALLBACK_ERROR_HTML.format(error="Missing code or state parameter"))
    pending = _pending_oauth_states.pop(state, None)
    if not pending:
        return HTMLResponse(_CALLBACK_ERROR_HTML.format(error="Invalid or expired state. Please try connecting again."))
    expected_connector, code_verifier = pending
    if expected_connector != connector_id:
        return HTMLResponse(_CALLBACK_ERROR_HTML.format(error="OAuth state does not match connector. Please try again."))
    try:
        from spark_cli.oauth_connectors import (
            OAUTH_PROVIDERS,
            enrich_token,
            exchange_code,
            save_token,
        )

        if connector_id not in OAUTH_PROVIDERS:
            return HTMLResponse(_CALLBACK_ERROR_HTML.format(error="Unknown OAuth connector"))
        token = exchange_code(
            connector_id,
            code=code,
            code_verifier=code_verifier,
            redirect_uri=_redirect_uri(connector_id),
        )
        token = enrich_token(connector_id, token)
        save_token(connector_id, token)
        provider_name = OAUTH_PROVIDERS[connector_id].name
        return HTMLResponse(_CALLBACK_SUCCESS_HTML.replace("Google", provider_name))
    except Exception as exc:
        logger.exception("%s OAuth callback failed: %s", connector_id, exc)
        return HTMLResponse(_CALLBACK_ERROR_HTML.format(error=f"Token exchange failed: {exc}"))


# ---------------------------------------------------------------------------
# DELETE /api/connectors/google — disconnect
# ---------------------------------------------------------------------------

@router.delete("/api/connectors/google")
async def google_disconnect(disable_skills: bool = True):
    try:
        import httpx

        from spark_cli.google_connector import clear_imap_credentials, clear_token, load_token

        # Best-effort token revocation
        token = load_token()
        if token:
            try:
                access_token = token.get("access_token", "")
                if access_token:
                    httpx.post(
                        "https://oauth2.googleapis.com/revoke",
                        params={"token": access_token},
                        timeout=5,
                    )
            except Exception:
                pass

        clear_token()
        clear_imap_credentials()
        skills_disabled: list[str] = []
        if disable_skills:
            try:
                from spark_cli.connector_skills import disable_connector_skills

                skills_disabled = disable_connector_skills("google")["skills"]
            except Exception as exc:
                logger.warning("Could not disable Google skills: %s", exc)
        return JSONResponse({"disconnected": True, "skills_disabled": skills_disabled})
    except Exception as exc:
        logger.warning("Error disconnecting Google: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# DELETE /api/connectors/{id} — one-click disconnect/revoke (any connector)
# ---------------------------------------------------------------------------

# Connectors authenticated through a CLI sign-in (claude, codex, …) may share
# env keys with the model providers (ANTHROPIC_API_KEY, OPENAI_API_KEY), so we
# never remove env credentials for those on disconnect.
_ENV_CLEAR_AUTH_TYPES = {"api_key", "multi_env", "oauth_or_api_key", "oauth"}


@router.delete("/api/connectors/{connector_id}")
async def connector_disconnect(connector_id: str, disable_skills: bool = True):
    if connector_id == "google":
        return await google_disconnect(disable_skills=disable_skills)
    try:
        from tools.connectors import get_connector

        connector = get_connector(connector_id)
        if connector is None:
            return JSONResponse({"error": "unknown_connector"}, status_code=404)

        # MCP preset connectors clean up their own tokens + mcp_servers entry.
        from tools.connectors import Transport

        if connector.transport is Transport.MCP:
            connector.disconnect()
            mcp_skills_disabled: list[str] = []
            if disable_skills:
                try:
                    from spark_cli.connector_skills import disable_connector_skills

                    mcp_skills_disabled = disable_connector_skills(
                        connector_id, connector.skills
                    )["skills"]
                except Exception as exc:
                    logger.warning("Could not disable skills for %s: %s", connector_id, exc)
            return JSONResponse(
                {"disconnected": True, "skills_disabled": mcp_skills_disabled}
            )

        # 1. Forget any stored OAuth token.
        try:
            from spark_cli.oauth_connectors import clear_token as clear_oauth_token

            clear_oauth_token(connector_id)
        except Exception as exc:
            logger.warning("Could not clear OAuth token for %s: %s", connector_id, exc)

        # 2. Remove pasted credentials from the Spark env file (token-paste
        #    connectors only — never CLI-shared provider keys).
        env_cleared: list[str] = []
        spec = getattr(connector, "spec", None)
        if spec is not None and spec.auth_type in _ENV_CLEAR_AUTH_TYPES:
            try:
                from spark_cli.config import remove_env_value

                for env_name in spec.env_vars:
                    if remove_env_value(env_name):
                        env_cleared.append(env_name)
            except Exception as exc:
                logger.warning("Could not clear env credentials for %s: %s", connector_id, exc)

        # 3. Disable dependent skills.
        skills_disabled: list[str] = []
        if disable_skills:
            try:
                from spark_cli.connector_skills import disable_connector_skills

                skills_disabled = disable_connector_skills(connector_id, connector.skills)[
                    "skills"
                ]
            except Exception as exc:
                logger.warning("Could not disable skills for %s: %s", connector_id, exc)

        return JSONResponse(
            {
                "disconnected": True,
                "env_cleared": env_cleared,
                "skills_disabled": skills_disabled,
            }
        )
    except Exception as exc:
        logger.warning("Error disconnecting %s: %s", connector_id, exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register_connectors_routes(app) -> None:
    app.include_router(router)
