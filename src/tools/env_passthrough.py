"""Environment variable passthrough registry.

Skills that declare ``required_environment_variables`` in their frontmatter
need those vars available in sandboxed execution environments (execute_code,
terminal).  By default both sandboxes strip secrets from the child process
environment for security.  This module provides a session-scoped allowlist
so skill-declared vars (and user-configured overrides) pass through.

Two sources feed the allowlist:

1. **Skill declarations** — when a skill is loaded via ``skill_view``, its
   ``required_environment_variables`` are registered here automatically.
2. **User config** — ``terminal.env_passthrough`` in config.yaml lets users
   explicitly allowlist vars for non-skill use cases.

Both ``code_execution_tool.py`` and ``tools/environments/local.py`` use the
shared subprocess env builder below so passthrough is explicit and consistent.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from contextvars import ContextVar

logger = logging.getLogger(__name__)


_SAFE_SUBPROCESS_ENV_KEYS = frozenset({
    "COLORTERM",
    "HOME",
    "LANG",
    "LOGNAME",
    "PATH",
    "SHELL",
    "TEMP",
    "TERM",
    "TMP",
    "TMPDIR",
    "TZ",
    "USER",
    "VIRTUAL_ENV",
    "VIRTUAL_ENV_PROMPT",
})

_SAFE_SUBPROCESS_ENV_PREFIXES = (
    "CONDA_",
    "LC_",
    "XDG_",
)

# Session-scoped set of env var names that should pass through to sandboxes.
# Backed by ContextVar to prevent cross-session data bleed in the gateway pipeline.
_allowed_env_vars_var: ContextVar[set[str]] = ContextVar("_allowed_env_vars")


def _get_allowed() -> set[str]:
    """Get or create the allowed env vars set for the current context/session."""
    try:
        return _allowed_env_vars_var.get()
    except LookupError:
        val: set[str] = set()
        _allowed_env_vars_var.set(val)
        return val


# Cache for the config-based allowlist (loaded once per process).
_config_passthrough: frozenset[str] | None = None


def register_env_passthrough(var_names: Iterable[str]) -> None:
    """Register environment variable names as allowed in sandboxed environments.

    Typically called when a skill declares ``required_environment_variables``.
    """
    for name in var_names:
        name = name.strip()
        if name:
            _get_allowed().add(name)
            logger.debug("env passthrough: registered %s", name)


def _load_config_passthrough() -> frozenset[str]:
    """Load ``tools.env_passthrough`` from config.yaml (cached)."""
    global _config_passthrough
    if _config_passthrough is not None:
        return _config_passthrough

    result: set[str] = set()
    try:
        from spark_cli.config import read_raw_config
        cfg = read_raw_config()
        passthrough = cfg.get("terminal", {}).get("env_passthrough")
        if isinstance(passthrough, list):
            for item in passthrough:
                if isinstance(item, str) and item.strip():
                    result.add(item.strip())
    except Exception as e:
        logger.debug("Could not read tools.env_passthrough from config: %s", e)

    _config_passthrough = frozenset(result)
    return _config_passthrough


def is_env_passthrough(var_name: str) -> bool:
    """Check whether *var_name* is allowed to pass through to sandboxes.

    Returns ``True`` if the variable was registered by a skill or listed in
    the user's ``tools.env_passthrough`` config.
    """
    if var_name in _get_allowed():
        return True
    return var_name in _load_config_passthrough()


def get_all_passthrough() -> frozenset[str]:
    """Return the union of skill-registered and config-based passthrough vars."""
    return frozenset(_get_allowed()) | _load_config_passthrough()


def is_safe_subprocess_env_var(var_name: str) -> bool:
    """Return True when *var_name* is safe to inherit by default.

    This is intentionally an allowlist for model-authored subprocesses. Provider
    credentials, token variables, credential-file paths, and unknown project
    variables are excluded unless explicitly registered via env passthrough.
    """
    return var_name in _SAFE_SUBPROCESS_ENV_KEYS or var_name.startswith(_SAFE_SUBPROCESS_ENV_PREFIXES)


def build_tool_subprocess_env(
    base_env: dict | None = None,
    extra_env: dict | None = None,
    *,
    force_prefix: str = "_SPARK_FORCE_",
    include_passthrough: bool = True,
    profile_home: bool = True,
) -> dict[str, str]:
    """Build an allowlisted environment for model-authored tool subprocesses.

    ``base_env`` defaults to the current process environment. Only safe runtime
    variables and env-passthrough registrations are inherited. ``extra_env``
    follows the same rule, except names prefixed with ``force_prefix`` are
    treated as an internal explicit opt-in and injected under the unprefixed
    name.
    """
    result: dict[str, str] = {}

    def _include(key: str, value: object) -> None:
        if value is None:
            return
        if is_safe_subprocess_env_var(key) or (include_passthrough and is_env_passthrough(key)):
            result[key] = str(value)

    for key, value in (os.environ if base_env is None else base_env).items():
        if key.startswith(force_prefix):
            continue
        _include(key, value)

    for key, value in (extra_env or {}).items():
        if key.startswith(force_prefix):
            real_key = key[len(force_prefix):]
            if real_key:
                result[real_key] = str(value)
        else:
            _include(key, value)

    if profile_home:
        try:
            from core.spark_constants import get_subprocess_home
            profile_home_value = get_subprocess_home()
        except Exception:
            profile_home_value = None
        if profile_home_value:
            result["HOME"] = profile_home_value

    return result


def clear_env_passthrough() -> None:
    """Reset the skill-scoped allowlist (e.g. on session reset)."""
    _get_allowed().clear()
