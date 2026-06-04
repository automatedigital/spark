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

# --- gws CLI command surface (verified against gws 0.13.2) -----------------
GWS_BINARY = "gws"
GWS_AUTH_LOGIN = ("auth", "login")
GWS_AUTH_STATUS = ("auth", "status")   # exit 0 when authed; exit 2 = auth error
GWS_AUTH_LOGOUT = ("auth", "logout")   # clears saved creds + token cache

# The gws CLI takes its OAuth *client* identity from these two env vars (used by
# `gws auth login`). We parse them out of the stored client_secret.json.
GWS_CLIENT_ID_ENV = "GOOGLE_WORKSPACE_CLI_CLIENT_ID"
GWS_CLIENT_SECRET_ENV = "GOOGLE_WORKSPACE_CLI_CLIENT_SECRET"
# Override the gws config/token dir → keeps each Spark profile isolated instead
# of sharing ~/.config/gws. Tokens (keyring/file) live under here.
GWS_CONFIG_DIR_ENV = "GOOGLE_WORKSPACE_CLI_CONFIG_DIR"
# Use the file keyring backend inside our config dir so tokens are profile-local
# and don't collide in the OS keyring across profiles.
GWS_KEYRING_BACKEND_ENV = "GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND"

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

    def _gws_config_dir(self) -> Path:
        """Per-profile gws config/token dir (keeps profiles isolated)."""
        d = self.state_dir() / "gws-config"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _auth_env(self) -> dict[str, str]:
        """Env that isolates gws to this profile and supplies our OAuth client.

        - Always pins gws's config/token dir under our state dir (file keyring),
          so tokens never land in the shared ~/.config/gws or OS keyring.
        - If a client_secret.json is stored, parse client_id/secret out of it and
          expose them via the env vars `gws auth login` reads.
        """
        env: dict[str, str] = {
            GWS_CONFIG_DIR_ENV: str(self._gws_config_dir()),
            GWS_KEYRING_BACKEND_ENV: "file",
        }
        cid, csecret = self._read_client_id_secret()
        if cid:
            env[GWS_CLIENT_ID_ENV] = cid
        if csecret:
            env[GWS_CLIENT_SECRET_ENV] = csecret
        return env

    def _read_client_id_secret(self) -> tuple[str | None, str | None]:
        """Extract (client_id, client_secret) from the stored client_secret.json.

        Accepts the standard Google download shape ({"installed": {...}} or
        {"web": {...}}) as well as a flat {client_id, client_secret} object.
        """
        import json
        path = self._client_secret_path()
        if not path.exists():
            return None, None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None, None
        inner = data.get("installed") or data.get("web") or data
        return inner.get("client_id"), inner.get("client_secret")

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

        # IMPORTANT: `gws auth status` exits 0 even when NOT authenticated and
        # reports the real state in JSON (`auth_method`/`storage` == "none").
        # Do NOT rely on the exit code to mean "connected".
        if _status_json_authenticated(res.stdout):
            return ConnectorStatus(
                state=ConnectorState.CONNECTED,
                detail="Connected to Google Workspace.",
                account=_parse_account(res.stdout),
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

        # Request exactly our free-tier scopes (no restricted/CASA scopes).
        login_args = [*GWS_AUTH_LOGIN, "--scopes", ",".join(self.scopes)]
        res = self._run(
            login_args, env=self._auth_env(),
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


def _status_json_authenticated(stdout: str) -> bool:
    """True if `gws auth status` JSON indicates a live credential.

    gws exits 0 regardless of auth state, so we inspect the payload. A logged-out
    state reports auth_method/credential_source/storage == "none". We treat the
    presence of any non-"none" credential source as authenticated. Falls back to
    a loose check if the output isn't the expected JSON.
    """
    import json
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        # Non-JSON output: be conservative — only "authenticated"-looking text.
        return "authenticated" in (stdout or "").lower()
    for key in ("auth_method", "credential_source", "storage"):
        val = data.get(key)
        if val and str(val).lower() != "none":
            return True
    return False


def _parse_account(stdout: str) -> str | None:
    """Best-effort extraction of the signed-in email from `gws auth status`.

    Prefers a JSON `email`/`account`/`user` field; falls back to the first
    email-looking token anywhere in the output.
    """
    import json
    import re
    try:
        data = json.loads(stdout)
        for key in ("email", "account", "user"):
            val = data.get(key)
            if isinstance(val, str) and "@" in val:
                return val
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass
    m = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", stdout or "")
    return m.group(0) if m else None
