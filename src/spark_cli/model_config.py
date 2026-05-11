"""Shared helpers for Spark's universal model configuration.

The model/runtime selection lives in config.yaml, not in platform-specific
session state.  TUI, WebUI, and gateway code use these helpers so updates made
from one surface are reflected everywhere on the next turn.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GlobalModelConfig:
    model: str = ""
    provider: str = ""
    base_url: str = ""
    api_mode: str = ""


def read_global_model_config(config: dict[str, Any] | None = None) -> GlobalModelConfig:
    """Return the normalized model selection from config.yaml or a config dict."""
    if config is None:
        from spark_cli.config import load_config

        config = load_config()

    model_cfg = config.get("model", "")
    if isinstance(model_cfg, dict):
        return GlobalModelConfig(
            model=str(model_cfg.get("default") or model_cfg.get("model") or model_cfg.get("name") or ""),
            provider=str(model_cfg.get("provider") or ""),
            base_url=str(model_cfg.get("base_url") or ""),
            api_mode=str(model_cfg.get("api_mode") or ""),
        )
    if isinstance(model_cfg, str):
        return GlobalModelConfig(model=model_cfg)
    return GlobalModelConfig()


def write_global_model_config(
    *,
    model: str,
    provider: str | None = None,
    base_url: str | None = None,
    api_mode: str | None = None,
    disable_smart_routing: bool | None = None,
) -> dict[str, Any]:
    """Persist the universal model selection to config.yaml.

    ``None`` means "leave this field unchanged" for optional runtime metadata.
    An empty string means "clear this field", which prevents stale provider
    metadata from leaking across model switches.
    """
    from spark_cli.config import load_config, save_config

    config = load_config()
    model_cfg = config.get("model")
    if isinstance(model_cfg, dict):
        model_section = dict(model_cfg)
    elif isinstance(model_cfg, str) and model_cfg.strip():
        model_section = {"default": model_cfg.strip()}
    else:
        model_section = {}

    model_section["default"] = model
    for key, value in (
        ("provider", provider),
        ("base_url", base_url),
        ("api_mode", api_mode),
    ):
        if value is None:
            continue
        value = str(value).strip()
        if value:
            model_section[key] = value
        else:
            model_section.pop(key, None)

    config["model"] = model_section

    if disable_smart_routing is not None:
        routing = config.get("smart_model_routing")
        if not isinstance(routing, dict):
            routing = {}
            config["smart_model_routing"] = routing
        routing["enabled"] = not disable_smart_routing

    save_config(config)
    return config


def write_model_switch_result(
    result: Any,
    *,
    disable_smart_routing: bool | None = None,
) -> dict[str, Any]:
    """Persist a ``ModelSwitchResult`` as the universal model selection."""
    return write_global_model_config(
        model=result.new_model,
        provider=result.target_provider,
        base_url=result.base_url or "",
        api_mode=result.api_mode or "",
        disable_smart_routing=disable_smart_routing,
    )
