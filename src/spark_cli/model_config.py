"""Shared helpers for Spark's universal model configuration.

The model/runtime selection lives in config.yaml, not in platform-specific
session state.  TUI, WebUI, and gateway code use these helpers so updates made
from one surface are reflected everywhere on the next turn.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

AUTO_ROLE_NAMES = ("lead", "balanced", "fast", "subagent")


@dataclass(frozen=True)
class ModelTarget:
    """A provider/model preference that can be checked against a live catalog."""

    provider: str = ""
    model: str = ""
    reasoning_effort: str = ""
    fallback: tuple[str, ...] = ()
    base_url: str = ""
    api_mode: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "fallback": list(self.fallback),
            "base_url": self.base_url,
            "api_mode": self.api_mode,
        }


@dataclass(frozen=True)
class AutoPolicy:
    """The single automatic routing policy shared by all Spark surfaces."""

    enabled: bool = True
    roles: Mapping[str, ModelTarget] = field(default_factory=dict)
    hysteresis_margin: int = 2
    context_threshold: int = 24_000

    def role(self, name: str) -> ModelTarget:
        return self.roles.get(name, ModelTarget())

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "hysteresis_margin": self.hysteresis_margin,
            "context_threshold": self.context_threshold,
            "roles": {name: target.as_dict() for name, target in self.roles.items()},
        }


@dataclass(frozen=True)
class GlobalModelConfig:
    model: str = ""
    provider: str = ""
    base_url: str = ""
    api_mode: str = ""
    selection: str = "auto"
    auto_policy: AutoPolicy = field(default_factory=AutoPolicy)

    @property
    def is_pinned(self) -> bool:
        return self.selection == "pinned"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _fallback_roles(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        values = list(value)
    else:
        values = []
    return tuple(role for role in (_text(item).lower() for item in values) if role in AUTO_ROLE_NAMES)


def _target_from_config(value: Any) -> ModelTarget:
    if not isinstance(value, Mapping):
        return ModelTarget()
    return ModelTarget(
        provider=_text(value.get("provider")).lower(),
        model=_text(value.get("model") or value.get("default")),
        reasoning_effort=_text(value.get("reasoning_effort") or value.get("effort")),
        fallback=_fallback_roles(value.get("fallback")),
        base_url=_text(value.get("base_url")),
        api_mode=_text(value.get("api_mode")),
    )


def _legacy_role_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Project legacy model, smart-routing, and delegation settings into roles."""
    model = config.get("model")
    model_section = model if isinstance(model, Mapping) else {"default": model}
    smart = config.get("smart_model_routing")
    smart = smart if isinstance(smart, Mapping) else {}
    cheap_value = smart.get("cheap_model")
    cheap: Mapping[str, Any] = cheap_value if isinstance(cheap_value, Mapping) else {}
    delegation_value = config.get("delegation")
    delegation: Mapping[str, Any] = delegation_value if isinstance(delegation_value, Mapping) else {}

    lead = {
        "provider": model_section.get("provider", ""),
        "model": model_section.get("default") or model_section.get("model", ""),
        "reasoning_effort": config.get("agent", {}).get("reasoning_effort", "")
        if isinstance(config.get("agent"), Mapping)
        else "",
        "fallback": ["balanced"],
        "base_url": model_section.get("base_url", ""),
        "api_mode": model_section.get("api_mode", ""),
    }
    balanced = dict(lead)
    balanced["fallback"] = ["fast"]
    fast = {
        "provider": cheap.get("provider", ""),
        "model": cheap.get("model", ""),
        "reasoning_effort": cheap.get("reasoning_effort", "low"),
        "fallback": ["balanced"],
        "base_url": cheap.get("base_url", ""),
        "api_mode": cheap.get("api_mode", ""),
    }
    subagent = {
        "provider": delegation.get("provider", ""),
        "model": delegation.get("model", ""),
        "reasoning_effort": delegation.get("reasoning_effort", ""),
        "fallback": ["balanced"],
        "base_url": delegation.get("base_url", ""),
        "api_mode": delegation.get("api_mode", ""),
    }
    return {"lead": lead, "balanced": balanced, "fast": fast, "subagent": subagent}


def normalize_auto_policy(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return a non-destructive, backward-compatible Auto policy projection.

    Legacy keys remain in the returned config. Missing role settings are filled
    from ``model.default``, ``smart_model_routing.cheap_model``, and
    ``delegation`` so old config files can be consumed by the new resolver.
    """
    source = deepcopy(dict(config or {}))
    model = source.get("model")
    model_section = dict(model) if isinstance(model, Mapping) else {"default": model or ""}
    legacy_roles = _legacy_role_config(source)
    existing = model_section.get("auto")
    if not isinstance(existing, Mapping):
        smart = source.get("smart_model_routing")
        smart = smart if isinstance(smart, Mapping) else {}
        existing = smart.get("auto")
    existing = existing if isinstance(existing, Mapping) else {}
    roles = existing.get("roles")
    roles = roles if isinstance(roles, Mapping) else {}

    normalized_roles: dict[str, dict[str, Any]] = {}
    for name in AUTO_ROLE_NAMES:
        merged = dict(legacy_roles[name])
        configured = roles.get(name)
        if isinstance(configured, Mapping):
            merged.update(configured)
        normalized_roles[name] = merged

    smart = source.get("smart_model_routing")
    smart = smart if isinstance(smart, Mapping) else {}
    auto = dict(existing)
    auto["enabled"] = bool(auto.get("enabled", smart.get("enabled", True)))
    auto["hysteresis_margin"] = max(0, int(auto.get("hysteresis_margin", 2) or 0))
    auto["context_threshold"] = max(1, int(auto.get("context_threshold", 24_000) or 1))
    auto["roles"] = normalized_roles
    model_section["auto"] = auto
    if "selection" not in model_section:
        old_default = _text(model_section.get("default"))
        model_section["selection"] = (
            "auto"
            if not old_default or old_default.lower() == "auto" or bool(smart.get("enabled"))
            else "pinned"
        )
    source["model"] = model_section
    return source


def read_auto_policy(config: Mapping[str, Any] | None = None) -> AutoPolicy:
    normalized = normalize_auto_policy(config)
    model = normalized.get("model")
    model = model if isinstance(model, Mapping) else {}
    auto = model.get("auto")
    auto = auto if isinstance(auto, Mapping) else {}
    roles_value = auto.get("roles")
    roles_cfg: Mapping[str, Any] = roles_value if isinstance(roles_value, Mapping) else {}
    roles = {name: _target_from_config(roles_cfg.get(name)) for name in AUTO_ROLE_NAMES}
    return AutoPolicy(
        enabled=bool(auto.get("enabled", True)),
        roles=roles,
        hysteresis_margin=max(0, int(auto.get("hysteresis_margin", 2) or 0)),
        context_threshold=max(1, int(auto.get("context_threshold", 24_000) or 1)),
    )


def read_global_model_config(config: dict[str, Any] | None = None) -> GlobalModelConfig:
    """Return the normalized model selection from config.yaml or a config dict."""
    if config is None:
        from spark_cli.config import load_config

        config = load_config()

    normalized = normalize_auto_policy(config)
    model_cfg = normalized.get("model", "")
    if isinstance(model_cfg, dict):
        selection = _text(model_cfg.get("selection")).lower()
        if selection not in {"auto", "pinned"}:
            selection = "auto" if not _text(model_cfg.get("default")) else "pinned"
        return GlobalModelConfig(
            model=_text(model_cfg.get("default") or model_cfg.get("model") or model_cfg.get("name")),
            provider=_text(model_cfg.get("provider")),
            base_url=_text(model_cfg.get("base_url")),
            api_mode=_text(model_cfg.get("api_mode")),
            selection=selection,
            auto_policy=read_auto_policy(normalized),
        )
    if isinstance(model_cfg, str):
        return GlobalModelConfig(model=model_cfg, selection="pinned" if model_cfg.strip() else "auto", auto_policy=read_auto_policy(normalized))
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

    model_value = str(model or "").strip()
    if model_value.lower() == "auto":
        model_section["default"] = ""
        model_section["selection"] = "auto"
    else:
        model_section["default"] = model_value
        model_section["selection"] = "pinned"
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
    elif model_value.lower() == "auto":
        routing = config.get("smart_model_routing")
        if isinstance(routing, dict):
            routing["enabled"] = True

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
