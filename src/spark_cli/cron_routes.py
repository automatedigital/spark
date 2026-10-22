"""FastAPI routes for the cron scheduler API.

Extracted from web_server.py, which declared these directly on the app.
Handlers import from cron.jobs lazily so that importing this module does not
pull the scheduler in.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, TypeAdapter

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cron", tags=["cron"])


class CronJobCreate(BaseModel):
    prompt: str
    schedule: str
    name: str = ""
    deliver: str = "local"
    model: str | None = None
    provider: str | None = None
    skills: list[str] | None = None


class CronJobUpdate(BaseModel):
    updates: dict


@router.get("/providers")
def list_cron_providers():
    """Reuse profile provider resolution, exposing identifiers and labels only."""
    from spark_cli.config import load_config
    from spark_cli.models import list_available_providers
    from spark_cli.providers import custom_provider_slug
    from spark_cli.runtime_provider import resolve_runtime_provider

    cfg = load_config()
    candidates = {
        item["id"]: item["label"]
        for item in list_available_providers()
        if item.get("authenticated")
    }
    for key, entry in (cfg.get("providers") or {}).items():
        if isinstance(entry, dict):
            candidates[str(key)] = str(entry.get("name") or key)

    for entry in cfg.get("custom_providers") or []:
        if isinstance(entry, dict) and entry.get("name"):
            key = entry.get("provider_key")
            requested = f"custom:{key}" if key else custom_provider_slug(entry["name"])
            candidates[requested] = entry["name"]
    # Include the resolved default (including legacy/custom configurations).
    try:
        default = resolve_runtime_provider()["provider"]
        candidates.setdefault(default, default)
    except Exception:
        pass
    providers = []
    for requested, label in candidates.items():
        try:
            resolve_runtime_provider(requested=requested)
        except Exception:
            continue
        providers.append({"id": requested, "label": label})
    return providers


@router.get("/jobs")
async def list_cron_jobs():
    from cron.jobs import list_jobs

    return list_jobs(include_disabled=True)


@router.get("/jobs/{job_id}")
async def get_cron_job(job_id: str):
    from cron.jobs import get_job

    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/jobs")
async def create_cron_job(body: CronJobCreate):
    from cron.jobs import create_job

    try:
        job = create_job(
            prompt=body.prompt,
            schedule=body.schedule,
            name=body.name,
            deliver=body.deliver,
            model=body.model or None,
            provider=body.provider or None,
            skills=body.skills,
        )
        return job
    except Exception as e:
        _log.exception("POST /api/cron/jobs failed")
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.put("/jobs/{job_id}")
async def update_cron_job(job_id: str, body: CronJobUpdate):
    from cron.jobs import parse_schedule, update_job

    try:
        updates = dict(body.updates)
        # Canonical skills must win over the legacy single-skill field, including
        # an explicit empty list. Do not let a stale legacy value reappear.
        if "skills" in updates:
            updates["skills"] = TypeAdapter(list[str] | None).validate_python(updates["skills"]) or []
            updates.pop("skill", None)
        for field in ("model", "provider"):
            if field in updates:
                value = updates[field]
                if value is not None and not isinstance(value, str):
                    raise ValueError(f"{field} must be a string or null")
                updates[field] = value.strip() or None if value is not None else None
        if isinstance(updates.get("schedule"), str):
            updates["schedule"] = parse_schedule(updates["schedule"])
        job = update_job(job_id, updates)
    except Exception as e:
        _log.exception("PUT /api/cron/jobs/%s failed", job_id)
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/jobs/{job_id}/pause")
async def pause_cron_job(job_id: str):
    from cron.jobs import pause_job

    job = pause_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/jobs/{job_id}/resume")
async def resume_cron_job(job_id: str):
    from cron.jobs import resume_job

    job = resume_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/jobs/{job_id}/trigger")
async def trigger_cron_job(job_id: str):
    from cron.jobs import trigger_job

    job = trigger_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.delete("/jobs/{job_id}")
async def delete_cron_job(job_id: str):
    from cron.jobs import remove_job

    if not remove_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return {"ok": True}


def register_cron_routes(app) -> None:
    app.include_router(router)
