"""FastAPI routes for the cron scheduler API.

Extracted from web_server.py, which declared these directly on the app.
Handlers import from cron.jobs lazily so that importing this module does not
pull the scheduler in.
"""

from __future__ import annotations

import logging
import os
from collections import Counter
from pathlib import PurePosixPath

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
    timezone: str | None = None


class CronPreview(BaseModel):
    schedule: str | dict
    timezone: str | None = None
    model: str | None = None
    provider: str | None = None
    skills: list[str] | None = None
    deliver: str = "local"


@router.post("/preview")
def preview_cron(body: CronPreview):
    from cron.jobs import preview_schedule
    from cron.scheduler import _resolve_delivery_target
    from spark_cli.auth import PROVIDER_REGISTRY, resolve_provider
    from spark_cli.config import load_config
    from spark_cli.runtime_provider import _get_named_custom_provider

    try:
        result = preview_schedule(body.schedule, body.timezone)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    errors = []
    provider = None
    cfg = load_config().get("model") or {}
    model = body.model or (cfg if isinstance(cfg, str) else cfg.get("default")) or os.getenv("SPARK_MODEL") or None
    requested = body.provider or os.getenv("SPARK_INFERENCE_PROVIDER") or (cfg.get("provider") if isinstance(cfg, dict) else None) or "auto"
    # Execution resolution may refresh OAuth, seed credential pools or query a local
    # model server. Preview must only inspect configuration, never invoke it.
    try:
        custom = _get_named_custom_provider(requested)
        if custom:
            provider = requested
            model = body.model or custom.get("model") or model
        elif requested == "auto":
            provider = "auto"
            errors.append("Automatic provider availability is unknown until execution; pin a configured provider for a deterministic preview")
        else:
            provider = resolve_provider(requested)
            metadata = PROVIDER_REGISTRY.get(provider)
            if metadata and metadata.auth_type == "api_key":
                available = any(os.getenv(key) for key in metadata.api_key_env_vars)
                if not available:
                    errors.append("Provider credential availability is unknown; verify credentials in model settings")
            elif provider != "custom":
                errors.append("Provider credential availability is unknown; preview does not refresh credentials")
    except Exception:
        errors.append("Provider configuration unavailable; configure the selected provider")
    if not model:
        errors.append("Model is not configured; select a model before scheduling")
    catalog = {item["id"]: item for item in _cron_skills()}
    skills = []
    for value in body.skills or []:
        available = bool(catalog.get(value, {}).get("enabled"))
        skills.append({"id": value, "available": available})
        if not available:
            errors.append(f"Skill unavailable: {value}")
    delivery = body.deliver == "local"
    if not delivery:
        from gateway.config import Platform, load_gateway_config

        target = _resolve_delivery_target({"deliver": body.deliver})
        if target:
            try:
                platform = Platform(target["platform"].lower())
                config = load_gateway_config().platforms.get(platform)
                delivery = bool(config and config.enabled)
            except ValueError:
                pass
    if not delivery:
        errors.append("Delivery target unavailable; configure a destination or choose local")
    result["readiness"] = {"provider": provider, "model": model, "skills": skills,
                           "delivery_available": delivery, "errors": errors,
                           "verification": "Configuration only; no provider or delivery request was made"}
    return result


class CronJobUpdate(BaseModel):
    updates: dict


def _cron_skills() -> list[dict]:
    """Keep display labels separate from skill_view's relative-path contract.

    Do not use _find_all_skills: it deduplicates display names. Colliding paths
    across trusted roots are unavailable rather than silently using first match.
    """
    from agent.skill_utils import (
        EXCLUDED_SKILL_DIRS,
        get_disabled_skill_names,
        get_external_skills_dirs,
        parse_frontmatter,
        skill_matches_platform,
    )
    from tools.skills_tool import SKILLS_DIR

    roots = list(dict.fromkeys([SKILLS_DIR, *get_external_skills_dirs()]))
    disabled = get_disabled_skill_names()
    records: list[dict] = []
    for root in roots:
        for document in sorted(root.rglob("SKILL.md")):
            relative = document.relative_to(root)
            if any(part in EXCLUDED_SKILL_DIRS for part in relative.parts):
                continue
            try:
                metadata, _ = parse_frontmatter(document.read_text(encoding="utf-8"))
            except (OSError, UnicodeError):
                continue
            name = str(metadata.get("name") or document.parent.name)
            path = relative.parent.as_posix()
            if path == ".":
                continue
            records.append({"id": path, "name": name,
                            "enabled": name not in disabled and skill_matches_platform(metadata)})
    counts = Counter(item["id"] for item in records)
    catalog: dict[str, dict] = {}
    for item in records:
        if counts[item["id"]] > 1:
            item.update(enabled=False, reason="Ambiguous skill path across installed roots")
        catalog.setdefault(item["id"], item)
    return list(catalog.values())


@router.get("/skills")
def list_cron_skills():
    return _cron_skills()


def _resolve_cron_skills(values: list[str] | None) -> list[str] | None:
    if values is None or not values:
        return values
    catalog = _cron_skills()
    resolved = []
    for value in values:
        value = value.strip()
        if not value:
            continue
        # Exact relative paths take precedence over old display/basename values.
        matches = [item for item in catalog if item["id"] == value]
        if not matches:
            matches = [item for item in catalog if item["name"] == value
                       or PurePosixPath(item["id"]).name == value]
        if len(matches) > 1 or any(item.get("reason") for item in matches):
            raise ValueError(f"Ambiguous skill '{value}'; choose a unique installed path")
        if matches:
            if not matches[0]["enabled"]:
                raise ValueError(f"Skill '{value}' is unavailable on this profile/platform")
            value = matches[0]["id"]
        # Preserve unavailable legacy string references so old jobs remain editable.
        if value not in resolved:
            resolved.append(value)
    return resolved


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
            timezone=body.timezone,
            prompt=body.prompt,
            schedule=body.schedule,
            name=body.name,
            deliver=body.deliver,
            model=body.model or None,
            provider=body.provider or None,
            skills=_resolve_cron_skills(body.skills),
        )
        return job
    except Exception as e:
        _log.exception("POST /api/cron/jobs failed")
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.put("/jobs/{job_id}")
async def update_cron_job(job_id: str, body: CronJobUpdate):
    from cron.jobs import update_job

    try:
        updates = dict(body.updates)
        # Canonical skills must win over the legacy single-skill field, including
        # an explicit empty list. Do not let a stale legacy value reappear.
        if "skills" in updates:
            updates["skills"] = _resolve_cron_skills(
                None if updates["skills"] is None else TypeAdapter(list[str]).validate_python(updates["skills"])
            ) or []
            updates.pop("skill", None)
        elif "skill" in updates:
            raw_legacy = updates.pop("skill")
            legacy = None if raw_legacy is None else TypeAdapter(str).validate_python(raw_legacy)
            updates["skills"] = _resolve_cron_skills([legacy] if legacy else []) or []
        for field in ("model", "provider"):
            if field in updates:
                value = updates[field]
                if value is not None and not isinstance(value, str):
                    raise ValueError(f"{field} must be a string or null")
                updates[field] = value.strip() or None if value is not None else None
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
    from spark_cli.cron_output_routes import router as output_router

    app.include_router(output_router, prefix="/api/cron", tags=["cron"])
    app.include_router(router)
