"""
Doctor command for spark CLI.

Diagnoses issues with Spark Agent setup.
"""

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from core.network_tls import CABundleError, httpx_verify_value, validate_ca_bundle
from core.spark_constants import OPENROUTER_MODELS_URL, display_spark_home
from core.spark_constants import is_termux as _is_termux
from spark_cli.colors import Colors, color
from spark_cli.config import get_env_path, get_project_root, get_spark_home

PROJECT_ROOT = get_project_root()
SPARK_HOME = get_spark_home()
_DHH = display_spark_home()  # user-facing display path (e.g. ~/.spark or ~/.spark/profiles/coder)

# Load environment variables from ~/.spark/.env so API key checks work
_env_path = get_env_path()
if _env_path.exists():
    try:
        load_dotenv(_env_path, encoding="utf-8")
    except UnicodeDecodeError:
        load_dotenv(_env_path, encoding="latin-1")
# Also try project .env as dev fallback
load_dotenv(PROJECT_ROOT / ".env", override=False, encoding="utf-8")


@dataclass(frozen=True)
class DoctorBlocker:
    """Actionable per-integration finding shown by ``spark doctor``."""

    area: str
    name: str
    problem: str
    fix: str

    def summary(self) -> str:
        return f"[{self.area}] {self.name}: {self.problem} - {self.fix}"


_PROVIDER_ENV_HINTS = (
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_TOKEN",
    "OPENAI_BASE_URL",
    "GLM_API_KEY",
    "ZAI_API_KEY",
    "Z_AI_API_KEY",
    "KIMI_API_KEY",
    "MINIMAX_API_KEY",
    "MINIMAX_CN_API_KEY",
    "KILOCODE_API_KEY",
    "DEEPSEEK_API_KEY",
    "DASHSCOPE_API_KEY",
    "HF_TOKEN",
    "AI_GATEWAY_API_KEY",
    "OPENCODE_ZEN_API_KEY",
    "OPENCODE_GO_API_KEY",
    "XIAOMI_API_KEY",
)


def _python_install_cmd() -> str:
    return "python -m pip install" if _is_termux() else "uv pip install"


def _system_package_install_cmd(pkg: str) -> str:
    if _is_termux():
        return f"pkg install {pkg}"
    if sys.platform == "darwin":
        return f"brew install {pkg}"
    return f"sudo apt install {pkg}"


def _termux_browser_setup_steps(node_installed: bool) -> list[str]:
    steps: list[str] = []
    step = 1
    if not node_installed:
        steps.append(f"{step}) pkg install nodejs")
        step += 1
    steps.append(f"{step}) npm install -g agent-browser")
    steps.append(f"{step + 1}) agent-browser install")
    return steps


def _has_provider_env_config(content: str) -> bool:
    """Return True when ~/.spark/.env contains provider auth/base URL settings."""
    return any(key in content for key in _PROVIDER_ENV_HINTS)


def _honcho_is_configured_for_doctor() -> bool:
    """Return True when Honcho is configured, even if this process has no active session."""
    try:
        from plugins.memory.honcho.client import HonchoClientConfig

        cfg = HonchoClientConfig.from_global_config()
        return bool(cfg.enabled and (cfg.api_key or cfg.base_url))
    except Exception:
        return False


def _apply_doctor_tool_availability_overrides(available: list[str], unavailable: list[dict]) -> tuple[list[str], list[dict]]:
    """Adjust runtime-gated tool availability for doctor diagnostics."""
    if not _honcho_is_configured_for_doctor():
        return available, unavailable

    updated_available = list(available)
    updated_unavailable = []
    for item in unavailable:
        if item.get("name") == "honcho":
            if "honcho" not in updated_available:
                updated_available.append("honcho")
            continue
        updated_unavailable.append(item)
    return updated_available, updated_unavailable


def check_ok(text: str, detail: str = ""):
    print(f"  {color('✓', Colors.GREEN)} {text}" + (f" {color(detail, Colors.DIM)}" if detail else ""))

def check_warn(text: str, detail: str = ""):
    print(f"  {color('⚠', Colors.YELLOW)} {text}" + (f" {color(detail, Colors.DIM)}" if detail else ""))

def check_fail(text: str, detail: str = ""):
    print(f"  {color('✗', Colors.RED)} {text}" + (f" {color(detail, Colors.DIM)}" if detail else ""))

def check_info(text: str):
    print(f"    {color('→', Colors.CYAN)} {text}")


def _check_ca_bundle(issues: list[str]) -> str | None:
    """Validate network.ca_bundle and return an httpx verify value if usable."""
    try:
        bundle_path = validate_ca_bundle()
    except CABundleError as exc:
        check_fail("Custom CA bundle", f"({exc})")
        issues.append(str(exc))
        return None

    if bundle_path is None:
        check_ok("Custom CA bundle", "(not configured)")
        return None

    check_ok("Custom CA bundle", f"({bundle_path})")
    return httpx_verify_value()


def _shorten(text: str, limit: int = 180) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _load_doctor_config() -> dict[str, Any]:
    """Load the profile config file without mutating it or requiring setup."""
    config_path = SPARK_HOME / "config.yaml"
    if not config_path.exists():
        return {}
    try:
        import yaml

        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _load_doctor_env() -> dict[str, str]:
    """Read env values from the process and active profile .env."""
    values: dict[str, str] = {}
    env_path = SPARK_HOME / ".env"
    if env_path.exists():
        try:
            for raw_line in env_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                if not key:
                    continue
                values[key] = value.strip().strip("\"'")
        except Exception:
            pass
    values.update(os.environ)
    return values


def _doctor_env_value(key: str, env_values: dict[str, str] | None = None) -> str:
    values = env_values if env_values is not None else _load_doctor_env()
    return str(values.get(key) or "").strip()


def _is_truthy_config(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _connector_configured_for_doctor(connector: Any, status: Any, env_values: dict[str, str]) -> bool:
    """Return True when a connector looks intentionally configured by the user."""
    if getattr(status, "state", None) and str(getattr(status.state, "value", status.state)) == "error":
        return True
    extra = getattr(status, "extra", {}) or {}
    if extra.get("oauth_configured"):
        return True
    for name in extra.get("env_vars") or ():
        if _doctor_env_value(str(name), env_values):
            return True
    for path in extra.get("config_paths") or ():
        try:
            if Path(str(path)).expanduser().exists():
                return True
        except Exception:
            continue
    meta = getattr(connector, "read_meta", None)
    if callable(meta):
        try:
            return bool(meta())
        except Exception:
            return False
    return False


def _connector_fix(connector: Any, status: Any) -> str:
    extra = getattr(status, "extra", {}) or {}
    setup_steps = [str(s) for s in extra.get("setup_steps") or [] if str(s).strip()]
    if setup_steps:
        return _shorten(" ".join(setup_steps), 220)
    primary_env = extra.get("primary_env_var")
    if primary_env:
        return f"set {primary_env} in {_DHH}/.env or reconnect from the Connectors tab"
    cli = extra.get("cli")
    if cli:
        return f"install/authenticate `{cli}` and refresh connector status"
    if getattr(connector, "docs_url", ""):
        return f"open {connector.docs_url} and complete setup"
    return "open the Connectors tab or run the relevant setup command"


def _collect_connector_blockers(env_values: dict[str, str]) -> list[DoctorBlocker]:
    blockers: list[DoctorBlocker] = []
    try:
        from tools.connectors import list_connectors
        from tools.connectors.base import ConnectorState
    except Exception as exc:
        return [
            DoctorBlocker(
                "connector",
                "registry",
                f"could not load connector registry: {_shorten(exc)}",
                "check connector optional dependencies and rerun spark doctor",
            )
        ]

    for connector in list_connectors():
        name = getattr(connector, "name", "") or getattr(connector, "id", "unknown")
        try:
            status = connector.status()
        except Exception as exc:
            blockers.append(
                DoctorBlocker(
                    "connector",
                    str(name),
                    f"status probe crashed: {_shorten(exc)}",
                    "fix the connector status probe or disable the connector",
                )
            )
            continue

        state = getattr(status, "state", None)
        if state is ConnectorState.CONNECTED:
            continue
        if not _connector_configured_for_doctor(connector, status, env_values):
            continue

        detail = _shorten(getattr(status, "detail", "") or getattr(state, "value", state))
        if state is ConnectorState.DISCONNECTED:
            problem = detail or "configured but disconnected"
        elif state is ConnectorState.NOT_INSTALLED:
            problem = detail or "required dependency is not installed"
        else:
            problem = detail or "status probe reported an error"
        blockers.append(DoctorBlocker("connector", str(name), problem, _connector_fix(connector, status)))
    return blockers


def _mcp_command_missing(command: str, env: dict[str, str]) -> str | None:
    command = os.path.expanduser(str(command).strip())
    if not command:
        return "empty command"
    if os.sep in command:
        return None if os.path.isfile(command) and os.access(command, os.X_OK) else command
    if shutil.which(command, path=env.get("PATH")):
        return None
    return command


def _collect_mcp_blockers(config: dict[str, Any]) -> list[DoctorBlocker]:
    blockers: list[DoctorBlocker] = []
    servers = config.get("mcp_servers")
    if not servers:
        return blockers
    if not isinstance(servers, dict):
        return [
            DoctorBlocker(
                "mcp",
                "config",
                "mcp_servers must be a mapping",
                f"edit {_DHH}/config.yaml so mcp_servers is a server-name map",
            )
        ]

    try:
        from tools.mcp_tool import _MCP_AVAILABLE, _MCP_HTTP_AVAILABLE
    except Exception:
        _MCP_AVAILABLE = False
        _MCP_HTTP_AVAILABLE = False

    for name, raw_cfg in servers.items():
        server_name = str(name)
        if not isinstance(raw_cfg, dict):
            blockers.append(
                DoctorBlocker(
                    "mcp",
                    server_name,
                    "server config must be a mapping",
                    f"edit mcp_servers.{server_name} in {_DHH}/config.yaml",
                )
            )
            continue

        enabled = _is_truthy_config(raw_cfg.get("enabled"), default=True)
        if not enabled:
            blockers.append(
                DoctorBlocker(
                    "mcp",
                    server_name,
                    "disabled in config",
                    f"set mcp_servers.{server_name}.enabled to true when this server should be available",
                )
            )
            continue

        if not _MCP_AVAILABLE:
            blockers.append(
                DoctorBlocker(
                    "mcp",
                    server_name,
                    "MCP SDK is not installed",
                    "install the optional MCP dependency for this Spark environment",
                )
            )
            continue

        command = raw_cfg.get("command")
        url = raw_cfg.get("url")
        if not command and not url:
            blockers.append(
                DoctorBlocker(
                    "mcp",
                    server_name,
                    "missing command or url",
                    f"add mcp_servers.{server_name}.command or .url in {_DHH}/config.yaml",
                )
            )
            continue

        if url and not _MCP_HTTP_AVAILABLE:
            blockers.append(
                DoctorBlocker(
                    "mcp",
                    server_name,
                    "HTTP MCP transport is unavailable",
                    "upgrade/install the MCP SDK with streamable HTTP support",
                )
            )

        if command:
            env = dict(os.environ)
            user_env = raw_cfg.get("env")
            if isinstance(user_env, dict):
                env.update({str(k): str(v) for k, v in user_env.items()})
            missing = _mcp_command_missing(str(command), env)
            if missing:
                fix = f"install `{missing}` or set mcp_servers.{server_name}.command to an absolute executable path"
                blockers.append(DoctorBlocker("mcp", server_name, f"missing executable `{missing}`", fix))
    return blockers


def _platform_config_value(platform_cfg: Any, env_key: str) -> str:
    key = env_key.lower()
    extra = getattr(platform_cfg, "extra", {}) or {}
    candidates = [
        key,
        key.split("_", 1)[-1],
        key.rsplit("_", 1)[-1],
        key.replace("_", ""),
    ]
    if key.endswith(("bot_token", "access_token", "_token")) and getattr(platform_cfg, "token", None):
        return str(platform_cfg.token)
    if key.endswith(("api_key", "auth_token")) and getattr(platform_cfg, "api_key", None):
        return str(platform_cfg.api_key)
    for candidate in candidates:
        if candidate in extra and extra[candidate]:
            return str(extra[candidate])
    return ""


def _collect_gateway_blockers(env_values: dict[str, str]) -> list[DoctorBlocker]:
    blockers: list[DoctorBlocker] = []
    try:
        from gateway.config import Platform, load_gateway_config
        from gateway.platform_fields import all_platform_specs
    except Exception as exc:
        return [
            DoctorBlocker(
                "gateway",
                "config",
                f"could not load gateway metadata: {_shorten(exc)}",
                "check gateway imports and rerun spark doctor",
            )
        ]

    try:
        gateway_config = load_gateway_config()
    except Exception as exc:
        return [
            DoctorBlocker(
                "gateway",
                "config",
                f"could not load gateway config: {_shorten(exc)}",
                f"fix {_DHH}/config.yaml or {_DHH}/.env",
            )
        ]

    for spec in all_platform_specs():
        try:
            platform = Platform(spec.id)
        except Exception:
            continue
        platform_cfg = gateway_config.platforms.get(platform)
        enabled_env = _doctor_env_value(spec.enabled_env, env_values)
        configured = bool(platform_cfg and platform_cfg.enabled) or _is_truthy_config(enabled_env)
        if not configured:
            continue
        for field in spec.required:
            env_value = _doctor_env_value(field.key, env_values)
            cfg_value = _platform_config_value(platform_cfg, field.key) if platform_cfg else ""
            if env_value or cfg_value:
                continue
            blockers.append(
                DoctorBlocker(
                    "gateway",
                    spec.name,
                    f"missing required {field.key}",
                    f"run `spark gateway setup` or set {field.key} in {_DHH}/.env",
                )
            )
    return blockers


def _configured_disabled_skill_names(config: dict[str, Any]) -> set[str]:
    skills_cfg = config.get("skills") if isinstance(config.get("skills"), dict) else {}
    disabled: set[str] = set()
    raw_disabled = skills_cfg.get("disabled")
    if isinstance(raw_disabled, str):
        disabled.add(raw_disabled)
    elif isinstance(raw_disabled, list):
        disabled.update(str(item) for item in raw_disabled if str(item).strip())
    platform_disabled = skills_cfg.get("platform_disabled")
    if isinstance(platform_disabled, dict):
        for names in platform_disabled.values():
            if isinstance(names, str):
                disabled.add(names)
            elif isinstance(names, list):
                disabled.update(str(item) for item in names if str(item).strip())
    return {name.strip() for name in disabled if name.strip()}


def _configured_skill_dirs(config: dict[str, Any]) -> tuple[list[Path], list[DoctorBlocker]]:
    blockers: list[DoctorBlocker] = []
    dirs = [SPARK_HOME / "skills"]
    skills_cfg = config.get("skills") if isinstance(config.get("skills"), dict) else {}
    external_dirs = skills_cfg.get("external_dirs") if isinstance(skills_cfg, dict) else None
    if isinstance(external_dirs, str):
        external_dirs = [external_dirs]
    if isinstance(external_dirs, list):
        for raw_dir in external_dirs:
            expanded = Path(os.path.expandvars(os.path.expanduser(str(raw_dir)))).resolve()
            if expanded.exists() and expanded.is_dir():
                dirs.append(expanded)
            else:
                blockers.append(
                    DoctorBlocker(
                        "skill",
                        str(raw_dir),
                        "configured external skill directory is missing",
                        f"create the directory or remove it from skills.external_dirs in {_DHH}/config.yaml",
                    )
                )
    return dirs, blockers


def _collect_skill_blockers(config: dict[str, Any]) -> list[DoctorBlocker]:
    blockers: list[DoctorBlocker] = []
    dirs, dir_blockers = _configured_skill_dirs(config)
    blockers.extend(dir_blockers)

    installed_names: set[str] = set()
    for skills_dir in dirs:
        if not skills_dir.exists():
            continue
        for skill_md in skills_dir.rglob("SKILL.md"):
            if any(part in {".git", ".github", ".hub"} for part in skill_md.parts):
                continue
            try:
                content = skill_md.read_text(encoding="utf-8")
            except Exception as exc:
                blockers.append(
                    DoctorBlocker(
                        "skill",
                        str(skill_md),
                        f"unreadable SKILL.md: {_shorten(exc)}",
                        "fix file permissions or remove the broken skill",
                    )
                )
                continue
            try:
                from agent.skill_utils import parse_frontmatter

                frontmatter, _ = parse_frontmatter(content)
            except Exception as exc:
                blockers.append(
                    DoctorBlocker(
                        "skill",
                        str(skill_md),
                        f"invalid frontmatter: {_shorten(exc)}",
                        "fix the SKILL.md YAML frontmatter",
                    )
                )
                continue
            name = str(frontmatter.get("name") or skill_md.parent.name).strip()
            if name:
                installed_names.add(name)

        for child in skills_dir.iterdir():
            if not child.is_dir() or child.name.startswith("."):
                continue
            if (child / "SKILL.md").exists():
                continue
            if any(grandchild.is_dir() and (grandchild / "SKILL.md").exists() for grandchild in child.iterdir()):
                continue
            if any(child.iterdir()):
                blockers.append(
                    DoctorBlocker(
                        "skill",
                        child.name,
                        "skill directory is missing SKILL.md",
                        f"add {child / 'SKILL.md'} or remove the incomplete skill directory",
                    )
                )

    for name in sorted(_configured_disabled_skill_names(config)):
        if name in installed_names:
            problem = "disabled in skills config"
            fix = "run `spark skills` to re-enable it or leave it disabled intentionally"
        else:
            problem = "listed in skills config but not installed"
            fix = f"install the skill or remove `{name}` from {_DHH}/config.yaml"
        blockers.append(DoctorBlocker("skill", name, problem, fix))
    return blockers


def _collect_integration_blockers() -> list[DoctorBlocker]:
    config = _load_doctor_config()
    env_values = _load_doctor_env()
    blockers: list[DoctorBlocker] = []
    for collector in (
        lambda: _collect_connector_blockers(env_values),
        lambda: _collect_mcp_blockers(config),
        lambda: _collect_gateway_blockers(env_values),
        lambda: _collect_skill_blockers(config),
    ):
        try:
            blockers.extend(collector())
        except Exception as exc:
            blockers.append(
                DoctorBlocker(
                    "doctor",
                    "integration probe",
                    f"probe collector failed: {_shorten(exc)}",
                    "fix the collector error and rerun spark doctor",
                )
            )
    return blockers


def _render_integration_blockers(issues: list[str]) -> None:
    print()
    print(color("◆ Integration Blockers", Colors.CYAN, Colors.BOLD))
    blockers = _collect_integration_blockers()
    if not blockers:
        check_ok("No configured integration blockers found")
        return
    for blocker in blockers:
        check_warn(f"[{blocker.area}] {blocker.name}: {blocker.problem}", f"- {blocker.fix}")
        issues.append(blocker.summary())


def _check_headless_browser_deps() -> None:
    """Advisory check for Chromium system libraries on headless Linux.

    On a Linux server with no ``$DISPLAY``, agent-browser's bundled Chromium
    still needs shared libraries (libnss3, libatk, libgbm, etc.). When they are
    missing, Chromium fails to launch and every browser command hangs to the
    full timeout. This check is purely advisory — it prints guidance and never
    appends to ``issues`` or fails the doctor run, because many headless setups
    (containers with deps preinstalled, custom Chromium) are perfectly valid.
    """
    if not sys.platform.startswith("linux"):
        return
    if os.environ.get("DISPLAY"):
        # A display is present — not the headless server scenario.
        return

    # Probe for a few representative Chromium runtime libraries. ldconfig is the
    # most portable way to ask "is this shared lib resolvable?" without launching
    # Chromium. If ldconfig itself is unavailable, stay silent rather than guess.
    if not shutil.which("ldconfig"):
        return
    try:
        ldconfig_out = subprocess.run(
            ["ldconfig", "-p"], capture_output=True, text=True, timeout=10
        ).stdout
    except Exception:
        return

    required = ["libnss3", "libgbm", "libatk-1.0", "libxkbcommon", "libasound"]
    missing = [lib for lib in required if lib not in ldconfig_out]

    if missing:
        check_warn(
            "Headless browser system libraries",
            f"(missing: {', '.join(missing)})",
        )
        check_info("No $DISPLAY detected — Chromium may fail to launch headless.")
        check_info("Install dependencies with: agent-browser install --with-deps")
        check_info("(advisory only — browser commands would otherwise hang to timeout)")
    else:
        check_ok("Headless browser system libraries", "(Chromium deps present)")


def _check_gateway_service_linger(issues: list[str]) -> None:
    """Warn when a systemd user gateway service will stop after logout."""
    try:
        from spark_cli.gateway import (
            get_systemd_linger_status,
            get_systemd_unit_path,
            is_linux,
        )
    except Exception as e:
        check_warn("Gateway service linger", f"(could not import gateway helpers: {e})")
        return

    if not is_linux():
        return

    unit_path = get_systemd_unit_path()
    if not unit_path.exists():
        return

    print()
    print(color("◆ Gateway Service", Colors.CYAN, Colors.BOLD))

    linger_enabled, linger_detail = get_systemd_linger_status()
    if linger_enabled is True:
        check_ok("Systemd linger enabled", "(gateway service survives logout)")
    elif linger_enabled is False:
        check_warn("Systemd linger disabled", "(gateway may stop after logout)")
        check_info("Run: sudo loginctl enable-linger $USER")
        issues.append("Enable linger for the gateway user service: sudo loginctl enable-linger $USER")
    else:
        check_warn("Could not verify systemd linger", f"({linger_detail})")


def run_doctor(args):
    """Run diagnostic checks."""
    should_fix = getattr(args, 'fix', False)

    # Doctor runs from the interactive CLI, so CLI-gated tool availability
    # checks (like cronjob management) should see the same context as `spark`.
    os.environ.setdefault("SPARK_INTERACTIVE", "1")

    issues = []
    manual_issues = []  # issues that can't be auto-fixed
    fixed_count = 0

    print()
    print(color("┌─────────────────────────────────────────────────────────┐", Colors.CYAN))
    print(color("│                 🩺 Spark Doctor                        │", Colors.CYAN))
    print(color("└─────────────────────────────────────────────────────────┘", Colors.CYAN))

    # =========================================================================
    # Check: Python version
    # =========================================================================
    print()
    print(color("◆ Python Environment", Colors.CYAN, Colors.BOLD))

    py_version = sys.version_info
    if py_version >= (3, 11):
        check_ok(f"Python {py_version.major}.{py_version.minor}.{py_version.micro}")
    elif py_version >= (3, 10):
        check_ok(f"Python {py_version.major}.{py_version.minor}.{py_version.micro}")
        check_warn("Python 3.11+ recommended for RL Training tools (tinker requires >= 3.11)")
    elif py_version >= (3, 8):
        check_warn(f"Python {py_version.major}.{py_version.minor}.{py_version.micro}", "(3.10+ recommended)")
    else:
        check_fail(f"Python {py_version.major}.{py_version.minor}.{py_version.micro}", "(3.10+ required)")
        issues.append("Upgrade Python to 3.10+")

    # Check if in virtual environment
    in_venv = sys.prefix != sys.base_prefix
    if in_venv:
        check_ok("Virtual environment active")
    else:
        check_warn("Not in virtual environment", "(recommended)")

    # =========================================================================
    # Check: Required packages
    # =========================================================================
    print()
    print(color("◆ Required Packages", Colors.CYAN, Colors.BOLD))

    required_packages = [
        ("openai", "OpenAI SDK"),
        ("rich", "Rich (terminal UI)"),
        ("dotenv", "python-dotenv"),
        ("yaml", "PyYAML"),
        ("httpx", "HTTPX"),
    ]

    optional_packages = [
        ("croniter", "Croniter (cron expressions)"),
        ("telegram", "python-telegram-bot"),
        ("discord", "discord.py"),
    ]

    for module, name in required_packages:
        try:
            __import__(module)
            check_ok(name)
        except ImportError:
            check_fail(name, "(missing)")
            issues.append(f"Install {name}: {_python_install_cmd()} {module}")

    for module, name in optional_packages:
        try:
            __import__(module)
            check_ok(name, "(optional)")
        except ImportError:
            check_warn(name, "(optional, not installed)")

    # =========================================================================
    # Check: Configuration files
    # =========================================================================
    print()
    print(color("◆ Configuration Files", Colors.CYAN, Colors.BOLD))

    # Check ~/.spark/.env (primary location for user config)
    env_path = SPARK_HOME / '.env'
    if env_path.exists():
        check_ok(f"{_DHH}/.env file exists")

        # Check for common issues
        content = env_path.read_text()
        if _has_provider_env_config(content):
            check_ok("API key or custom endpoint configured")
        else:
            check_warn(f"No API key found in {_DHH}/.env")
            issues.append("Run 'spark setup' to configure API keys")
    else:
        # Also check project root as fallback
        fallback_env = PROJECT_ROOT / '.env'
        if fallback_env.exists():
            check_ok(".env file exists (in project directory)")
        else:
            check_fail(f"{_DHH}/.env file missing")
            if should_fix:
                env_path.parent.mkdir(parents=True, exist_ok=True)
                env_path.touch()
                check_ok(f"Created empty {_DHH}/.env")
                check_info("Run 'spark setup' to configure API keys")
                fixed_count += 1
            else:
                check_info("Run 'spark setup' to create one")
                issues.append("Run 'spark setup' to create .env")

    # Check ~/.spark/config.yaml (primary) or project cli-config.yaml (fallback)
    config_path = SPARK_HOME / 'config.yaml'
    if config_path.exists():
        check_ok(f"{_DHH}/config.yaml exists")
    else:
        fallback_config = PROJECT_ROOT / 'cli-config.yaml'
        if fallback_config.exists():
            check_ok("cli-config.yaml exists (in project directory)")
        else:
            example_config = PROJECT_ROOT / 'cli-config.yaml.example'
            if should_fix and example_config.exists():
                config_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(example_config), str(config_path))
                check_ok(f"Created {_DHH}/config.yaml from cli-config.yaml.example")
                fixed_count += 1
            elif should_fix:
                check_warn("config.yaml not found and no example to copy from")
                manual_issues.append(f"Create {_DHH}/config.yaml manually")
            else:
                check_warn("config.yaml not found", "(using defaults)")

    # Check config version and stale keys
    config_path = SPARK_HOME / 'config.yaml'
    if config_path.exists():
        try:
            from spark_cli.config import check_config_version, migrate_config
            current_ver, latest_ver = check_config_version()
            if current_ver < latest_ver:
                check_warn(
                    f"Config version outdated (v{current_ver} → v{latest_ver})",
                    "(new settings available)"
                )
                if should_fix:
                    try:
                        migrate_config(interactive=False, quiet=False)
                        check_ok("Config migrated to latest version")
                        fixed_count += 1
                    except Exception as mig_err:
                        check_warn(f"Auto-migration failed: {mig_err}")
                        issues.append("Run 'spark setup' to migrate config")
                else:
                    issues.append("Run 'spark doctor --fix' or 'spark setup' to migrate config")
            else:
                check_ok(f"Config version up to date (v{current_ver})")
        except Exception:
            pass

        # Detect stale root-level model keys (known bug source — PR #4329)
        try:
            import yaml
            with open(config_path) as f:
                raw_config = yaml.safe_load(f) or {}
            stale_root_keys = [k for k in ("provider", "base_url") if k in raw_config and isinstance(raw_config[k], str)]
            if stale_root_keys:
                check_warn(
                    f"Stale root-level config keys: {', '.join(stale_root_keys)}",
                    "(should be under 'model:' section)"
                )
                if should_fix:
                    model_section = raw_config.setdefault("model", {})
                    for k in stale_root_keys:
                        if not model_section.get(k):
                            model_section[k] = raw_config.pop(k)
                        else:
                            raw_config.pop(k)
                    from core.utils import atomic_yaml_write
                    atomic_yaml_write(config_path, raw_config)
                    check_ok("Migrated stale root-level keys into model section")
                    fixed_count += 1
                else:
                    issues.append("Stale root-level provider/base_url in config.yaml — run 'spark doctor --fix'")
        except Exception:
            pass

        # Validate config structure (catches malformed custom_providers, etc.)
        try:
            from spark_cli.config import validate_config_structure
            config_issues = validate_config_structure()
            if config_issues:
                print()
                print(color("◆ Config Structure", Colors.CYAN, Colors.BOLD))
                for ci in config_issues:
                    if ci.severity == "error":
                        check_fail(ci.message)
                    else:
                        check_warn(ci.message)
                    # Show the hint indented
                    for hint_line in ci.hint.splitlines():
                        check_info(hint_line)
                    issues.append(ci.message)
        except Exception:
            pass

    # =========================================================================
    # Check: Auth providers
    # =========================================================================
    print()
    print(color("◆ Auth Providers", Colors.CYAN, Colors.BOLD))

    try:
        from spark_cli.auth import get_codex_auth_status

        codex_status = get_codex_auth_status()
        if codex_status.get("logged_in"):
            check_ok("OpenAI Codex auth", "(logged in)")
        else:
            check_warn("OpenAI Codex auth", "(not logged in)")
            if codex_status.get("error"):
                check_info(codex_status["error"])
    except Exception as e:
        check_warn("Auth provider status", f"(could not check: {e})")

    if shutil.which("codex"):
        check_ok("codex CLI")
    else:
        check_warn("codex CLI not found", "(required for openai-codex login)")

    # =========================================================================
    # Check: Directory structure
    # =========================================================================
    print()
    print(color("◆ Directory Structure", Colors.CYAN, Colors.BOLD))

    spark_home = SPARK_HOME
    if spark_home.exists():
        check_ok(f"{_DHH} directory exists")
    else:
        if should_fix:
            spark_home.mkdir(parents=True, exist_ok=True)
            check_ok(f"Created {_DHH} directory")
            fixed_count += 1
        else:
            check_warn(f"{_DHH} not found", "(will be created on first use)")

    # Check expected subdirectories
    expected_subdirs = ["cron", "sessions", "logs", "skills", "memories", "cache/vision"]
    for subdir_name in expected_subdirs:
        subdir_path = spark_home / subdir_name
        if subdir_path.exists():
            check_ok(f"{_DHH}/{subdir_name}/ exists")
        else:
            if should_fix:
                subdir_path.mkdir(parents=True, exist_ok=True)
                check_ok(f"Created {_DHH}/{subdir_name}/")
                fixed_count += 1
            else:
                check_warn(f"{_DHH}/{subdir_name}/ not found", "(will be created on first use)")

    # Check for SOUL.md persona file
    soul_path = spark_home / "SOUL.md"
    if soul_path.exists():
        content = soul_path.read_text(encoding="utf-8").strip()
        # Check if it has any non-comment, non-heading real content
        real_lines = [
            line for line in content.splitlines()
            if line.strip() and not line.strip().startswith(("<!--", "-->", "#"))
        ]
        if real_lines:
            check_ok(f"{_DHH}/SOUL.md exists (personalised)")
        else:
            check_ok(f"{_DHH}/SOUL.md exists", f"(edit {_DHH}/SOUL.md to personalise your assistant)")
    else:
        check_warn(f"{_DHH}/SOUL.md not found", "(optional — personalises your assistant)")
        if should_fix:
            soul_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                from spark_cli.default_soul import read_default_soul_md
                soul_path.write_text(read_default_soul_md() + "\n", encoding="utf-8")
            except Exception:
                soul_path.write_text(
                    "# Spark Agent - Base Soul\n\n"
                    "You are Spark Agent, an intelligent AI assistant. "
                    "Be warm, direct, honest, and useful.\n",
                    encoding="utf-8",
                )
            check_ok(f"Created {_DHH}/SOUL.md with base identity")
            fixed_count += 1

    # Check memory directory
    memories_dir = spark_home / "memories"
    if memories_dir.exists():
        check_ok(f"{_DHH}/memories/ directory exists")
        memory_file = memories_dir / "MEMORY.md"
        user_file = memories_dir / "USER.md"
        if memory_file.exists():
            size = len(memory_file.read_text(encoding="utf-8").strip())
            check_ok(f"MEMORY.md exists ({size} chars)")
        else:
            check_info("MEMORY.md not created yet (will be created when the agent first writes a memory)")
        if user_file.exists():
            size = len(user_file.read_text(encoding="utf-8").strip())
            check_ok(f"USER.md exists ({size} chars)")
        else:
            check_info("USER.md not created yet (will be created when the agent first writes a memory)")
    else:
        check_warn(f"{_DHH}/memories/ not found", "(will be created on first use)")
        if should_fix:
            memories_dir.mkdir(parents=True, exist_ok=True)
            check_ok(f"Created {_DHH}/memories/")
            fixed_count += 1

    # Check SQLite session store
    state_db_path = spark_home / "state.db"
    if state_db_path.exists():
        try:
            import sqlite3
            conn = sqlite3.connect(str(state_db_path))
            cursor = conn.execute("SELECT COUNT(*) FROM sessions")
            count = cursor.fetchone()[0]
            conn.close()
            check_ok(f"{_DHH}/state.db exists ({count} sessions)")
        except Exception as e:
            check_warn(f"{_DHH}/state.db exists but has issues: {e}")
    else:
        check_info(f"{_DHH}/state.db not created yet (will be created on first session)")

    # Check WAL file size (unbounded growth indicates missed checkpoints)
    wal_path = spark_home / "state.db-wal"
    if wal_path.exists():
        try:
            wal_size = wal_path.stat().st_size
            if wal_size > 50 * 1024 * 1024:  # 50 MB
                check_warn(
                    f"WAL file is large ({wal_size // (1024*1024)} MB)",
                    "(may indicate missed checkpoints)"
                )
                if should_fix:
                    import sqlite3
                    conn = sqlite3.connect(str(state_db_path))
                    conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
                    conn.close()
                    new_size = wal_path.stat().st_size if wal_path.exists() else 0
                    check_ok(f"WAL checkpoint performed ({wal_size // 1024}K → {new_size // 1024}K)")
                    fixed_count += 1
                else:
                    issues.append("Large WAL file — run 'spark doctor --fix' to checkpoint")
            elif wal_size > 10 * 1024 * 1024:  # 10 MB
                check_info(f"WAL file is {wal_size // (1024*1024)} MB (normal for active sessions)")
        except Exception:
            pass

    _check_gateway_service_linger(issues)

    # =========================================================================
    # Check: External tools
    # =========================================================================
    print()
    print(color("◆ External Tools", Colors.CYAN, Colors.BOLD))

    # Git
    if shutil.which("git"):
        check_ok("git")
    else:
        check_warn("git not found", "(optional)")

    # ripgrep (optional, for faster file search)
    if shutil.which("rg"):
        check_ok("ripgrep (rg)", "(faster file search)")
    else:
        check_warn("ripgrep (rg) not found", "(file search uses grep fallback)")
        check_info(f"Install for faster search: {_system_package_install_cmd('ripgrep')}")

    # Docker (optional)
    terminal_env = os.getenv("TERMINAL_ENV", "local")
    if terminal_env == "docker":
        if shutil.which("docker"):
            # Check if docker daemon is running
            try:
                result = subprocess.run(["docker", "info"], capture_output=True, timeout=10)
            except subprocess.TimeoutExpired:
                result = None
            if result is not None and result.returncode == 0:
                check_ok("docker", "(daemon running)")
            else:
                check_fail("docker daemon not running")
                issues.append("Start Docker daemon")
        else:
            check_fail("docker not found", "(required for TERMINAL_ENV=docker)")
            issues.append("Install Docker or change TERMINAL_ENV")
    else:
        if shutil.which("docker"):
            check_ok("docker", "(optional)")
        else:
            if _is_termux():
                check_info("Docker backend is not available inside Termux (expected on Android)")
            else:
                check_warn("docker not found", "(optional)")

    # SSH (if using ssh backend)
    if terminal_env == "ssh":
        ssh_host = os.getenv("TERMINAL_SSH_HOST")
        if ssh_host:
            # Try to connect
            try:
                result = subprocess.run(
                    ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", ssh_host, "echo ok"],
                    capture_output=True,
                    text=True,
                    timeout=15
                )
            except subprocess.TimeoutExpired:
                result = None
            if result is not None and result.returncode == 0:
                check_ok(f"SSH connection to {ssh_host}")
            else:
                check_fail(f"SSH connection to {ssh_host}")
                issues.append(f"Check SSH configuration for {ssh_host}")
        else:
            check_fail("TERMINAL_SSH_HOST not set", "(required for TERMINAL_ENV=ssh)")
            issues.append("Set TERMINAL_SSH_HOST in .env")

    # Daytona (if using daytona backend)
    if terminal_env == "daytona":
        daytona_key = os.getenv("DAYTONA_API_KEY")
        if daytona_key:
            check_ok("Daytona API key", "(configured)")
        else:
            check_fail("DAYTONA_API_KEY not set", "(required for TERMINAL_ENV=daytona)")
            issues.append("Set DAYTONA_API_KEY environment variable")
        try:
            from daytona import Daytona  # noqa: F401 — SDK presence check
            check_ok("daytona SDK", "(installed)")
        except ImportError:
            check_fail("daytona SDK not installed", "(pip install daytona)")
            issues.append("Install daytona SDK: pip install daytona")

    # cua-driver (macOS background computer-use)
    import platform as _platform
    if _platform.system() == "Darwin":
        try:
            from tools.computer_use.cua_backend import (
                cua_driver_install_command as _cua_install_command,
            )
            from tools.computer_use.cua_backend import (
                is_available as _cua_available,
            )
            _ok = _cua_available()
        except Exception:
            _ok = bool(shutil.which("cua-driver"))

            def _cua_install_command():
                return (
                    '/bin/bash -c "$(curl -fsSL '
                    "https://raw.githubusercontent.com/trycua/cua/main/libs/"
                    'cua-driver/scripts/install.sh)"'
                )
        if _ok:
            check_ok("cua-driver", "(macOS background computer-use)")
        else:
            check_warn("cua-driver not found", "(optional, enables computer_use toolset)")
            check_info(
                f"Install: {_cua_install_command()}"
                " — or: brew install cua-driver"
            )

    # Piper (local neural TTS)
    try:
        import importlib.util as _ilu
        _piper_ok = _ilu.find_spec("piper") is not None
    except Exception:
        _piper_ok = False
    if _piper_ok:
        check_ok("piper-tts", "(local TTS, no API key required)")
    else:
        check_info("piper-tts not installed (optional, enables local TTS: pip install piper-tts)")

    # Node.js + managed agent-browser runtime
    if shutil.which("node"):
        check_ok("Node.js")
        try:
            from spark_cli.browser_runtime import (
                agent_browser_path,
                agent_browser_ready,
                agent_browser_version,
                install_agent_browser,
            )

            binary = agent_browser_path()
            if binary:
                version = agent_browser_version()
                check_ok("agent-browser package", f"({version or binary})")
            elif _is_termux():
                check_info("agent-browser is not installed (expected in the tested Termux path)")
                check_info("Install it manually later with: npm install -g agent-browser && agent-browser install")
                check_info("Termux browser setup:")
                for step in _termux_browser_setup_steps(node_installed=True):
                    check_info(step)
                binary = None
            else:
                check_warn("agent-browser package not installed", "(managed browser runtime)")

            if not _is_termux():
                ready, detail = agent_browser_ready()
                if ready:
                    check_ok("agent-browser runtime", "(browser engine ready)")
                elif should_fix:
                    check_info("Installing agent-browser runtime...")
                    result = install_agent_browser(quiet=True)
                    if result.get("ok"):
                        check_ok("agent-browser runtime repaired", f"({result.get('version') or result.get('binary')})")
                        fixed_count += 1
                    else:
                        check_fail("agent-browser runtime setup failed", str(result.get("error") or detail))
                        issues.append("agent-browser runtime setup failed")
                else:
                    check_warn("agent-browser runtime not ready", f"({detail})")
                    issues.append("Run 'spark doctor --fix' to install agent-browser")
        except Exception as exc:
            check_warn("agent-browser check failed", f"({exc})")
            issues.append("Run 'spark doctor --fix' to repair agent-browser")

        # Headless Linux advisory — on a server with no $DISPLAY, Chromium
        # needs its system libraries or every browser command hangs to the
        # full timeout. Advisory only: it does not append to ``issues`` and
        # never fails the run, since many headless setups are perfectly fine.
        _check_headless_browser_deps()
    else:
        if _is_termux():
            check_info("Node.js not found (browser tools are optional in the tested Termux path)")
            check_info("Install Node.js on Termux with: pkg install nodejs")
            check_info("Termux browser setup:")
            for step in _termux_browser_setup_steps(node_installed=False):
                check_info(step)
        else:
            check_warn("Node.js not found", "(optional, needed for browser tools)")
            issues.append("Install Node.js to enable Spark's browser tab")

    # npm audit for all Node.js packages
    if shutil.which("npm"):
        npm_dirs = [
            (PROJECT_ROOT, "Browser tools (agent-browser)"),
            (PROJECT_ROOT / "scripts" / "whatsapp-bridge", "WhatsApp bridge"),
        ]
        for npm_dir, label in npm_dirs:
            if not (npm_dir / "node_modules").exists():
                continue
            try:
                audit_result = subprocess.run(
                    ["npm", "audit", "--json"],
                    cwd=str(npm_dir),
                    capture_output=True, text=True, timeout=30,
                )
                import json as _json
                audit_data = _json.loads(audit_result.stdout) if audit_result.stdout.strip() else {}
                vuln_count = audit_data.get("metadata", {}).get("vulnerabilities", {})
                critical = vuln_count.get("critical", 0)
                high = vuln_count.get("high", 0)
                moderate = vuln_count.get("moderate", 0)
                total = critical + high + moderate
                if total == 0:
                    check_ok(f"{label} deps", "(no known vulnerabilities)")
                elif critical > 0 or high > 0:
                    check_warn(
                        f"{label} deps",
                        f"({critical} critical, {high} high, {moderate} moderate — run: cd {npm_dir} && npm audit fix)"
                    )
                    issues.append(f"{label} has {total} npm vulnerability(ies)")
                else:
                    check_ok(f"{label} deps", f"({moderate} moderate vulnerability(ies))")
            except Exception:
                pass

    # =========================================================================
    # Check: API connectivity
    # =========================================================================
    print()
    print(color("◆ API Connectivity", Colors.CYAN, Colors.BOLD))
    ca_bundle_verify = _check_ca_bundle(issues)
    httpx_tls_kwargs = {"verify": ca_bundle_verify} if ca_bundle_verify else {}

    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    if openrouter_key:
        print("  Checking OpenRouter API...", end="", flush=True)
        try:
            import httpx
            response = httpx.get(
                OPENROUTER_MODELS_URL,
                headers={"Authorization": f"Bearer {openrouter_key}"},
                timeout=10,
                **httpx_tls_kwargs,
            )
            if response.status_code == 200:
                print(f"\r  {color('✓', Colors.GREEN)} OpenRouter API                          ")
            elif response.status_code == 401:
                print(f"\r  {color('✗', Colors.RED)} OpenRouter API {color('(invalid API key)', Colors.DIM)}                ")
                issues.append("Check OPENROUTER_API_KEY in .env")
            else:
                print(f"\r  {color('✗', Colors.RED)} OpenRouter API {color(f'(HTTP {response.status_code})', Colors.DIM)}                ")
        except Exception as e:
            print(f"\r  {color('✗', Colors.RED)} OpenRouter API {color(f'({e})', Colors.DIM)}                ")
            issues.append("Check network connectivity")
    else:
        check_warn("OpenRouter API", "(not configured)")

    from spark_cli.auth import get_anthropic_key
    anthropic_key = get_anthropic_key()
    if anthropic_key:
        print("  Checking Anthropic API...", end="", flush=True)
        try:
            import httpx

            from agent.anthropic_adapter import _COMMON_BETAS, _OAUTH_ONLY_BETAS, _is_oauth_token

            headers = {"anthropic-version": "2023-06-01"}
            if _is_oauth_token(anthropic_key):
                headers["Authorization"] = f"Bearer {anthropic_key}"
                headers["anthropic-beta"] = ",".join(_COMMON_BETAS + _OAUTH_ONLY_BETAS)
            else:
                headers["x-api-key"] = anthropic_key
            response = httpx.get(
                "https://api.anthropic.com/v1/models",
                headers=headers,
                timeout=10,
                **httpx_tls_kwargs,
            )
            if response.status_code == 200:
                print(f"\r  {color('✓', Colors.GREEN)} Anthropic API                           ")
            elif response.status_code == 401:
                print(f"\r  {color('✗', Colors.RED)} Anthropic API {color('(invalid API key)', Colors.DIM)}                 ")
            else:
                msg = "(couldn't verify)"
                print(f"\r  {color('⚠', Colors.YELLOW)} Anthropic API {color(msg, Colors.DIM)}                 ")
        except Exception as e:
            print(f"\r  {color('⚠', Colors.YELLOW)} Anthropic API {color(f'({e})', Colors.DIM)}                 ")

    # -- API-key providers --
    # Tuple: (name, env_vars, default_url, base_env, supports_models_endpoint)
    # If supports_models_endpoint is False, we skip the health check and just show "configured"
    _apikey_providers = [
        ("Z.AI / GLM",      ("GLM_API_KEY", "ZAI_API_KEY", "Z_AI_API_KEY"), "https://api.z.ai/api/paas/v4/models", "GLM_BASE_URL", True),
        ("Kimi / Moonshot",  ("KIMI_API_KEY",),                              "https://api.moonshot.ai/v1/models",   "KIMI_BASE_URL", True),
        ("Kimi / Moonshot (China)", ("KIMI_CN_API_KEY",),                    "https://api.moonshot.cn/v1/models",   None, True),
        ("Arcee AI",         ("ARCEEAI_API_KEY",),                            "https://api.arcee.ai/api/v1/models",  "ARCEE_BASE_URL", True),
        ("DeepSeek",         ("DEEPSEEK_API_KEY",),                           "https://api.deepseek.com/v1/models",  "DEEPSEEK_BASE_URL", True),
        ("Hugging Face",     ("HF_TOKEN",),                                   "https://router.huggingface.co/v1/models", "HF_BASE_URL", True),
        ("Alibaba/DashScope", ("DASHSCOPE_API_KEY",),                         "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/models", "DASHSCOPE_BASE_URL", True),
        # MiniMax: the /anthropic endpoint doesn't support /models, but the /v1 endpoint does.
        ("MiniMax",          ("MINIMAX_API_KEY",),                            "https://api.minimax.io/v1/models",    "MINIMAX_BASE_URL", True),
        ("MiniMax (China)",  ("MINIMAX_CN_API_KEY",),                         "https://api.minimaxi.com/v1/models",  "MINIMAX_CN_BASE_URL", True),
        ("Vercel AI Gateway",       ("AI_GATEWAY_API_KEY",),                          "https://ai-gateway.vercel.sh/v1/models", "AI_GATEWAY_BASE_URL", True),
        ("Kilo Code",        ("KILOCODE_API_KEY",),                            "https://api.kilo.ai/api/gateway/models",  "KILOCODE_BASE_URL", True),
        ("OpenCode Zen",     ("OPENCODE_ZEN_API_KEY",),                        "https://opencode.ai/zen/v1/models",  "OPENCODE_ZEN_BASE_URL", True),
        ("OpenCode Go",      ("OPENCODE_GO_API_KEY",),                         "https://opencode.ai/zen/go/v1/models", "OPENCODE_GO_BASE_URL", True),
    ]
    for _pname, _env_vars, _default_url, _base_env, _supports_health_check in _apikey_providers:
        _key = ""
        for _ev in _env_vars:
            _key = os.getenv(_ev, "")
            if _key:
                break
        if _key:
            _label = _pname.ljust(20)
            # Some providers (like MiniMax) don't support /models endpoint
            if not _supports_health_check:
                print(f"  {color('✓', Colors.GREEN)} {_label} {color('(key configured)', Colors.DIM)}")
                continue
            print(f"  Checking {_pname} API...", end="", flush=True)
            try:
                import httpx
                _base = os.getenv(_base_env, "")
                # Auto-detect Kimi Code keys (sk-kimi-) → api.kimi.com
                if not _base and _key.startswith("sk-kimi-"):
                    _base = "https://api.kimi.com/coding/v1"
                # Anthropic-compat endpoints (/anthropic) don't support /models.
                # Rewrite to the OpenAI-compat /v1 surface for health checks.
                if _base and _base.rstrip("/").endswith("/anthropic"):
                    from agent.auxiliary_client import _to_openai_base_url
                    _base = _to_openai_base_url(_base)
                _url = (_base.rstrip("/") + "/models") if _base else _default_url
                _headers = {"Authorization": f"Bearer {_key}"}
                if "api.kimi.com" in _url.lower():
                    _headers["User-Agent"] = "KimiCLI/1.30.0"
                _resp = httpx.get(
                    _url,
                    headers=_headers,
                    timeout=10,
                    **httpx_tls_kwargs,
                )
                if _resp.status_code == 200:
                    print(f"\r  {color('✓', Colors.GREEN)} {_label}                          ")
                elif _resp.status_code == 401:
                    print(f"\r  {color('✗', Colors.RED)} {_label} {color('(invalid API key)', Colors.DIM)}           ")
                    issues.append(f"Check {_env_vars[0]} in .env")
                else:
                    print(f"\r  {color('⚠', Colors.YELLOW)} {_label} {color(f'(HTTP {_resp.status_code})', Colors.DIM)}           ")
            except Exception as _e:
                print(f"\r  {color('⚠', Colors.YELLOW)} {_label} {color(f'({_e})', Colors.DIM)}           ")

    # =========================================================================
    # Check: Submodules
    # =========================================================================
    print()
    print(color("◆ Submodules", Colors.CYAN, Colors.BOLD))

    # tinker-atropos (RL training backend)
    tinker_dir = PROJECT_ROOT / "tinker-atropos"
    if tinker_dir.exists() and (tinker_dir / "pyproject.toml").exists():
        if py_version >= (3, 11):
            try:
                __import__("tinker_atropos")
                check_ok("tinker-atropos", "(RL training backend)")
            except ImportError:
                install_cmd = f"{_python_install_cmd()} -e ./tinker-atropos"
                check_warn("tinker-atropos found but not installed", f"(run: {install_cmd})")
                issues.append(f"Install tinker-atropos: {install_cmd}")
        else:
            check_warn("tinker-atropos requires Python 3.11+", f"(current: {py_version.major}.{py_version.minor})")
    else:
        check_warn("tinker-atropos not found", "(run: git submodule update --init --recursive)")

    # =========================================================================
    # Check: Tool Availability
    # =========================================================================
    print()
    print(color("◆ Tool Availability", Colors.CYAN, Colors.BOLD))

    try:
        # Add project root to path for imports
        sys.path.insert(0, str(PROJECT_ROOT))
        from core.model_tools import TOOLSET_REQUIREMENTS, check_tool_availability

        available, unavailable = check_tool_availability()
        available, unavailable = _apply_doctor_tool_availability_overrides(available, unavailable)

        for tid in available:
            info = TOOLSET_REQUIREMENTS.get(tid, {})
            check_ok(info.get("name", tid))

        for item in unavailable:
            env_vars = item.get("missing_vars") or item.get("env_vars") or []
            if env_vars:
                vars_str = ", ".join(env_vars)
                check_warn(item["name"], f"(missing {vars_str})")
            else:
                check_warn(item["name"], "(system dependency not met)")

        # Count disabled tools with API key requirements
        api_disabled = [u for u in unavailable if (u.get("missing_vars") or u.get("env_vars"))]
        if api_disabled:
            issues.append("Run 'spark setup' to configure missing API keys for full tool access")
    except Exception as e:
        check_warn("Could not check tool availability", f"({e})")

    # =========================================================================
    # Check: Skills Hub
    # =========================================================================
    print()
    print(color("◆ Skills Hub", Colors.CYAN, Colors.BOLD))

    hub_dir = SPARK_HOME / "skills" / ".hub"
    if hub_dir.exists():
        check_ok("Skills Hub directory exists")
        lock_file = hub_dir / "lock.json"
        if lock_file.exists():
            try:
                import json
                lock_data = json.loads(lock_file.read_text())
                count = len(lock_data.get("installed", {}))
                check_ok(f"Lock file OK ({count} hub-installed skill(s))")
            except Exception:
                check_warn("Lock file", "(corrupted or unreadable)")
        quarantine = hub_dir / "quarantine"
        q_count = sum(1 for d in quarantine.iterdir() if d.is_dir()) if quarantine.exists() else 0
        if q_count > 0:
            check_warn(f"{q_count} skill(s) in quarantine", "(pending review)")
    else:
        check_warn("Skills Hub directory not initialized", "(run: spark skills list)")

    from spark_cli.config import get_env_value
    github_token = get_env_value("GITHUB_TOKEN") or get_env_value("GH_TOKEN")
    if github_token:
        check_ok("GitHub token configured (authenticated API access)")
    else:
        check_warn("No GITHUB_TOKEN", f"(60 req/hr rate limit — set in {_DHH}/.env for better rates)")

    # =========================================================================
    # Check: Integration Blockers
    # =========================================================================
    _render_integration_blockers(issues)

    # =========================================================================
    # Memory Provider (only check the active provider, if any)
    # =========================================================================
    print()
    print(color("◆ Memory Provider", Colors.CYAN, Colors.BOLD))

    _active_memory_provider = ""
    try:
        import yaml as _yaml
        _mem_cfg_path = SPARK_HOME / "config.yaml"
        if _mem_cfg_path.exists():
            with open(_mem_cfg_path) as _f:
                _raw_cfg = _yaml.safe_load(_f) or {}
            _active_memory_provider = (_raw_cfg.get("memory") or {}).get("provider", "")
    except Exception:
        pass

    if not _active_memory_provider:
        check_ok("Built-in memory active", "(no external provider configured — this is fine)")
    elif _active_memory_provider == "honcho":
        try:
            from plugins.memory.honcho.client import HonchoClientConfig, resolve_config_path
            hcfg = HonchoClientConfig.from_global_config()
            _honcho_cfg_path = resolve_config_path()

            if not _honcho_cfg_path.exists():
                check_warn("Honcho config not found", "run: spark memory setup")
            elif not hcfg.enabled:
                check_info(f"Honcho disabled (set enabled: true in {_honcho_cfg_path} to activate)")
            elif not (hcfg.api_key or hcfg.base_url):
                check_fail("Honcho API key or base URL not set", "run: spark memory setup")
                issues.append("No Honcho API key — run 'spark memory setup'")
            else:
                from plugins.memory.honcho.client import get_honcho_client, reset_honcho_client
                reset_honcho_client()
                try:
                    get_honcho_client(hcfg)
                    check_ok(
                        "Honcho connected",
                        f"workspace={hcfg.workspace_id} mode={hcfg.recall_mode} freq={hcfg.write_frequency}",
                    )
                except Exception as _e:
                    check_fail("Honcho connection failed", str(_e))
                    issues.append(f"Honcho unreachable: {_e}")
        except ImportError:
            check_fail("honcho-ai not installed", "pip install honcho-ai")
            issues.append("Honcho is set as memory provider but honcho-ai is not installed")
        except Exception as _e:
            check_warn("Honcho check failed", str(_e))
    elif _active_memory_provider == "mem0":
        try:
            from plugins.memory.mem0 import _load_config as _load_mem0_config
            mem0_cfg = _load_mem0_config()
            mem0_key = mem0_cfg.get("api_key", "")
            if mem0_key:
                check_ok("Mem0 API key configured")
                check_info(f"user_id={mem0_cfg.get('user_id', '?')}  agent_id={mem0_cfg.get('agent_id', '?')}")
            else:
                check_fail("Mem0 API key not set", "(set MEM0_API_KEY in .env or run spark memory setup)")
                issues.append("Mem0 is set as memory provider but API key is missing")
        except ImportError:
            check_fail("Mem0 plugin not loadable", "pip install mem0ai")
            issues.append("Mem0 is set as memory provider but mem0ai is not installed")
        except Exception as _e:
            check_warn("Mem0 check failed", str(_e))
    else:
        # Generic check for other memory providers (openviking, hindsight, etc.)
        try:
            from plugins.memory import load_memory_provider
            _provider = load_memory_provider(_active_memory_provider)
            if _provider and _provider.is_available():
                check_ok(f"{_active_memory_provider} provider active")
            elif _provider:
                check_warn(f"{_active_memory_provider} configured but not available", "run: spark memory status")
            else:
                check_warn(f"{_active_memory_provider} plugin not found", "run: spark memory setup")
        except Exception as _e:
            check_warn(f"{_active_memory_provider} check failed", str(_e))

    # =========================================================================
    # Profiles
    # =========================================================================
    try:
        import re as _re

        from spark_cli.profiles import _get_wrapper_dir, list_profiles, profile_exists

        named_profiles = [p for p in list_profiles() if not p.is_default]
        if named_profiles:
            print()
            print(color("◆ Profiles", Colors.CYAN, Colors.BOLD))
            check_ok(f"{len(named_profiles)} profile(s) found")
            wrapper_dir = _get_wrapper_dir()
            for p in named_profiles:
                parts = []
                if p.gateway_running:
                    parts.append("gateway running")
                if p.model:
                    parts.append(p.model[:30])
                if not (p.path / "config.yaml").exists():
                    parts.append("⚠ missing config")
                if not (p.path / ".env").exists():
                    parts.append("no .env")
                wrapper = wrapper_dir / p.name
                if not wrapper.exists():
                    parts.append("no alias")
                status = ", ".join(parts) if parts else "configured"
                check_ok(f"  {p.name}: {status}")

            # Check for orphan wrappers
            if wrapper_dir.is_dir():
                for wrapper in wrapper_dir.iterdir():
                    if not wrapper.is_file():
                        continue
                    try:
                        content = wrapper.read_text()
                        if "spark -p" in content:
                            _m = _re.search(r"spark -p (\S+)", content)
                            if _m and not profile_exists(_m.group(1)):
                                check_warn(f"Orphan alias: {wrapper.name} → profile '{_m.group(1)}' no longer exists")
                    except Exception:
                        pass
    except ImportError:
        pass
    except Exception:
        pass

    # =========================================================================
    # Summary
    # =========================================================================
    print()
    remaining_issues = issues + manual_issues
    if should_fix and fixed_count > 0:
        print(color("─" * 60, Colors.GREEN))
        print(color(f"  Fixed {fixed_count} issue(s).", Colors.GREEN, Colors.BOLD), end="")
        if remaining_issues:
            print(color(f" {len(remaining_issues)} issue(s) require manual intervention.", Colors.YELLOW, Colors.BOLD))
        else:
            print()
        print()
        if remaining_issues:
            for i, issue in enumerate(remaining_issues, 1):
                print(f"  {i}. {issue}")
            print()
    elif remaining_issues:
        print(color("─" * 60, Colors.YELLOW))
        print(color(f"  Found {len(remaining_issues)} issue(s) to address:", Colors.YELLOW, Colors.BOLD))
        print()
        for i, issue in enumerate(remaining_issues, 1):
            print(f"  {i}. {issue}")
        print()
        if not should_fix:
            print(color("  Tip: run 'spark doctor --fix' to auto-fix what's possible.", Colors.DIM))
    else:
        print(color("─" * 60, Colors.GREEN))
        print(color("  All checks passed! 🎉", Colors.GREEN, Colors.BOLD))

    print()
