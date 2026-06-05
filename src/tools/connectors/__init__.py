"""Connectors — link Spark to external platforms (Google Workspace, GitHub, ...).

A *connector* is a data-driven description of an external platform plus the glue
needed to authenticate with it and report status. Connectors prefer **CLI**
transport (most context-efficient, easiest setup), falling back to MCP or skills.

Public surface:
    from tools.connectors import (
        Connector, ConnectorState, ConnectorStatus,
        get_connector, list_connectors,
    )

The registry (`registry.py`) is the single source of truth for which connectors
exist. Each concrete connector (e.g. `google.py`) subclasses `Connector`.

State for each connector lives under ``SPARK_HOME/connectors/<id>/`` via
``get_spark_home()`` — never hardcode ``~/.spark``.
"""

from tools.connectors.base import (
    Connector,
    ConnectorState,
    ConnectorStatus,
    Transport,
)
from tools.connectors.registry import (
    CONNECTOR_REGISTRY,
    get_connector,
    list_connectors,
)

__all__ = [
    "Connector",
    "ConnectorState",
    "ConnectorStatus",
    "Transport",
    "CONNECTOR_REGISTRY",
    "get_connector",
    "list_connectors",
]
