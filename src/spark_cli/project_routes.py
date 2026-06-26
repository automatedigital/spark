"""Canonical Project route registration for the dashboard backend.

The legacy ``/api/workspace/...`` route surface remains public compatibility
API.  This module registers that compatibility surface and mirrors project
routes onto ``/api/projects/...`` so new callers can use Project terminology
without duplicating handlers.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.routing import APIRoute

from spark_cli.workspace_routes import register_workspace_routes, router as workspace_router

_PROJECT_PREFIX_COMPAT = "/api/workspace/projects"
_PROJECT_PREFIX_CANONICAL = "/api/projects"
_TEMPLATES_PATH_COMPAT = "/api/workspace/project-templates"
_TEMPLATES_PATH_CANONICAL = "/api/project-templates"


def _canonical_project_path(path: str) -> str | None:
    if path == _TEMPLATES_PATH_COMPAT:
        return _TEMPLATES_PATH_CANONICAL
    if path.startswith(_PROJECT_PREFIX_COMPAT):
        return path.replace(_PROJECT_PREFIX_COMPAT, _PROJECT_PREFIX_CANONICAL, 1)
    return None


def _register_canonical_project_aliases(app: FastAPI) -> None:
    if getattr(app.state, "_spark_project_routes_registered", False):
        return

    for route in workspace_router.routes:
        if not isinstance(route, APIRoute):
            continue
        canonical_path = _canonical_project_path(route.path)
        if canonical_path is None:
            continue
        app.add_api_route(
            canonical_path,
            route.endpoint,
            methods=list(route.methods or []),
            name=f"project:{route.name}",
            response_model=route.response_model,
            status_code=route.status_code,
            tags=["project"],
            dependencies=route.dependencies,
            summary=route.summary,
            description=route.description,
            response_description=route.response_description,
            responses=route.responses,
            deprecated=route.deprecated,
            operation_id=route.operation_id,
            response_class=route.response_class,
        )

    app.state._spark_project_routes_registered = True


def register_project_routes(app: FastAPI, *, include_workspace_compat: bool = True) -> None:
    """Register canonical Project routes and optional workspace compatibility routes."""
    if include_workspace_compat and not getattr(
        app.state, "_spark_workspace_routes_registered", False
    ):
        register_workspace_routes(app)
        app.state._spark_workspace_routes_registered = True
    _register_canonical_project_aliases(app)
