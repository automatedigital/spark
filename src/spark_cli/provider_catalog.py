"""Read-only provider metadata. Never resolves credentials or contacts providers."""
from __future__ import annotations

from typing import Any

from dotenv import dotenv_values

from core.spark_constants import OPENROUTER_BASE_URL, get_spark_home
from spark_cli.auth import ProviderConfig
from spark_cli.config import get_compatible_custom_providers
from spark_cli.runtime_provider import registered_provider_metadata


def provider_catalog(config: dict[str, Any]) -> dict[str, Any]:
    """Project registered routes without importing SDKs or adopting external auth.

    Availability is deliberately unknown: saved credentials are configuration,
    not proof of a usable SDK, OAuth session, endpoint or model capability.
    """
    local_env = dotenv_values(get_spark_home() / ".env", interpolate=False)
    definitions = registered_provider_metadata()
    definitions["openrouter"] = ProviderConfig(
        id="openrouter", name="OpenRouter", auth_type="api_key",
        inference_base_url=OPENROUTER_BASE_URL,
        api_key_env_vars=("OPENROUTER_API_KEY", "OPENAI_API_KEY"),
    )
    definitions["custom"] = ProviderConfig(
        id="custom", name="Custom endpoint", auth_type="optional_api_key",
        api_key_env_vars=("OPENAI_API_KEY",),
    )
    inline_configured: set[str] = set()
    for entry in get_compatible_custom_providers(config):
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        pid = "custom:" + str(entry.get("provider_key") or name).strip().lower().replace(" ", "-")
        if entry.get("api_key"):
            inline_configured.add(pid)
        key_env = str(entry.get("key_env") or "")
        definitions[pid] = ProviderConfig(
            id=pid, name=name, auth_type="optional_api_key",
            api_key_env_vars=(key_env,) if key_env else (),
        )
    entries = []
    for pid, definition in definitions.items():
        entries.append({
            "id": pid,
            "label": definition.name,
            "credential": {
                "mechanism": definition.auth_type,
                "env_vars": list(definition.api_key_env_vars),
                "configured": pid in inline_configured or any(
                    bool(local_env.get(key)) for key in definition.api_key_env_vars
                ),
            },
            "base_url": {"policy": "editable", "default": definition.inference_base_url},
            "availability": "unknown",
            "capabilities": {"tools": "unknown", "vision": "unknown", "reasoning": "unknown"},
        })
    model = config.get("model")
    selected = model.get("provider", "") if isinstance(model, dict) else ""
    return {"schema_version": 1, "providers": entries, "selected_provider": selected}
