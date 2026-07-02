"""Validation helpers for setup and onboarding entry points."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse, urlunparse


def normalize_port(value: Any, *, field_name: str = "Port") -> int:
    """Return a TCP port number or raise ``ValueError`` with a user-facing message."""
    raw = "" if value is None else str(value).strip()
    if not raw:
        raise ValueError(f"{field_name} is required.")
    if not raw.isdigit():
        raise ValueError(f"{field_name} must be a whole number from 1 to 65535.")
    port = int(raw, 10)
    if not 1 <= port <= 65535:
        raise ValueError(f"{field_name} must be between 1 and 65535.")
    return port


def normalize_http_base_url(value: Any, *, field_name: str = "Base URL") -> str:
    """Normalize an HTTP(S) base URL, rejecting malformed schemes, ports, and paths."""
    raw = "" if value is None else str(value).strip()
    if not raw:
        raise ValueError(f"{field_name} is required.")
    if any(ch.isspace() for ch in raw):
        raise ValueError(f"{field_name} must not contain spaces.")

    parsed = urlparse(raw)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field_name} must start with http:// or https://.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"{field_name} has an invalid port.") from exc
    if port is not None and not 1 <= port <= 65535:
        raise ValueError(f"{field_name} port must be between 1 and 65535.")
    if parsed.params or parsed.query or parsed.fragment:
        raise ValueError(f"{field_name} must not include query strings or fragments.")

    path = (parsed.path or "").rstrip("/")
    return urlunparse((parsed.scheme.lower(), parsed.netloc, path, "", "", "")).rstrip("/")


def normalize_model_name(value: Any, *, field_name: str = "Model name") -> str:
    """Return a conservative model identifier accepted by setup/onboarding."""
    raw = "" if value is None else str(value).strip()
    if not raw:
        raise ValueError(f"{field_name} is required.")
    if len(raw) > 200:
        raise ValueError(f"{field_name} must be 200 characters or fewer.")
    if any(ch.isspace() or ord(ch) < 32 for ch in raw):
        raise ValueError(f"{field_name} must not contain spaces or control characters.")
    return raw


_SECRET_ENV_NAMES = {
    "API_SERVER_KEY",
    "WEBHOOK_SECRET",
    "BLUEBUBBLES_PASSWORD",
}


def is_secret_env_key(key: Any) -> bool:
    raw = "" if key is None else str(key).strip().upper()
    return raw in _SECRET_ENV_NAMES or raw.endswith(("_API_KEY", "_TOKEN", "_SECRET"))


def is_port_env_key(key: Any) -> bool:
    raw = "" if key is None else str(key).strip().upper()
    return raw.endswith("_PORT")


def normalize_secret(
    value: Any,
    *,
    field_name: str = "Secret",
    min_length: int = 4,
) -> str:
    """Return a trimmed secret that is not empty or an obvious placeholder."""
    raw = "" if value is None else str(value).strip()
    from spark_cli.auth import has_usable_secret

    if not has_usable_secret(raw, min_length=min_length):
        raise ValueError(
            f"{field_name} must be at least {min_length} characters and not a placeholder."
        )
    return raw


def validate_env_assignment(key: Any, value: Any) -> str:
    """Validate a web/CLI env assignment and return the value to persist."""
    raw_value = "" if value is None else str(value).strip()
    if is_port_env_key(key):
        return str(normalize_port(raw_value, field_name=str(key).strip() or "Port"))
    if is_secret_env_key(key):
        label = str(key).strip() or "Secret"
        return normalize_secret(raw_value, field_name=label)
    return raw_value
