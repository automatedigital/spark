"""Shared constants for Spark Agent.

Import-safe module with no dependencies — can be imported from anywhere
without risk of circular imports.
"""

import os
from pathlib import Path


def get_spark_home() -> Path:
    """Return the Spark home directory (default: ~/.spark).

    Reads SPARK_HOME env var, falls back to ~/.spark.
    This is the single source of truth — all other copies should import this.
    """
    return Path(os.getenv("SPARK_HOME", Path.home() / ".spark"))


def get_spark_workspace() -> Path:
    """Return the profile-scoped default workspace directory."""
    return get_spark_home() / "workspace"


def get_default_spark_root() -> Path:
    """Return the root Spark directory for profile-level operations.

    In standard deployments this is ``~/.spark``.

    In Docker or custom deployments where ``SPARK_HOME`` points outside
    ``~/.spark`` (e.g. ``/opt/data``), returns ``SPARK_HOME`` directly
    — that IS the root.

    In profile mode where ``SPARK_HOME`` is ``<root>/profiles/<name>``,
    returns ``<root>`` so that ``profile list`` can see all profiles.
    Works both for standard (``~/.spark/profiles/coder``) and Docker
    (``/opt/data/profiles/coder``) layouts.

    Import-safe — no dependencies beyond stdlib.
    """
    native_home = Path.home() / ".spark"
    env_home = os.environ.get("SPARK_HOME", "")
    if not env_home:
        return native_home
    env_path = Path(env_home)
    try:
        env_path.resolve().relative_to(native_home.resolve())
        # SPARK_HOME is under ~/.spark (normal or profile mode)
        return native_home
    except ValueError:
        pass

    # Docker / custom deployment.
    # Check if this is a profile path: <root>/profiles/<name>
    # If the immediate parent dir is named "profiles", the root is
    # the grandparent — this covers Docker profiles correctly.
    if env_path.parent.name == "profiles":
        return env_path.parent.parent

    # Not a profile path — SPARK_HOME itself is the root
    return env_path


def get_optional_skills_dir(default: Path | None = None) -> Path:
    """Return the optional-skills directory, honoring package-manager wrappers.

    Packaged installs may ship ``optional-skills`` outside the Python package
    tree and expose it via ``SPARK_OPTIONAL_SKILLS``.
    """
    override = os.getenv("SPARK_OPTIONAL_SKILLS", "").strip()
    if override:
        return Path(override)
    if default is not None:
        return default
    return get_spark_home() / "optional-skills"


def get_spark_dir(new_subpath: str, old_name: str) -> Path:
    """Resolve a Spark subdirectory with backward compatibility.

    New installs get the consolidated layout (e.g. ``cache/images``).
    Existing installs that already have the old path (e.g. ``image_cache``)
    keep using it — no migration required.

    Args:
        new_subpath: Preferred path relative to SPARK_HOME (e.g. ``"cache/images"``).
        old_name: Legacy path relative to SPARK_HOME (e.g. ``"image_cache"``).

    Returns:
        Absolute ``Path`` — old location if it exists on disk, otherwise the new one.
    """
    home = get_spark_home()
    old_path = home / old_name
    if old_path.exists():
        return old_path
    return home / new_subpath


def display_spark_home() -> str:
    """Return a user-friendly display string for the current SPARK_HOME.

    Uses ``~/`` shorthand for readability::

        default:  ``~/.spark``
        profile:  ``~/.spark/profiles/coder``
        custom:   ``/opt/spark-custom``

    Use this in **user-facing** print/log messages instead of hardcoding
    ``~/.spark``.  For code that needs a real ``Path``, use
    :func:`get_spark_home` instead.
    """
    home = get_spark_home()
    try:
        return "~/" + str(home.relative_to(Path.home()))
    except ValueError:
        return str(home)


def display_spark_workspace() -> str:
    """Return a user-friendly display string for the default workspace."""
    workspace = get_spark_workspace()
    try:
        return "~/" + str(workspace.relative_to(Path.home()))
    except ValueError:
        return str(workspace)


def get_subprocess_home() -> str | None:
    """Return a per-profile HOME directory for subprocesses, or None.

    When ``{SPARK_HOME}/home/`` exists on disk, subprocesses should use it
    as ``HOME`` so system tools (git, ssh, gh, npm …) write their configs
    inside the Spark data directory instead of the OS-level ``/root`` or
    ``~/``.  This provides:

    * **Docker persistence** — tool configs land inside the persistent volume.
    * **Profile isolation** — each profile gets its own git identity, SSH
      keys, gh tokens, etc.

    The Python process's own ``os.environ["HOME"]`` and ``Path.home()`` are
    **never** modified — only subprocess environments should inject this value.
    Activation is directory-based: if the ``home/`` subdirectory doesn't
    exist, returns ``None`` and behavior is unchanged.
    """
    spark_home = os.getenv("SPARK_HOME")
    if not spark_home:
        return None
    profile_home = os.path.join(spark_home, "home")
    if os.path.isdir(profile_home):
        return profile_home
    return None


VALID_REASONING_EFFORTS = ("minimal", "low", "medium", "high", "xhigh")


def parse_reasoning_effort(effort: str) -> dict | None:
    """Parse a reasoning effort level into a config dict.

    Valid levels: "none", "minimal", "low", "medium", "high", "xhigh".
    Returns None when the input is empty or unrecognized (caller uses default).
    Returns {"enabled": False} for "none".
    Returns {"enabled": True, "effort": <level>} for valid effort levels.
    """
    if not effort or not effort.strip():
        return None
    effort = effort.strip().lower()
    if effort == "none":
        return {"enabled": False}
    if effort in VALID_REASONING_EFFORTS:
        return {"enabled": True, "effort": effort}
    return None


def is_termux() -> bool:
    """Return True when running inside a Termux (Android) environment.

    Checks ``TERMUX_VERSION`` (set by Termux) or the Termux-specific
    ``PREFIX`` path.  Import-safe — no heavy deps.
    """
    prefix = os.getenv("PREFIX", "")
    return bool(os.getenv("TERMUX_VERSION") or "com.termux/files/usr" in prefix)


_wsl_detected: bool | None = None


def is_wsl() -> bool:
    """Return True when running inside WSL (Windows Subsystem for Linux).

    Checks ``/proc/version`` for the ``microsoft`` marker that both WSL1
    and WSL2 inject.  Result is cached for the process lifetime.
    Import-safe — no heavy deps.
    """
    global _wsl_detected
    if _wsl_detected is not None:
        return _wsl_detected
    try:
        with open("/proc/version") as f:
            _wsl_detected = "microsoft" in f.read().lower()
    except Exception:
        _wsl_detected = False
    return _wsl_detected


_container_detected: bool | None = None


def is_container() -> bool:
    """Return True when running inside a Docker/Podman container.

    Checks ``/.dockerenv`` (Docker), ``/run/.containerenv`` (Podman),
    and ``/proc/1/cgroup`` for container runtime markers.  Result is
    cached for the process lifetime.  Import-safe — no heavy deps.
    """
    global _container_detected
    if _container_detected is not None:
        return _container_detected
    if os.path.exists("/.dockerenv"):
        _container_detected = True
        return True
    if os.path.exists("/run/.containerenv"):
        _container_detected = True
        return True
    try:
        with open("/proc/1/cgroup") as f:
            cgroup = f.read()
            if "docker" in cgroup or "podman" in cgroup or "/lxc/" in cgroup:
                _container_detected = True
                return True
    except OSError:
        pass
    _container_detected = False
    return False


# ─── Server Environment Detection ────────────────────────────────────────────

_server_env_detected: bool | None = None


def is_server_environment() -> bool:
    """Return True when Spark appears to be running on a remote/headless server.

    Detection order (first match wins):
    1. ``dashboard.public_url`` set in config — user explicitly configured a
       public URL, so this is clearly a server deployment.
    2. ``dashboard.host`` is not loopback in config — bound to 0.0.0.0 etc.,
       meaning the user intends external access.
    3. SSH session — ``SSH_CLIENT``, ``SSH_TTY``, or ``SSH_CONNECTION`` is set.
    4. Headless Linux — no ``DISPLAY`` or ``WAYLAND_DISPLAY`` (services started
       by systemd/supervisor don't have X11 forwarding).

    macOS without SSH markers is always treated as a desktop.
    Result is cached for the process lifetime.
    """
    global _server_env_detected
    if _server_env_detected is not None:
        return _server_env_detected

    # 1 & 2. Config signals — most reliable for daemon/service deployments
    try:
        import yaml  # type: ignore[import]

        _cfg_path = get_config_path()
        if _cfg_path.exists():
            with open(_cfg_path) as _f:
                _cfg = yaml.safe_load(_f) or {}
            _dash = _cfg.get("dashboard") or {}
            if _dash.get("public_url", "").strip():
                _server_env_detected = True
                return True
            _dash_host = _dash.get("host", "").strip()
            _LOOPBACK = {"127.0.0.1", "::1", "localhost", ""}
            if _dash_host and _dash_host not in _LOOPBACK:
                _server_env_detected = True
                return True
    except Exception:
        pass

    # 3. SSH session — works for interactive sessions on all platforms
    if any(os.getenv(v) for v in ("SSH_CLIENT", "SSH_TTY", "SSH_CONNECTION")):
        _server_env_detected = True
        return True

    # 4. Headless Linux (no X11 / Wayland display)
    import sys

    if sys.platform.startswith("linux"):
        has_display = bool(os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"))
        _server_env_detected = not has_display
        return _server_env_detected

    _server_env_detected = False
    return False


def get_server_hostname() -> str:
    """Return the machine's primary hostname for use in user-facing URLs.

    Prefers ``socket.gethostname()`` over ``socket.getfqdn()`` to avoid
    slow reverse-DNS lookups and ARPA artifacts on macOS/containers.
    """
    import socket

    try:
        name = socket.gethostname()
        if name and name != "localhost":
            return name
    except Exception:
        pass
    return "localhost"


def get_public_base_url(host: str, port: int, scheme: str = "http") -> str:
    """Return the URL a browser should open to reach Spark on *host:port*.

    Resolution order:
    1. ``dashboard.public_url`` in ``config.yaml`` — user-configured override
    2. Server environment detected → replace loopback/wildcard with the
       machine's real hostname so remote users get a clickable link
    3. Desktop (default) → ``scheme://127.0.0.1:port`` for local access

    The function never raises; it always returns a usable URL string.
    """
    _LOOPBACK = {"127.0.0.1", "::1", "localhost"}
    _WILDCARD = {"0.0.0.0", "::", "[::]"}

    # 1. Config override — loaded lazily to keep this module import-safe
    try:
        import yaml  # type: ignore[import]

        _cfg_path = get_config_path()
        if _cfg_path.exists():
            with open(_cfg_path) as _f:
                _cfg = yaml.safe_load(_f) or {}
            _pub = (_cfg.get("dashboard") or {}).get("public_url", "").strip()
            if _pub:
                return _pub.rstrip("/")
    except Exception:
        pass

    # 2. Server environment — use real hostname
    display_host = host
    if host in _WILDCARD or host in _LOOPBACK:
        if is_server_environment():
            display_host = get_server_hostname()
        else:
            display_host = "127.0.0.1" if host in _WILDCARD else host

    return f"{scheme}://{display_host}:{port}"


# ─── Well-Known Paths ─────────────────────────────────────────────────────────


def get_config_path() -> Path:
    """Return the path to ``config.yaml`` under SPARK_HOME.

    Replaces the ``get_spark_home() / "config.yaml"`` pattern repeated
    in 7+ files (skill_utils.py, spark_logging.py, spark_time.py, etc.).
    """
    return get_spark_home() / "config.yaml"


def get_skills_dir() -> Path:
    """Return the path to the skills directory under SPARK_HOME."""
    return get_spark_home() / "skills"



def get_env_path() -> Path:
    """Return the path to the ``.env`` file under SPARK_HOME."""
    return get_spark_home() / ".env"


# ─── Network Preferences ─────────────────────────────────────────────────────


def apply_ipv4_preference(force: bool = False) -> None:
    """Monkey-patch ``socket.getaddrinfo`` to prefer IPv4 connections.

    On servers with broken or unreachable IPv6, Python tries AAAA records
    first and hangs for the full TCP timeout before falling back to IPv4.
    This affects httpx, requests, urllib, the OpenAI SDK — everything that
    uses ``socket.getaddrinfo``.

    When *force* is True, patches ``getaddrinfo`` so that calls with
    ``family=AF_UNSPEC`` (the default) resolve as ``AF_INET`` instead,
    skipping IPv6 entirely.  If no A record exists, falls back to the
    original unfiltered resolution so pure-IPv6 hosts still work.

    Safe to call multiple times — only patches once.
    Set ``network.force_ipv4: true`` in ``config.yaml`` to enable.
    """
    if not force:
        return

    import socket

    # Guard against double-patching
    if getattr(socket.getaddrinfo, "_spark_ipv4_patched", False):
        return

    _original_getaddrinfo = socket.getaddrinfo

    def _ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        if family == 0:  # AF_UNSPEC — caller didn't request a specific family
            try:
                return _original_getaddrinfo(
                    host, port, socket.AF_INET, type, proto, flags
                )
            except socket.gaierror:
                # No A record — fall back to full resolution (pure-IPv6 hosts)
                return _original_getaddrinfo(host, port, family, type, proto, flags)
        return _original_getaddrinfo(host, port, family, type, proto, flags)

    _ipv4_getaddrinfo._spark_ipv4_patched = True  # type: ignore[attr-defined]
    socket.getaddrinfo = _ipv4_getaddrinfo  # type: ignore[assignment]


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODELS_URL = f"{OPENROUTER_BASE_URL}/models"

AI_GATEWAY_BASE_URL = "https://ai-gateway.vercel.sh/v1"
