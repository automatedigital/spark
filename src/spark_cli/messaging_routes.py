"""FastAPI routes for the Messaging page (/api/messaging).

Reads and writes per-platform gateway credentials + enabled state so that
messaging platforms (Telegram, Discord, Slack, ...) can be configured from
the web UI. Implemented in Phase 5 of PLAN.md.

Storage convention (matches `spark gateway setup` and the gateway itself):

- Every field maps 1:1 to an env var persisted in ``{SPARK_HOME}/.env`` via
  :func:`spark_cli.config.save_env_value`. The gateway loads ``.env`` at
  startup and reads these variables in ``gateway/config.py`` and the
  platform adapters.
- Secrets are never echoed back: reads return a masked value
  (``"••••" + last 4``) plus a ``set`` flag, and masked values submitted on
  save are ignored rather than persisted.
- After a successful save the running gateway (if any) is asked to restart
  via SIGUSR1 — best-effort, so saves never fail because the gateway is down.

The declarative per-platform field registry lives in
``gateway/platform_fields.py``.
"""

from __future__ import annotations

import logging
import os
import signal
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel

from gateway.platform_fields import (
    FieldSpec,
    PlatformSpec,
    all_platform_specs,
    get_platform_spec,
)

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/messaging", tags=["messaging"])

_MASK = "••••"  # "••••"

_TRUE_VALUES = ("true", "1", "yes", "on")
_FALSE_VALUES = ("false", "0", "no", "off")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_env_values() -> dict[str, str]:
    """Current env values: ``.env`` file first, then process environment.

    The ``.env`` file wins because the gateway re-loads it on restart and it
    is the canonical user-managed store (see ``gateway/run.py``).
    """
    from spark_cli.config import load_env

    merged: dict[str, str] = dict(os.environ)
    merged.update(load_env())
    return merged


def _mask_secret(value: str) -> str:
    """Mask a secret for display, keeping the last 4 chars when long enough."""
    if len(value) > 8:
        return _MASK + value[-4:]
    return _MASK


def _is_masked(value: str) -> bool:
    return value.startswith(_MASK)


def _field_payload(spec: FieldSpec, env: dict[str, str]) -> dict[str, Any]:
    raw = (env.get(spec.key) or "").strip()
    payload: dict[str, Any] = spec.to_dict()
    payload["set"] = bool(raw)
    if spec.type == "secret" and raw:
        payload["value"] = _mask_secret(raw)
    else:
        payload["value"] = raw
    return payload


def _parse_bool(raw: str | None) -> bool | None:
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if lowered in _TRUE_VALUES:
        return True
    if lowered in _FALSE_VALUES:
        return False
    return None


def _is_configured(spec: PlatformSpec, env: dict[str, str]) -> bool:
    """True when every required field has a non-empty value."""
    return all((env.get(f.key) or "").strip() for f in spec.required)


def _is_enabled(spec: PlatformSpec, env: dict[str, str]) -> bool:
    """Effective enabled state.

    An explicit ``*_ENABLED`` flag wins. When unset, credential-based
    platforms mirror the gateway's behaviour: they auto-enable as soon as
    their required credentials are present. Flag-native platforms
    (whatsapp/webhook/api_server) default to off.
    """
    flag = _parse_bool(env.get(spec.enabled_env))
    if flag is not None:
        return flag
    if spec.enabled_env_is_native or not spec.required:
        return False
    return _is_configured(spec, env)


def _runtime_platform_states() -> dict[str, Any]:
    """Per-platform runtime state persisted by the gateway (best-effort)."""
    try:
        from gateway.status import read_runtime_status

        state = read_runtime_status() or {}
        platforms = state.get("platforms")
        return platforms if isinstance(platforms, dict) else {}
    except Exception:
        return {}


def _gateway_running() -> bool:
    try:
        from gateway.status import is_gateway_running

        return is_gateway_running()
    except Exception:
        return False


def _platform_payload(
    spec: PlatformSpec,
    env: dict[str, str],
    runtime_states: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": spec.id,
        "name": spec.name,
        "description": spec.description,
        "help_text": spec.help_text,
        "setup_guide_url": spec.setup_guide_url,
        "enabled": _is_enabled(spec, env),
        "configured": _is_configured(spec, env),
        "runtime": runtime_states.get(spec.id),
        "fields": {
            "required": [_field_payload(f, env) for f in spec.required],
            "recommended": [_field_payload(f, env) for f in spec.recommended],
            "advanced": [_field_payload(f, env) for f in spec.advanced],
        },
    }


def _require_spec(platform_id: str) -> PlatformSpec:
    spec = get_platform_spec(platform_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Unknown platform: {platform_id}")
    return spec


def _coerce_value(value: Any) -> str:
    """Normalize an incoming JSON value to its .env string form."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip()


def _trigger_gateway_restart() -> dict[str, Any]:
    """Ask a running gateway to gracefully restart (best-effort).

    The gateway installs a SIGUSR1 handler that drains in-flight work and
    restarts with fresh config/env (see ``gateway/run.py``).
    """
    if os.environ.get("SPARK_DESKTOP") == "1":
        try:
            from spark_cli.desktop_gateway import restart_desktop_gateway

            restarted = restart_desktop_gateway()
        except Exception as exc:
            return {"ok": False, "running": True, "detail": f"Desktop gateway restart failed: {exc}"}
        return {
            "ok": restarted,
            "running": restarted,
            "detail": "Desktop gateway restarted." if restarted else "Desktop gateway did not restart.",
        }

    try:
        from gateway.status import get_running_pid

        pid = get_running_pid()
    except Exception as exc:  # pragma: no cover - defensive
        return {"ok": False, "running": False, "detail": f"status check failed: {exc}"}

    if pid is None:
        return {"ok": False, "running": False, "detail": "Gateway is not running."}
    if not hasattr(signal, "SIGUSR1"):
        return {
            "ok": False,
            "running": True,
            "detail": "Restart signal not supported on this platform.",
        }
    try:
        os.kill(pid, signal.SIGUSR1)
    except OSError as exc:
        return {"ok": False, "running": True, "detail": str(exc)}
    return {"ok": True, "running": True, "detail": "Gateway restart requested."}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


class PlatformUpdateRequest(BaseModel):
    enabled: bool | None = None
    values: dict[str, Any] | None = None


@router.get("/platforms")
def list_platforms() -> dict[str, Any]:
    """All messaging platforms with field specs and current (masked) values."""
    env = _load_env_values()
    runtime_states = _runtime_platform_states()
    return {
        "platforms": [
            _platform_payload(spec, env, runtime_states)
            for spec in all_platform_specs()
        ],
        "gateway_running": _gateway_running(),
    }


@router.get("/platforms/{platform_id}")
def get_platform(platform_id: str) -> dict[str, Any]:
    """Full detail for a single platform."""
    spec = _require_spec(platform_id)
    payload = _platform_payload(spec, _load_env_values(), _runtime_platform_states())
    payload["gateway_running"] = _gateway_running()
    return payload


@router.put("/platforms/{platform_id}")
def update_platform(platform_id: str, body: PlatformUpdateRequest) -> dict[str, Any]:
    """Persist credential values and/or the enabled toggle for a platform.

    Masked secret placeholders ("••••1234") are ignored so an untouched
    secret field never overwrites the stored value. On success the gateway
    is asked to restart (best-effort; never fails the save).
    """
    from spark_cli.config import save_env_value

    spec = _require_spec(platform_id)
    known_keys = {f.key for f in spec.all_fields()}

    values = body.values or {}
    unknown = sorted(set(values) - known_keys)
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown field(s) for {platform_id}: {', '.join(unknown)}",
        )

    secret_keys = {f.key for f in spec.all_fields() if f.type == "secret"}
    saved: list[str] = []
    for key, raw in values.items():
        value = _coerce_value(raw)
        if key in secret_keys and value and _is_masked(value):
            continue  # untouched masked placeholder — keep the stored secret
        save_env_value(key, value)
        saved.append(key)

    if body.enabled is not None:
        save_env_value(spec.enabled_env, "true" if body.enabled else "false")
    elif saved and spec.required and not spec.enabled_env_is_native:
        # Credential save without an explicit toggle: once the platform is
        # fully configured, persist the advisory enabled flag so the state
        # survives in .env (e.g. SLACK_ENABLED=true). An explicit user
        # toggle-off (flag already "false") is never overridden.
        env_after_save = _load_env_values()
        if (
            _is_configured(spec, env_after_save)
            and _parse_bool(env_after_save.get(spec.enabled_env)) is None
        ):
            save_env_value(spec.enabled_env, "true")

    restart: dict[str, Any] = {"ok": False, "running": False, "detail": "skipped"}
    try:
        restart = _trigger_gateway_restart()
    except Exception as exc:  # never fail a save because the gateway is down
        _log.warning("Gateway restart after %s save failed: %s", platform_id, exc)
        restart = {"ok": False, "running": False, "detail": str(exc)}

    payload = _platform_payload(spec, _load_env_values(), _runtime_platform_states())
    payload["gateway_running"] = _gateway_running()
    payload["saved"] = saved
    payload["restart"] = restart
    return payload


@router.post("/platforms/{platform_id}/restart")
def restart_platform(platform_id: str) -> dict[str, Any]:
    """Trigger a gateway restart so the platform picks up new config."""
    _require_spec(platform_id)  # 404 on unknown ids
    result = _trigger_gateway_restart()
    result["platform"] = platform_id
    return result


def register_messaging_routes(app: FastAPI) -> None:
    app.include_router(router)
