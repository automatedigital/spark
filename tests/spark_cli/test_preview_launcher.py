"""Platform-specific launch and lifecycle contracts for workspace previews."""

from __future__ import annotations

import json
import signal
from pathlib import Path

from spark_cli import workspace_routes as w


def test_windows_preview_argv_uses_comspec_and_cmd_shim(monkeypatch):
    monkeypatch.setattr(w.sys, "platform", "win32")
    monkeypatch.setenv("COMSPEC", r"C:\\Windows\\System32\\cmd.exe")
    monkeypatch.setattr(w.shutil, "which", lambda name: r"C:\\Tools\\npm.cmd" if name in {"npm", "npm.cmd"} else None)

    argv = w._preview_launch_argv("npm run dev -- --port 4173")

    assert argv[:3] == [r"C:\\Windows\\System32\\cmd.exe", "/d", "/s"]
    assert argv[4].startswith(r"C:\\Tools\\npm.cmd run dev")
    assert "/bin/bash" not in " ".join(argv)
    assert "-lc" not in argv


def test_unix_preview_argv_preserves_login_shell(monkeypatch):
    monkeypatch.setattr(w.sys, "platform", "linux")
    monkeypatch.setenv("SHELL", "/usr/bin/zsh")

    assert w._preview_launch_argv("npm run dev") == ["/usr/bin/zsh", "-lc", "npm run dev"]


def test_windows_popen_options_use_utf8_and_process_group(monkeypatch):
    monkeypatch.setattr(w.sys, "platform", "win32")
    options = w._preview_popen_kwargs({"PORT": "4173"})

    assert options["encoding"] == "utf-8"
    assert options["errors"] == "replace"
    assert "start_new_session" not in options
    assert options["creationflags"]


def test_unix_popen_options_use_new_session(monkeypatch):
    monkeypatch.setattr(w.sys, "platform", "linux")
    options = w._preview_popen_kwargs({"PORT": "4173"})

    assert options["start_new_session"] is True
    assert "creationflags" not in options


def test_windows_detected_commands_resolve_native_shims(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(w.sys, "platform", "win32")
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"dev": "vite"}}), encoding="utf-8")
    monkeypatch.setattr(w, "_port_is_free", lambda _port: True)

    def fake_which(name: str) -> str | None:
        return {"npm.cmd": r"C:\\Node\\npm.cmd", "npm": r"C:\\Node\\npm.cmd"}.get(name)

    monkeypatch.setattr(w.shutil, "which", fake_which)
    detected = w._detect_preview(tmp_path)

    assert detected["kind"] == "node"
    assert detected["command"].startswith(r"C:\\Node\\npm.cmd run dev")


def test_stop_preview_windows_kills_process_tree(monkeypatch):
    monkeypatch.setattr(w.sys, "platform", "win32")
    calls: list[list[str]] = []

    class FakeProc:
        pid = 1234

        def poll(self):
            return None

        def terminate(self):
            raise AssertionError("taskkill should handle a live Windows tree")

        def kill(self):
            raise AssertionError("taskkill should handle a live Windows tree")

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(w.subprocess, "run", lambda argv, **kwargs: calls.append(argv) or Result())
    w._preview_sessions["windows-stop"] = {
        "slug": "windows-stop",
        "status": "running",
        "url": "http://127.0.0.1:4173",
        "process": FakeProc(),
    }

    try:
        result = w._stop_preview_session("windows-stop")
    finally:
        w._preview_sessions.pop("windows-stop", None)

    assert result["status"] == "stopped"
    assert calls == [["taskkill", "/PID", "1234", "/T", "/F"]]


def test_stop_preview_unix_kills_process_group(monkeypatch):
    monkeypatch.setattr(w.sys, "platform", "linux")
    calls: list[tuple[int, signal.Signals]] = []

    class FakeProc:
        pid = 9876

        def poll(self):
            return None

        def terminate(self):
            raise AssertionError("process-group termination should be attempted first")

        def kill(self):
            raise AssertionError("process-group termination should be attempted first")

    monkeypatch.setattr(w.os, "killpg", lambda pid, sig: calls.append((pid, sig)))
    w._preview_sessions["unix-stop"] = {
        "slug": "unix-stop",
        "status": "running",
        "url": "http://127.0.0.1:4173",
        "process": FakeProc(),
    }

    try:
        w._stop_preview_session("unix-stop")
    finally:
        w._preview_sessions.pop("unix-stop", None)

    assert calls == [(9876, signal.SIGTERM)]
