"""Account-scoped Codex model discovery and capability metadata.

The Codex model endpoint and its local cache are the only authoritative
sources for account availability.  ``get_codex_model_ids`` intentionally keeps
the historical slug-list API; ``get_codex_model_catalog`` adds normalized
metadata for callers that need to make routing decisions.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, TypedDict

logger = logging.getLogger(__name__)

DEFAULT_CODEX_MODELS: list[str] = [
    "gpt-5.4-mini",
    "gpt-5.4",
    "gpt-5.3-codex",
    "gpt-5.2-codex",
    "gpt-5.1-codex-max",
    "gpt-5.1-codex-mini",
]


class CodexModelMetadata(TypedDict):
    """Normalized metadata for one visible, account-discovered model."""

    slug: str
    display_name: str
    visibility: str | None
    supported_reasoning_efforts: list[str]
    context_window: int | None
    max_output_tokens: int | None
    multi_agent_version: str | None
    source: str
    fetched_at: str | None


class CodexModelCatalog(TypedDict):
    """The JSON-safe catalog contract returned to CLI/web callers."""

    models: list[str]
    catalog: list[CodexModelMetadata]
    source: str
    freshness: str | None
    fetched_at: str | None
    live: bool
    stale: bool
    authoritative: bool
    warning: str


def _codex_home() -> Path:
    codex_home_str = os.getenv("CODEX_HOME", "").strip()
    return Path(codex_home_str or (Path.home() / ".codex")).expanduser()


def _coerce_priority(value: Any) -> int:
    if isinstance(value, bool):
        return 10_000
    try:
        return int(value)
    except (TypeError, ValueError):
        return 10_000


def _visible_model_entries(entries: Any) -> list[dict[str, Any]]:
    """Filter and order raw account entries without fabricating model slugs."""
    sortable: list[tuple[int, str, dict[str, Any]]] = []
    if not isinstance(entries, list):
        return []

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
        if isinstance(visibility, str) and visibility.strip().lower() in {
            "hide",
            "hidden",
        }:
            continue
        normalized = dict(item)
        normalized["slug"] = slug
        sortable.append((_coerce_priority(item.get("priority")), slug, normalized))

    sortable.sort(key=lambda item: (item[0], item[1]))
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _, slug, item in sortable:
        if slug not in seen:
            deduped.append(item)
            seen.add(slug)
    return deduped


def _fetch_model_entries_from_api(
    access_token: str, timeout: float = 10.0
) -> tuple[list[dict[str, Any]], str | None] | None:
    """Fetch visible raw model entries and response freshness from Codex."""
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
        if not isinstance(data, dict):
            return []
        entries = _visible_model_entries(data.get("models", []))
        freshness = _first_string(data, ("fetched_at", "updated_at", "created_at"))
        return entries, freshness
    except Exception as exc:
        logger.debug("Failed to fetch Codex models from API: %s", exc)
        return None


def _fetch_models_from_api(access_token: str, timeout: float = 10.0) -> list[str] | None:
    """Fetch available Codex model IDs, retaining the legacy return type."""
    result = _fetch_model_entries_from_api(access_token, timeout=timeout)
    if result is None:
        return None
    raw_entries, _ = result
    return [item["slug"] for item in _visible_model_entries(raw_entries)]


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


def _read_cache_payload(codex_home: Path) -> tuple[list[dict[str, Any]], str | None]:
    cache_path = codex_home / "models_cache.json"
    if not cache_path.exists():
        return [], None
    try:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return [], None
    if not isinstance(raw, dict):
        return [], None
    freshness = _first_string(raw, ("fetched_at", "updated_at", "created_at"))
    return _visible_model_entries(raw.get("models", [])), freshness


def _read_cache_models(codex_home: Path) -> list[str]:
    """Return visible cached slugs, preserving the historical helper."""
    entries, _ = _read_cache_payload(codex_home)
    return [item["slug"] for item in entries]


def get_codex_model_ids(
    access_token: str | None = None,
    *,
    api_timeout: float = 10.0,
) -> list[str]:
    """Return available Codex model IDs using live, cache, and legacy fallback.

    A successful account-scoped API response, including an empty response, is
    authoritative.  Cache and built-in defaults are only used when live
    discovery is unavailable, and the richer catalog marks those results
    stale/non-authoritative.
    """
    codex_home = _codex_home()

    if access_token:
        api_models = _fetch_models_from_api(access_token, timeout=api_timeout)
        if api_models is not None:
            return api_models

    ordered: list[str] = []
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


def _first_string(payload: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _first_int(payload: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, bool) or value in (None, ""):
            continue
        try:
            result = int(value)
        except (TypeError, ValueError):
            continue
        if result > 0:
            return result
    return None


def _reasoning_efforts(payload: dict[str, Any]) -> list[str]:
    values: Any = payload.get("supported_reasoning_levels")
    if values is None:
        values = payload.get("supported_reasoning_efforts")
    if values is None:
        values = payload.get("reasoning_efforts")
    if isinstance(values, dict):
        values = values.keys()
    if not isinstance(values, (list, tuple, set)):
        return []

    efforts: list[str] = []
    for value in values:
        if isinstance(value, dict):
            value = value.get("effort") or value.get("level") or value.get("name")
        if not isinstance(value, str) or not value.strip():
            continue
        effort = value.strip()
        if effort not in efforts:
            efforts.append(effort)
    return efforts


def _multi_agent_version(payload: dict[str, Any]) -> str | None:
    value: Any = payload.get("multi_agent_version")
    if value is None:
        for key in ("multi_agent", "multi_agent_capability", "capabilities", "features"):
            nested = payload.get(key)
            if isinstance(nested, dict):
                value = nested.get("multi_agent_version") or nested.get("version")
                if value is not None:
                    break
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        text = str(value).strip()
        return text or None
    return None


def _normalize_model_metadata(
    payload: dict[str, Any], *, source: str, fetched_at: str | None
) -> CodexModelMetadata:
    slug = str(payload["slug"])
    return {
        "slug": slug,
        "display_name": str(payload.get("display_name") or payload.get("name") or slug),
        "visibility": (
            payload["visibility"].strip()
            if isinstance(payload.get("visibility"), str)
            else None
        ),
        "supported_reasoning_efforts": _reasoning_efforts(payload),
        "context_window": _first_int(
            payload,
            (
                "context_window",
                "max_context_window",
                "context_length",
                "max_context_length",
            ),
        ),
        "max_output_tokens": _first_int(
            payload,
            (
                "max_output_tokens",
                "max_completion_tokens",
                "output_token_limit",
                "max_output",
            ),
        ),
        "multi_agent_version": _multi_agent_version(payload),
        "source": source,
        "fetched_at": fetched_at,
    }


def _minimal_model_catalog(
    model_ids: list[str], *, source: str, fetched_at: str | None
) -> list[CodexModelMetadata]:
    return [
        _normalize_model_metadata({"slug": model_id}, source=source, fetched_at=fetched_at)
        for model_id in model_ids
    ]


def get_codex_model_catalog(
    access_token: str | None = None,
    *,
    api_timeout: float = 10.0,
) -> CodexModelCatalog:
    """Return account-aware Codex slugs plus normalized capability metadata.

    ``models`` remains a list of slugs for existing callers.  ``catalog`` is
    the new metadata list.  ``source`` is ``live``, ``cache``, or
    ``offline-fallback``; ``freshness``/``fetched_at`` is copied from the
    endpoint or cache when provided.  No fallback entry is claimed to be
    account-authoritative.
    """
    if access_token:
        live_result = _fetch_model_entries_from_api(access_token, timeout=api_timeout)
        if live_result is not None:
            raw_entries, fetched_at = live_result
            metadata = [
                _normalize_model_metadata(item, source="live", fetched_at=fetched_at)
                for item in _visible_model_entries(raw_entries)
            ]
            return {
                "models": [item["slug"] for item in metadata],
                "catalog": metadata,
                "source": "live",
                "freshness": fetched_at,
                "fetched_at": fetched_at,
                "live": True,
                "stale": False,
                "authoritative": True,
                "warning": "",
            }

    codex_home = _codex_home()
    cached_entries, cached_fetched_at = _read_cache_payload(codex_home)
    if cached_entries:
        metadata = [
            _normalize_model_metadata(
                item, source="cache", fetched_at=cached_fetched_at
            )
            for item in cached_entries
        ]
        if access_token:
            warning = (
                "Could not load this account's live Codex model catalog; "
                "showing the cached catalog."
            )
        else:
            warning = (
                "OpenAI Codex is not authenticated; showing the cached catalog. "
                "Connect Codex to refresh account availability."
            )
        return {
            "models": [item["slug"] for item in metadata],
            "catalog": metadata,
            "source": "cache",
            "freshness": cached_fetched_at,
            "fetched_at": cached_fetched_at,
            "live": False,
            "stale": True,
            "authoritative": False,
            "warning": warning,
        }

    model_ids = get_codex_model_ids()
    warning = (
        "Could not load an account-scoped Codex model catalog; showing the "
        "offline fallback."
        if access_token
        else "OpenAI Codex is not authenticated; showing the offline fallback. "
        "Connect Codex to load the models available to this account."
    )
    metadata = _minimal_model_catalog(
        model_ids, source="offline-fallback", fetched_at=None
    )
    return {
        "models": model_ids,
        "catalog": metadata,
        "source": "offline-fallback",
        "freshness": None,
        "fetched_at": None,
        "live": False,
        "stale": True,
        "authoritative": False,
        "warning": warning,
    }
