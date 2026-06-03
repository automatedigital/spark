"""Managed agent-browser runtime helpers for Spark's sidebar browser."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from spark_cli.config import get_project_root

AGENT_BROWSER_PACKAGE = "agent-browser"


def _npm_project_root() -> Path:
    start = get_project_root()
    for candidate in [start, *start.parents]:
        package_json = candidate / "package.json"
        if not package_json.exists():
            continue
        try:
            text = package_json.read_text(encoding="utf-8")
        except OSError:
            continue
        if AGENT_BROWSER_PACKAGE in text:
            return candidate
    return start


def _candidate_node_bins() -> list[Path]:
    root = _npm_project_root()
    candidates = [
        root / "node_modules" / ".bin",
        root / "src" / "spark_cli" / "web" / "node_modules" / ".bin",
    ]
    return [p for p in candidates if p.exists()]


def agent_browser_path() -> str | None:
    """Return Spark's preferred agent-browser executable path."""
    exe_name = "agent-browser.cmd" if os.name == "nt" else "agent-browser"
    for bin_dir in _candidate_node_bins():
        candidate = bin_dir / exe_name
        if candidate.exists():
            return str(candidate)
    return shutil.which("agent-browser")


def node_path() -> str | None:
    return shutil.which("node")


def npm_path() -> str | None:
    root = get_project_root()
    candidates = [
        root / "node_modules" / ".bin" / ("npm.cmd" if os.name == "nt" else "npm"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return shutil.which("npm")


def agent_browser_version() -> str | None:
    binary = agent_browser_path()
    if not binary:
        return None
    try:
        result = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception:
        return None
    version = (result.stdout or result.stderr).strip()
    return version or None


def agent_browser_ready() -> tuple[bool, str]:
    binary = agent_browser_path()
    if not binary:
        return False, "agent-browser is not installed"
    try:
        result = subprocess.run(
            [
                binary,
                "--session",
                "spark-runtime-check",
                "--json",
                "open",
                "about:blank",
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except Exception as exc:
        return False, str(exc)
    if result.returncode == 0:
        return True, "ready"
    detail = (result.stderr or result.stdout).strip()
    return False, detail or f"agent-browser exited with code {result.returncode}"


def install_agent_browser(*, quiet: bool = False) -> dict[str, Any]:
    """Install/update Spark's local agent-browser package and browser runtime."""
    root = _npm_project_root()
    npm = npm_path()
    if not npm:
        return {"ok": False, "error": "npm is not installed"}
    if not (root / "package.json").exists():
        return {"ok": False, "error": f"package.json not found at {root}"}

    env = dict(os.environ)
    if str(root / "node_modules" / ".bin") not in env.get("PATH", ""):
        env["PATH"] = f"{root / 'node_modules' / '.bin'}{os.pathsep}{env.get('PATH', '')}"

    commands = [
        [npm, "install", "--silent"],
    ]
    output: list[str] = []
    for command in commands:
        if not quiet:
            print(f"-> {' '.join(command)}")
        result = subprocess.run(
            command,
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        output.extend([result.stdout.strip(), result.stderr.strip()])
        if result.returncode != 0:
            return {
                "ok": False,
                "error": (result.stderr or result.stdout).strip() or f"{command[0]} failed",
                "output": "\n".join(part for part in output if part),
            }

    binary = agent_browser_path()
    if not binary:
        return {"ok": False, "error": "agent-browser binary was not created by npm install"}

    install_cmd = [binary, "install"]
    if not quiet:
        print(f"-> {' '.join(install_cmd)}")
    result = subprocess.run(
        install_cmd,
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )
    output.extend([result.stdout.strip(), result.stderr.strip()])
    if result.returncode != 0:
        return {
            "ok": False,
            "error": (result.stderr or result.stdout).strip() or "agent-browser install failed",
            "output": "\n".join(part for part in output if part),
            "binary": binary,
        }

    ready, detail = agent_browser_ready()
    return {
        "ok": ready,
        "error": None if ready else detail,
        "binary": binary,
        "version": agent_browser_version(),
        "output": "\n".join(part for part in output if part),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage Spark's agent-browser runtime")
    sub = parser.add_subparsers(dest="command", required=True)
    install_parser = sub.add_parser("install")
    install_parser.add_argument("--quiet", action="store_true")
    sub.add_parser("status")
    args = parser.parse_args(argv)

    if args.command == "install":
        result = install_agent_browser(quiet=args.quiet)
        if result.get("ok"):
            if not args.quiet:
                print(f"OK agent-browser ready ({result.get('version') or result.get('binary')})")
            return 0
        print(f"WARN agent-browser setup failed: {result.get('error')}", file=sys.stderr)
        return 1

    ready, detail = agent_browser_ready()
    if ready:
        print(f"OK agent-browser ready ({agent_browser_version() or agent_browser_path()})")
        return 0
    print(f"WARN agent-browser not ready: {detail}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
