"""Google Workspace connector — drives the `gws` CLI.

Auth strategy (see PLAN.md):
  * **No relay server.** The `gws` CLI runs the OAuth loopback + PKCE flow
    locally; the auth code never leaves the user's machine.
  * **Two client modes:**
      - BYO-client: the user supplies their own `client_secret.json`.
      - Shared-client: Spark ships its own (verified) `client_secret.json`.
    Either way we just make the secret available to `gws` and run `gws auth login`.
  * **Free-tier scopes only for v1** (`gmail.send`, `drive.file`, calendar, docs,
    sheets, slides) — no restricted scopes, so no paid CASA assessment.

We deliberately delegate token storage/refresh to `gws` itself rather than
reimplementing OAuth. This module only handles: install detection, placing the
client secret, kicking off `gws auth login`, status probing, and disconnect.

NOTE: a few `gws` subcommand strings below are marked `# verify:` — confirm them
against the real binary once installed; they are centralized here for easy fixup.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.connectors.base import (
    Connector,
    ConnectorState,
    ConnectorStatus,
    Transport,
)

logger = logging.getLogger(__name__)

# --- gws CLI command surface (centralized for easy correction) -------------
GWS_BINARY = "gws"
GWS_AUTH_LOGIN = ("auth", "login")
GWS_AUTH_STATUS = ("auth", "status")   # verify: exit 0 + email on stdout when logged in
GWS_AUTH_LOGOUT = ("auth", "logout")   # verify: revokes/forgets local token

# Env var the gws CLI reads to locate an OAuth client secret / credentials.
# verify: confirm exact name against the binary (docs mention
# GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE for *exported* creds).
GWS_CLIENT_SECRET_ENV = "GOOGLE_WORKSPACE_CLI_CLIENT_SECRET_FILE"

# Free-tier ("sensitive", no CASA) scopes for v1.
FREE_TIER_SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/presentations",
)

GWS_SKILLS: tuple[str, ...] = (
    "gws-gmail", "gws-gmail-send", "gws-calendar", "gws-calendar-insert",
    "gws-drive", "gws-drive-upload", "gws-docs", "gws-sheets", "gws-slides",
)


# Result of running a gws subcommand — keeps the connector logic testable by
# letting tests inject a fake runner.
@dataclass
class RunResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0


Runner = Callable[..., RunResult]


def _default_runner(args: list[str], *, env: dict[str, str] | None = None,
                    interactive: bool = False, timeout: float | None = None) -> RunResult:
    """Run `gws <args>` as a subprocess.

    For interactive auth (`gws auth login` opens a browser) we let the child
    inherit stdio so the user sees prompts and the loopback flow can complete.
    """
    cmd = [GWS_BINARY, *args]
    full_env = {**os.environ, **(env or {})}
    try:
        if interactive:
            cp = subprocess.run(cmd, env=full_env, timeout=timeout)
            return RunResult(cp.returncode)
        cp = subprocess.run(
            cmd, env=full_env, capture_output=True, text=True, timeout=timeout
        )
        return RunResult(cp.returncode, cp.stdout or "", cp.stderr or "")
    except FileNotFoundError:
        return RunResult(127, "", f"{GWS_BINARY} not found")
    except subprocess.TimeoutExpired:
        return RunResult(124, "", "timed out")


class GoogleWorkspaceConnector(Connector):
    id = "google"
    name = "Google Workspace"
    description = (
        "Send email, manage your calendar, and create Docs/Sheets/Slides and "
        "Drive files. Free-tier scopes only — no full-inbox or full-Drive read."
    )
    transport = Transport.CLI
    scopes = FREE_TIER_SCOPES
    skills = GWS_SKILLS
    docs_url = "https://github.com/googleworkspace/cli"

    def __init__(self, runner: Runner | None = None) -> None:
        self._run: Runner = runner or _default_runner

    # --- install detection ----------------------------------------------

    def is_installed(self) -> bool:
        """True if the `gws` binary is on PATH."""
        return shutil.which(GWS_BINARY) is not None

    # --- client secret placement ----------------------------------------

    def _client_secret_path(self) -> Path:
        """Where we keep the active OAuth client secret for this profile."""
        return self.state_dir() / "client_secret.json"

    def has_client_secret(self) -> bool:
        return self._client_secret_path().exists()

    def install_client_secret(self, secret_json: str | dict[str, Any]) -> None:
        """Store an OAuth client secret (BYO or shipped/shared) for this profile."""
        import json
        if isinstance(secret_json, dict):
            secret_json = json.dumps(secret_json, indent=2)
        path = self._client_secret_path()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(secret_json, encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(path)
        logger.info("Stored Google OAuth client secret at %s", path)

    def _auth_env(self) -> dict[str, str]:
        """Env pointing gws at our stored client secret, if present."""
        env: dict[str, str] = {}
        if self.has_client_secret():
            env[GWS_CLIENT_SECRET_ENV] = str(self._client_secret_path())
        return env

    # --- status ----------------------------------------------------------

    def status(self) -> ConnectorStatus:
        if not self.is_installed():
            return ConnectorStatus(
                state=ConnectorState.NOT_INSTALLED,
                detail="The `gws` CLI is not installed.",
            )
        try:
            res = self._run(list(GWS_AUTH_STATUS), env=self._auth_env(), timeout=20)
        except Exception as exc:  # never raise out of status()
            logger.warning("gws auth status failed: %s", exc)
            return ConnectorStatus(state=ConnectorState.ERROR, detail=str(exc))

        if res.ok:
            account = _parse_account(res.stdout)
            return ConnectorStatus(
                state=ConnectorState.CONNECTED,
                detail="Connected to Google Workspace.",
                account=account,
                scopes=list(self.scopes),
            )
        return ConnectorStatus(
            state=ConnectorState.DISCONNECTED,
            detail="Not signed in. Click Connect to authorize.",
        )

    # --- connect ---------------------------------------------------------

    def connect(self, *, interactive: bool = True, **kwargs: Any) -> ConnectorStatus:
        if not self.is_installed():
            return ConnectorStatus(
                state=ConnectorState.NOT_INSTALLED,
                detail="Install the `gws` CLI first (see docs_url).",
            )
        # Optional inline client secret (BYO flow from the UI).
        secret = kwargs.get("client_secret")
        if secret:
            self.install_client_secret(secret)

        res = self._run(
            list(GWS_AUTH_LOGIN), env=self._auth_env(),
            interactive=interactive, timeout=kwargs.get("timeout", 300),
        )
        if not res.ok:
            return ConnectorStatus(
                state=ConnectorState.DISCONNECTED,
                detail=f"Login did not complete (exit {res.returncode}). "
                       f"{res.stderr.strip()}".strip(),
            )
        return self.status()

    # --- disconnect ------------------------------------------------------

    def disconnect(self) -> ConnectorStatus:
        if self.is_installed():
            self._run(list(GWS_AUTH_LOGOUT), env=self._auth_env(), timeout=30)
        # Forget the local client secret too.
        self._client_secret_path().unlink(missing_ok=True)
        return ConnectorStatus(
            state=ConnectorState.DISCONNECTED,
            detail="Disconnected from Google Workspace.",
        )


def _parse_account(stdout: str) -> str | None:
    """Best-effort extraction of an email address from `gws auth status` output."""
    import re
    m = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", stdout or "")
    return m.group(0) if m else None
