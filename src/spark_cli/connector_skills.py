"""Declarative connectors → skills/toolsets mapping.

Single source of truth for which skills and toolsets "light up" when a
connector reaches the connected state (and which get disabled again on
disconnect). Used by ``connectors_routes.py`` to:

* extend the ``/api/connectors`` list payload with ``skills`` + ``toolsets``
* auto-enable skills/toolsets after a successful connect
* disable dependent skills on disconnect

Skill enablement persists through the existing ``skills.disabled`` config list
(`spark_cli.skills_config`); toolset enablement persists through
``platform_toolsets`` (`spark_cli.tools_config`).
"""

from __future__ import annotations

from dataclasses import dataclass

# Platform whose toolsets we toggle when a connector connects. Matches the
# platform used by the web UI's /api/tools/toolsets endpoint.
_TOOLSET_PLATFORM = "cli"


@dataclass(frozen=True)
class ConnectorGrant:
    """Skills + toolsets unlocked by one connector."""

    skills: tuple[str, ...] = ()
    toolsets: tuple[str, ...] = ()


# connector id → grant. Connector specs in ``tools/connectors/generic.py`` may
# also declare ``skills``; those are merged in by ``grant_for``.
CONNECTOR_GRANTS: dict[str, ConnectorGrant] = {
    "google": ConnectorGrant(
        skills=(
            "gws-gmail",
            "gws-calendar",
            "gws-drive",
            "gws-docs",
            "gws-sheets",
            "gws-slides",
        ),
    ),
    "github": ConnectorGrant(
        skills=(
            "github-auth",
            "github-repo-management",
            "github-pr-workflow",
            "github-code-review",
            "github-issues",
        ),
    ),
    "notion": ConnectorGrant(skills=("notion",)),
    "imap-mail": ConnectorGrant(skills=("himalaya",)),
    "claude-code": ConnectorGrant(skills=("claude-code",), toolsets=("delegation",)),
    "codex": ConnectorGrant(skills=("codex",), toolsets=("delegation",)),
    "opencode": ConnectorGrant(skills=("opencode",), toolsets=("delegation",)),
    "tinker": ConnectorGrant(toolsets=("rl",)),
}


def grant_for(connector_id: str, declared_skills: tuple[str, ...] | list[str] = ()) -> dict:
    """Merged mapping for a connector: declared (spec) skills + grant table.

    Returns ``{"skills": [...], "toolsets": [...]}`` with stable ordering
    (declared first, then grant additions).
    """
    grant = CONNECTOR_GRANTS.get(connector_id, ConnectorGrant())
    skills: list[str] = []
    for name in (*declared_skills, *grant.skills):
        if name and name not in skills:
            skills.append(name)
    return {"skills": skills, "toolsets": list(grant.toolsets)}


def enable_connector_skills(
    connector_id: str, declared_skills: tuple[str, ...] | list[str] = ()
) -> dict:
    """Enable the mapped skills + toolsets for a connector. Returns what changed."""
    from spark_cli.config import load_config
    from spark_cli.skills_config import get_disabled_skills, save_disabled_skills

    mapping = grant_for(connector_id, declared_skills)
    skills: list[str] = mapping["skills"]
    toolsets: list[str] = mapping["toolsets"]

    config = load_config()
    skills_enabled: list[str] = []
    if skills:
        disabled = get_disabled_skills(config)
        newly = [name for name in skills if name in disabled]
        if newly:
            disabled.difference_update(newly)
            save_disabled_skills(config, disabled)
        # Report the full mapped set so the UI can show what's active.
        skills_enabled = skills

    toolsets_enabled: list[str] = []
    if toolsets:
        from spark_cli.tools_config import _get_platform_tools, _save_platform_tools

        current = set(
            _get_platform_tools(config, _TOOLSET_PLATFORM, include_default_mcp_servers=False)
        )
        missing = [name for name in toolsets if name not in current]
        if missing:
            _save_platform_tools(config, _TOOLSET_PLATFORM, current | set(missing))
        toolsets_enabled = toolsets

    return {"skills": skills_enabled, "toolsets": toolsets_enabled}


def disable_connector_skills(
    connector_id: str, declared_skills: tuple[str, ...] | list[str] = ()
) -> dict:
    """Disable the mapped skills for a connector (toolsets are left alone —
    they are coarse-grained and often shared by other features)."""
    from spark_cli.config import load_config
    from spark_cli.skills_config import get_disabled_skills, save_disabled_skills

    mapping = grant_for(connector_id, declared_skills)
    skills: list[str] = mapping["skills"]
    if not skills:
        return {"skills": [], "toolsets": []}

    config = load_config()
    disabled = get_disabled_skills(config)
    disabled.update(skills)
    save_disabled_skills(config, disabled)
    return {"skills": skills, "toolsets": []}
