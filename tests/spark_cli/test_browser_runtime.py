"""Tests for Spark's managed agent-browser runtime."""

from __future__ import annotations

import os
import subprocess

from spark_cli import browser_runtime


def test_agent_browser_path_prefers_project_local_bin(monkeypatch, tmp_path):
    root = tmp_path / "project"
    local_bin = root / "node_modules" / ".bin"
    local_bin.mkdir(parents=True)
    binary = local_bin / ("agent-browser.cmd" if os.name == "nt" else "agent-browser")
    binary.write_text("#!/bin/sh\n")

    monkeypatch.setattr(browser_runtime, "get_project_root", lambda: root)
    monkeypatch.setattr(browser_runtime.shutil, "which", lambda name: "/usr/bin/agent-browser")

    assert browser_runtime.agent_browser_path() == str(binary)


def test_install_agent_browser_runs_npm_and_agent_browser_install(monkeypatch, tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "package.json").write_text('{"dependencies":{"agent-browser":"^0.27.1"}}')
    local_bin = root / "node_modules" / ".bin"
    local_bin.mkdir(parents=True)
    binary = local_bin / ("agent-browser.cmd" if os.name == "nt" else "agent-browser")
    binary.write_text("#!/bin/sh\n")
    calls: list[list[str]] = []

    monkeypatch.setattr(browser_runtime, "get_project_root", lambda: root)
    monkeypatch.setattr(browser_runtime, "npm_path", lambda: "/usr/bin/npm")
    monkeypatch.setattr(browser_runtime, "agent_browser_ready", lambda: (True, "ready"))
    monkeypatch.setattr(browser_runtime, "agent_browser_version", lambda: "agent-browser 0.27.1")

    def fake_run(cmd, **kwargs):
        calls.append([str(part) for part in cmd])
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(browser_runtime.subprocess, "run", fake_run)

    result = browser_runtime.install_agent_browser(quiet=True)

    assert result["ok"] is True
    assert calls[0] == ["/usr/bin/npm", "install", "--silent"]
    assert calls[1] == [str(binary), "install"]
