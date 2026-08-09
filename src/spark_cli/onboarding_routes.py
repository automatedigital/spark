"""FastAPI routes for the onboarding API.

Extracted from web_server.py, which declared these directly on the app.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from spark_cli.config import get_config_path, load_config, load_env, save_config
from spark_cli.web_runtime import _run_blocking

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])


@router.get("/status")
async def get_onboarding_status():
    """First-run detection for the desktop onboarding wizard.

    ``needs_onboarding`` is true when no config.yaml exists yet, or when
    ``model.provider`` is unset/empty.
    """
    config_exists = get_config_path().exists()

    config = load_config() if config_exists else {}
    model = config.get("model") if isinstance(config, dict) else {}
    if not isinstance(model, dict):
        model = {}
    provider = (model.get("provider") or "").strip()
    has_model = bool(provider)

    env_on_disk = load_env()
    has_api_key = any(
        bool(env_on_disk.get(var_name))
        for var_name in ("OPENAI_API_KEY", "GOOGLE_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY")
    )

    return {
        "needs_onboarding": (not config_exists) or (not has_model),
        "has_model": has_model,
        "has_api_key": has_api_key,
    }


_MINIMAL_SKILLS = {"find-skills", "codebase-inspection", "frontend-design", "excalidraw", "claude-code"}


class OnboardingSkillsRequest(BaseModel):
    mode: str  # "recommended" | "minimal" | "none"


@router.post("/skills")
async def setup_onboarding_skills(req: OnboardingSkillsRequest):
    """Seed the user's skills directory according to their onboarding choice.

    - ``recommended``: seed all bundled Spark skills.
    - ``minimal``: seed a small curated subset.
    - ``none``: seed nothing (blank slate; Spark creates skills over time).

    The choice is persisted under ``skills.onboarding_mode`` in config.
    """
    mode = (req.mode or "").strip().lower()
    if mode not in {"recommended", "minimal", "none"}:
        raise HTTPException(status_code=400, detail=f"Unknown skills mode: {mode}")

    result: dict = {"copied": [], "total_bundled": 0}
    if mode in {"recommended", "minimal"}:
        from tools.skills_sync import sync_skills

        only = _MINIMAL_SKILLS if mode == "minimal" else None
        result = await _run_blocking(sync_skills, True, only)

    # Persist the choice so re-running setup / diagnostics knows the intent.
    try:
        cfg = load_config()
        if isinstance(cfg, dict):
            skills_cfg = dict(cfg.get("skills") or {})
            skills_cfg["onboarding_mode"] = mode
            cfg["skills"] = skills_cfg
            save_config(cfg)
    except Exception:
        _log.debug("Ignoring error in setup_onboarding_skills()", exc_info=True)

    return {
        "ok": True,
        "mode": mode,
        "seeded": len(result.get("copied", [])),
        "total_bundled": result.get("total_bundled", 0),
    }


def register_onboarding_routes(app) -> None:
    app.include_router(router)
