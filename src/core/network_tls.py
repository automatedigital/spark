"""TLS verification helpers for outbound provider HTTP clients."""

from __future__ import annotations

import os
import ssl
from pathlib import Path
from typing import Any

import yaml

from core.spark_constants import get_spark_home


class CABundleError(ValueError):
    """Raised when the configured custom CA bundle cannot be used."""


def _configured_ca_bundle_value(config: dict[str, Any] | None = None) -> str:
    if config is None:
        config_path = get_spark_home() / "config.yaml"
        try:
            config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except FileNotFoundError:
            return ""
        except Exception as exc:
            raise CABundleError(
                f"Could not read Spark config for network.ca_bundle: {exc}"
            ) from exc

    network = config.get("network", {}) if isinstance(config, dict) else {}
    if not isinstance(network, dict):
        return ""
    value = network.get("ca_bundle", "")
    return value.strip() if isinstance(value, str) else ""


def resolve_ca_bundle_path(
    config: dict[str, Any] | None = None,
    *,
    require_exists: bool = True,
) -> Path | None:
    """Return the configured CA bundle path, expanding env vars and ``~``."""

    raw_value = _configured_ca_bundle_value(config)
    if not raw_value:
        return None

    expanded = os.path.expanduser(os.path.expandvars(raw_value))
    path = Path(expanded)
    if not require_exists:
        return path

    if not path.exists():
        raise CABundleError(f"network.ca_bundle path does not exist: {path}")
    if not path.is_file():
        raise CABundleError(f"network.ca_bundle is not a file: {path}")
    try:
        with path.open("rb") as handle:
            handle.read(1)
    except OSError as exc:
        raise CABundleError(f"network.ca_bundle is not readable: {path}") from exc
    return path


def validate_ca_bundle(config: dict[str, Any] | None = None) -> Path | None:
    """Validate that the configured CA bundle can be loaded by OpenSSL."""

    path = resolve_ca_bundle_path(config)
    if path is None:
        return None
    try:
        ssl.create_default_context(cafile=str(path))
    except Exception as exc:
        raise CABundleError(f"network.ca_bundle could not be loaded by OpenSSL: {path}") from exc
    return path


def httpx_verify_value(config: dict[str, Any] | None = None) -> str | None:
    """Return a value suitable for httpx ``verify=`` or None for defaults."""

    path = resolve_ca_bundle_path(config)
    return str(path) if path is not None else None


def requests_verify_value(config: dict[str, Any] | None = None) -> str | None:
    """Return a value suitable for requests ``verify=`` or None for defaults."""

    return httpx_verify_value(config)


def httpx_client_kwargs(*, async_mode: bool = False) -> dict[str, Any]:
    """Return OpenAI/Anthropic SDK kwargs for custom httpx TLS verification."""

    verify = httpx_verify_value()
    if verify is None:
        return {}
    import httpx

    client_cls = httpx.AsyncClient if async_mode else httpx.Client
    return {"http_client": client_cls(verify=verify)}


def urllib_request_kwargs(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return ``urllib.request.urlopen`` kwargs for configured TLS verification."""

    path = resolve_ca_bundle_path(config)
    if path is None:
        return {}
    return {"context": ssl.create_default_context(cafile=str(path))}
