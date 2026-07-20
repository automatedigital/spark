"""Health checks for the Spark web dashboard.

Used by update/install flows to ensure a headless gateway restart did not leave
the VPS/LAN dashboard unavailable while the messaging gateway stayed healthy.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib import error, request

_WILDCARD_HOSTS = {"", "*", "0.0.0.0", "::", "[::]"}


class _FrontendAssetParser(HTMLParser):
    """Collect local assets that must exist for the dashboard to boot."""

    def __init__(self) -> None:
        super().__init__()
        self.paths: set[str] = set()

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        values = dict(attrs)
        candidate = values.get("src") if tag == "script" else values.get("href")
        if candidate and candidate.startswith("/assets/"):
            self.paths.add(candidate.split("?", 1)[0].split("#", 1)[0])


@dataclass
class DashboardHealthResult:
    enabled: bool
    ok: bool
    url: str
    host: str
    port: int
    status_code: int | None = None
    error: str = ""


def dashboard_frontend_assets_ready(web_dist: Path | None = None) -> tuple[bool, str]:
    """Return whether ``index.html`` and its exact hashed assets are coherent."""
    dist = web_dist or (Path(__file__).parent / "web_dist")
    if not dist.exists():
        return False, f"Dashboard frontend bundle is missing: {dist}"
    if not (dist / "index.html").is_file():
        return False, f"Dashboard frontend index is missing: {dist / 'index.html'}"
    assets_dir = dist / "assets"
    if not assets_dir.is_dir():
        return False, f"Dashboard frontend assets directory is missing: {assets_dir}"
    if not any(assets_dir.glob("*.js")):
        return False, f"Dashboard frontend JavaScript assets are missing: {assets_dir}"
    if not any(assets_dir.glob("*.css")):
        return False, f"Dashboard frontend CSS assets are missing: {assets_dir}"

    try:
        parser = _FrontendAssetParser()
        parser.feed((dist / "index.html").read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        return False, f"Dashboard frontend index cannot be read: {exc}"
    if not parser.paths:
        return False, "Dashboard frontend index does not reference any bundled assets"

    missing = [
        path
        for path in sorted(parser.paths)
        if not (dist / path.removeprefix("/")).is_file()
    ]
    if missing:
        return False, (
            "Dashboard frontend index references missing assets: "
            + ", ".join(missing)
        )
    return True, ""


def _load_dashboard_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    if config is None:
        from spark_cli.config import load_config

        loaded = load_config()
        config = loaded if isinstance(loaded, dict) else {}
    dash = config.get("dashboard") if isinstance(config, dict) else {}
    return dash if isinstance(dash, dict) else {}


def dashboard_probe_host(host: str) -> str:
    """Return a local probe host for a configured bind host."""
    host = str(host or "").strip()
    if host in _WILDCARD_HOSTS:
        return "127.0.0.1"
    return host


def _url_host(host: str) -> str:
    if ":" in host and not host.startswith("["):
        return f"[{host}]"
    return host


def dashboard_health_url(config: dict[str, Any] | None = None) -> tuple[bool, str, str, int]:
    dash = _load_dashboard_config(config)
    enabled = bool(dash.get("enabled_with_gateway", True))
    host = str(dash.get("host", "0.0.0.0"))
    port = int(dash.get("port", 9119))
    probe_host = dashboard_probe_host(host)
    return enabled, f"http://{_url_host(probe_host)}:{port}/api/dashboard/auth/info", host, port


def check_dashboard_health(
    config: dict[str, Any] | None = None,
    *,
    timeout: float = 2.0,
    wait_seconds: float = 0.0,
    interval: float = 1.0,
) -> DashboardHealthResult:
    enabled, url, host, port = dashboard_health_url(config)
    if not enabled:
        return DashboardHealthResult(
            enabled=False,
            ok=True,
            url=url,
            host=host,
            port=port,
        )

    assets_ready, assets_error = dashboard_frontend_assets_ready()
    if not assets_ready:
        return DashboardHealthResult(
            enabled=True,
            ok=False,
            url=url,
            host=host,
            port=port,
            error=assets_error,
        )

    deadline = time.monotonic() + max(0.0, wait_seconds)
    last_error = ""
    last_status: int | None = None

    while True:
        try:
            req = request.Request(url, headers={"User-Agent": "spark-dashboard-health/1.0"})
            with request.urlopen(req, timeout=timeout) as response:
                status = int(response.getcode())
                if 200 <= status < 400:
                    return DashboardHealthResult(
                        enabled=True,
                        ok=True,
                        url=url,
                        host=host,
                        port=port,
                        status_code=status,
                    )
                last_status = status
                last_error = f"HTTP {status}"
        except error.HTTPError as exc:
            last_status = int(exc.code)
            last_error = f"HTTP {exc.code}"
        except Exception as exc:
            last_error = str(exc)

        if time.monotonic() >= deadline:
            return DashboardHealthResult(
                enabled=True,
                ok=False,
                url=url,
                host=host,
                port=port,
                status_code=last_status,
                error=last_error,
            )
        time.sleep(max(0.1, interval))


def format_dashboard_health_failure(result: DashboardHealthResult) -> str:
    detail = f" ({result.error})" if result.error else ""
    return (
        f"Dashboard did not respond at {result.url}{detail}.\n"
        "Recovery:\n"
        "  spark config migrate\n"
        "  spark gateway restart\n"
        "  journalctl --user -u spark-gateway.service -n 100 --no-pager\n"
        f"  spark dashboard --host {result.host} --port {result.port}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Spark dashboard health")
    parser.add_argument("--wait", type=float, default=0.0, help="Seconds to wait for readiness")
    parser.add_argument("--timeout", type=float, default=2.0, help="Per-request timeout")
    parser.add_argument("--interval", type=float, default=1.0, help="Retry interval")
    parser.add_argument("--json", action="store_true", help="Print JSON result")
    args = parser.parse_args(argv)

    result = check_dashboard_health(
        wait_seconds=args.wait,
        timeout=args.timeout,
        interval=args.interval,
    )
    if args.json:
        print(json.dumps(asdict(result)))
    elif not result.enabled:
        print("Dashboard is disabled in config.")
    elif result.ok:
        print(f"Dashboard healthy: {result.url}")
    else:
        print(format_dashboard_health_failure(result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
