"""FastAPI routes for model selection, status, and Codex usage.

Extracted from web_server.py. Provider and catalog lookups are imported
inside the handlers so importing this module performs no network or disk IO.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from spark_cli.codex_models import CodexModelCatalog

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from spark_cli.config import load_config, load_env
from spark_cli.onboarding_validation import normalize_http_base_url, normalize_model_name

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/model", tags=["model"])


def _normalize_config_provider_key(value: str) -> str:
    return str(value or "").strip().lower().replace(" ", "-")


_EMPTY_MODEL_INFO: dict = {
    "model": "",
    "provider": "",
    "auto_context_length": 0,
    "config_context_length": 0,
    "effective_context_length": 0,
    "capabilities": {},
}


_PROVIDER_MODEL_SUGGESTIONS: dict[str, list] = {
    "openai-codex": [
        "gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex", "gpt-5.2-codex",
    ],
    "qwen-oauth": ["qwen3-coder-plus", "qwen3-coder-flash"],
    "openai": [
        "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna",
        "gpt-5.5", "gpt-5.4", "gpt-5.4-mini",
        "gpt-4.1", "gpt-4.1-mini", "gpt-4o", "gpt-4o-mini", "o3", "o4-mini",
    ],
    "anthropic": [
        "claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5-20251001",
        "claude-opus-4-5", "claude-sonnet-4-5",
    ],
    "google": ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash"],
    "openrouter": ["anthropic/claude-sonnet-4-6", "openai/gpt-4o", "google/gemini-2.5-pro"],
    "deepseek": ["deepseek-chat", "deepseek-reasoner"],
    "xai": ["grok-3", "grok-3-mini"],
    "ollama": ["llama3.3", "qwen2.5-coder:32b", "mistral", "phi4"],
}


def _models_from_provider_config(provider: str) -> tuple[list, str]:
    """Return ``(models, base_url)`` for a provider defined in config.yaml."""
    requested = _normalize_config_provider_key(provider)
    if not requested:
        return [], ""
    requested_no_custom = requested
    if requested.startswith("custom:"):
        requested_no_custom = requested.removeprefix("custom:")
    try:
        cfg = load_config()
    except Exception:
        return [], ""
    providers_cfg = cfg.get("providers")
    if not isinstance(providers_cfg, dict):
        return [], ""

    for key, entry in providers_cfg.items():
        if not isinstance(entry, dict):
            continue
        key_norm = _normalize_config_provider_key(str(key))
        display = _normalize_config_provider_key(str(entry.get("name", "") or ""))
        candidates = {key_norm, f"custom:{key_norm}"}
        if display:
            candidates.update({display, f"custom:{display}"})
        if (
            requested not in candidates
            and requested_no_custom not in {key_norm, display}
        ):
            continue

        models: list[str] = []
        default_model = str(entry.get("default_model", "") or "").strip()
        if default_model:
            models.append(default_model)
        cfg_models = entry.get("models", [])
        if isinstance(cfg_models, list):
            for model_id in cfg_models:
                model_id = str(model_id or "").strip()
                if model_id and model_id not in models:
                    models.append(model_id)
        base_url = str(
            entry.get("api") or entry.get("url") or entry.get("base_url") or ""
        ).strip()
        return models, base_url
    return [], ""


def _codex_usage_windows(rate_limit: Any) -> list[dict[str, Any]]:
    """Build displayable Codex usage windows from the live response.

    Codex can independently omit or null either window (for example, while a
    plan has no weekly limit).  Keep every window that is actually present
    instead of letting one absent window discard the entire usage meter.
    """
    if not isinstance(rate_limit, dict):
        return []

    windows: list[dict[str, Any]] = []
    for key in ("primary_window", "secondary_window"):
        window = rate_limit.get(key)
        if not isinstance(window, dict):
            continue
        used_percent = window.get("used_percent")
        if not isinstance(used_percent, (int, float)):
            continue
        window_seconds = window.get("limit_window_seconds")
        if not isinstance(window_seconds, (int, float)) or window_seconds <= 0:
            continue
        if window_seconds == 604800:
            label = "Weekly limit"
        elif window_seconds == 18000:
            label = "5h limit"
        elif window_seconds % 86400 == 0:
            label = f"{int(window_seconds / 86400)}d limit"
        elif window_seconds % 3600 == 0:
            label = f"{int(window_seconds / 3600)}h limit"
        else:
            label = "Usage limit"
        windows.append({
            "label": label,
            "used_percent": used_percent,
            "reset_at": window.get("reset_at"),
            "reset_after_seconds": window.get("reset_after_seconds"),
            "window_seconds": window_seconds,
        })
    return windows


@router.get("/codex-usage")
def get_codex_usage():
    """Return Codex provider status and any captured usage-limit state.

    The ChatGPT backend ``usage_limits`` endpoint is Cloudflare-protected and
    requires browser session cookies — it cannot be called server-side with the
    Codex OAuth token.  The Codex Responses API also does not return
    x-ratelimit-* headers.  Instead, this endpoint surfaces:

    1. ``provider_connected`` — whether the provider is openai-codex and the
       user is authenticated (always available when Codex is configured).
    2. ``limit_hit`` — non-null when a ``usage_limit_reached`` error was
       detected during a recent inference turn, including reset info.
    3. ``rate_limit`` — the last x-ratelimit-* state from any active web agent,
       if the provider returned those headers (most non-Codex providers do).
    """
    try:
        cfg = load_config()
        model_cfg = cfg.get("model", "")
        if isinstance(model_cfg, dict):
            provider = str(model_cfg.get("provider", "") or "").strip()
        else:
            provider = ""

        if provider != "openai-codex":
            return {"available": False, "reason": "not_codex_provider"}

        from spark_cli.auth import get_codex_auth_status

        status = get_codex_auth_status()
        if not status.get("logged_in"):
            return {"available": False, "reason": "not_authenticated"}

        # Resolve active model name for display
        active_model = ""
        try:
            if isinstance(model_cfg, dict):
                active_model = str(model_cfg.get("default", model_cfg.get("name", "")) or "").strip()
            else:
                active_model = str(model_cfg or "").strip()
            if active_model:
                active_model = active_model.replace("-", " ").title().replace(" ", "-").replace("Gpt", "GPT")
        except Exception:
            _log.debug("Ignoring error in get_codex_usage()", exc_info=True)

        # Fetch live usage from the wham/usage endpoint (discovered via CodexBar)
        # Requires the ChatGPT-Account-Id header extracted from the JWT claims.
        try:
            import base64 as _base64

            import httpx as _httpx

            access_token = status.get("api_key", "")
            # Extract chatgpt_account_id from JWT payload
            account_id = ""
            try:
                parts = access_token.split(".")
                if len(parts) >= 2:
                    padded = parts[1] + "=" * (-len(parts[1]) % 4)
                    jwt_claims = __import__("json").loads(_base64.urlsafe_b64decode(padded))
                    auth_ns = jwt_claims.get("https://api.openai.com/auth", {})
                    account_id = auth_ns.get("chatgpt_account_id", "")
            except Exception:
                _log.debug("Ignoring error in get_codex_usage()", exc_info=True)

            wham_headers = {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
                "User-Agent": "Spark/1.0",
            }
            if account_id:
                wham_headers["ChatGPT-Account-Id"] = account_id

            # Do not require HTTP/2 here. It is an optional httpx dependency
            # and is intentionally absent from the frozen desktop sidecar;
            # chatgpt.com serves this endpoint correctly over HTTP/1.1.
            with _httpx.Client(timeout=10.0) as _hc:
                wham = _hc.get("https://chatgpt.com/backend-api/wham/usage", headers=wham_headers)

            if wham.status_code == 200:
                wham_data = wham.json()
                rl = wham_data.get("rate_limit")
                if not isinstance(rl, dict):
                    rl = {}
                return {
                    "available": True,
                    "provider_connected": True,
                    "active_model": active_model,
                    "plan_type": wham_data.get("plan_type"),
                    "limit_reached": rl.get("limit_reached", False),
                    "windows": _codex_usage_windows(rl),
                }
        except Exception as exc:
            _log.debug("wham/usage fetch failed: %s", exc)

        # Fallback: return connected state without usage windows
        return {
            "available": True,
            "provider_connected": True,
            "active_model": active_model,
            "windows": [],
        }
    except Exception:
        _log.exception("GET /api/model/codex-usage failed")
        return {"available": False, "reason": "internal_error"}


@router.get("/info")
def get_model_info():
    """Return resolved model metadata for the currently configured model.

    Calls the same context-length resolution chain the agent uses, so the
    frontend can display "Auto-detected: 200K" alongside the override field.
    Also returns model capabilities (vision, reasoning, tools) when available.
    """
    try:
        cfg = load_config()
        model_cfg = cfg.get("model", "")

        # Extract model name and provider from the config
        if isinstance(model_cfg, dict):
            model_name = model_cfg.get("default", model_cfg.get("name", ""))
            provider = model_cfg.get("provider", "")
            base_url = model_cfg.get("base_url", "")
            config_ctx = model_cfg.get("context_length")
        else:
            model_name = str(model_cfg) if model_cfg else ""
            provider = ""
            base_url = ""
            config_ctx = None

        if not model_name:
            return dict(_EMPTY_MODEL_INFO, provider=provider)

        # Resolve auto-detected context length (pass config_ctx=None to get
        # purely auto-detected value, then separately report the override)
        try:
            from agent.model_metadata import get_model_context_length

            auto_ctx = get_model_context_length(
                model=model_name,
                base_url=base_url,
                provider=provider,
                config_context_length=None,  # ignore override — we want auto value
            )
        except Exception:
            auto_ctx = 0

        config_ctx_int = 0
        if isinstance(config_ctx, int) and config_ctx > 0:
            config_ctx_int = config_ctx

        # Effective is what the agent actually uses
        effective_ctx = config_ctx_int if config_ctx_int > 0 else auto_ctx

        # Try to get model capabilities from models.dev
        caps = {}
        try:
            from agent.models_dev import get_model_capabilities

            mc = get_model_capabilities(provider=provider, model=model_name)
            if mc is not None:
                caps = {
                    "supports_tools": mc.supports_tools,
                    "supports_vision": mc.supports_vision,
                    "supports_reasoning": mc.supports_reasoning,
                    "context_window": mc.context_window,
                    "max_output_tokens": mc.max_output_tokens,
                    "model_family": mc.model_family,
                }
        except Exception:
            _log.debug("Ignoring error in get_model_info()", exc_info=True)

        return {
            "model": model_name,
            "provider": provider,
            "auto_context_length": auto_ctx,
            "config_context_length": config_ctx_int,
            "effective_context_length": effective_ctx,
            "capabilities": caps,
        }
    except Exception:
        _log.exception("GET /api/model/info failed")
        return dict(_EMPTY_MODEL_INFO)


@router.get("/status")
def get_model_status():
    """Return all model/routing/reasoning state needed by the prompt bar."""
    try:
        cfg = load_config()
        from spark_cli.model_config import read_auto_policy, read_global_model_config

        global_model = read_global_model_config(cfg)
        policy = read_auto_policy(cfg)
        model_cfg = cfg.get("model", "")
        if isinstance(model_cfg, dict):
            smart_model = str(model_cfg.get("default", model_cfg.get("name", "")) or "")
            smart_provider = str(model_cfg.get("provider", "") or "")
        else:
            smart_model = str(model_cfg or "")
            smart_provider = ""

        routing_cfg = cfg.get("smart_model_routing", {}) or {}
        multi_enabled = bool(routing_cfg.get("enabled", False))
        cheap = routing_cfg.get("cheap_model", {}) or {}
        fast_model = str(cheap.get("model", "") or "")
        fast_provider = str(cheap.get("provider", "") or "")

        agent_cfg = cfg.get("agent", {}) if isinstance(cfg.get("agent"), dict) else {}
        effort = str(agent_cfg.get("reasoning_effort") or "").strip().lower() or "none"

        # Reasoning support
        reasoning_supported = False
        try:
            from agent.models_dev import get_model_capabilities
            if smart_model:
                mc = get_model_capabilities(provider=smart_provider, model=smart_model)
                reasoning_supported = bool(mc and mc.supports_reasoning)
        except Exception:
            _log.debug("Ignoring error in get_model_status()", exc_info=True)

        catalog_source = "unavailable"
        catalog_warning = ""
        try:
            catalog = _resolve_codex_model_catalog()
            catalog_source = str(catalog.get("source") or "unavailable")
            catalog_warning = str(catalog.get("warning") or "")
        except Exception:
            _log.debug("Ignoring error in get_model_status()", exc_info=True)

        return {
            "smart_model": "auto" if global_model.selection == "auto" else smart_model,
            "smart_provider": smart_provider,
            "fast_model": fast_model,
            "fast_provider": fast_provider,
            "multi_model_enabled": multi_enabled,
            "reasoning_effort": effort,
            "reasoning_supported": reasoning_supported,
            "auto_enabled": policy.enabled,
            "selection": global_model.selection,
            "auto_roles": {name: target.as_dict() for name, target in policy.roles.items()},
            "catalog_source": catalog_source,
            "catalog_warning": catalog_warning,
        }
    except Exception:
        _log.exception("GET /api/model/status failed")
        return {
            "smart_model": "", "smart_provider": "", "fast_model": "", "fast_provider": "",
            "multi_model_enabled": False, "reasoning_effort": "none", "reasoning_supported": False,
            "auto_enabled": True, "selection": "auto", "auto_roles": {},
            "catalog_source": "unavailable", "catalog_warning": "",
        }


_STRICT_MODEL_PROVIDERS = frozenset({"openai-codex", "qwen-oauth"})


def _resolve_codex_model_catalog() -> CodexModelCatalog:
    """Return the account-scoped Codex catalog with explicit trust metadata."""
    from spark_cli.auth import get_codex_auth_status
    from spark_cli.codex_models import get_codex_model_catalog

    status = get_codex_auth_status()
    token = str(status.get("api_key", "") or "") if status.get("logged_in") else ""
    return get_codex_model_catalog(access_token=token, api_timeout=2.0)


def _resolve_provider_models(provider: str, base_url: str = "") -> tuple[list, bool]:
    """Resolve the model catalog for ``provider`` (live where possible).

    Returns ``(models, live)`` where ``live`` indicates the list came from
    querying the provider directly (vs. static suggestions). For ollama,
    openrouter and OpenAI-compatible custom endpoints we query the provider so
    the dropdown reflects what's actually installed/available. Everything else
    falls back to the curated suggestion lists.
    """
    provider = (provider or "").strip()
    base_url = (base_url or "").strip()

    config_models, config_base_url = _models_from_provider_config(provider)
    if config_models:
        return config_models, False
    if not base_url and config_base_url:
        base_url = config_base_url

    if provider == "openai-codex":
        try:
            catalog = _resolve_codex_model_catalog()
            return list(catalog["models"]), bool(catalog["live"])
        except Exception:
            return list(_PROVIDER_MODEL_SUGGESTIONS.get(provider, [])), False

    if provider in {"ollama", "openrouter", "custom"} or base_url:
        try:
            from agent.model_metadata import list_provider_models

            api_key = ""
            if provider == "openrouter":
                api_key = load_env().get("OPENROUTER_API_KEY", "") or ""
            live = list_provider_models(provider, base_url=base_url, api_key=api_key)
            if live:
                return live, True
        except Exception:
            _log.exception("live model fetch failed for provider=%s", provider)
        # Fall back to static hints when the provider is unreachable.
        return list(_PROVIDER_MODEL_SUGGESTIONS.get(provider, [])), False

    return list(_PROVIDER_MODEL_SUGGESTIONS.get(provider, [])), False


@router.get("/available")
def get_available_models(provider: str = "", base_url: str = ""):
    """Return the model catalog for a given provider plus whether the UI should
    enforce a strict dropdown.

    Query params:
        provider — provider id (e.g. "openai-codex"). Defaults to "".
        base_url — optional endpoint URL used to query local/custom providers
                   (ollama, OpenAI-compatible servers) for their live catalog.

    Response:
        provider — echoed provider id
        models   — list of known model names for that provider (may be empty)
        live     — True when the list was fetched live from the provider
        strict   — True when the UI should only allow choosing from `models`
                   (fixed/managed catalogs like openai-codex); False when the
                   user may type a custom name (ollama, openrouter, custom).
    """
    provider = (provider or "").strip()
    normalized_base_url = ""
    if (base_url or "").strip():
        try:
            normalized_base_url = normalize_http_base_url(
                base_url, field_name="Model base URL"
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    codex_catalog = None
    if provider == "openai-codex":
        try:
            codex_catalog = _resolve_codex_model_catalog()
            models = list(codex_catalog["models"])
            live = bool(codex_catalog["live"])
        except Exception:
            models = list(_PROVIDER_MODEL_SUGGESTIONS.get(provider, []))
            live = False
    else:
        models, live = _resolve_provider_models(provider, normalized_base_url)
    strict = provider in _STRICT_MODEL_PROVIDERS
    warning = ""
    source = "live" if live else "curated"
    if provider == "openai-codex" and not live:
        source = "offline-fallback"
        warning = (
            "The live Codex catalog is unavailable. Only conservative offline "
            "fallback models are shown; reconnect Codex to refresh account availability."
        )
    response = {
        "provider": provider,
        "models": models,
        "live": live,
        "strict": strict,
        "source": source,
        "warning": warning,
    }
    if codex_catalog is not None:
        response.update(
            {
                "catalog": list(codex_catalog["catalog"]),
                "source": codex_catalog["source"],
                "freshness": codex_catalog["freshness"],
                "stale": bool(codex_catalog["stale"]),
                "authoritative": bool(codex_catalog["authoritative"]),
                "warning": codex_catalog["warning"],
            }
        )
    return response


@router.get("/suggestions")
def get_model_suggestions():
    """Return provider-aware model name suggestions for the quick-settings popover."""
    try:
        from spark_cli.model_config import read_auto_policy

        cfg = load_config()
        model_cfg = cfg.get("model", "")
        smart_provider = ""
        smart_base_url = ""
        if isinstance(model_cfg, dict):
            smart_provider = str(model_cfg.get("provider", "") or "")
            smart_base_url = str(model_cfg.get("base_url", "") or "")

        routing_cfg = cfg.get("smart_model_routing", {}) or {}
        cheap = routing_cfg.get("cheap_model", {}) or {}
        fast_provider = str(cheap.get("provider", "") or "")
        fast_base_url = str(cheap.get("base_url", "") or "")

        if not smart_provider:
            policy = read_auto_policy(cfg)
            smart_provider = policy.role("balanced").provider
        smart_models, _ = _resolve_provider_models(smart_provider, smart_base_url)
        fast_models, _ = _resolve_provider_models(fast_provider, fast_base_url)

        return {
            "smart": ["auto", *[model for model in smart_models if model != "auto"]],
            "fast": fast_models,
            "smart_provider": smart_provider,
            "fast_provider": fast_provider,
        }
    except Exception:
        _log.exception("GET /api/model/suggestions failed")
        return {"smart": [], "fast": [], "smart_provider": "", "fast_provider": ""}


@router.put("/fast")
def set_fast_model(body: dict[str, Any]):
    """Update just the fast model name, preserving other routing config."""
    try:
        from spark_cli.config import save_config

        try:
            new_model = normalize_model_name(body.get("model"), field_name="Model name")
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        cfg = load_config()
        if "smart_model_routing" not in cfg or not isinstance(cfg["smart_model_routing"], dict):
            cfg["smart_model_routing"] = {}
        if "cheap_model" not in cfg["smart_model_routing"] or not isinstance(cfg["smart_model_routing"]["cheap_model"], dict):
            cfg["smart_model_routing"]["cheap_model"] = {}
        cfg["smart_model_routing"]["cheap_model"]["model"] = new_model
        save_config(cfg)
        return {"ok": True, "model": new_model}
    except Exception:
        _log.exception("PUT /api/model/fast failed")
        return JSONResponse({"error": "Failed to save fast model"}, status_code=500)


@router.put("/smart")
def set_smart_model(body: dict[str, Any]):
    """Update just the smart model name, preserving provider/url/api_mode."""
    try:
        from spark_cli.config import save_config

        raw_model = str(body.get("model") or "").strip()
        if raw_model.lower() == "auto":
            from spark_cli.model_config import write_global_model_config

            write_global_model_config(model="auto")
            return {"ok": True, "model": "auto", "selection": "auto"}
        try:
            new_model = normalize_model_name(body.get("model"), field_name="Model name")
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        cfg = load_config()
        model_cfg = cfg.get("model", "")
        if isinstance(model_cfg, dict):
            model_cfg["default"] = new_model
            cfg["model"] = model_cfg
        else:
            cfg["model"] = new_model
        save_config(cfg)
        return {"ok": True, "model": new_model}
    except Exception:
        _log.exception("PUT /api/model/smart failed")
        return JSONResponse({"error": "Failed to save model"}, status_code=500)


@router.get("/reasoning")
def get_reasoning_effort():
    """Return current reasoning effort and whether the active model supports it."""
    try:
        cfg = load_config()
        agent_cfg = cfg.get("agent", {}) if isinstance(cfg.get("agent"), dict) else {}
        effort = str(agent_cfg.get("reasoning_effort") or "").strip().lower() or "none"

        # Check if active model supports reasoning
        supported = False
        try:
            from agent.models_dev import get_model_capabilities

            model_cfg = cfg.get("model", "")
            if isinstance(model_cfg, dict):
                model_name = model_cfg.get("default", model_cfg.get("name", ""))
                provider = model_cfg.get("provider", "")
            else:
                model_name = str(model_cfg) if model_cfg else ""
                provider = ""
            if model_name:
                mc = get_model_capabilities(provider=provider, model=model_name)
                supported = bool(mc and mc.supports_reasoning)
        except Exception:
            _log.debug("Ignoring error in get_reasoning_effort()", exc_info=True)

        return {"effort": effort, "supported": supported}
    except Exception:
        _log.exception("GET /api/model/reasoning failed")
        return {"effort": "none", "supported": False}


@router.put("/reasoning")
def set_reasoning_effort(body: dict[str, Any]):
    """Set reasoning effort level. Valid values: none, minimal, low, medium, high, xhigh."""
    try:
        from core.spark_constants import parse_reasoning_effort
        from spark_cli.config import save_config

        effort = str(body.get("effort", "none")).strip().lower()
        if effort != "none" and parse_reasoning_effort(effort) is None:
            return JSONResponse({"error": f"Invalid effort: {effort}"}, status_code=400)

        cfg = load_config()
        if "agent" not in cfg or not isinstance(cfg["agent"], dict):
            cfg["agent"] = {}
        cfg["agent"]["reasoning_effort"] = "" if effort == "none" else effort
        save_config(cfg)
        return {"effort": effort, "ok": True}
    except Exception:
        _log.exception("PUT /api/model/reasoning failed")
        return JSONResponse({"error": "Failed to save reasoning effort"}, status_code=500)


def register_model_routes(app) -> None:
    app.include_router(router)
