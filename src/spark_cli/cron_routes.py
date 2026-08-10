"""FastAPI routes for the cron scheduler API.

Extracted from web_server.py, which declared these directly on the app.
Handlers import from cron.jobs lazily so that importing this module does not
pull the scheduler in.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cron", tags=["cron"])


class CronJobCreate(BaseModel):
    prompt: str
    schedule: str
    name: str = ""
    deliver: str = "local"


class CronJobUpdate(BaseModel):
    updates: dict


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
