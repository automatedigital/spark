"""Connector registry — single source of truth for available connectors.

Mirrors the data-driven pattern used elsewhere in the codebase (skins, command
registry): adding a connector means appending one factory here. Keep this module
import-light; concrete connectors may pull heavier deps lazily inside methods.
"""

from __future__ import annotations

from collections.abc import Callable

from tools.connectors.base import Connector
from tools.connectors.google import GoogleWorkspaceConnector

# Factories (not instances) so each lookup gets a fresh object and tests can
# construct connectors with injected runners without mutating shared state.
_FACTORIES: dict[str, Callable[[], Connector]] = {
    "google": GoogleWorkspaceConnector,
}

# Ordered list of connector ids for stable UI display.
CONNECTOR_REGISTRY: list[str] = list(_FACTORIES.keys())


def get_connector(connector_id: str) -> Connector | None:
    """Return a fresh connector instance for `connector_id`, or None."""
    factory = _FACTORIES.get(connector_id)
    return factory() if factory else None


def list_connectors() -> list[Connector]:
    """Return a fresh instance of every registered connector."""
    return [factory() for factory in _FACTORIES.values()]
