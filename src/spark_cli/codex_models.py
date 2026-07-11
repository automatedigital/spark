"""Codex model discovery from API, local cache, and config."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CODEX_MODELS: list[str] = [
    "gpt-5.4-mini",
    "gpt-5.4",
    "gpt-5.3-codex",
    "gpt-5.2-codex",
    "gpt-5.1-codex-max",
    "gpt-5.1-codex-mini",
]

def _fetch_models_from_api(access_token: str, timeout: float = 10.0) -> list[str] | None:
    """Fetch available models from the Codex API. Returns visible models sorted by priority."""
    try:
        import httpx
        resp = httpx.get(
            "https://chatgpt.com/backend-api/codex/models?client_version=1.0.0",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=timeout,
        )
        if resp.status_code != 200:
            logger.debug("Codex model discovery returned HTTP %s", resp.status_code)
            return None
        data = resp.json()
        entries = data.get("models", []) if isinstance(data, dict) else []
    except Exception as exc:
        logger.debug("Failed to fetch Codex models from API: %s", exc)
        return None

    sortable = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        slug = item.get("slug")
        if not isinstance(slug, str) or not slug.strip():
            continue
        slug = slug.strip()
        if item.get("supported_in_api") is False:
            continue
        visibility = item.get("visibility", "")
        if isinstance(visibility, str) and visibility.strip().lower() in ("hide", "hidden"):
            continue
        priority = item.get("priority")
        rank = int(priority) if isinstance(priority, (int, float)) else 10_000
        sortable.append((rank, slug))

    sortable.sort(key=lambda x: (x[0], x[1]))
    # A successful account-scoped response is authoritative. Never append
    # models merely because they exist in the direct OpenAI API catalog.
    return list(dict.fromkeys(slug for _, slug in sortable))


def _read_default_model(codex_home: Path) -> str | None:
    config_path = codex_home / "config.toml"
    if not config_path.exists():
        return None
    try:
        import tomllib
    except Exception:
        return None
    try:
        payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    model = payload.get("model") if isinstance(payload, dict) else None
    if isinstance(model, str) and model.strip():
        return model.strip()
    return None


def _read_cache_models(codex_home: Path) -> list[str]:
    cache_path = codex_home / "models_cache.json"
    if not cache_path.exists():
        return []
    try:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    entries = raw.get("models") if isinstance(raw, dict) else None
    sortable = []
    if isinstance(entries, list):
        for item in entries:
            if not isinstance(item, dict):
                continue
            slug = item.get("slug")
            if not isinstance(slug, str) or not slug.strip():
                continue
            slug = slug.strip()
            if item.get("supported_in_api") is False:
                continue
            visibility = item.get("visibility")
            if isinstance(visibility, str) and visibility.strip().lower() in ("hide", "hidden"):
                continue
            priority = item.get("priority")
            rank = int(priority) if isinstance(priority, (int, float)) else 10_000
            sortable.append((rank, slug))

    sortable.sort(key=lambda item: (item[0], item[1]))
    deduped: list[str] = []
    for _, slug in sortable:
        if slug not in deduped:
            deduped.append(slug)
    return deduped


def get_codex_model_ids(
    access_token: str | None = None,
    *,
    api_timeout: float = 10.0,
) -> list[str]:
    """Return available Codex model IDs, trying API first, then local sources.

    Resolution order: API (live, if token provided) > config.toml default >
    local cache > hardcoded defaults.
    """
    codex_home_str = os.getenv("CODEX_HOME", "").strip() or str(Path.home() / ".codex")
    codex_home = Path(codex_home_str).expanduser()
    ordered: list[str] = []

    # A non-empty account-scoped result is authoritative. Synthesizing slugs
    # here creates options the user's Codex subscription may not expose.
    if access_token:
        api_models = _fetch_models_from_api(access_token, timeout=api_timeout)
        if api_models:
            return api_models

    # Fall back to local sources
    default_model = _read_default_model(codex_home)
    if default_model:
        ordered.append(default_model)

    for model_id in _read_cache_models(codex_home):
        if model_id not in ordered:
            ordered.append(model_id)

    for model_id in DEFAULT_CODEX_MODELS:
        if model_id not in ordered:
            ordered.append(model_id)

    return ordered


def get_codex_model_catalog(
    access_token: str | None = None,
    *,
    api_timeout: float = 10.0,
) -> dict[str, object]:
    """Return Codex models with discovery provenance for user-facing clients."""
    if access_token:
        live = _fetch_models_from_api(access_token, timeout=api_timeout)
        if live:
            return {"models": live, "source": "live", "live": True, "warning": ""}
        warning = (
            "Could not load this account's live Codex model catalog; "
            "showing the offline fallback."
        )
    else:
        warning = (
            "OpenAI Codex is not authenticated; showing the offline fallback. "
            "Connect Codex to load the models available to this account."
        )
    return {
        "models": get_codex_model_ids(),
        "source": "offline-fallback",
        "live": False,
        "warning": warning,
    }
