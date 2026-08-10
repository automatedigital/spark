"""FastAPI routes for the gateway API.

Extracted from web_server.py, which declared these directly on the app.
"""

from __future__ import annotations

import logging
import platform
import threading

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from gateway.status import get_running_pid, read_runtime_status
from spark_cli.admin_runs import (
    ADMIN_ACTIONS,
    _new_admin_run,
    _run_admin_action,
)

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/gateway", tags=["gateway"])


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


def _runtime_gateway_pid(runtime: dict | None) -> int | None:
    if not runtime:
        return None
    pid = runtime.get("pid")
    try:
        return int(pid) if pid is not None else None
    except (TypeError, ValueError):
        return None


def _runtime_gateway_running(runtime: dict | None) -> bool:
    if not runtime:
        return False
    return runtime.get("gateway_state") == "running" and _runtime_gateway_pid(runtime) is not None


class GatewayControlRequest(BaseModel):
    action: str
    confirm: bool = False


@router.get("/status")
async def gateway_admin_status():
    runtime = read_runtime_status() or {}
    pid = get_running_pid()
    running = pid is not None
    if not running and _runtime_gateway_running(runtime):
        pid = _runtime_gateway_pid(runtime)
        running = True
    return {
        "ok": True,
        "running": running,
        "pid": pid,
        "runtime": runtime,
        "platforms": runtime.get("platforms") or {},
        "configured_platforms": _configured_gateway_platforms(),
        "service_system": platform.system(),
        "last_error": runtime.get("last_startup_error") or runtime.get("exit_reason"),
        "state": runtime.get("gateway_state") if running else "stopped",
    }


@router.post("/control")
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


def register_gateway_routes(app) -> None:
    app.include_router(router)
