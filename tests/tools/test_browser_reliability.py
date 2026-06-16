"""Tests for browser_tool.py headless-VPS reliability (Phase 0.2/0.3).

Covers:
- Preflight backend health check + fast unhealthy fail.
- Consecutive-timeout circuit breaker.
- Malformed (non-JSON) daemon response classification.
- Concurrent session isolation (distinct task_ids -> distinct sessions/sockets).

All tests mock the agent-browser subprocess/daemon — no real browser launches
and no network access.
"""

import json
import subprocess
import threading
from unittest.mock import MagicMock, patch

import pytest

import tools.browser_tool as bt


@pytest.fixture(autouse=True)
def _clean_state():
    """Reset all reliability + cache state before and after each test."""
    def _reset():
        bt._cached_agent_browser = None
        bt._agent_browser_resolved = False
        bt._cached_command_timeout = None
        bt._command_timeout_resolved = False
        bt._reset_backend_health_state()
        with bt._cleanup_lock:
            bt._active_sessions.clear()
            bt._session_last_activity.clear()
    _reset()
    yield
    _reset()


# ---------------------------------------------------------------------------
# Preflight health check
# ---------------------------------------------------------------------------

class TestPreflightHealth:
    def test_healthy_when_version_probe_succeeds(self):
        with patch.object(bt, "_is_camofox_mode", return_value=False), \
             patch.object(bt, "_find_agent_browser", return_value="/usr/bin/agent-browser"), \
             patch.object(bt, "_requires_real_termux_browser_install", return_value=False), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="1.2.3", stderr="")
            healthy, err = bt._browser_backend_healthy()
        assert healthy is True
        assert err == ""

    def test_unhealthy_when_cli_missing(self):
        with patch.object(bt, "_is_camofox_mode", return_value=False), \
             patch.object(bt, "_find_agent_browser", side_effect=FileNotFoundError("not installed")):
            healthy, err = bt._browser_backend_healthy()
        assert healthy is False
        assert "not installed" in err

    def test_unhealthy_when_probe_times_out(self):
        with patch.object(bt, "_is_camofox_mode", return_value=False), \
             patch.object(bt, "_find_agent_browser", return_value="/usr/bin/agent-browser"), \
             patch.object(bt, "_requires_real_termux_browser_install", return_value=False), \
             patch("subprocess.run", side_effect=subprocess.TimeoutExpired("agent-browser", 8)):
            healthy, err = bt._browser_backend_healthy()
        assert healthy is False
        assert "did not respond" in err

    def test_health_result_is_cached(self):
        with patch.object(bt, "_is_camofox_mode", return_value=False), \
             patch.object(bt, "_find_agent_browser", return_value="/usr/bin/agent-browser"), \
             patch.object(bt, "_requires_real_termux_browser_install", return_value=False), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="1.0", stderr="")
            bt._browser_backend_healthy()
            bt._browser_backend_healthy()
            # Probe only runs once despite two calls.
            assert mock_run.call_count == 1

    def test_navigate_fast_fails_when_unhealthy(self):
        """Unhealthy backend -> navigate returns actionable error, no command run."""
        with patch.object(bt, "_is_camofox_mode", return_value=False), \
             patch.object(bt, "_browser_backend_healthy", return_value=(False, "boom")), \
             patch.object(bt, "_run_browser_command") as mock_cmd:
            out = json.loads(bt.browser_navigate("https://example.com", task_id="t1"))
        assert out["success"] is False
        assert "not available" in out["error"]
        assert "boom" in out["error"]
        # The expensive navigation command must never be attempted.
        mock_cmd.assert_not_called()


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------

class TestCircuitBreaker:
    def test_trips_after_threshold_timeouts(self):
        assert bt._breaker_is_open() is False
        for _ in range(bt._TIMEOUT_BREAKER_THRESHOLD):
            bt._record_browser_timeout()
        assert bt._breaker_is_open() is True

    def test_does_not_trip_below_threshold(self):
        for _ in range(bt._TIMEOUT_BREAKER_THRESHOLD - 1):
            bt._record_browser_timeout()
        assert bt._breaker_is_open() is False

    def test_success_resets_breaker(self):
        for _ in range(bt._TIMEOUT_BREAKER_THRESHOLD):
            bt._record_browser_timeout()
        assert bt._breaker_is_open() is True
        bt._record_browser_success()
        assert bt._breaker_is_open() is False

    def test_run_command_short_circuits_when_open(self):
        for _ in range(bt._TIMEOUT_BREAKER_THRESHOLD):
            bt._record_browser_timeout()
        # _find_agent_browser must never be reached once the breaker is open.
        with patch.object(bt, "_find_agent_browser") as mock_find:
            result = bt._run_browser_command("t1", "snapshot")
        assert result["success"] is False
        assert result["error_type"] == "circuit_open"
        mock_find.assert_not_called()

    def test_timeout_increments_breaker_counter(self):
        """A real command timeout feeds the breaker counter."""
        proc = MagicMock()
        # First wait(timeout=) raises; the post-kill wait() returns cleanly.
        proc.wait.side_effect = [subprocess.TimeoutExpired("agent-browser", 30), None]
        with patch.object(bt, "_find_agent_browser", return_value="/usr/bin/agent-browser"), \
             patch.object(bt, "_requires_real_termux_browser_install", return_value=False), \
             patch.object(bt, "_get_session_info", return_value={"session_name": "h_abc"}), \
             patch("tools.interrupt.is_interrupted", return_value=False), \
             patch("os.makedirs"), patch("os.open", return_value=3), patch("os.close"), \
             patch("subprocess.Popen", return_value=proc):
            result = bt._run_browser_command("t1", "open", ["https://example.com"], timeout=30)
        assert result["success"] is False
        assert result["error_type"] == "timeout"
        assert bt._consecutive_timeouts == 1


# ---------------------------------------------------------------------------
# Malformed response classification
# ---------------------------------------------------------------------------

class TestMalformedResponse:
    def _run_with_stdout(self, stdout_text):
        proc = MagicMock()
        proc.wait.return_value = None
        proc.returncode = 0

        m = MagicMock()
        m.read.return_value = stdout_text

        def _fake_open(path, mode="r", *a, **k):
            cm = MagicMock()
            handle = MagicMock()
            handle.read.return_value = stdout_text if path.endswith("_stdout_open") else ""
            cm.__enter__.return_value = handle
            return cm

        with patch.object(bt, "_find_agent_browser", return_value="/usr/bin/agent-browser"), \
             patch.object(bt, "_requires_real_termux_browser_install", return_value=False), \
             patch.object(bt, "_get_session_info", return_value={"session_name": "h_abc"}), \
             patch("tools.interrupt.is_interrupted", return_value=False), \
             patch("os.makedirs"), patch("os.open", return_value=3), patch("os.close"), \
             patch("os.unlink"), \
             patch("subprocess.Popen", return_value=proc), \
             patch("builtins.open", side_effect=_fake_open):
            return bt._run_browser_command("t1", "open", ["https://example.com"], timeout=30)

    def test_non_json_output_classified_distinctly(self):
        garbage = "{...about:blank...}\n<garbage daemon dump>"
        result = self._run_with_stdout(garbage)
        assert result["success"] is False
        assert result["error_type"] == "malformed_response"
        # The raw blob is preserved separately, not leaked into the main error.
        assert result["raw_output"]
        assert "Malformed" in result["error"]

    def test_valid_json_not_classified_as_malformed(self):
        good = json.dumps({"success": True, "data": {"url": "https://example.com"}})
        result = self._run_with_stdout(good)
        assert result["success"] is True
        assert "error_type" not in result


# ---------------------------------------------------------------------------
# Concurrency isolation (Phase 0.3)
# ---------------------------------------------------------------------------

class TestConcurrencyIsolation:
    def test_distinct_task_ids_get_distinct_sessions(self):
        with patch.object(bt, "_get_cdp_override", return_value=""), \
             patch.object(bt, "_get_cloud_provider", return_value=None), \
             patch.object(bt, "_start_browser_cleanup_thread"):
            s1 = bt._get_session_info("task-A")
            s2 = bt._get_session_info("task-B")
        assert s1["session_name"] != s2["session_name"]

    def test_same_task_id_reuses_session(self):
        with patch.object(bt, "_get_cdp_override", return_value=""), \
             patch.object(bt, "_get_cloud_provider", return_value=None), \
             patch.object(bt, "_start_browser_cleanup_thread"):
            s1 = bt._get_session_info("task-A")
            s2 = bt._get_session_info("task-A")
        assert s1["session_name"] == s2["session_name"]

    def test_parallel_navigations_use_isolated_sessions_and_sockets(self):
        """Two concurrent agents navigating in parallel must not collide.

        Each gets its own session_name and therefore its own socket dir under
        ``agent-browser-<session_name>``. The backend is fully mocked.
        """
        captured_socket_dirs: dict = {}
        lock = threading.Lock()

        def fake_run(task_id, command, args=None, timeout=None):
            info = bt._get_session_info(task_id)
            socket_dir = f"agent-browser-{info['session_name']}"
            with lock:
                captured_socket_dirs[task_id] = socket_dir
            return {"success": True, "data": {"url": (args or [""])[0], "title": "ok"}}

        with patch.object(bt, "_get_cdp_override", return_value=""), \
             patch.object(bt, "_get_cloud_provider", return_value=None), \
             patch.object(bt, "_start_browser_cleanup_thread"), \
             patch.object(bt, "_is_camofox_mode", return_value=False), \
             patch.object(bt, "_browser_backend_healthy", return_value=(True, "")), \
             patch.object(bt, "_get_command_timeout", return_value=30), \
             patch.object(bt, "_run_browser_command", side_effect=fake_run):

            results: dict = {}

            def nav(task_id, url):
                results[task_id] = bt.browser_navigate(url, task_id=task_id)

            threads = [
                threading.Thread(target=nav, args=("agent-1", "https://a.example")),
                threading.Thread(target=nav, args=("agent-2", "https://b.example")),
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        # Both navigations succeeded.
        for tid in ("agent-1", "agent-2"):
            assert json.loads(results[tid])["success"] is True

        # Crucially, the two agents resolved to DIFFERENT socket directories.
        assert captured_socket_dirs["agent-1"] != captured_socket_dirs["agent-2"]
