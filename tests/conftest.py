"""Shared fixtures for the spark-agent test suite."""

import asyncio
import sys
from pathlib import Path

import pytest

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(autouse=True)
def _isolate_spark_home(tmp_path, monkeypatch):
    """Redirect app auth/state homes so tests never write to real user data."""
    fake_home = tmp_path / "spark_test"
    fake_codex_home = tmp_path / "codex_test"
    fake_home.mkdir()
    fake_codex_home.mkdir()
    (fake_home / "sessions").mkdir()
    (fake_home / "cron").mkdir()
    (fake_home / "memories").mkdir()
    (fake_home / "skills").mkdir()
    monkeypatch.setenv("SPARK_HOME", str(fake_home))
    # Codex OAuth refresh writes rotated tokens back to CODEX_HOME. Isolate it
    # globally: a credential-pool test that only redirected SPARK_HOME once
    # replaced the developer's real ~/.codex/auth.json with fixture tokens.
    monkeypatch.setenv("CODEX_HOME", str(fake_codex_home))
    # Reset plugin singleton so tests don't leak plugins from ~/.spark/plugins/
    try:
        import spark_cli.plugins as _plugins_mod
        monkeypatch.setattr(_plugins_mod, "_plugin_manager", None)
    except Exception:
        pass
    # Patch the module-level DEFAULT_DB_PATH constant so SessionDB() picks up
    # the redirected SPARK_HOME even when spark_state was already imported.
    try:
        import core.spark_state as _state_mod
        monkeypatch.setattr(_state_mod, "DEFAULT_DB_PATH", fake_home / "state.db")
    except Exception:
        pass
    # Tests should not inherit the agent's current gateway/messaging surface.
    # Individual tests that need gateway behavior set these explicitly.
    monkeypatch.delenv("SPARK_SESSION_PLATFORM", raising=False)
    monkeypatch.delenv("SPARK_SESSION_CHAT_ID", raising=False)
    monkeypatch.delenv("SPARK_SESSION_CHAT_NAME", raising=False)
    monkeypatch.delenv("SPARK_SESSION_CHAT_TYPE", raising=False)
    monkeypatch.delenv("SPARK_GATEWAY_SESSION", raising=False)
    # Avoid making real calls during tests if this key is set in the env files.
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    # Prevent API server env vars from leaking between tests
    monkeypatch.delenv("API_SERVER_KEY", raising=False)
    monkeypatch.delenv("API_SERVER_ENABLED", raising=False)
    monkeypatch.delenv("API_SERVER_HOST", raising=False)
    monkeypatch.delenv("API_SERVER_PORT", raising=False)


@pytest.fixture()
def tmp_dir(tmp_path):
    """Provide a temporary directory that is cleaned up automatically."""
    return tmp_path


@pytest.fixture()
def mock_config():
    """Return a minimal spark config dict suitable for unit tests."""
    return {
        "model": "test/mock-model",
        "toolsets": ["terminal", "file"],
        "max_turns": 10,
        "terminal": {
            "backend": "local",
            "cwd": "/tmp",
            "timeout": 30,
        },
        "compression": {"enabled": False},
        "memory": {"memory_enabled": False, "user_profile_enabled": False},
        "command_allowlist": [],
    }


# ── Global test timeout ─────────────────────────────────────────────────────
# Kill any individual test that takes longer than 30 seconds.
# Per-test timeout is configured via pytest-timeout in pyproject.toml
# (timeout = 30 in [tool.pytest.ini_options]).  That replaces the old
# SIGALRM-based fixture which was not safe under pytest-xdist workers.

@pytest.fixture(autouse=True)
def _ensure_current_event_loop(request):
    """Provide a default event loop for sync tests that call get_event_loop().

    Python 3.11+ no longer guarantees a current loop for plain synchronous tests.
    A number of gateway tests still use asyncio.get_event_loop().run_until_complete(...).
    Ensure they always have a usable loop without interfering with pytest-asyncio's
    own loop management for @pytest.mark.asyncio tests.
    """
    if request.node.get_closest_marker("asyncio") is not None:
        yield
        return

    try:
        loop = asyncio.get_event_loop_policy().get_event_loop()
    except RuntimeError:
        loop = None

    created = loop is None or loop.is_closed()
    if created:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    try:
        yield
    finally:
        if created and loop is not None:
            try:
                loop.close()
            finally:
                asyncio.set_event_loop(None)

@pytest.fixture(autouse=True)
def _block_desktop_app_spawn(monkeypatch):
    """Stop a test from driving the installed desktop app.

    A mac-update test patched subprocess.Popen through a module attribute.
    When the handler moved to another module the patch stopped covering it,
    the real installer ran: it quit Spark.app, installed a DMG, and relaunched
    the app with pytest's SPARK_HOME, so the app came back pointed at a temp
    directory and showed an empty session list.

    Ordinary subprocess use is untouched. Only commands that would act on the
    installed app are refused.
    """
    import subprocess

    real_popen = subprocess.Popen
    danger = ("/Applications/Spark.app", "spark.app", "hdiutil", "osascript")

    class _GuardedPopen(real_popen):  # type: ignore[misc,valid-type]
        def __init__(self, args, *a, **kw):
            argv = args if isinstance(args, str) else " ".join(str(x) for x in args)
            low = argv.lower()
            if any(d in low for d in danger):
                raise AssertionError(
                    "A test tried to drive the installed desktop app:\n"
                    f"  {argv[:300]}\n"
                    "Patch subprocess.Popen at its source module, not through a "
                    "module attribute that stops matching when code moves."
                )
            super().__init__(args, *a, **kw)

    monkeypatch.setattr(subprocess, "Popen", _GuardedPopen)
