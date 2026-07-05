"""MCP preset connectors — one-click remote MCP servers with browser OAuth.

An `McpConnector` wraps a curated remote MCP server preset (name + URL). On
`connect()` it writes the server entry into config.yaml (`mcp_servers`) and,
for OAuth servers, kicks off the browser OAuth flow in a background thread
(reusing `mcp_config._probe_single_server`, which drives
`mcp_oauth.build_oauth_auth` → browser → `SparkTokenStorage`). Status is
derived from the config entry + stored tokens, plus a small meta file so the
web UI can poll a pending/error connect state.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

from tools.connectors.base import Connector, ConnectorState, ConnectorStatus, Transport


@dataclass(frozen=True)
class McpConnectorSpec:
    id: str
    name: str
    description: str
    url: str
    server_name: str = ""          # key under mcp_servers (defaults to id)
    auth: str = "oauth"            # "oauth" | "none"
    skills: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    docs_url: str = ""
    setup_steps: tuple[str, ...] = ()


class McpConnector(Connector):
    """Connector backed by a curated remote MCP server preset."""

    transport = Transport.MCP

    def __init__(self, spec: McpConnectorSpec):
        self.spec = spec
        self.id = spec.id
        self.name = spec.name
        self.description = spec.description
        self.skills = spec.skills
        self.capabilities = spec.capabilities
        self.docs_url = spec.docs_url

    # --- helpers ----------------------------------------------------------

    @property
    def server_name(self) -> str:
        return self.spec.server_name or self.spec.id

    def _server_config(self) -> dict[str, Any]:
        cfg: dict[str, Any] = {"url": self.spec.url}
        if self.spec.auth == "oauth":
            cfg["auth"] = "oauth"
        return cfg

    def _config_entry(self) -> dict[str, Any] | None:
        try:
            from spark_cli.mcp_config import _get_mcp_servers

            return _get_mcp_servers().get(self.server_name)
        except Exception:
            return None

    def _has_tokens(self) -> bool:
        try:
            from tools.mcp_oauth import SparkTokenStorage

            return SparkTokenStorage(self.server_name).has_cached_tokens()
        except Exception:
            return False

    def _extra(self) -> dict[str, Any]:
        meta = self.read_meta()
        return {
            "installed": True,
            "auth_type": "mcp_oauth" if self.spec.auth == "oauth" else "mcp",
            "server_name": self.server_name,
            "server_url": self.spec.url,
            "setup_steps": list(self.spec.setup_steps),
            "connect_state": meta.get("connect_state", ""),
            "connect_error": meta.get("connect_error", ""),
        }

    # --- Connector API ------------------------------------------------------

    def status(self) -> ConnectorStatus:
        try:
            entry = self._config_entry()
            tokens = self._has_tokens()
            meta = self.read_meta()
            pending = meta.get("connect_state") == "pending"
            if entry is not None and (self.spec.auth != "oauth" or tokens):
                return ConnectorStatus(
                    state=ConnectorState.CONNECTED,
                    detail=f"MCP server '{self.server_name}' configured"
                    + (" with OAuth tokens" if tokens else ""),
                    extra=self._extra(),
                )
            if pending:
                started = float(meta.get("connect_started", 0) or 0)
                if time.time() - started < 600:
                    return ConnectorStatus(
                        state=ConnectorState.DISCONNECTED,
                        detail="Waiting for browser authorization…",
                        extra=self._extra(),
                    )
            if meta.get("connect_state") == "error":
                return ConnectorStatus(
                    state=ConnectorState.ERROR,
                    detail=str(meta.get("connect_error") or "Connection failed"),
                    extra=self._extra(),
                )
            return ConnectorStatus(
                state=ConnectorState.DISCONNECTED,
                detail="Connect to authorize this MCP server in your browser.",
                extra=self._extra(),
            )
        except Exception as exc:
            return ConnectorStatus(state=ConnectorState.ERROR, detail=str(exc))

    def connect(self, *, interactive: bool = True, **kwargs: Any) -> ConnectorStatus:
        """Write the server entry and start OAuth in the background."""
        from spark_cli.mcp_config import _save_mcp_server

        _save_mcp_server(self.server_name, self._server_config())

        if self.spec.auth != "oauth" or self._has_tokens():
            self.write_meta({"connect_state": "done"})
            return self.status()

        self.write_meta({"connect_state": "pending", "connect_started": time.time()})

        def _run() -> None:
            try:
                from spark_cli.mcp_config import _probe_single_server

                _probe_single_server(self.server_name, self._server_config(),
                                     connect_timeout=300)
                self.write_meta({"connect_state": "done"})
            except Exception as exc:
                self.write_meta({"connect_state": "error", "connect_error": str(exc)})

        threading.Thread(target=_run, daemon=True,
                         name=f"mcp-connect-{self.server_name}").start()
        return self.status()

    def disconnect(self) -> ConnectorStatus:
        try:
            from tools.mcp_oauth import remove_oauth_tokens

            remove_oauth_tokens(self.server_name)
        except Exception:
            pass
        try:
            from spark_cli.mcp_config import _remove_mcp_server

            _remove_mcp_server(self.server_name)
        except Exception:
            pass
        self.write_meta({})
        return self.status()


MCP_PRESET_CONNECTORS: tuple[McpConnectorSpec, ...] = (
    McpConnectorSpec(
        id="notion-mcp",
        name="Notion MCP",
        description="Official Notion MCP server — search, read, and edit pages and databases with one-click OAuth.",
        url="https://mcp.notion.com/mcp",
        capabilities=("Pages", "Databases", "Search", "Comments"),
        docs_url="https://developers.notion.com/docs/mcp",
        setup_steps=("Click Connect.", "Approve access in the browser window."),
    ),
    McpConnectorSpec(
        id="figma-mcp",
        name="Figma",
        description="Figma remote MCP server — inspect designs, frames, and components straight from your files.",
        url="https://mcp.figma.com/mcp",
        capabilities=("Design context", "Frames", "Components", "Variables"),
        docs_url="https://help.figma.com/hc/en-us/articles/32132100833559",
        setup_steps=("Click Connect.", "Sign in to Figma and approve access."),
    ),
    McpConnectorSpec(
        id="linear",
        name="Linear",
        description="Linear MCP server — create and update issues, projects, and cycles.",
        url="https://mcp.linear.app/mcp",
        capabilities=("Issues", "Projects", "Cycles", "Comments"),
        docs_url="https://linear.app/docs/mcp",
        setup_steps=("Click Connect.", "Approve the Linear OAuth prompt."),
    ),
    McpConnectorSpec(
        id="github-mcp",
        name="GitHub MCP",
        description="GitHub's hosted MCP server — repos, issues, PRs, and code search over MCP.",
        url="https://api.githubcopilot.com/mcp/",
        capabilities=("Repositories", "Issues", "Pull requests", "Code search"),
        docs_url="https://github.com/github/github-mcp-server",
        setup_steps=("Click Connect.", "Authorize with your GitHub account."),
    ),
    McpConnectorSpec(
        id="sentry",
        name="Sentry",
        description="Sentry MCP server — query issues, events, and projects from your Sentry org.",
        url="https://mcp.sentry.dev/mcp",
        capabilities=("Issues", "Events", "Projects", "Releases"),
        docs_url="https://docs.sentry.io/product/sentry-mcp/",
        setup_steps=("Click Connect.", "Approve access in the browser."),
    ),
    McpConnectorSpec(
        id="context7",
        name="Context7",
        description="Up-to-date library documentation for coding — no sign-in required.",
        url="https://mcp.context7.com/mcp",
        auth="none",
        capabilities=("Library docs", "Code examples"),
        docs_url="https://context7.com/",
        setup_steps=("Click Connect — no account needed.",),
    ),
)


def mcp_factories() -> dict[str, Any]:
    return {
        spec.id: (lambda spec=spec: McpConnector(spec))
        for spec in MCP_PRESET_CONNECTORS
    }
