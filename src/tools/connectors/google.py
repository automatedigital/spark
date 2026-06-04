"""Google Workspace connector — adapter over the unified OAuth engine.

Architecture (see PLAN.md):
  * **Connect** uses the web-OAuth flow in ``spark_cli/google_connector.py`` +
    ``spark_cli/connectors_routes.py``. A server-side callback makes it work
    across all deployments: VPS web UI, local web UI, and the desktop app.
  * **Bridge:** that same connection writes a gws "authorized_user" credentials
    file, so the agent drives Google through the **gws CLI** and ``gws-*`` skills
    (which self-refresh from the bridge file). See ``google_connector.gws_env()``.
  * **Free-tier scopes only** (gmail.send, drive.file, calendar, docs, sheets,
    slides) — no restricted scopes, so no paid CASA. NOTE: reading email needs
    the restricted gmail.readonly scope, so the free tier is *send-only* for Gmail.

This class is a thin façade: it does not own OAuth or tokens — it reports status,
points users at the web connect flow, and tears the connection down.
"""

from __future__ import annotations

import logging
from typing import Any

from tools.connectors.base import (
    Connector,
    ConnectorState,
    ConnectorStatus,
    Transport,
)

logger = logging.getLogger(__name__)

GWS_SKILLS: tuple[str, ...] = (
    "gws-gmail", "gws-gmail-send", "gws-gmail-triage", "gws-calendar",
    "gws-calendar-insert", "gws-drive", "gws-drive-upload", "gws-docs",
    "gws-sheets", "gws-slides",
)


def _active_scopes() -> tuple[str, ...]:
    """The scopes actually requested at auth (config-overridable)."""
    try:
        from spark_cli.google_connector import get_scopes
        return tuple(get_scopes())
    except Exception:
        return ()


class GoogleWorkspaceConnector(Connector):
    id = "google"
    name = "Google Workspace"
    description = (
        "Read & send email, manage your calendar, and create/edit Docs, Sheets, "
        "Slides, and Drive files via the gws CLI."
    )
    transport = Transport.CLI
    skills = GWS_SKILLS
    docs_url = "https://github.com/googleworkspace/cli"

    @property
    def scopes(self) -> tuple[str, ...]:  # type: ignore[override]
        return _active_scopes()

    # --- status ----------------------------------------------------------

    def status(self) -> ConnectorStatus:
        try:
            from spark_cli import google_connector as gc
            token = gc.load_token()
            configured = gc.is_configured()
            bridge = bool(gc.gws_env()) if token else False
        except Exception as exc:  # never raise out of status()
            return ConnectorStatus(state=ConnectorState.ERROR, detail=str(exc))

        if not token:
            detail = (
                "Not connected. Open the Connectors tab to sign in."
                if configured
                else "Not configured. Add a Google OAuth client to config.yaml "
                     "(connectors.google) or set GOOGLE_OAUTH_CLIENT_ID/SECRET."
            )
            return ConnectorStatus(state=ConnectorState.DISCONNECTED, detail=detail)

        return ConnectorStatus(
            state=ConnectorState.CONNECTED,
            detail="Connected to Google Workspace (gws CLI bridge active).",
            account=token.get("email"),
            scopes=list(self.scopes),
            extra={"bridge": bridge},
        )

    # --- connect ---------------------------------------------------------

    def connect(self, *, interactive: bool = True, **kwargs: Any) -> ConnectorStatus:
        """Connecting is a browser OAuth flow served by the web UI/routes.

        We don't run it inline here — the same server-side callback flow powers
        VPS, local-web, and desktop. Report current status + where to go.
        """
        st = self.status()
        if st.connected:
            return st
        st.extra["how_to_connect"] = (
            "Open the Connectors tab in the Spark web UI and click Connect, "
            "which works for desktop, local web, and remote/VPS installs."
        )
        return st

    # --- disconnect ------------------------------------------------------

    def disconnect(self) -> ConnectorStatus:
        try:
            from spark_cli import google_connector as gc
            token = gc.load_token()
            if token and token.get("access_token"):
                try:
                    import httpx
                    httpx.post(gc.GOOGLE_REVOKE_URL,
                               params={"token": token["access_token"]}, timeout=5)
                except Exception:
                    pass
            gc.clear_token()  # also removes the gws bridge credentials file
        except Exception as exc:
            return ConnectorStatus(state=ConnectorState.ERROR, detail=str(exc))
        return ConnectorStatus(
            state=ConnectorState.DISCONNECTED,
            detail="Disconnected from Google Workspace.",
        )

    # --- gws bridge env --------------------------------------------------

    def gws_env(self) -> dict[str, str]:
        """Env that points the gws CLI at this connection's bridge credentials."""
        try:
            from spark_cli import google_connector as gc
            return gc.gws_env()
        except Exception:
            return {}
