"""Agent tool: `connectors` — list, inspect, and manage platform connectors.

Thin agent-facing wrapper over `tools.connectors`. Lets the agent answer
"what can I connect to?" / "am I connected to Google?" and kick off or tear down
a connection.

Connecting is an interactive browser flow (delegated to the platform CLI, e.g.
`gws auth login`). We only run it inline when a real TTY is present (the TUI);
in headless/gateway contexts we return guidance pointing at the Connectors tab
or the `/connect` slash command rather than hanging the agent loop on a browser.
"""

from __future__ import annotations

import json
import logging
import sys

from tools.connectors import get_connector, list_connectors
from tools.registry import registry, tool_error

logger = logging.getLogger(__name__)


CONNECTORS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "connectors",
        "description": (
            "List and manage connections to external platforms (e.g. Google "
            "Workspace, GitHub, Notion, HubSpot, Asana, Airtable, Tinker, Slack, IMAP "
            "mail) so you can act on the user's behalf. Actions: 'list' "
            "(all connectors + their status), 'status' (one connector), "
            "'connect' (start sign-in — interactive browser flow), 'disconnect' "
            "(revoke local credentials). Prefer 'list'/'status' to check before "
            "using a platform's skills/tools."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "status", "connect", "disconnect"],
                    "description": "Operation to perform.",
                },
                "connector": {
                    "type": "string",
                    "description": (
                        "Connector id (e.g. 'google', 'github', 'notion', "
                        "'hubspot', 'asana', 'airtable', 'tinker', 'slack', 'imap-mail'). "
                        "Required for status/connect/disconnect; ignored for 'list'."
                    ),
                },
            },
            "required": ["action"],
        },
    },
}


def _is_interactive() -> bool:
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def _connector_or_error(connector_id: str | None):
    if not connector_id:
        return None, tool_error("A 'connector' id is required for this action.")
    c = get_connector(connector_id)
    if c is None:
        known = ", ".join(c.id for c in list_connectors()) or "(none)"
        return None, tool_error(f"Unknown connector '{connector_id}'. Known: {known}")
    return c, None


def connectors_tool(action: str, connector: str | None = None) -> str:
    action = (action or "").strip().lower()

    if action == "list":
        out = []
        for c in list_connectors():
            st = c.status()
            out.append({**c.describe(), "status": st.to_dict()})
        return json.dumps({"connectors": out}, indent=2)

    if action == "status":
        c, err = _connector_or_error(connector)
        if err:
            return err
        return json.dumps({"connector": c.id, "status": c.status().to_dict()}, indent=2)

    if action == "disconnect":
        c, err = _connector_or_error(connector)
        if err:
            return err
        return json.dumps({"connector": c.id, "status": c.disconnect().to_dict()}, indent=2)

    if action == "connect":
        c, err = _connector_or_error(connector)
        if err:
            return err
        st = c.status()
        if st.connected:
            return json.dumps(
                {"connector": c.id, "already_connected": True, "status": st.to_dict()},
                indent=2,
            )
        if not _is_interactive():
            # Headless/gateway: don't block on a browser. Tell the user how.
            return json.dumps({
                "connector": c.id,
                "started": False,
                "message": (
                    f"Connecting to {c.name} needs an interactive browser sign-in. "
                    f"Open the Connectors tab in the web UI, or run `/connect {c.id}` "
                    f"in the terminal, to complete it."
                ),
                "status": st.to_dict(),
            }, indent=2)
        result = c.connect(interactive=True)
        return json.dumps({"connector": c.id, "status": result.to_dict()}, indent=2)

    return tool_error(f"Unknown action '{action}'. Use list, status, connect, or disconnect.")


registry.register(
    name="connectors",
    toolset="connectors",
    schema=CONNECTORS_SCHEMA,
    handler=lambda args, **kw: connectors_tool(
        action=args.get("action", ""),
        connector=args.get("connector"),
    ),
    emoji="🔌",
    description="List and manage connections to external platforms.",
)
