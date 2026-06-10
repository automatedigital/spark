"""Lightweight connector catalog entries for CLI, skill, and env-token tools."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.connectors.base import Connector, ConnectorState, ConnectorStatus, Transport


@dataclass(frozen=True)
class CatalogConnectorSpec:
    id: str
    name: str
    description: str
    transport: Transport
    env_vars: tuple[str, ...] = ()
    cli: str | None = None
    cli_auth_check: tuple[str, ...] = ()
    config_paths: tuple[str, ...] = ()
    auth_type: str = "api_key"
    auth_url: str = ""
    api_key_url: str = ""
    primary_env_var: str = ""
    scopes: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    docs_url: str = ""
    setup_steps: tuple[str, ...] = ()


class CatalogConnector(Connector):
    """Connector backed by existing CLIs, env vars, or bundled skills."""

    spec: CatalogConnectorSpec

    def __init__(self, spec: CatalogConnectorSpec):
        self.spec = spec
        self.id = spec.id
        self.name = spec.name
        self.description = spec.description
        self.transport = spec.transport
        self.scopes = spec.scopes
        self.skills = spec.skills
        self.capabilities = spec.capabilities
        self.docs_url = spec.docs_url

    def status(self) -> ConnectorStatus:
        try:
            oauth_connected, oauth_account = self._oauth_status()
            if oauth_connected:
                return ConnectorStatus(
                    state=ConnectorState.CONNECTED,
                    detail=f"Connected as {oauth_account}" if oauth_account else "Connected with OAuth",
                    account=oauth_account,
                    scopes=list(self.scopes),
                    extra=self._extra(installed=True),
                )
            installed = self._installed()
            if not installed:
                return ConnectorStatus(
                    state=ConnectorState.NOT_INSTALLED,
                    detail=self._not_installed_detail(),
                    extra=self._extra(installed=False),
                )
            account, validation_error = self._account()
            if validation_error:
                return ConnectorStatus(
                    state=ConnectorState.ERROR,
                    detail=validation_error,
                    scopes=list(self.scopes),
                    extra=self._extra(installed=True),
                )
            if account:
                return ConnectorStatus(
                    state=ConnectorState.CONNECTED,
                    detail=f"Connected as {account}",
                    account=account,
                    scopes=list(self.scopes),
                    extra=self._extra(installed=True),
                )
            return ConnectorStatus(
                state=ConnectorState.DISCONNECTED,
                detail=self._disconnected_detail(),
                scopes=list(self.scopes),
                extra=self._extra(installed=True),
            )
        except Exception as exc:
            return ConnectorStatus(
                state=ConnectorState.ERROR,
                detail=str(exc),
                extra=self._extra(installed=self._installed()),
            )

    def connect(self, *, interactive: bool = True, **kwargs: Any) -> ConnectorStatus:
        return self.status()

    def disconnect(self) -> ConnectorStatus:
        return ConnectorStatus(
            state=ConnectorState.DISCONNECTED,
            detail="Remove the configured credentials or sign out of the CLI to disconnect.",
            extra=self._extra(installed=self._installed()),
        )

    def _installed(self) -> bool:
        if self.spec.cli and not _command_path(self.spec.cli):
            return self._has_env_credentials() or self._has_config_file()
        return True

    def _account(self) -> tuple[str | None, str | None]:
        if self.spec.cli_auth_check:
            account = _run_auth_check(self.spec.cli_auth_check)
            if account:
                return account, None
        if self.spec.auth_type == "multi_env":
            values = {name: _env_value(name) for name in self.spec.env_vars}
            if all(values.values()):
                return values.get(self.spec.primary_env_var or self.spec.env_vars[0]) or self.spec.env_vars[0], None
            return None, None
        for name in self.spec.env_vars:
            value = _env_value(name)
            if value:
                return _validate_env_token(self.id, name, value)
        for path in self.spec.config_paths:
            expanded = Path(path).expanduser()
            if expanded.exists():
                return str(expanded), None
        return None, None

    def _oauth_status(self) -> tuple[bool, str | None]:
        if self.spec.auth_type not in {"oauth", "oauth_or_api_key"}:
            return False, None
        try:
            from spark_cli.oauth_connectors import token_status

            return token_status(self.id)
        except Exception:
            return False, None

    def _has_env_credentials(self) -> bool:
        if self.spec.auth_type == "multi_env":
            return all(_env_value(name) for name in self.spec.env_vars)
        return any(_env_value(name) for name in self.spec.env_vars)

    def _has_config_file(self) -> bool:
        return any(Path(path).expanduser().exists() for path in self.spec.config_paths)

    def _extra(self, *, installed: bool) -> dict[str, Any]:
        sync = _connector_sync_status(self.id)
        return {
            "installed": installed,
            "auth_type": self.spec.auth_type,
            "auth_url": self.spec.auth_url,
            "api_key_url": self.spec.api_key_url,
            "primary_env_var": self.spec.primary_env_var or (self.spec.env_vars[0] if self.spec.env_vars else ""),
            "oauth_configured": _oauth_configured(self.id),
            "env_vars": list(self.spec.env_vars),
            "cli": self.spec.cli,
            "cli_sync": sync,
            "config_paths": list(self.spec.config_paths),
            "setup_steps": list(self.spec.setup_steps),
        }

    def _not_installed_detail(self) -> str:
        if self.spec.cli:
            return f"Install and authenticate the `{self.spec.cli}` CLI to use this connector."
        return "Configure credentials to use this connector."

    def _disconnected_detail(self) -> str:
        if self.spec.env_vars:
            return f"Set one of: {', '.join(self.spec.env_vars)}."
        if self.spec.cli:
            return f"Run `{self.spec.cli}` authentication, then refresh this page."
        return "Configure credentials, then refresh this page."


def _run_auth_check(command: tuple[str, ...]) -> str | None:
    executable = _command_path(command[0])
    if not executable:
        return None
    try:
        proc = subprocess.run(
            (executable, *command[1:]),
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    text = (proc.stdout or proc.stderr or "").strip()
    if not text:
        return command[0]
    first = text.splitlines()[0].strip()
    return first[:120] if first else command[0]


def _env_value(name: str) -> str:
    if os.getenv(name):
        return os.environ[name]
    try:
        from spark_cli.config import get_env_value

        return get_env_value(name) or ""
    except Exception:
        return ""


def _validate_env_token(connector_id: str, name: str, value: str) -> tuple[str | None, str | None]:
    validator = _VALIDATORS.get(connector_id)
    if not validator:
        return name, None
    try:
        account = validator(value)
        if account:
            return account, None
        return None, f"{name} did not validate. Check the token and try again."
    except Exception as exc:
        return None, f"{name} validation failed: {exc}"


def _command_path(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for path in (
        Path("/opt/homebrew/bin") / name,
        Path("/usr/local/bin") / name,
        Path.home() / ".local" / "bin" / name,
    ):
        try:
            if path.is_file() and os.access(path, os.X_OK):
                return str(path)
        except OSError:
            continue
    return None


def _oauth_configured(connector_id: str) -> bool:
    try:
        from spark_cli.oauth_connectors import is_configured

        return is_configured(connector_id)
    except Exception:
        return False


def _connector_sync_status(connector_id: str) -> dict:
    try:
        from spark_cli.oauth_connectors import sync_status

        return sync_status(connector_id)
    except Exception:
        return {}


def _http_get_json(url: str, token: str, *, headers: dict[str, str] | None = None) -> dict:
    import httpx

    merged = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if headers:
        merged.update(headers)
    resp = httpx.get(url, headers=merged, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _validate_github(token: str) -> str:
    data = _http_get_json("https://api.github.com/user", token)
    return str(data.get("login") or data.get("email") or "GitHub")


def _validate_notion(token: str) -> str:
    data = _http_get_json(
        "https://api.notion.com/v1/users/me",
        token,
        headers={"Notion-Version": "2022-06-28"},
    )
    return str(data.get("name") or data.get("type") or "Notion")


def _validate_hubspot(token: str) -> str:
    data = _http_get_json(f"https://api.hubapi.com/oauth/v1/access-tokens/{token}", token)
    return str(data.get("hub_domain") or data.get("user") or "HubSpot")


def _validate_asana(token: str) -> str:
    data = _http_get_json("https://app.asana.com/api/1.0/users/me", token)
    user = data.get("data") or data
    return str(user.get("email") or user.get("name") or "Asana")


def _validate_airtable(token: str) -> str:
    data = _http_get_json("https://api.airtable.com/v0/meta/whoami", token)
    return str(data.get("email") or data.get("id") or "Airtable")


def _validate_slack(token: str) -> str:
    import httpx

    resp = httpx.post(
        "https://slack.com/api/auth.test",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise ValueError(str(data.get("error") or "Slack token rejected"))
    return str(data.get("team") or data.get("user") or "Slack")


_VALIDATORS: dict[str, Callable[[str], str]] = {
    "github": _validate_github,
    "notion": _validate_notion,
    "hubspot": _validate_hubspot,
    "asana": _validate_asana,
    "airtable": _validate_airtable,
    "slack": _validate_slack,
}


CATALOG_CONNECTORS: tuple[CatalogConnectorSpec, ...] = (
    CatalogConnectorSpec(
        id="github",
        name="GitHub",
        description="Manage repositories, issues, pull requests, releases, and code-review workflows.",
        transport=Transport.CLI,
        cli="gh",
        cli_auth_check=("gh", "auth", "status"),
        env_vars=("GITHUB_TOKEN", "GH_TOKEN"),
        auth_type="oauth_or_api_key",
        api_key_url="https://github.com/settings/personal-access-tokens/new",
        primary_env_var="GITHUB_TOKEN",
        skills=(
            "github-auth",
            "github-repo-management",
            "github-pr-workflow",
            "github-code-review",
            "github-issues",
        ),
        capabilities=("Repositories", "Issues", "Pull requests", "Releases", "Code review"),
        docs_url="https://cli.github.com/",
        setup_steps=("Install GitHub CLI.", "Run `gh auth login` or set GITHUB_TOKEN/GH_TOKEN."),
    ),
    CatalogConnectorSpec(
        id="notion",
        name="Notion",
        description="Search, read, and update Notion pages and databases through the bundled Notion skill.",
        transport=Transport.SKILL,
        env_vars=("NOTION_API_KEY",),
        auth_type="api_key",
        api_key_url="https://www.notion.so/profile/integrations",
        primary_env_var="NOTION_API_KEY",
        skills=("notion",),
        capabilities=("Pages", "Databases", "Search", "Content updates"),
        docs_url="https://developers.notion.com/docs/create-a-notion-integration",
        setup_steps=(
            "Create a Notion integration.",
            "Copy the internal integration secret.",
            "Set NOTION_API_KEY and share pages/databases with the integration.",
        ),
    ),
    CatalogConnectorSpec(
        id="hubspot",
        name="HubSpot",
        description="Work with HubSpot CRM contacts, companies, deals, tickets, and notes through API-backed agent actions.",
        transport=Transport.SKILL,
        env_vars=("HUBSPOT_ACCESS_TOKEN", "HUBSPOT_API_KEY"),
        auth_type="api_key",
        api_key_url="https://app.hubspot.com/private-apps/",
        primary_env_var="HUBSPOT_ACCESS_TOKEN",
        docs_url="https://developers.hubspot.com/docs/api/private-apps",
        capabilities=("Contacts", "Companies", "Deals", "Tickets", "Notes"),
        setup_steps=(
            "Create a HubSpot private app.",
            "Copy the private app access token.",
            "Set HUBSPOT_ACCESS_TOKEN.",
        ),
    ),
    CatalogConnectorSpec(
        id="asana",
        name="Asana",
        description="Inspect and update Asana workspaces, projects, tasks, and comments through API-backed agent actions.",
        transport=Transport.SKILL,
        env_vars=("ASANA_ACCESS_TOKEN",),
        auth_type="api_key",
        api_key_url="https://app.asana.com/0/my-apps",
        primary_env_var="ASANA_ACCESS_TOKEN",
        docs_url="https://developers.asana.com/docs/personal-access-token",
        capabilities=("Tasks", "Projects", "Comments", "Workspace lookup"),
        setup_steps=(
            "Create an Asana personal access token.",
            "Copy the token.",
            "Set ASANA_ACCESS_TOKEN.",
        ),
    ),
    CatalogConnectorSpec(
        id="tinker",
        name="Tinker",
        description="Run and inspect Tinker RL training workflows with the existing training tools.",
        transport=Transport.SKILL,
        env_vars=("TINKER_API_KEY",),
        auth_type="api_key",
        api_key_url="https://tinker.thinkingmachines.ai/",
        primary_env_var="TINKER_API_KEY",
        scopes=("WANDB_API_KEY optional for run metrics",),
        capabilities=("Training runs", "Run status", "Metrics", "Result inspection"),
        docs_url="https://tinker.thinkingmachines.ai/",
        setup_steps=("Set TINKER_API_KEY.", "Set WANDB_API_KEY if you want W&B metrics in training tools."),
    ),
    CatalogConnectorSpec(
        id="slack",
        name="Slack",
        description="Use Slack as a gateway surface and send or receive workspace messages through the Slack app tokens.",
        transport=Transport.SKILL,
        env_vars=("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"),
        auth_type="api_key",
        api_key_url="https://api.slack.com/apps",
        primary_env_var="SLACK_BOT_TOKEN",
        docs_url="https://api.slack.com/start/quickstart",
        capabilities=("Messages", "Channels", "Gateway bot", "Cron delivery"),
        setup_steps=("Create a Slack app with bot permissions.", "Set SLACK_BOT_TOKEN and SLACK_APP_TOKEN for Socket Mode."),
    ),
    CatalogConnectorSpec(
        id="imap-mail",
        name="IMAP Mail",
        description="General email over IMAP/SMTP using the Himalaya CLI skill or Spark email gateway settings.",
        transport=Transport.CLI,
        cli="himalaya",
        cli_auth_check=("himalaya", "account", "list"),
        env_vars=("EMAIL_ADDRESS", "EMAIL_PASSWORD", "EMAIL_IMAP_HOST", "EMAIL_SMTP_HOST"),
        auth_type="multi_env",
        primary_env_var="EMAIL_ADDRESS",
        config_paths=("~/.config/himalaya/config.toml",),
        skills=("himalaya",),
        capabilities=("Read mail", "Send mail", "Search inbox", "Reply/forward"),
        docs_url="https://pimalaya.org/himalaya/",
        setup_steps=("Install Himalaya.", "Configure an IMAP/SMTP account, or set EMAIL_* gateway variables."),
    ),
    CatalogConnectorSpec(
        id="claude-code",
        name="Claude Code",
        description="Delegate coding tasks to the Claude Code CLI agent (features, refactors, PRs).",
        transport=Transport.CLI,
        cli="claude",
        env_vars=("ANTHROPIC_API_KEY",),
        config_paths=("~/.claude.json",),
        auth_type="cli",
        primary_env_var="ANTHROPIC_API_KEY",
        skills=("claude-code",),
        capabilities=("Feature building", "Refactoring", "PR review", "Iterative coding"),
        docs_url="https://docs.anthropic.com/en/docs/claude-code",
        setup_steps=("Install Claude Code: npm install -g @anthropic-ai/claude-code", "Run `claude` once to sign in."),
    ),
    CatalogConnectorSpec(
        id="codex",
        name="OpenAI Codex",
        description="Delegate coding tasks to the OpenAI Codex CLI agent (features, refactors, batch fixes).",
        transport=Transport.CLI,
        cli="codex",
        env_vars=("OPENAI_API_KEY",),
        config_paths=("~/.codex/auth.json",),
        auth_type="cli",
        primary_env_var="OPENAI_API_KEY",
        skills=("codex",),
        capabilities=("Feature building", "Refactoring", "Batch issue fixing"),
        docs_url="https://github.com/openai/codex",
        setup_steps=("Install Codex CLI: npm install -g @openai/codex", "Run `codex` once to sign in."),
    ),
    CatalogConnectorSpec(
        id="opencode",
        name="OpenCode",
        description="Delegate coding tasks to the OpenCode CLI agent (features, PR review).",
        transport=Transport.CLI,
        cli="opencode",
        config_paths=("~/.local/share/opencode/auth.json",),
        auth_type="cli",
        skills=("opencode",),
        capabilities=("Feature building", "PR review"),
        docs_url="https://opencode.ai/",
        setup_steps=("Install OpenCode: npm install -g opencode-ai", "Run `opencode auth login`."),
    ),
    CatalogConnectorSpec(
        id="airtable",
        name="Airtable",
        description="Read and update Airtable bases, tables, records, and views with a personal access token.",
        transport=Transport.SKILL,
        env_vars=("AIRTABLE_TOKEN", "AIRTABLE_API_KEY"),
        auth_type="api_key",
        api_key_url="https://airtable.com/create/tokens",
        primary_env_var="AIRTABLE_TOKEN",
        docs_url="https://support.airtable.com/docs/creating-personal-access-tokens",
        capabilities=("Bases", "Tables", "Records", "Views"),
        setup_steps=(
            "Create an Airtable personal access token.",
            "Grant the bases/scopes Spark should use.",
            "Set AIRTABLE_TOKEN.",
        ),
    ),
)


def catalog_factories() -> dict[str, Callable[[], Connector]]:
    return {
        spec.id: (lambda spec=spec: CatalogConnector(spec))
        for spec in CATALOG_CONNECTORS
    }
