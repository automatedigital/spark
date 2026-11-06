"""FastAPI routes for the mcp API.

Extracted from web_server.py, which declared these directly on the app.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel

from spark_cli.mcp_readiness import owner

_log = logging.getLogger(__name__)

class SafeMcpRoute(APIRoute):
    """Keep rejected credential fields out of validation error responses."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def handle(request):
            try:
                return await original(request)
            except RequestValidationError:
                raise HTTPException(status_code=400, detail="Invalid MCP configuration") from None

        return handle


router = APIRouter(prefix="/api/mcp", tags=["mcp"], route_class=SafeMcpRoute)


class McpServerCreate(BaseModel):
    name: str
    url: str | None = None
    command: str | None = None
    args: list[str] = []
    env: dict[str, str] = {}
    headers: dict[str, str] = {}


@router.get("/servers")
async def mcp_servers_list():
    from spark_cli.mcp_config import _get_mcp_servers

    servers = _get_mcp_servers()
    return {"ok": True, "servers": {name: {"configured": True} for name in servers},
            "readiness": owner.summaries(servers)}


@router.post("/servers")
async def mcp_servers_create(payload: McpServerCreate):
    from spark_cli.mcp_config import _get_mcp_servers, _save_mcp_server

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
    if payload.headers:
        server["headers"] = payload.headers
    try:
        _save_mcp_server(payload.name, server)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Unable to save MCP configuration") from exc
    owner.summaries(_get_mcp_servers())
    return {"ok": True, "name": payload.name, "server": {"configured": True}}


@router.delete("/servers/{name}")
async def mcp_servers_delete(name: str, confirm: bool = False):
    if not confirm:
        raise HTTPException(status_code=400, detail="Confirmation required")
    from spark_cli.mcp_config import _remove_mcp_server

    if not _remove_mcp_server(name):
        raise HTTPException(status_code=404, detail="MCP server not found")
    from spark_cli.mcp_config import _get_mcp_servers

    owner.summaries(_get_mcp_servers())
    return {"ok": True}


@router.post("/servers/{name}/test")
async def mcp_servers_test(name: str):
    from spark_cli.mcp_config import _get_mcp_servers

    servers = _get_mcp_servers()
    if name not in servers:
        raise HTTPException(status_code=404, detail="MCP server not found")
    try:
        return owner.start(name, servers[name])
    except OverflowError:
        raise HTTPException(status_code=429, detail="MCP test queue is full; retry later") from None



def register_mcp_routes(app) -> None:
    app.include_router(router)
