"""Tests for spark_cli.web_server and related config utilities."""

import os
import sys
import time
import urllib.request
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from spark_cli.config import (
    reload_env,
    redact_key,
    OPTIONAL_ENV_VARS,
)


# ---------------------------------------------------------------------------
# reload_env tests
# ---------------------------------------------------------------------------


class TestReloadEnv:
    """Tests for reload_env() — re-reads .env into os.environ."""

    def test_adds_new_vars(self, tmp_path):
        """reload_env() adds vars from .env that are not in os.environ."""
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_RELOAD_VAR=hello123\n")
        with patch("spark_cli.config.get_env_path", return_value=env_file):
            os.environ.pop("TEST_RELOAD_VAR", None)
            count = reload_env()
            assert count >= 1
            assert os.environ.get("TEST_RELOAD_VAR") == "hello123"
        os.environ.pop("TEST_RELOAD_VAR", None)

    def test_updates_changed_vars(self, tmp_path):
        """reload_env() updates vars whose value changed on disk."""
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_RELOAD_VAR=old_value\n")
        with patch("spark_cli.config.get_env_path", return_value=env_file):
            os.environ["TEST_RELOAD_VAR"] = "old_value"
            # Now change the file
            env_file.write_text("TEST_RELOAD_VAR=new_value\n")
            count = reload_env()
            assert count >= 1
            assert os.environ.get("TEST_RELOAD_VAR") == "new_value"
        os.environ.pop("TEST_RELOAD_VAR", None)

    def test_removes_deleted_known_vars(self, tmp_path):
        """reload_env() removes known Spark vars not present in .env."""
        env_file = tmp_path / ".env"
        env_file.write_text("")  # empty .env
        # Pick a known key from OPTIONAL_ENV_VARS
        known_key = next(iter(OPTIONAL_ENV_VARS.keys()))
        with patch("spark_cli.config.get_env_path", return_value=env_file):
            os.environ[known_key] = "stale_value"
            count = reload_env()
            assert known_key not in os.environ
            assert count >= 1

    def test_does_not_remove_unknown_vars(self, tmp_path):
        """reload_env() preserves non-Spark env vars even when absent from .env."""
        env_file = tmp_path / ".env"
        env_file.write_text("")
        with patch("spark_cli.config.get_env_path", return_value=env_file):
            os.environ["MY_CUSTOM_UNRELATED_VAR"] = "keep_me"
            reload_env()
            assert os.environ.get("MY_CUSTOM_UNRELATED_VAR") == "keep_me"
        os.environ.pop("MY_CUSTOM_UNRELATED_VAR", None)


# ---------------------------------------------------------------------------
# redact_key tests
# ---------------------------------------------------------------------------


class TestRedactKey:
    def test_long_key_shows_prefix_suffix(self):
        result = redact_key("sk-1234567890abcdef")
        assert result.startswith("sk-1")
        assert result.endswith("cdef")
        assert "..." in result

    def test_short_key_fully_masked(self):
        assert redact_key("short") == "***"

    def test_empty_key(self):
        result = redact_key("")
        assert "not set" in result.lower() or result == "***" or "\x1b" in result


# ---------------------------------------------------------------------------
# web_server tests (FastAPI endpoints)
# ---------------------------------------------------------------------------


class TestWebServerEndpoints:
    """Test the FastAPI REST endpoints using Starlette TestClient."""

    @pytest.fixture(autouse=True)
    def _setup_test_client(self):
        """Create a TestClient — import is deferred to avoid requiring fastapi."""
        try:
            from starlette.testclient import TestClient
        except ImportError:
            pytest.skip("fastapi/starlette not installed")

        from spark_cli.web_server import app
        self.client = TestClient(app)

    def test_kanban_board_endpoint(self):
        resp = self.client.get("/api/kanban/board")
        assert resp.status_code == 200
        data = resp.json()
        assert "columns" in data
        assert "triage" in data["columns"]
        assert "user_review" in data["columns"]

    def test_stream_screencast_501_when_backend_unsupported(self):
        """A backend without start_screencast → 501 so the pane keeps polling
        the /frame source (Item 2b graceful fallback)."""
        import spark_cli.workspace_routes as wr

        class _NoScreencast:
            viewport = (1280, 800)

        with patch.object(wr, "_streamed_session", return_value=(_NoScreencast(), RuntimeError)):
            resp = self.client.get("/api/workspace/projects/demo/preview/stream/screencast")
        assert resp.status_code == 501

    def test_stream_input_unsupported_verb_returns_400(self):
        """Extended input verbs (clipboard/upload) 400 on a backend that lacks
        them rather than crashing — the Playwright fallback degrades cleanly."""
        import spark_cli.workspace_routes as wr

        class _MinimalSession:
            current_url = "https://ex.com"
            title = "Ex"
            # No clipboard_write method → _require() must 400.

        with patch.object(wr, "_streamed_session", return_value=(_MinimalSession(), RuntimeError)):
            resp = self.client.post(
                "/api/workspace/projects/demo/preview/stream/input",
                json={"type": "clipboard-write", "text": "hi"},
            )
        assert resp.status_code == 400

    def test_stream_input_clipboard_read_returns_value(self):
        """clipboard-read surfaces the page clipboard text in the JSON body."""
        import spark_cli.workspace_routes as wr

        class _ClipSession:
            current_url = "https://ex.com"
            title = "Ex"

            def clipboard_read(self):
                return "copied-text"

        with patch.object(wr, "_streamed_session", return_value=(_ClipSession(), RuntimeError)):
            resp = self.client.post(
                "/api/workspace/projects/demo/preview/stream/input",
                json={"type": "clipboard-read"},
            )
        assert resp.status_code == 200
        assert resp.json()["clipboard"] == "copied-text"

    def test_available_models_codex_is_strict(self):
        """Managed OAuth catalogs (openai-codex) return a fixed list + strict=True
        so the Config editor renders a dropdown."""
        resp = self.client.get("/api/model/available", params={"provider": "openai-codex"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "openai-codex"
        assert data["strict"] is True
        assert "gpt-5.5" in data["models"]

    def test_available_models_open_providers_are_freetext(self):
        """Open-ended providers (ollama, openrouter) return strict=False so the
        Config editor keeps a free-text field (suggestions only)."""
        for provider in ("ollama", "openrouter"):
            resp = self.client.get("/api/model/available", params={"provider": provider})
            assert resp.status_code == 200
            data = resp.json()
            assert data["provider"] == provider
            assert data["strict"] is False
            assert isinstance(data["models"], list)

    def test_available_models_unknown_provider(self):
        """Unknown/custom providers return an empty, non-strict catalog."""
        resp = self.client.get("/api/model/available", params={"provider": "custom"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["models"] == []
        assert data["strict"] is False

    def test_mac_update_installer_script_stages_and_installs_app(self, tmp_path):
        import spark_cli.web_server as ws

        script = ws._build_mac_update_installer_script(
            dmg_path=tmp_path / "Spark-1.3.11.dmg",
            work_dir=tmp_path,
            log_path=tmp_path / "install.log",
        )

        assert "/usr/bin/hdiutil attach" in script
        assert "-mountpoint" in script
        assert "-name 'Spark.app'" in script
        assert "CFBundleIdentifier" in script
        assert "studio.fromtheroot.spark" in script
        assert "tell application id \"studio.fromtheroot.spark\" to quit" in script
        assert "/Applications/Spark.app" in script
        assert "with administrator privileges" in script
        assert "/usr/bin/open \"$INSTALL_PATH\"" in script

    def test_run_mac_update_downloads_and_starts_detached_installer(self, monkeypatch, tmp_path):
        import spark_cli.web_server as ws

        work_dir = tmp_path / "spark-update"
        popen_calls = []

        monkeypatch.setenv("SPARK_DESKTOP", "1")
        monkeypatch.setattr(
            ws,
            "_check_mac_update",
            lambda force=False: {
                "download_url": "https://example.com/Spark.dmg",
                "latest_version": "1.3.11",
            },
        )
        monkeypatch.setattr(ws.tempfile, "mkdtemp", lambda prefix: str(work_dir))

        def fake_urlretrieve(url, dest):
            Path(dest).parent.mkdir(parents=True, exist_ok=True)
            Path(dest).write_bytes(b"fake dmg")
            return dest, None

        class FakePopen:
            def __init__(self, args, **kwargs):
                popen_calls.append((args, kwargs))

        monkeypatch.setattr(ws.urllib.request, "urlretrieve", fake_urlretrieve)
        monkeypatch.setattr(ws.subprocess, "Popen", FakePopen)

        resp = self.client.post("/api/mac/update/run")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["status"] == "installing"
        assert data["path"].endswith("Spark-1.3.11.dmg")
        assert data["installer_script"].endswith("install-spark-update.zsh")
        assert data["log_path"].endswith("install.log")
        assert popen_calls
        assert popen_calls[0][0] == ["/bin/zsh", data["installer_script"]]
        assert popen_calls[0][1]["start_new_session"] is True
        assert not any(call[0][0] == "open" for call in popen_calls)
        script = (work_dir / "install-spark-update.zsh").read_text()
        assert "/usr/bin/hdiutil attach" in script
        assert "/Applications/Spark.app" in script

    def test_run_mac_update_requires_downloadable_release_asset(self, monkeypatch):
        import spark_cli.web_server as ws

        monkeypatch.setenv("SPARK_DESKTOP", "1")
        monkeypatch.setattr(
            ws,
            "_check_mac_update",
            lambda force=False: {"download_url": None, "latest_version": "1.3.11"},
        )

        resp = self.client.post("/api/mac/update/run")

        assert resp.status_code == 400
        assert "No downloadable macOS release found" in resp.json()["detail"]

    def test_run_mac_update_reports_download_failure(self, monkeypatch, tmp_path):
        import spark_cli.web_server as ws

        work_dir = tmp_path / "spark-update"

        monkeypatch.setenv("SPARK_DESKTOP", "1")
        monkeypatch.setattr(
            ws,
            "_check_mac_update",
            lambda force=False: {
                "download_url": "https://example.com/Spark.dmg",
                "latest_version": "1.3.11",
            },
        )
        monkeypatch.setattr(ws.tempfile, "mkdtemp", lambda prefix: str(work_dir))
        monkeypatch.setattr(
            ws.urllib.request,
            "urlretrieve",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("network down")),
        )

        resp = self.client.post("/api/mac/update/run")

        assert resp.status_code == 500
        assert "Failed to start macOS update installer" in resp.json()["detail"]
        assert "network down" in resp.json()["detail"]

    def test_oauth_endpoints_accept_dashboard_token(self):
        """OAuth connect/disconnect must accept the dashboard token (not only the
        per-process session token) — the desktop app authenticates with the
        dashboard token, and a session-only check made these endpoints 401 even
        though the rest of the dashboard was authorized."""
        import spark_cli.web_server as ws

        with patch.object(ws, "get_configured_dashboard_secret", return_value="testsecret"), \
             patch("spark_cli.auth.clear_provider_auth", return_value=True):
            # TestClient is a trusted local client; the important regression is
            # that dashboard-token auth reaches the handler instead of requiring
            # only the ephemeral session token.
            ok = self.client.request(
                "DELETE",
                "/api/providers/oauth/openai-codex",
                headers={"Authorization": "Bearer testsecret"},
            )
            assert ok.status_code != 401

    def test_oauth_start_accepts_trusted_local_client(self):
        """Local desktop/web clients should pass the same auth rule as the
        dashboard middleware instead of being forced through session-token auth."""
        import spark_cli.web_server as ws

        with patch.object(ws, "get_configured_dashboard_secret", return_value="testsecret"), \
             patch.object(ws, "_start_device_code_flow", return_value={"session_id": "s", "flow": "device_code"}):
            resp = self.client.post(
                "/api/providers/oauth/openai-codex/start",
                headers={"Content-Type": "application/json"},
                json={},
            )
            assert resp.status_code != 401

    def test_codex_cli_auth_preference_only_when_installed(self, monkeypatch):
        """Auto mode uses the official Codex CLI only when it is installed; users
        without Codex installed still get Spark's built-in device-code flow."""
        import spark_cli.web_server as ws

        monkeypatch.delenv("SPARK_CODEX_DEVICE_AUTH_IMPL", raising=False)
        monkeypatch.setattr(ws.shutil, "which", lambda name: "/usr/bin/codex" if name == "codex" else None)
        assert ws._codex_cli_device_login_preferred() is True

        monkeypatch.setattr(ws.shutil, "which", lambda _name: None)
        assert ws._codex_cli_device_login_preferred() is False

        monkeypatch.setenv("SPARK_CODEX_DEVICE_AUTH_IMPL", "inline")
        monkeypatch.setattr(ws.shutil, "which", lambda name: "/usr/bin/codex" if name == "codex" else None)
        assert ws._codex_cli_device_login_preferred() is False

    def test_codex_cli_auth_returns_false_when_no_code_is_emitted(self, monkeypatch):
        """The WebUI must not sit forever at "requesting code" if an installed
        Codex CLI does not print a device code; Spark should fall back inline."""
        import spark_cli.web_server as ws

        class SilentCodexProcess:
            stdout = []

            def poll(self):
                return None

            def terminate(self):
                pass

            def wait(self, timeout=None):
                return 0

            def kill(self):
                pass

        monkeypatch.delenv("SPARK_CODEX_DEVICE_AUTH_IMPL", raising=False)
        monkeypatch.setenv("SPARK_CODEX_CLI_DEVICE_AUTH_CODE_TIMEOUT_SECONDS", "0.01")
        monkeypatch.setattr(ws.shutil, "which", lambda name: "/usr/bin/codex" if name == "codex" else None)
        monkeypatch.setattr(ws.subprocess, "Popen", lambda *args, **kwargs: SilentCodexProcess())

        assert ws._codex_cli_device_login_worker("missing-session") is False

    def test_kanban_task_create_patch_comment_and_link(self):
        parent_resp = self.client.post(
            "/api/kanban/tasks",
            json={"title": "Parent web task", "assignee": "worker-a"},
        )
        child_resp = self.client.post(
            "/api/kanban/tasks",
            json={"title": "Child web task", "assignee": "worker-b"},
        )
        assert parent_resp.status_code == 200
        assert child_resp.status_code == 200
        parent = parent_resp.json()
        child = child_resp.json()
        assert parent["status"] == "todo"
        assert child["status"] == "todo"

        patch_resp = self.client.patch(
            f"/api/kanban/tasks/{child['id']}",
            json={"status": "blocked", "priority": 7},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["priority"] == 7

        comment_resp = self.client.post(
            f"/api/kanban/tasks/{child['id']}/comments",
            json={"body": "Needs review", "author": "test"},
        )
        assert comment_resp.status_code == 200
        assert comment_resp.json()["ok"] is True

        link_resp = self.client.post(
            "/api/kanban/links",
            json={"parent_id": parent["id"], "child_id": child["id"]},
        )
        assert link_resp.status_code == 200
        assert link_resp.json() == {"ok": True}

    def test_kanban_bulk_patch_reports_partial_errors(self):
        created = self.client.post(
            "/api/kanban/tasks",
            json={"title": "Bulk web task", "assignee": "worker-a"},
        ).json()

        resp = self.client.post(
            "/api/kanban/tasks/bulk",
            json={"ids": [created["id"], "missing"], "status": "done"},
        )

        assert resp.status_code == 200
        assert resp.json() == {"ok": False, "errors": {"missing": "Task not found"}}

    def test_kanban_dispatch_dry_run_shape(self):
        created = self.client.post(
            "/api/kanban/tasks",
            json={"title": "Ready dispatch web task", "assignee": "worker-a"},
        ).json()
        self.client.patch(
            f"/api/kanban/tasks/{created['id']}",
            json={"status": "ready"},
        )

        resp = self.client.post("/api/kanban/dispatch?max_tasks=3&dry_run=true")

        assert resp.status_code == 200
        body = resp.json()
        assert body["dry_run"] is True
        assert created["id"] in body["ready"]
        assert "blocked_by_assignee" in body

    def test_workspace_terminal_run_streams_output_in_project_cwd(self):
        created = self.client.post("/api/workspace/projects", json={"name": "terminal-test"}).json()
        slug = created["slug"]

        start = self.client.post(
            f"/api/workspace/projects/{slug}/terminal/runs",
            json={"command": "pwd; printf 'hello-workspace\\n'"},
        )

        assert start.status_code == 200
        run = start.json()
        assert run["cwd"].endswith(f"/workspace/{slug}")

        chunks = []
        with self.client.stream(
            "GET",
            f"/api/workspace/projects/{slug}/terminal/runs/{run['run_id']}/stream",
        ) as resp:
            assert resp.status_code == 200
            for line in resp.iter_lines():
                if line.startswith("data: "):
                    chunks.append(line)
                    if '"type": "done"' in line:
                        break

        joined = "\n".join(chunks)
        assert f"/workspace/{slug}" in joined
        assert "hello-workspace" in joined
        assert '"exit_code": 0' in joined

    def test_workspace_terminal_interactive_shell_accepts_input(self):
        created = self.client.post("/api/workspace/projects", json={"name": "terminal-shell-test"}).json()
        slug = created["slug"]

        start = self.client.post(f"/api/workspace/projects/{slug}/terminal/runs", json={})
        assert start.status_code == 200
        run_id = start.json()["run_id"]

        resized = None
        for _ in range(20):
            resized = self.client.post(
                f"/api/workspace/projects/{slug}/terminal/runs/{run_id}/resize",
                json={"rows": 33, "cols": 101},
            )
            if resized.status_code == 200:
                break
            time.sleep(0.05)
        assert resized is not None
        assert resized.status_code == 200
        assert resized.json()["rows"] == 33
        assert resized.json()["cols"] == 101

        sent = self.client.post(
            f"/api/workspace/projects/{slug}/terminal/runs/{run_id}/input",
            json={"input": "printf 'interactive-ok\\n'; exit\n"},
        )
        assert sent.status_code == 200

        chunks = []
        with self.client.stream(
            "GET",
            f"/api/workspace/projects/{slug}/terminal/runs/{run_id}/stream",
        ) as resp:
            assert resp.status_code == 200
            for line in resp.iter_lines():
                if line.startswith("data: "):
                    chunks.append(line)
                    if '"type": "done"' in line:
                        break

        joined = "\n".join(chunks)
        assert "interactive-ok" in joined

    def test_workspace_terminal_rejects_invalid_or_missing_project(self):
        invalid = self.client.post(
            "/api/workspace/projects/bad$name/terminal/runs",
            json={"command": "pwd"},
        )
        missing = self.client.post(
            "/api/workspace/projects/missing-project/terminal/runs",
            json={"command": "pwd"},
        )
        empty = self.client.post(
            "/api/workspace/projects/missing-project/terminal/runs",
            json={"command": ""},
        )

        assert invalid.status_code == 400
        assert missing.status_code == 404
        assert empty.status_code == 404

    def test_workspace_preview_serves_static_project(self):
        created = self.client.post("/api/workspace/projects", json={"name": "preview-static"}).json()
        slug = created["slug"]
        project_dir = created["path"]
        with open(os.path.join(project_dir, "index.html"), "w", encoding="utf-8") as fh:
            fh.write("<!doctype html><title>Preview OK</title><h1>preview-ok</h1>")

        start = self.client.post(f"/api/workspace/projects/{slug}/preview/start", json={})
        try:
            assert start.status_code == 200
            body = start.json()
            # The preview starts as "starting" and is promoted to "running" only
            # once an HTTP probe succeeds (readiness gate, _await_preview_ready).
            assert body["status"] in {"starting", "running"}
            assert body["kind"] == "static"
            assert body["url"].startswith("http://127.0.0.1:")
            assert not body["url"].startswith("http://0.0.0.0")

            # Poll the status endpoint until the readiness gate flips to running.
            status = body
            for _ in range(60):
                status = self.client.get(f"/api/workspace/projects/{slug}/preview/status").json()
                if status["status"] == "running":
                    break
                assert status["status"] in {"starting", "running"}, status
                time.sleep(0.05)
            assert status["status"] == "running"

            html = ""
            for _ in range(20):
                try:
                    with urllib.request.urlopen(body["url"], timeout=1) as resp:
                        html = resp.read().decode("utf-8")
                    break
                except Exception:
                    time.sleep(0.05)
            assert "preview-ok" in html

            logs = self.client.get(f"/api/workspace/projects/{slug}/preview/logs")
            assert logs.status_code == 200
            assert any("http.server" in item["text"] for item in logs.json()["logs"])
        finally:
            stopped = self.client.post(f"/api/workspace/projects/{slug}/preview/stop")
            assert stopped.status_code == 200

    def test_workspace_preview_navigation_is_general_browser(self):
        created = self.client.post("/api/workspace/projects", json={"name": "preview-nav"}).json()
        slug = created["slug"]

        unsafe = self.client.post(
            f"/api/workspace/projects/{slug}/preview/navigate",
            json={"url": "javascript:alert(1)"},
        )
        external = self.client.post(
            f"/api/workspace/projects/{slug}/preview/navigate",
            json={"url": "https://example.com"},
        )
        shorthand = self.client.post(
            f"/api/workspace/projects/{slug}/preview/navigate",
            json={"url": "example.org/path"},
        )

        assert unsafe.status_code == 400
        assert external.status_code == 200
        assert external.json()["url"] == "https://example.com"
        assert external.json()["kind"] == "browser"
        assert shorthand.status_code == 200
        assert shorthand.json()["url"] == "https://example.org/path"


    def test_workspace_preview_snapshot_and_config(self):
        created = self.client.post("/api/workspace/projects", json={"name": "preview-config"}).json()
        slug = created["slug"]
        project_dir = created["path"]
        with open(os.path.join(project_dir, "index.html"), "w", encoding="utf-8") as fh:
            fh.write("<!doctype html><title>Configured</title><main>configured-preview</main>")
        with open(os.path.join(project_dir, "spark.preview.json"), "w", encoding="utf-8") as fh:
            fh.write('{"autoRefresh": true, "autoVerify": false}')

        start = self.client.post(f"/api/workspace/projects/{slug}/preview/start", json={})
        try:
            assert start.status_code == 200
            assert 4173 <= int(start.json()["port"]) <= 6173
            # The page is opened (and its title becomes snapshot-able) only after
            # the readiness gate promotes the session to "running".
            for _ in range(60):
                if self.client.get(
                    f"/api/workspace/projects/{slug}/preview/status"
                ).json()["status"] == "running":
                    break
                time.sleep(0.05)
            snapshot = self.client.get(f"/api/workspace/projects/{slug}/preview/snapshot")
            assert snapshot.status_code == 200
            body = snapshot.json()
            assert body["title"] == "Configured"
            assert "configured-preview" in body["text"]
        finally:
            self.client.post(f"/api/workspace/projects/{slug}/preview/stop")

    def test_workspace_preview_reuses_existing_project_server(self, monkeypatch):
        from spark_cli import workspace_routes as routes

        created = self.client.post("/api/workspace/projects", json={"name": "preview-existing"}).json()
        slug = created["slug"]

        monkeypatch.setattr(
            routes,
            "_find_running_project_preview",
            lambda project_dir: {
                "kind": "existing",
                "command": None,
                "url": "http://127.0.0.1:5949",
                "port": 5949,
                "process": None,
                "auto_refresh": False,
                "auto_verify": True,
            },
        )
        monkeypatch.setattr(routes, "_run_agent_browser", lambda *args, **kwargs: {"success": True})

        start = self.client.post(f"/api/workspace/projects/{slug}/preview/start", json={})

        assert start.status_code == 200
        body = start.json()
        assert body["status"] == "running"
        assert body["kind"] == "existing"
        assert body["url"] == "http://127.0.0.1:5949"
        assert body["command"] is None

    def test_workspace_preview_uses_recent_chat_url(self, monkeypatch):
        from core.spark_state import SessionDB
        from spark_cli import workspace_routes as routes

        created = self.client.post("/api/workspace/projects", json={"name": "preview-remembered"}).json()
        slug = created["slug"]
        session_id = "preview_remembered_session"
        db = SessionDB()
        try:
            db._conn.execute(
                "INSERT OR REPLACE INTO sessions (id, source, model, started_at, title) VALUES (?, ?, ?, ?, ?)",
                (session_id, f"workspace:{slug}", "test-model", time.time(), "remembered preview"),
            )
            db._conn.execute(
                "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                (
                    session_id,
                    "assistant",
                    "I started the project and pointed the preview at: http://nova:5949",
                    time.time(),
                ),
            )
            db._conn.commit()
        finally:
            db.close()

        monkeypatch.setattr(routes, "_probe_preview_url", lambda url: url == "http://nova:5949")
        monkeypatch.setattr(routes, "_run_agent_browser", lambda *args, **kwargs: {"success": True})

        start = self.client.post(f"/api/workspace/projects/{slug}/preview/start", json={})

        assert start.status_code == 200
        body = start.json()
        assert body["status"] == "running"
        assert body["kind"] == "remembered"
        assert body["url"] == "http://nova:5949"
        assert body["port"] == 5949
        assert body["command"] is None

    def test_workspace_preview_logs_are_bounded_and_redacted(self):
        from spark_cli import workspace_routes as routes

        slug = "log-test"
        session = {"logs": [], "updated_at": time.time()}
        for idx in range(505):
            routes._append_preview_log(
                slug,
                session,
                f"line {idx} API_KEY=secret-{idx}\n",
                "server",
            )

        assert len(session["logs"]) == 500
        assert all("secret-" not in entry["text"] for entry in session["logs"])
        assert any("[redacted]" in entry["text"] for entry in session["logs"])

    def test_workspace_preview_invalid_config_reports_400(self):
        created = self.client.post("/api/workspace/projects", json={"name": "preview-bad-config"}).json()
        slug = created["slug"]
        project_dir = created["path"]
        with open(os.path.join(project_dir, "index.html"), "w", encoding="utf-8") as fh:
            fh.write("<h1>bad config</h1>")
        with open(os.path.join(project_dir, "spark.preview.json"), "w", encoding="utf-8") as fh:
            fh.write("{bad json")

        resp = self.client.post(f"/api/workspace/projects/{slug}/preview/start", json={})

        assert resp.status_code == 400

    def test_workspace_preview_agent_tools_return_bounded_json(self):
        from tools import preview_tool

        created = self.client.post("/api/workspace/projects", json={"name": "preview-tools"}).json()
        slug = created["slug"]
        project_dir = created["path"]
        with open(os.path.join(project_dir, "index.html"), "w", encoding="utf-8") as fh:
            fh.write("<!doctype html><title>Tools</title><main>tool-preview</main>")

        try:
            opened = preview_tool.preview_open(slug)
            assert '"success": true' in opened
            snapshot = preview_tool.preview_snapshot(slug)
            assert len(snapshot) < 14000
            assert "tool-preview" in snapshot
            console = preview_tool.preview_console(slug)
            assert len(console) < 14000
            assert '"messages"' in console
        finally:
            self.client.post(f"/api/workspace/projects/{slug}/preview/stop")

    def test_kanban_complete_endpoint_moves_to_user_review(self):
        created = self.client.post(
            "/api/kanban/tasks",
            json={"title": "Review web task", "assignee": "worker-a"},
        ).json()

        resp = self.client.post(
            f"/api/kanban/tasks/{created['id']}/complete",
            json={"summary": "Ready for review"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "user_review"
        assert body["result"] == "Ready for review"

    def test_kanban_missing_comment_and_link_errors_are_clean(self):
        comment_resp = self.client.post(
            "/api/kanban/tasks/missing/comments",
            json={"body": "Nope"},
        )
        assert comment_resp.status_code == 404

        link_resp = self.client.post(
            "/api/kanban/links",
            json={"parent_id": "missing-a", "child_id": "missing-b"},
        )
        assert link_resp.status_code == 400

    def test_dashboard_auth_info_public(self):
        resp = self.client.get("/api/dashboard/auth/info")
        assert resp.status_code == 200
        body = resp.json()
        assert "require_auth_nonlocal" in body
        assert "token_file" in body

    def test_get_status(self):
        resp = self.client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "version" in data
        assert "server_instance_id" in data
        assert "spark_home" in data
        assert "active_sessions" in data

    def test_admin_actions_metadata_and_confirmation_gate(self):
        resp = self.client.get("/api/admin/actions")
        assert resp.status_code == 200
        actions = {item["id"]: item for item in resp.json()["actions"]}
        assert "gateway.restart" in actions
        assert actions["gateway.restart"]["requires_confirmation"] is True
        assert "args_schema" in actions["diagnostics.debug"]

        blocked = self.client.post("/api/admin/actions/gateway.restart", json={"confirm": False})
        assert blocked.status_code == 400
        assert "Confirmation required" in blocked.text

    def test_admin_action_run_lifecycle(self, monkeypatch):
        import spark_cli.web_server as web_server

        action = web_server.AdminAction(
            "test.echo",
            "Echo",
            "Test action",
            "low",
            lambda _args: [sys.executable, "-c", "print('admin-ok')"],
        )
        monkeypatch.setitem(web_server.ADMIN_ACTIONS, "test.echo", action)

        started = self.client.post("/api/admin/actions/test.echo", json={})
        assert started.status_code == 200
        run_id = started.json()["run_id"]

        for _ in range(100):
            state = self.client.get(f"/api/admin/actions/runs/{run_id}").json()
            if state["status"] in {"done", "failed"}:
                break
            time.sleep(0.05)

        assert state["status"] == "done"
        assert any(line["text"] == "admin-ok" for line in state["output_tail"])

    def test_admin_resource_endpoints(self):
        gateway = self.client.get("/api/gateway/status")
        assert gateway.status_code == 200
        assert gateway.json()["ok"] is True

        profiles = self.client.get("/api/profiles")
        assert profiles.status_code == 200
        assert "profiles" in profiles.json()

        plugins = self.client.get("/api/plugins")
        assert plugins.status_code == 200
        assert "plugins" in plugins.json()

        mcp = self.client.get("/api/mcp/servers")
        assert mcp.status_code == 200
        assert "servers" in mcp.json()

        diag = self.client.get("/api/diagnostics/summary")
        assert diag.status_code == 200
        assert "actions" in diag.json()

    def test_get_status_filters_unconfigured_gateway_platforms(self, monkeypatch):
        import gateway.config as gateway_config
        import spark_cli.web_server as web_server

        class _Platform:
            def __init__(self, value):
                self.value = value

        class _GatewayConfig:
            def get_connected_platforms(self):
                return [_Platform("telegram")]

        monkeypatch.setattr(web_server, "get_running_pid", lambda: 1234)
        monkeypatch.setattr(
            web_server,
            "read_runtime_status",
            lambda: {
                "gateway_state": "running",
                "updated_at": "2026-04-12T00:00:00+00:00",
                "platforms": {
                    "telegram": {"state": "connected", "updated_at": "2026-04-12T00:00:00+00:00"},
                    "whatsapp": {"state": "retrying", "updated_at": "2026-04-12T00:00:00+00:00"},
                    "feishu": {"state": "connected", "updated_at": "2026-04-12T00:00:00+00:00"},
                },
            },
        )
        monkeypatch.setattr(web_server, "check_config_version", lambda: (1, 1))
        monkeypatch.setattr(gateway_config, "load_gateway_config", lambda: _GatewayConfig())

        resp = self.client.get("/api/status")

        assert resp.status_code == 200
        assert resp.json()["gateway_platforms"] == {
            "telegram": {"state": "connected", "updated_at": "2026-04-12T00:00:00+00:00"},
        }

    def test_get_status_hides_stale_platforms_when_gateway_not_running(self, monkeypatch):
        import gateway.config as gateway_config
        import spark_cli.web_server as web_server

        class _GatewayConfig:
            def get_connected_platforms(self):
                return []

        monkeypatch.setattr(web_server, "get_running_pid", lambda: None)
        monkeypatch.setattr(
            web_server,
            "read_runtime_status",
            lambda: {
                "gateway_state": "startup_failed",
                "updated_at": "2026-04-12T00:00:00+00:00",
                "platforms": {
                    "whatsapp": {"state": "retrying", "updated_at": "2026-04-12T00:00:00+00:00"},
                    "feishu": {"state": "connected", "updated_at": "2026-04-12T00:00:00+00:00"},
                },
            },
        )
        monkeypatch.setattr(web_server, "check_config_version", lambda: (1, 1))
        monkeypatch.setattr(gateway_config, "load_gateway_config", lambda: _GatewayConfig())

        resp = self.client.get("/api/status")

        assert resp.status_code == 200
        assert resp.json()["gateway_state"] == "startup_failed"
        assert resp.json()["gateway_platforms"] == {}

    def test_get_config_schema(self):
        resp = self.client.get("/api/config/schema")
        assert resp.status_code == 200
        data = resp.json()
        assert "fields" in data
        assert "category_order" in data
        schema = data["fields"]
        assert len(schema) > 100  # Should have 150+ fields
        assert "model" in schema
        # Verify category_order is a non-empty list
        assert isinstance(data["category_order"], list)
        assert len(data["category_order"]) > 0
        assert "general" in data["category_order"]

    def test_get_config_defaults(self):
        resp = self.client.get("/api/config/defaults")
        assert resp.status_code == 200
        defaults = resp.json()
        assert "model" in defaults

    def test_get_env_vars(self):
        resp = self.client.get("/api/env")
        assert resp.status_code == 200
        data = resp.json()
        # Should contain known env var names
        assert any(k.endswith("_API_KEY") or k.endswith("_TOKEN") for k in data.keys())

    def test_reveal_env_var(self, tmp_path):
        """POST /api/env/reveal should return the real unredacted value."""
        from spark_cli.config import save_env_value
        from spark_cli.web_server import _SESSION_TOKEN
        save_env_value("TEST_REVEAL_KEY", "super-secret-value-12345")
        resp = self.client.post(
            "/api/env/reveal",
            json={"key": "TEST_REVEAL_KEY"},
            headers={"Authorization": f"Bearer {_SESSION_TOKEN}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["key"] == "TEST_REVEAL_KEY"
        assert data["value"] == "super-secret-value-12345"

    def test_reveal_env_var_not_found(self):
        """POST /api/env/reveal should 404 for unknown keys."""
        from spark_cli.web_server import _SESSION_TOKEN
        resp = self.client.post(
            "/api/env/reveal",
            json={"key": "NONEXISTENT_KEY_XYZ"},
            headers={"Authorization": f"Bearer {_SESSION_TOKEN}"},
        )
        assert resp.status_code == 404

    def test_reveal_env_var_no_token(self, tmp_path):
        """POST /api/env/reveal without token should return 401."""
        from spark_cli.config import save_env_value
        save_env_value("TEST_REVEAL_NOAUTH", "secret-value")
        resp = self.client.post(
            "/api/env/reveal",
            json={"key": "TEST_REVEAL_NOAUTH"},
        )
        assert resp.status_code == 401

    def test_reveal_env_var_bad_token(self, tmp_path):
        """POST /api/env/reveal with wrong token should return 401."""
        from spark_cli.config import save_env_value
        save_env_value("TEST_REVEAL_BADAUTH", "secret-value")
        resp = self.client.post(
            "/api/env/reveal",
            json={"key": "TEST_REVEAL_BADAUTH"},
            headers={"Authorization": "Bearer wrong-token-here"},
        )
        assert resp.status_code == 401

    def test_session_token_endpoint(self):
        """GET /api/auth/session-token should return a token."""
        from spark_cli.web_server import _SESSION_TOKEN
        resp = self.client.get("/api/auth/session-token")
        assert resp.status_code == 200
        assert resp.json()["token"] == _SESSION_TOKEN

    def test_path_traversal_blocked(self):
        """Verify URL-encoded path traversal is blocked."""
        # %2e%2e = ..
        resp = self.client.get("/%2e%2e/%2e%2e/etc/passwd")
        # Should return 200 with index.html (SPA fallback), not the actual file
        assert resp.status_code in (200, 404)
        if resp.status_code == 200:
            # Should be the SPA fallback, not the system file
            assert "root:" not in resp.text

    def test_path_traversal_dotdot_blocked(self):
        """Direct .. path traversal via encoded sequences."""
        resp = self.client.get("/%2e%2e/spark_cli/web_server.py")
        assert resp.status_code in (200, 404)
        if resp.status_code == 200:
            assert "FastAPI" not in resp.text  # Should not serve the actual source


# ---------------------------------------------------------------------------
# _build_schema_from_config tests
# ---------------------------------------------------------------------------


class TestBuildSchemaFromConfig:
    def test_produces_expected_field_count(self):
        from spark_cli.web_server import CONFIG_SCHEMA
        # DEFAULT_CONFIG has ~150+ leaf fields
        assert len(CONFIG_SCHEMA) > 100

    def test_schema_entries_have_required_fields(self):
        from spark_cli.web_server import CONFIG_SCHEMA
        for key, entry in list(CONFIG_SCHEMA.items())[:10]:
            assert "type" in entry, f"Missing type for {key}"
            assert "category" in entry, f"Missing category for {key}"

    def test_overrides_applied(self):
        from spark_cli.web_server import CONFIG_SCHEMA
        # terminal.backend should be a select with options
        if "terminal.backend" in CONFIG_SCHEMA:
            entry = CONFIG_SCHEMA["terminal.backend"]
            assert entry["type"] == "select"
            assert "options" in entry
            assert "local" in entry["options"]

    def test_empty_prefix_produces_correct_keys(self):
        from spark_cli.web_server import _build_schema_from_config
        test_config = {"model": "test", "nested": {"key": "val"}}
        schema = _build_schema_from_config(test_config)
        assert "model" in schema
        assert "nested.key" in schema

    def test_top_level_scalars_get_general_category(self):
        """Top-level scalar fields should be in 'general' unless overridden."""
        from spark_cli.web_server import CONFIG_SCHEMA
        assert CONFIG_SCHEMA["toolsets"]["category"] == "general"

    def test_nested_keys_get_parent_category(self):
        """Nested fields should use the top-level parent as their category."""
        from spark_cli.web_server import CONFIG_SCHEMA
        if "agent.max_turns" in CONFIG_SCHEMA:
            assert CONFIG_SCHEMA["agent.max_turns"]["category"] == "agent"

    def test_category_merge_applied(self):
        """Small categories should be merged into larger ones."""
        from spark_cli.web_server import CONFIG_SCHEMA
        categories = {e["category"] for e in CONFIG_SCHEMA.values()}
        # These should be merged away
        assert "privacy" not in categories  # merged into security
        assert "context" not in categories  # merged into agent

    def test_no_single_field_categories(self):
        """After merging, no category should have just 1 field."""
        from spark_cli.web_server import CONFIG_SCHEMA
        from collections import Counter
        cats = Counter(e["category"] for e in CONFIG_SCHEMA.values())
        for cat, count in cats.items():
            assert count >= 2, f"Category '{cat}' has only {count} field(s) — should be merged"


# ---------------------------------------------------------------------------
# Config round-trip tests
# ---------------------------------------------------------------------------


class TestConfigRoundTrip:
    """Verify config survives GET → edit → PUT without data loss."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        try:
            from starlette.testclient import TestClient
        except ImportError:
            pytest.skip("fastapi/starlette not installed")
        from spark_cli.web_server import app
        self.client = TestClient(app)

    def test_get_config_no_internal_keys(self):
        """GET /api/config should not expose _config_version or _model_meta."""
        config = self.client.get("/api/config").json()
        internal = [k for k in config if k.startswith("_")]
        assert not internal, f"Internal keys leaked to frontend: {internal}"

    def test_get_config_model_is_string(self):
        """GET /api/config should normalize model dict to a string."""
        config = self.client.get("/api/config").json()
        assert isinstance(config.get("model"), str), \
            f"model should be string, got {type(config.get('model'))}"

    def test_round_trip_preserves_model_subkeys(self):
        """Save and reload should not lose model.provider, model.base_url, etc."""
        from spark_cli.config import load_config, save_config

        # Set up a config with model as a dict (the common user config form)
        save_config({
            "model": {
                "default": "anthropic/claude-sonnet-4",
                "provider": "openrouter",
                "base_url": "https://openrouter.ai/api/v1",
                "api_mode": "openai",
            }
        })

        before = load_config()
        assert isinstance(before.get("model"), dict)
        original_keys = set(before["model"].keys())

        # GET → PUT unchanged
        web_config = self.client.get("/api/config").json()
        assert isinstance(web_config.get("model"), str), "GET should normalize model to string"

        self.client.put("/api/config", json={"config": web_config})

        after = load_config()
        assert isinstance(after.get("model"), dict), "model should still be a dict after save"
        assert set(after["model"].keys()) >= original_keys, \
            f"Lost model subkeys: {original_keys - set(after['model'].keys())}"

    def test_edit_model_name_preserved(self):
        """Changing the model string should update model.default on disk."""
        from spark_cli.config import load_config

        web_config = self.client.get("/api/config").json()
        original_model = web_config["model"]

        # Change model
        web_config["model"] = "test/editing-model"
        self.client.put("/api/config", json={"config": web_config})

        after = load_config()
        if isinstance(after.get("model"), dict):
            assert after["model"]["default"] == "test/editing-model"
        else:
            assert after["model"] == "test/editing-model"

        # Restore
        web_config["model"] = original_model
        self.client.put("/api/config", json={"config": web_config})

    def test_edit_nested_value(self):
        """Editing a nested config value should persist correctly."""
        from spark_cli.config import load_config

        web_config = self.client.get("/api/config").json()
        original_turns = web_config.get("agent", {}).get("max_turns")

        # Change max_turns
        if "agent" not in web_config:
            web_config["agent"] = {}
        web_config["agent"]["max_turns"] = 42

        self.client.put("/api/config", json={"config": web_config})

        after = load_config()
        assert after.get("agent", {}).get("max_turns") == 42

        # Restore
        web_config["agent"]["max_turns"] = original_turns
        self.client.put("/api/config", json={"config": web_config})

    def test_schema_types_match_config_values(self):
        """Every schema field should have a matching-type value in the config."""
        config = self.client.get("/api/config").json()
        schema_resp = self.client.get("/api/config/schema").json()
        schema = schema_resp["fields"]

        def get_nested(obj, path):
            parts = path.split(".")
            cur = obj
            for p in parts:
                if cur is None or not isinstance(cur, dict):
                    return None
                cur = cur.get(p)
            return cur

        mismatches = []
        for key, entry in schema.items():
            val = get_nested(config, key)
            if val is None:
                continue  # not set in user config — fine
            expected = entry["type"]
            if expected in ("string", "select") and not isinstance(val, str):
                mismatches.append(f"{key}: expected str, got {type(val).__name__}")
            elif expected == "number" and not isinstance(val, (int, float)):
                mismatches.append(f"{key}: expected number, got {type(val).__name__}")
            elif expected == "boolean" and not isinstance(val, bool):
                mismatches.append(f"{key}: expected bool, got {type(val).__name__}")
            elif expected == "list" and not isinstance(val, list):
                mismatches.append(f"{key}: expected list, got {type(val).__name__}")
        assert not mismatches, "Type mismatches:\n" + "\n".join(mismatches)


# ---------------------------------------------------------------------------
# New feature endpoint tests
# ---------------------------------------------------------------------------


class TestNewEndpoints:
    """Tests for session detail, logs, cron, skills, tools, raw config, analytics."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        try:
            from starlette.testclient import TestClient
        except ImportError:
            pytest.skip("fastapi/starlette not installed")
        from spark_cli.web_server import app
        self.client = TestClient(app)

    def test_get_logs_default(self):
        resp = self.client.get("/api/logs")
        assert resp.status_code == 200
        data = resp.json()
        assert "file" in data
        assert "lines" in data
        assert isinstance(data["lines"], list)

    def test_get_logs_invalid_file(self):
        resp = self.client.get("/api/logs?file=nonexistent")
        assert resp.status_code == 400

    def test_download_log_returns_known_log_file(self):
        from core.spark_constants import get_spark_home

        logs_dir = get_spark_home() / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        (logs_dir / "agent.log").write_text("hello from logs\n", encoding="utf-8")

        resp = self.client.get("/api/logs/download?file=agent")

        assert resp.status_code == 200
        assert resp.text == "hello from logs\n"
        assert "agent.log" in resp.headers["content-disposition"]

    def test_download_log_rejects_unknown_file(self):
        resp = self.client.get("/api/logs/download?file=../agent")
        assert resp.status_code == 400

    def test_cron_list(self):
        resp = self.client.get("/api/cron/jobs")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_cron_job_not_found(self):
        resp = self.client.get("/api/cron/jobs/nonexistent-id")
        assert resp.status_code == 404

    def test_cron_job_update_accepts_schedule_string(self):
        create_resp = self.client.post(
            "/api/cron/jobs",
            json={"prompt": "daily report", "schedule": "0 9 * * *", "name": "Report", "deliver": "local"},
        )
        assert create_resp.status_code == 200
        job_id = create_resp.json()["id"]

        update_resp = self.client.put(
            f"/api/cron/jobs/{job_id}",
            json={"updates": {"prompt": "updated report", "schedule": "30 13 * * *", "name": "Updated Report"}},
        )

        assert update_resp.status_code == 200
        updated = update_resp.json()
        assert updated["prompt"] == "updated report"
        assert updated["name"] == "Updated Report"
        assert updated["schedule"]["expr"] == "30 13 * * *"
        assert updated["schedule_display"] == "30 13 * * *"

    def test_skills_list(self):
        resp = self.client.get("/api/skills")
        assert resp.status_code == 200
        skills = resp.json()
        assert isinstance(skills, list)
        if skills:
            assert "name" in skills[0]
            assert "enabled" in skills[0]

    def test_skills_list_includes_disabled_skills(self, monkeypatch):
        import tools.skills_sync as skills_sync
        import tools.skills_tool as skills_tool
        import spark_cli.skills_config as skills_config
        import spark_cli.web_server as web_server

        sync_calls = []

        def _fake_find_all_skills(*, skip_disabled=False):
            if skip_disabled:
                return [
                    {"name": "active-skill", "description": "active", "category": "demo"},
                    {"name": "design-md", "description": "design", "category": "creative"},
                    {"name": "disabled-skill", "description": "disabled", "category": "demo"},
                    {"name": "frontend-design", "description": "frontend", "category": "creative"},
                ]
            return [
                {"name": "active-skill", "description": "active", "category": "demo"},
            ]

        monkeypatch.setattr(skills_sync, "sync_skills", lambda quiet=True: sync_calls.append(quiet) or {})
        monkeypatch.setattr(skills_tool, "_find_all_skills", _fake_find_all_skills)
        monkeypatch.setattr(skills_config, "get_disabled_skills", lambda config: {"disabled-skill"})
        monkeypatch.setattr(web_server, "load_config", lambda: {"skills": {"disabled": ["disabled-skill"]}})

        resp = self.client.get("/api/skills")

        assert resp.status_code == 200
        assert sync_calls == [True]
        assert resp.json() == [
            {
                "name": "active-skill",
                "description": "active",
                "category": "demo",
                "enabled": True,
                "use_count": 0,
                "view_count": 0,
                "patch_count": 0,
                "skill_state": "active",
            },
            {
                "name": "design-md",
                "description": "design",
                "category": "creative",
                "enabled": True,
                "use_count": 0,
                "view_count": 0,
                "patch_count": 0,
                "skill_state": "active",
            },
            {
                "name": "disabled-skill",
                "description": "disabled",
                "category": "demo",
                "enabled": False,
                "use_count": 0,
                "view_count": 0,
                "patch_count": 0,
                "skill_state": "active",
            },
            {
                "name": "frontend-design",
                "description": "frontend",
                "category": "creative",
                "enabled": True,
                "use_count": 0,
                "view_count": 0,
                "patch_count": 0,
                "skill_state": "active",
            },
        ]

    def test_toolsets_list(self):
        resp = self.client.get("/api/tools/toolsets")
        assert resp.status_code == 200
        toolsets = resp.json()
        assert isinstance(toolsets, list)
        if toolsets:
            assert "name" in toolsets[0]
            assert "label" in toolsets[0]
            assert "enabled" in toolsets[0]

    def test_toolsets_list_matches_cli_enabled_state(self, monkeypatch):
        import spark_cli.tools_config as tools_config
        import core.toolsets as toolsets_module
        import spark_cli.web_server as web_server

        monkeypatch.setattr(
            tools_config,
            "_get_effective_configurable_toolsets",
            lambda: [
                ("web", "🔍 Web Search & Scraping", "web_search, web_extract"),
                ("skills", "📚 Skills", "list, view, manage"),
                ("memory", "💾 Memory", "persistent memory across sessions"),
            ],
        )
        monkeypatch.setattr(
            tools_config,
            "_get_platform_tools",
            lambda config, platform, include_default_mcp_servers=False: {"web", "skills"},
        )
        monkeypatch.setattr(
            tools_config,
            "_toolset_has_keys",
            lambda ts_key, config=None: ts_key != "web",
        )
        monkeypatch.setattr(
            toolsets_module,
            "resolve_toolset",
            lambda name: {
                "web": ["web_search", "web_extract"],
                "skills": ["skills_list", "skill_view"],
                "memory": ["memory_read"],
            }[name],
        )
        monkeypatch.setattr(web_server, "load_config", lambda: {"platform_toolsets": {"cli": ["web", "skills"]}})

        resp = self.client.get("/api/tools/toolsets")

        assert resp.status_code == 200
        assert resp.json() == [
            {
                "name": "web",
                "label": "🔍 Web Search & Scraping",
                "description": "web_search, web_extract",
                "enabled": True,
                "available": True,
                "configured": False,
                "tools": ["web_extract", "web_search"],
            },
            {
                "name": "skills",
                "label": "📚 Skills",
                "description": "list, view, manage",
                "enabled": True,
                "available": True,
                "configured": True,
                "tools": ["skill_view", "skills_list"],
            },
            {
                "name": "memory",
                "label": "💾 Memory",
                "description": "persistent memory across sessions",
                "enabled": False,
                "available": False,
                "configured": True,
                "tools": ["memory_read"],
            },
        ]

    def test_computer_use_slash_enables_web_and_falls_through_for_task(self, monkeypatch):
        import platform
        import spark_cli.tools_config as tools_config
        import spark_cli.web_server as web_server

        calls = []

        monkeypatch.setattr(platform, "system", lambda: "Darwin")
        monkeypatch.setattr(
            tools_config,
            "enable_computer_use_web_toolset",
            lambda: calls.append("enabled"),
        )

        result = web_server._execute_web_slash_command(
            "session-123",
            "/computer-use open Helium browser",
        )

        assert result is None
        assert calls == ["enabled"]

    def test_computer_use_slash_refreshes_stale_web_agent_tools(self, monkeypatch):
        import spark_cli.web_server as web_server

        class Agent:
            session_id = "session-123"
            disabled_toolsets = None
            enabled_toolsets = set()
            tools = []
            valid_tool_names = set()
            invalidated = False

            def _invalidate_system_prompt(self):
                self.invalidated = True

        agent = Agent()

        monkeypatch.setattr(
            "spark_cli.config.load_config",
            lambda: {"platform_toolsets": {"cli": ["computer_use"]}},
        )
        def fake_get_platform_tools(config, platform):
            assert platform == "cli"
            return {"computer_use", "terminal"}

        monkeypatch.setattr("spark_cli.tools_config._get_platform_tools", fake_get_platform_tools)
        monkeypatch.setattr(
            "core.model_tools.get_tool_definitions",
            lambda enabled_toolsets, disabled_toolsets, quiet_mode: [
                {"function": {"name": "computer_use"}},
            ],
        )

        web_server._refresh_web_agent_for_computer_use(
            agent,
            "[Project: demo]\n\n/computer-use open Helium browser",
        )

        assert agent.enabled_toolsets == {"computer_use", "terminal"}
        assert agent.valid_tool_names == {"computer_use"}
        assert agent.invalidated is True

    def test_config_raw_get(self):
        resp = self.client.get("/api/config/raw")
        assert resp.status_code == 200
        assert "yaml" in resp.json()

    def test_config_raw_put_valid(self):
        resp = self.client.put(
            "/api/config/raw",
            json={"yaml_text": "model: test\ntoolsets:\n  - all\n"},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_config_raw_put_invalid(self):
        resp = self.client.put(
            "/api/config/raw",
            json={"yaml_text": "- this is a list not a dict"},
        )
        assert resp.status_code == 400

    def test_analytics_usage(self):
        resp = self.client.get("/api/analytics/usage?days=7")
        assert resp.status_code == 200
        data = resp.json()
        assert "daily" in data
        assert "by_model" in data
        assert "totals" in data
        assert isinstance(data["daily"], list)
        assert "total_sessions" in data["totals"]

    def test_session_token_endpoint(self):
        from spark_cli.web_server import _SESSION_TOKEN
        resp = self.client.get("/api/auth/session-token")
        assert resp.status_code == 200
        assert resp.json()["token"] == _SESSION_TOKEN


# ---------------------------------------------------------------------------
# Model context length: normalize/denormalize + /api/model/info
# ---------------------------------------------------------------------------


class TestModelContextLength:
    """Tests for model_context_length in normalize/denormalize and /api/model/info."""

    def test_normalize_extracts_context_length_from_dict(self):
        """normalize should surface context_length from model dict."""
        from spark_cli.web_server import _normalize_config_for_web

        cfg = {
            "model": {
                "default": "anthropic/claude-opus-4.6",
                "provider": "openrouter",
                "context_length": 200000,
            }
        }
        result = _normalize_config_for_web(cfg)
        assert result["model"] == "anthropic/claude-opus-4.6"
        assert result["model_provider"] == "openrouter"
        assert result["model_base_url"] == ""
        assert result["model_api_mode"] == ""
        assert result["model_context_length"] == 200000

    def test_normalize_bare_string_model_yields_zero(self):
        """normalize should set model_context_length=0 for bare string model."""
        from spark_cli.web_server import _normalize_config_for_web

        result = _normalize_config_for_web({"model": "anthropic/claude-sonnet-4"})
        assert result["model"] == "anthropic/claude-sonnet-4"
        assert result["model_provider"] == ""
        assert result["model_base_url"] == ""
        assert result["model_api_mode"] == ""
        assert result["model_context_length"] == 0

    def test_normalize_dict_without_context_length_yields_zero(self):
        """normalize should default to 0 when model dict has no context_length."""
        from spark_cli.web_server import _normalize_config_for_web

        cfg = {"model": {"default": "test/model", "provider": "openrouter"}}
        result = _normalize_config_for_web(cfg)
        assert result["model_context_length"] == 0

    def test_normalize_non_int_context_length_yields_zero(self):
        """normalize should coerce non-int context_length to 0."""
        from spark_cli.web_server import _normalize_config_for_web

        cfg = {"model": {"default": "test/model", "context_length": "invalid"}}
        result = _normalize_config_for_web(cfg)
        assert result["model_context_length"] == 0

    def test_denormalize_writes_context_length_into_model_dict(self):
        """denormalize should write model_context_length back into model dict."""
        from spark_cli.web_server import _denormalize_config_from_web
        from spark_cli.config import save_config

        # Set up disk config with model as a dict
        save_config({
            "model": {"default": "anthropic/claude-opus-4.6", "provider": "openrouter"}
        })

        result = _denormalize_config_from_web({
            "model": "anthropic/claude-opus-4.6",
            "model_context_length": 100000,
        })
        assert isinstance(result["model"], dict)
        assert result["model"]["context_length"] == 100000
        assert "model_context_length" not in result  # virtual field removed

    def test_denormalize_zero_removes_context_length(self):
        """denormalize with model_context_length=0 should remove context_length key."""
        from spark_cli.web_server import _denormalize_config_from_web
        from spark_cli.config import save_config

        save_config({
            "model": {
                "default": "anthropic/claude-opus-4.6",
                "provider": "openrouter",
                "context_length": 50000,
            }
        })

        result = _denormalize_config_from_web({
            "model": "anthropic/claude-opus-4.6",
            "model_context_length": 0,
        })
        assert isinstance(result["model"], dict)
        assert "context_length" not in result["model"]

    def test_denormalize_upgrades_bare_string_to_dict(self):
        """denormalize should upgrade bare string model to dict when context_length set."""
        from spark_cli.web_server import _denormalize_config_from_web
        from spark_cli.config import save_config

        # Disk has model as bare string
        save_config({"model": "anthropic/claude-sonnet-4"})

        result = _denormalize_config_from_web({
            "model": "anthropic/claude-sonnet-4",
            "model_context_length": 65000,
        })
        assert isinstance(result["model"], dict)
        assert result["model"]["default"] == "anthropic/claude-sonnet-4"
        assert result["model"]["context_length"] == 65000

    def test_denormalize_bare_string_stays_string_when_zero(self):
        """denormalize should keep bare string model as string when context_length=0."""
        from spark_cli.web_server import _denormalize_config_from_web
        from spark_cli.config import save_config

        save_config({"model": "anthropic/claude-sonnet-4"})

        result = _denormalize_config_from_web({
            "model": "anthropic/claude-sonnet-4",
            "model_context_length": 0,
        })
        assert result["model"] == "anthropic/claude-sonnet-4"

    def test_denormalize_coerces_string_context_length(self):
        """denormalize should handle string model_context_length from frontend."""
        from spark_cli.web_server import _denormalize_config_from_web
        from spark_cli.config import save_config

        save_config({
            "model": {"default": "test/model", "provider": "openrouter"}
        })

        result = _denormalize_config_from_web({
            "model": "test/model",
            "model_context_length": "32000",
        })
        assert isinstance(result["model"], dict)
        assert result["model"]["context_length"] == 32000

    def test_denormalize_writes_model_virtual_fields(self):
        from spark_cli.config import save_config
        from spark_cli.web_server import _denormalize_config_from_web

        save_config({"model": "gpt-5.5"})

        result = _denormalize_config_from_web({
            "model": "gpt-5.5",
            "model_provider": "openai-codex",
            "model_base_url": "https://chatgpt.com/backend-api/codex",
            "model_api_mode": "codex_responses",
            "model_context_length": 0,
        })

        assert result["model"] == {
            "default": "gpt-5.5",
            "provider": "openai-codex",
            "base_url": "https://chatgpt.com/backend-api/codex",
            "api_mode": "codex_responses",
        }


class TestModelContextLengthSchema:
    """Tests for model_context_length placement in CONFIG_SCHEMA."""

    def test_schema_has_model_context_length(self):
        from spark_cli.web_server import CONFIG_SCHEMA
        assert "model_context_length" in CONFIG_SCHEMA

    def test_schema_model_context_length_after_model(self):
        """Model virtual fields should render together near the top."""
        from spark_cli.web_server import CONFIG_SCHEMA
        keys = list(CONFIG_SCHEMA.keys())
        model_idx = keys.index("model")
        assert keys[model_idx + 1] == "model_provider"
        assert keys[model_idx + 2] == "model_base_url"
        assert keys[model_idx + 3] == "model_api_mode"
        assert keys[model_idx + 4] == "model_context_length"

    def test_schema_model_context_length_is_number(self):
        from spark_cli.web_server import CONFIG_SCHEMA
        entry = CONFIG_SCHEMA["model_context_length"]
        assert entry["type"] == "number"
        assert "category" in entry

    def test_schema_has_general_category_for_multi_model_routing(self):
        from spark_cli.web_server import CONFIG_SCHEMA

        assert CONFIG_SCHEMA["model"]["category"] == "general"
        assert CONFIG_SCHEMA["model_provider"]["category"] == "general"
        assert CONFIG_SCHEMA["model_context_length"]["category"] == "general"
        assert CONFIG_SCHEMA["smart_model_routing.enabled"]["category"] == "general"
        assert (
            CONFIG_SCHEMA["smart_model_routing.cheap_model.model"]["category"]
            == "general"
        )
        assert "Multi-model" in CONFIG_SCHEMA["smart_model_routing.enabled"]["description"]

    def test_schema_exposes_fast_model_fields(self):
        from spark_cli.web_server import CONFIG_SCHEMA

        assert "smart_model_routing.cheap_model.provider" in CONFIG_SCHEMA
        assert "smart_model_routing.cheap_model.model" in CONFIG_SCHEMA
        assert "smart_model_routing.cheap_model.base_url" in CONFIG_SCHEMA
        assert "smart_model_routing.cheap_model.api_mode" in CONFIG_SCHEMA


class TestModelInfoEndpoint:
    """Tests for GET /api/model/info endpoint."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        try:
            from starlette.testclient import TestClient
        except ImportError:
            pytest.skip("fastapi/starlette not installed")
        from spark_cli.web_server import app
        self.client = TestClient(app)

    def test_model_info_returns_200(self):
        resp = self.client.get("/api/model/info")
        assert resp.status_code == 200
        data = resp.json()
        assert "model" in data
        assert "provider" in data
        assert "auto_context_length" in data
        assert "config_context_length" in data
        assert "effective_context_length" in data
        assert "capabilities" in data

    def test_model_info_with_dict_config(self, monkeypatch):
        import spark_cli.web_server as ws

        monkeypatch.setattr(ws, "load_config", lambda: {
            "model": {
                "default": "anthropic/claude-opus-4.6",
                "provider": "openrouter",
                "context_length": 100000,
            }
        })

        with patch("agent.model_metadata.get_model_context_length", return_value=200000):
            resp = self.client.get("/api/model/info")

        data = resp.json()
        assert data["model"] == "anthropic/claude-opus-4.6"
        assert data["provider"] == "openrouter"
        assert data["auto_context_length"] == 200000
        assert data["config_context_length"] == 100000
        assert data["effective_context_length"] == 100000  # override wins

    def test_model_info_auto_detect_when_no_override(self, monkeypatch):
        import spark_cli.web_server as ws

        monkeypatch.setattr(ws, "load_config", lambda: {
            "model": {"default": "anthropic/claude-opus-4.6", "provider": "openrouter"}
        })

        with patch("agent.model_metadata.get_model_context_length", return_value=200000):
            resp = self.client.get("/api/model/info")

        data = resp.json()
        assert data["auto_context_length"] == 200000
        assert data["config_context_length"] == 0
        assert data["effective_context_length"] == 200000  # auto wins

    def test_model_info_empty_model(self, monkeypatch):
        import spark_cli.web_server as ws

        monkeypatch.setattr(ws, "load_config", lambda: {"model": ""})

        resp = self.client.get("/api/model/info")
        data = resp.json()
        assert data["model"] == ""
        assert data["effective_context_length"] == 0

    def test_model_info_bare_string_model(self, monkeypatch):
        import spark_cli.web_server as ws

        monkeypatch.setattr(ws, "load_config", lambda: {
            "model": "anthropic/claude-sonnet-4"
        })

        with patch("agent.model_metadata.get_model_context_length", return_value=200000):
            resp = self.client.get("/api/model/info")

        data = resp.json()
        assert data["model"] == "anthropic/claude-sonnet-4"
        assert data["provider"] == ""
        assert data["config_context_length"] == 0
        assert data["effective_context_length"] == 200000

    def test_model_info_capabilities(self, monkeypatch):
        import spark_cli.web_server as ws

        monkeypatch.setattr(ws, "load_config", lambda: {
            "model": {"default": "anthropic/claude-opus-4.6", "provider": "openrouter"}
        })

        mock_caps = MagicMock()
        mock_caps.supports_tools = True
        mock_caps.supports_vision = True
        mock_caps.supports_reasoning = True
        mock_caps.context_window = 200000
        mock_caps.max_output_tokens = 32000
        mock_caps.model_family = "claude-opus"

        with patch("agent.model_metadata.get_model_context_length", return_value=200000), \
             patch("agent.models_dev.get_model_capabilities", return_value=mock_caps):
            resp = self.client.get("/api/model/info")

        caps = resp.json()["capabilities"]
        assert caps["supports_tools"] is True
        assert caps["supports_vision"] is True
        assert caps["supports_reasoning"] is True
        assert caps["max_output_tokens"] == 32000
        assert caps["model_family"] == "claude-opus"

    def test_model_info_graceful_on_metadata_error(self, monkeypatch):
        """Endpoint should return zeros on import/resolution errors, not 500."""
        import spark_cli.web_server as ws

        monkeypatch.setattr(ws, "load_config", lambda: {
            "model": "some/obscure-model"
        })

        with patch("agent.model_metadata.get_model_context_length", side_effect=Exception("boom")):
            resp = self.client.get("/api/model/info")

        assert resp.status_code == 200
        data = resp.json()
        assert data["auto_context_length"] == 0
