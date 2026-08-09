"""FastAPI routes for the env API.

Extracted from web_server.py, which declared these directly on the app.
"""

from __future__ import annotations

import logging
import secrets
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from spark_cli.config import (
    OPTIONAL_ENV_VARS,
    load_env,
    redact_key,
    remove_env_value,
    save_env_value,
)
from spark_cli.dashboard_auth import (
    ensure_dashboard_token_file,
    extract_bearer_token,
    get_configured_dashboard_secret,
    validate_dashboard_request,
)
from spark_cli.onboarding_validation import validate_env_assignment
from spark_cli.web_runtime import _SESSION_TOKEN

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/env", tags=["env"])


_reveal_timestamps: list[float] = []


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


_REVEAL_MAX_PER_WINDOW = 5


_REVEAL_WINDOW_SECONDS = 30


class EnvVarUpdate(BaseModel):
    key: str
    value: str


class EnvVarDelete(BaseModel):
    key: str


class EnvVarReveal(BaseModel):
    key: str


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


@router.get("")
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


@router.put("")
async def set_env_var(body: EnvVarUpdate):
    try:
        value = validate_env_assignment(body.key, body.value)
        save_env_value(body.key, value)
        return {"ok": True, "key": body.key}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as err:
        _log.exception("PUT /api/env failed")
        raise HTTPException(status_code=500, detail="Internal server error") from err


@router.delete("")
async def remove_env_var(body: EnvVarDelete):
    try:
        removed = remove_env_value(body.key)
        if not removed:
            raise HTTPException(status_code=404, detail=f"{body.key} not found in .env")
        return {"ok": True, "key": body.key}
    except HTTPException:
        raise
    except Exception as err:
        _log.exception("DELETE /api/env failed")
        raise HTTPException(status_code=500, detail="Internal server error") from err


@router.post("/reveal")
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


def register_env_routes(app) -> None:
    app.include_router(router)
