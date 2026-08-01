#!/usr/bin/env python3
"""Exercise packaged Spark desktop backend flows through its real HTTP API.

The caller owns application/sidecar startup. Run ``prepare`` before a restart
and ``resume`` afterwards with the same SPARK_HOME to prove persisted native
file state survives the packaged lifecycle.
"""

from __future__ import annotations

import argparse
import json
import platform
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AcceptanceReport:
    base_url: str
    phase: str
    platform: str
    checks: list[dict[str, Any]] = field(default_factory=list)

    def record(self, name: str, *, seconds: float, **details: Any) -> None:
        self.checks.append({"name": name, "ok": True, "seconds": round(seconds, 4), **details})


class DesktopClient:
    def __init__(self, base_url: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        query: dict[str, str] | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {path} returned HTTP {exc.code}: {detail}") from exc
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            return json.loads(payload)
        return payload.decode("utf-8", errors="replace")


def _timed(report: AcceptanceReport, name: str, operation, **details: Any) -> Any:
    started = time.perf_counter()
    result = operation()
    report.record(name, seconds=time.perf_counter() - started, **details)
    return result


def _ensure_project(client: DesktopClient, report: AcceptanceReport, slug: str) -> None:
    projects = _timed(
        report,
        "workspace.list",
        lambda: client.request("GET", "/api/workspace/projects"),
    )
    if any(item.get("slug") == slug for item in projects.get("projects", [])):
        return
    templates = client.request("GET", "/api/workspace/project-templates")
    available = templates.get("templates", [])
    if not available:
        raise RuntimeError("packaged backend exposed no project templates")
    template_ids = [str(item.get("id")) for item in available]
    template_id = "vanilla" if "vanilla" in template_ids else template_ids[0]
    created = _timed(
        report,
        "workspace.create",
        lambda: client.request(
            "POST",
            "/api/workspace/projects",
            body={"name": slug, "template": template_id},
        ),
        template=template_id,
    )
    if created.get("slug") != slug:
        raise RuntimeError(f"project slug mismatch: {created!r}")


def _write_and_read(
    client: DesktopClient,
    report: AcceptanceReport,
    slug: str,
    path: str,
    content: str,
) -> None:
    _timed(
        report,
        f"file.write.{path}",
        lambda: client.request(
            "PUT",
            f"/api/workspace/projects/{slug}/file",
            query={"path": path},
            body={"content": content},
        ),
    )
    payload = _timed(
        report,
        f"file.read.{path}",
        lambda: client.request(
            "GET",
            f"/api/workspace/projects/{slug}/file",
            query={"path": path},
        ),
    )
    if payload.get("content") != content:
        raise RuntimeError(f"packaged file round-trip mismatch for {path}")


def _verify_terminal(
    client: DesktopClient,
    report: AcceptanceReport,
    slug: str,
    platform_name: str,
) -> None:
    marker = "terminal-output.txt"
    command = (
        f"echo terminal-ok>{marker}"
        if platform_name == "windows"
        else f"printf terminal-ok > {marker}"
    )
    started = _timed(
        report,
        "terminal.start",
        lambda: client.request(
            "POST",
            f"/api/workspace/projects/{slug}/terminal/runs",
            body={"command": command},
        ),
        command_family="cmd" if platform_name == "windows" else "posix-shell",
    )
    if not started.get("run_id"):
        raise RuntimeError(f"terminal did not return a run ID: {started!r}")
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            payload = client.request(
                "GET",
                f"/api/workspace/projects/{slug}/file",
                query={"path": marker},
            )
            if payload.get("content", "").strip() == "terminal-ok":
                report.record("terminal.native", seconds=0.0, marker=marker)
                return
        except RuntimeError as exc:
            if "HTTP 404" not in str(exc):
                raise
        time.sleep(0.1)
    raise RuntimeError("native packaged terminal did not create its marker file")


def _verify_preview(client: DesktopClient, report: AcceptanceReport, slug: str) -> None:
    status = _timed(
        report,
        "preview.start",
        lambda: client.request(
            "POST",
            f"/api/workspace/projects/{slug}/preview/start",
            body={"url": f"{client.base_url}/"},
        ),
    )
    if status.get("status") != "running":
        raise RuntimeError(f"packaged preview did not become ready: {status!r}")
    current = client.request("GET", f"/api/workspace/projects/{slug}/preview/status")
    if current.get("status") != "running":
        raise RuntimeError(f"packaged preview status mismatch: {current!r}")
    _timed(
        report,
        "preview.stop",
        lambda: client.request("POST", f"/api/workspace/projects/{slug}/preview/stop"),
    )


def run_acceptance(
    base_url: str,
    phase: str,
    platform_name: str,
    project_slug: str,
) -> AcceptanceReport:
    report = AcceptanceReport(base_url=base_url, phase=phase, platform=platform_name)
    client = DesktopClient(base_url)
    root = _timed(report, "frontend.root", lambda: client.request("GET", "/"))
    if "<html" not in str(root).lower():
        raise RuntimeError("packaged frontend root did not return HTML")
    status = _timed(report, "backend.status", lambda: client.request("GET", "/api/status"))
    if not isinstance(status, dict) or not status.get("version"):
        raise RuntimeError(f"packaged status response is incomplete: {status!r}")
    _ensure_project(client, report, project_slug)

    if phase in {"prepare", "all"}:
        _write_and_read(client, report, project_slug, "resume-marker.txt", "persisted-ok")
        _verify_terminal(client, report, project_slug, platform_name)
        _verify_preview(client, report, project_slug)
    if phase in {"resume", "all"}:
        persisted = _timed(
            report,
            "file.resume",
            lambda: client.request(
                "GET",
                f"/api/workspace/projects/{project_slug}/file",
                query={"path": "resume-marker.txt"},
            ),
        )
        if persisted.get("content") != "persisted-ok":
            raise RuntimeError("packaged state did not survive restart")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--phase", choices=("prepare", "resume", "all"), default="all")
    parser.add_argument(
        "--platform",
        choices=("macos", "windows", "linux"),
        default={"Darwin": "macos", "Windows": "windows"}.get(platform.system(), "linux"),
    )
    parser.add_argument("--project", default="efficiency-desktop-smoke")
    args = parser.parse_args()
    report = run_acceptance(args.base_url, args.phase, args.platform, args.project)
    print(json.dumps(report.__dict__, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
