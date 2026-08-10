"""FastAPI routes for Spark profile management.

Extracted from web_server.py. spark_cli.profiles is imported inside each
handler so that importing this module does not touch the profile store.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.spark_constants import get_spark_home

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


class ProfileCreateRequest(BaseModel):
    name: str
    clone_from: str | None = None
    clone_config: bool = False
    clone_all: bool = False
    no_alias: bool = True


class ProfileRenameRequest(BaseModel):
    new_name: str
    confirm: bool = False


class ProfileExportRequest(BaseModel):
    output_path: str | None = None
    confirm: bool = False


class ProfileImportRequest(BaseModel):
    archive_path: str
    name: str | None = None
    confirm: bool = False


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


@router.get("")
async def profiles_list():
    from spark_cli.profiles import get_active_profile, list_profiles

    active = get_active_profile()
    return {"ok": True, "active": active, "profiles": [_profile_info_dict(p, active) for p in list_profiles()]}


@router.post("")
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


@router.post("/{name}/use")
async def profiles_use(name: str):
    from spark_cli.profiles import set_active_profile

    try:
        set_active_profile(name)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "active": name}


@router.post("/{name}/rename")
async def profiles_rename(name: str, payload: ProfileRenameRequest):
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required")
    from spark_cli.profiles import rename_profile

    try:
        path = rename_profile(name, payload.new_name)
    except (ValueError, FileExistsError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "path": str(path), "name": payload.new_name}


@router.delete("/{name}")
async def profiles_delete(name: str, confirm: bool = False):
    if not confirm:
        raise HTTPException(status_code=400, detail="Confirmation required")
    from spark_cli.profiles import delete_profile

    try:
        path = delete_profile(name, yes=True)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "path": str(path)}


@router.post("/{name}/export")
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


@router.post("/import")
async def profiles_import(payload: ProfileImportRequest):
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required")
    from spark_cli.profiles import import_profile

    try:
        path = import_profile(payload.archive_path, payload.name)
    except (ValueError, FileExistsError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "path": str(path)}


def register_profiles_routes(app) -> None:
    app.include_router(router)
