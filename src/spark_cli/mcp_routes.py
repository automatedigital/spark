"""FastAPI routes for the mcp API.

Extracted from web_server.py, which declared these directly on the app.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from spark_cli.admin_runs import (
    AdminAction,
    _new_admin_run,
    _run_admin_action,
    _spark_command,
)

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


class McpServerCreate(BaseModel):
    name: str
    url: str | None = None
    command: str | None = None
    args: list[str] = []
    env: dict[str, str] = {}


@router.get("/servers")
async def mcp_servers_list():
    from spark_cli.mcp_config import _get_mcp_servers

    return {"ok": True, "servers": _get_mcp_servers()}


@router.post("/servers")
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


@router.delete("/servers/{name}")
async def mcp_servers_delete(name: str, confirm: bool = False):
    if not confirm:
        raise HTTPException(status_code=400, detail="Confirmation required")
    from spark_cli.mcp_config import _remove_mcp_server

    if not _remove_mcp_server(name):
        raise HTTPException(status_code=404, detail="MCP server not found")
    return {"ok": True}


@router.post("/servers/{name}/test")
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


def register_mcp_routes(app) -> None:
    app.include_router(router)
