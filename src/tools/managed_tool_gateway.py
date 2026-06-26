"""Generic managed-tool gateway helpers.

Managed hosted gateways were tied to the removed provider flow and are disabled.
The URL helpers remain for diagnostics/tests, but runtime resolution
intentionally returns ``None``.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_DEFAULT_TOOL_GATEWAY_DOMAIN = "automatedigital.ai"
_DEFAULT_TOOL_GATEWAY_SCHEME = "https"


@dataclass(frozen=True)
class ManagedToolGatewayConfig:
    vendor: str
    gateway_origin: str
    access_token: str
    managed_mode: bool


def get_tool_gateway_scheme() -> str:
    """Return configured shared gateway URL scheme."""
    scheme = os.getenv("TOOL_GATEWAY_SCHEME", "").strip().lower()
    if not scheme:
        return _DEFAULT_TOOL_GATEWAY_SCHEME

    if scheme in {"http", "https"}:
        return scheme

    raise ValueError("TOOL_GATEWAY_SCHEME must be 'http' or 'https'")


def build_vendor_gateway_url(vendor: str) -> str:
    """Return the gateway origin for a specific vendor."""
    vendor_key = f"{vendor.upper().replace('-', '_')}_GATEWAY_URL"
    explicit_vendor_url = os.getenv(vendor_key, "").strip().rstrip("/")
    if explicit_vendor_url:
        return explicit_vendor_url

    shared_scheme = get_tool_gateway_scheme()
    shared_domain = os.getenv("TOOL_GATEWAY_DOMAIN", "").strip().strip("/")
    if shared_domain:
        return f"{shared_scheme}://{vendor}-gateway.{shared_domain}"

    return f"{shared_scheme}://{vendor}-gateway.{_DEFAULT_TOOL_GATEWAY_DOMAIN}"


def resolve_managed_tool_gateway(
    vendor: str,
    gateway_builder: Callable[[str], str] | None = None,
    token_reader: Callable[[], str | None] | None = None,
) -> ManagedToolGatewayConfig | None:
    """Managed tool gateways are disabled after provider cleanup."""
    return None


def is_managed_tool_gateway_ready(
    vendor: str,
    gateway_builder: Callable[[str], str] | None = None,
    token_reader: Callable[[], str | None] | None = None,
) -> bool:
    """Return False while hosted managed gateways are disabled."""
    return False


def read_managed_gateway_access_token() -> str | None:
    """Managed gateway token resolution is disabled."""
    return None
