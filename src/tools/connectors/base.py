"""Connector base types — the abstraction shared by all platforms.

A `Connector` is intentionally thin. It knows:
  - identity (id / name / description)
  - what transport + auth it uses, and which scopes/skills it unlocks
  - how to probe its own status (installed? connected?)
  - how to start auth and how to disconnect

Concrete connectors (e.g. `GoogleWorkspaceConnector`) implement the abstract
methods. Everything here is import-light so the registry can be loaded without
pulling in heavy/optional deps.
"""

from __future__ import annotations

import enum
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class Transport(enum.StrEnum):
    """How the agent actually talks to the platform once connected."""

    CLI = "cli"      # shell out to a platform CLI (preferred — context-efficient)
    MCP = "mcp"      # remote/local MCP server
    SKILL = "skill"  # the connector merely enables a set of skills


class ConnectorState(enum.StrEnum):
    """Coarse lifecycle state, derived by `Connector.status()`."""

    NOT_INSTALLED = "not_installed"  # required CLI/dep missing
    DISCONNECTED = "disconnected"    # installed but not authenticated
    CONNECTED = "connected"          # authenticated and ready
    ERROR = "error"                  # probe failed unexpectedly


@dataclass
class ConnectorStatus:
    """Result of `Connector.status()` — safe to serialize to the web UI."""

    state: ConnectorState
    detail: str = ""                       # human-readable one-liner
    account: str | None = None             # e.g. connected email, if known
    scopes: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def connected(self) -> bool:
        return self.state is ConnectorState.CONNECTED

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "detail": self.detail,
            "account": self.account,
            "scopes": list(self.scopes),
            "extra": dict(self.extra),
        }


class Connector(ABC):
    """Abstract base for a single external-platform connector.

    Subclasses set the class-level metadata attributes and implement
    `status()`, `connect()`, and `disconnect()`.
    """

    # --- identity / metadata (override in subclass) ----------------------
    id: str = ""
    name: str = ""
    description: str = ""
    transport: Transport = Transport.CLI
    # OAuth scopes requested (informational — shown in UI). Empty for non-OAuth.
    scopes: tuple[str, ...] = ()
    # Skills surfaced to the agent once connected.
    skills: tuple[str, ...] = ()
    # User-facing capabilities unlocked by this connector.
    capabilities: tuple[str, ...] = ()
    # Optional docs URL for the "learn more" link in the UI.
    docs_url: str = ""

    # --- per-connector state directory -----------------------------------

    def state_dir(self) -> Path:
        """Directory for this connector's local state (tokens, metadata).

        Layout: ``SPARK_HOME/connectors/<id>/``. Uses get_spark_home() so each
        profile is isolated. Never hardcode ``~/.spark``.
        """
        try:
            from core.spark_constants import get_spark_home
            base = Path(get_spark_home())
        except ImportError:  # pragma: no cover - fallback for early import
            base = Path(os.environ.get("SPARK_HOME", str(Path.home() / ".spark")))
        d = base / "connectors" / self.id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _meta_path(self) -> Path:
        return self.state_dir() / "meta.json"

    def read_meta(self) -> dict[str, Any]:
        p = self._meta_path()
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def write_meta(self, data: dict[str, Any]) -> None:
        p = self._meta_path()
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(p)

    # --- abstract behaviour ----------------------------------------------

    @abstractmethod
    def status(self) -> ConnectorStatus:
        """Probe and return the current connection status. Must not raise."""

    @abstractmethod
    def connect(self, *, interactive: bool = True, **kwargs: Any) -> ConnectorStatus:
        """Start/complete authentication. Returns the resulting status."""

    @abstractmethod
    def disconnect(self) -> ConnectorStatus:
        """Revoke/forget local credentials. Returns the resulting status."""

    # --- serialization for the web UI ------------------------------------

    def describe(self) -> dict[str, Any]:
        """Static metadata for listing in the Connectors tab."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "transport": self.transport.value,
            "scopes": list(self.scopes),
            "skills": list(self.skills),
            "capabilities": list(self.capabilities),
            "docs_url": self.docs_url,
        }
