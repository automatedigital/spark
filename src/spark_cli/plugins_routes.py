"""FastAPI routes for the plugins API.

Extracted from web_server.py, which declared these directly on the app.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.spark_constants import get_spark_home
from spark_cli.admin_runs import (
    AdminAction,
    _admin_runs,
    _new_admin_run,
    _run_admin_action,
    _spark_command,
)

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/plugins", tags=["plugins"])


class PluginActionRequest(BaseModel):
    name: str
    confirm: bool = False


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


@router.get("")
async def plugins_list():
    return {"ok": True, "plugins": _list_plugin_dirs()}


@router.post("/{action}")
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


def register_plugins_routes(app) -> None:
    app.include_router(router)
