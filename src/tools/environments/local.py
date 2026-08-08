"""Local execution environment — spawn-per-call with session snapshot."""

import base64
import logging
import os
import platform
import shutil
import signal
import subprocess
import tempfile

from tools.env_passthrough import build_tool_subprocess_env
from tools.environments.base import BaseEnvironment, _pipe_stdin

logger = logging.getLogger(__name__)

_IS_WINDOWS = platform.system() == "Windows"


# Spark-internal env vars that should NOT leak into terminal subprocesses.
_SPARK_PROVIDER_ENV_FORCE_PREFIX = "_SPARK_FORCE_"


def _build_provider_env_blocklist() -> frozenset:
    """Derive the blocklist from provider, tool, and gateway config."""
    blocked: set[str] = set()

    try:
        from spark_cli.auth import PROVIDER_REGISTRY
        for pconfig in PROVIDER_REGISTRY.values():
            blocked.update(pconfig.api_key_env_vars)
            if pconfig.base_url_env_var:
                blocked.add(pconfig.base_url_env_var)
    except ImportError:
        logger.debug("Ignoring error in _build_provider_env_blocklist()", exc_info=True)

    try:
        from spark_cli.config import OPTIONAL_ENV_VARS
        for name, metadata in OPTIONAL_ENV_VARS.items():
            category = metadata.get("category")
            if category in {"tool", "messaging"}:
                blocked.add(name)
            elif category == "setting" and metadata.get("password"):
                blocked.add(name)
    except ImportError:
        logger.debug("Ignoring error in _build_provider_env_blocklist()", exc_info=True)

    blocked.update({
        "OPENAI_BASE_URL",
        "OPENAI_API_KEY",
        "OPENAI_API_BASE",
        "OPENAI_ORG_ID",
        "OPENAI_ORGANIZATION",
        "OPENROUTER_API_KEY",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "LLM_MODEL",
        "GOOGLE_API_KEY",
        "DEEPSEEK_API_KEY",
        "MISTRAL_API_KEY",
        "GROQ_API_KEY",
        "TOGETHER_API_KEY",
        "PERPLEXITY_API_KEY",
        "COHERE_API_KEY",
        "FIREWORKS_API_KEY",
        "XAI_API_KEY",
        "HELICONE_API_KEY",
        "PARALLEL_API_KEY",
        "FIRECRAWL_API_KEY",
        "FIRECRAWL_API_URL",
        "TELEGRAM_HOME_CHANNEL",
        "TELEGRAM_HOME_CHANNEL_NAME",
        "DISCORD_HOME_CHANNEL",
        "DISCORD_HOME_CHANNEL_NAME",
        "DISCORD_REQUIRE_MENTION",
        "DISCORD_FREE_RESPONSE_CHANNELS",
        "DISCORD_AUTO_THREAD",
        "SLACK_HOME_CHANNEL",
        "SLACK_HOME_CHANNEL_NAME",
        "SLACK_ALLOWED_USERS",
        "WHATSAPP_ENABLED",
        "WHATSAPP_MODE",
        "WHATSAPP_ALLOWED_USERS",
        "SIGNAL_HTTP_URL",
        "SIGNAL_ACCOUNT",
        "SIGNAL_ALLOWED_USERS",
        "SIGNAL_GROUP_ALLOWED_USERS",
        "SIGNAL_HOME_CHANNEL",
        "SIGNAL_HOME_CHANNEL_NAME",
        "SIGNAL_IGNORE_STORIES",
        "HASS_TOKEN",
        "HASS_URL",
        "EMAIL_ADDRESS",
        "EMAIL_PASSWORD",
        "EMAIL_IMAP_HOST",
        "EMAIL_SMTP_HOST",
        "EMAIL_HOME_ADDRESS",
        "EMAIL_HOME_ADDRESS_NAME",
        "GATEWAY_ALLOWED_USERS",
        "GH_TOKEN",
        "GITHUB_APP_ID",
        "GITHUB_APP_PRIVATE_KEY_PATH",
        "GITHUB_APP_INSTALLATION_ID",
        "MODAL_TOKEN_ID",
        "MODAL_TOKEN_SECRET",
        "DAYTONA_API_KEY",
    })
    return frozenset(blocked)


_SPARK_PROVIDER_ENV_BLOCKLIST = _build_provider_env_blocklist()


def _sanitize_subprocess_env(base_env: dict | None, extra_env: dict | None = None) -> dict:
    """Build an allowlisted environment for a local tool subprocess."""
    return build_tool_subprocess_env(
        base_env,
        extra_env,
        force_prefix=_SPARK_PROVIDER_ENV_FORCE_PREFIX,
    )


def _find_bash() -> str:
    """Find bash for command execution."""
    if not _IS_WINDOWS:
        return (
            shutil.which("bash")
            or ("/usr/bin/bash" if os.path.isfile("/usr/bin/bash") else None)
            or ("/bin/bash" if os.path.isfile("/bin/bash") else None)
            or os.environ.get("SHELL")
            or "/bin/sh"
        )

    # Native Windows uses PowerShell.  Keep this function as the historical
    # POSIX-shell lookup used by remote backends and third-party callers, but
    # never silently route native commands through Git Bash/WSL.
    return _find_windows_shell()


def _find_windows_shell() -> str:
    """Resolve PowerShell 7 first, then the inbox Windows PowerShell.

    ``shutil.which`` handles installations in paths containing spaces.  The
    explicit fallback is useful in minimal Windows environments where PATH is
    incomplete, and deliberately excludes ``bash.exe``/``wsl.exe``.
    """
    for name in ("pwsh", "pwsh.exe", "powershell", "powershell.exe"):
        found = shutil.which(name)
        if found and os.path.basename(found).lower() not in {"bash.exe", "wsl.exe"}:
            return found
    candidates = [
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "PowerShell", "7", "pwsh.exe"),
        os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe"),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    raise RuntimeError(
        "PowerShell was not found. Install PowerShell 7 or enable Windows PowerShell 5.1."
    )


def _find_shell() -> str:
    """Resolve the shell for native local process execution."""
    return _find_windows_shell() if _IS_WINDOWS else _find_bash()


# Standard PATH entries for environments with minimal PATH.
_SANE_PATH = (
    "/opt/homebrew/bin:/opt/homebrew/sbin:"
    "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
)


def _make_run_env(env: dict) -> dict:
    """Build an allowlisted run environment with a sane PATH."""
    run_env = build_tool_subprocess_env(
        os.environ,
        env,
        force_prefix=_SPARK_PROVIDER_ENV_FORCE_PREFIX,
    )
    existing_path = run_env.get("PATH", "")
    if not _IS_WINDOWS and "/usr/bin" not in existing_path.split(os.pathsep):
        run_env["PATH"] = f"{existing_path}{os.pathsep}{_SANE_PATH}" if existing_path else _SANE_PATH

    return run_env


class LocalEnvironment(BaseEnvironment):
    """Run commands directly on the host machine.

    Spawn-per-call: every execute() spawns a fresh bash process.
    Session snapshot preserves env vars across calls.
    CWD persists via file-based read after each command.
    """
    shell_family = "powershell" if _IS_WINDOWS else "posix"

    def __init__(self, cwd: str = "", timeout: int = 60, env: dict = None):
        super().__init__(cwd=cwd or os.getcwd(), timeout=timeout, env=env)
        self.init_session()

    def get_temp_dir(self) -> str:
        """Return a shell-safe writable temp dir for local execution.

        Termux does not provide /tmp by default, but exposes a POSIX TMPDIR.
        Prefer POSIX-style env vars when available, keep using /tmp on regular
        Unix systems, and only fall back to tempfile.gettempdir() when it also
        resolves to a POSIX path.

        Check the environment configured for this backend first so callers can
        override the temp root explicitly (for example via terminal.env or a
        custom TMPDIR), then fall back to the host process environment.
        """
        if _IS_WINDOWS:
            for env_var in ("TEMP", "TMP", "TMPDIR"):
                candidate = self.env.get(env_var) or os.environ.get(env_var)
                if candidate:
                    return candidate
            return tempfile.gettempdir()

        for env_var in ("TMPDIR", "TMP", "TEMP"):
            candidate = self.env.get(env_var) or os.environ.get(env_var)
            if candidate and candidate.startswith("/"):
                return candidate.rstrip("/") or "/"

        if os.path.isdir("/tmp") and os.access("/tmp", os.W_OK | os.X_OK):
            return "/tmp"

        candidate = tempfile.gettempdir()
        if candidate.startswith("/"):
            return candidate.rstrip("/") or "/"

        return "/tmp"

    def _run_bash(self, cmd_string: str, *, login: bool = False,
                  timeout: int = 120,
                  stdin_data: str | None = None) -> subprocess.Popen:
        if _IS_WINDOWS:
            shell = _find_windows_shell()
            # EncodedCommand is understood by both PowerShell 7 and 5.1 and
            # avoids quoting/escaping bugs for paths and multiline commands.
            encoded = base64.b64encode(cmd_string.encode("utf-16le")).decode("ascii")
            args = [
                shell, "-NoLogo", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded,
            ]
        else:
            bash = _find_bash()
            args = [bash, "-l", "-c", cmd_string] if login else [bash, "-c", cmd_string]
        run_env = _make_run_env(self.env)

        proc = subprocess.Popen(
            args,
            text=True,
            env=run_env,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE if stdin_data is not None else subprocess.DEVNULL,
            preexec_fn=None if _IS_WINDOWS else os.setsid,
            creationflags=(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if _IS_WINDOWS else 0),
        )

        if stdin_data is not None:
            _pipe_stdin(proc, stdin_data)

        return proc

    def _kill_process(self, proc):
        """Kill the entire process group (all children)."""
        try:
            if _IS_WINDOWS:
                # taskkill /T is the only reliable way to terminate a
                # PowerShell process tree (TerminateProcess leaves children).
                try:
                    subprocess.run(
                        ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                except (FileNotFoundError, OSError):
                    proc.terminate()
            else:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGTERM)
                try:
                    proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                proc.kill()
            except Exception:
                logger.debug("Ignoring error in _kill_process()", exc_info=True)

    def _update_cwd(self, result: dict):
        """Read CWD from temp file (local-only, no round-trip needed)."""
        try:
            cwd_path = open(self._cwd_file).read().strip()
            if cwd_path:
                self.cwd = cwd_path
        except (OSError, FileNotFoundError):
            logger.debug("Ignoring error in _update_cwd()", exc_info=True)

        # Still strip the marker from output so it's not visible
        self._extract_cwd_from_output(result)

    def cleanup(self):
        """Clean up temp files."""
        for f in (self._snapshot_path, self._cwd_file):
            try:
                os.unlink(f)
            except OSError:
                logger.debug("Ignoring error in cleanup()", exc_info=True)
