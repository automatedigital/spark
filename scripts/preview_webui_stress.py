#!/usr/bin/env python3
"""Run an isolated, disposable WebUI stress preview.

The dashboard and Vite server share a temporary SPARK_HOME that is removed with
both child processes on normal exit, failure, SIGINT, or SIGTERM.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "src" / "spark_cli" / "web"
CHILDREN: list[subprocess.Popen[bytes]] = []
STOPPING = False


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for(url: str, timeout: float = 45.0) -> None:
    deadline = time.monotonic() + timeout
    error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status < 400:
                    return
        except (OSError, urllib.error.URLError) as exc:
            error = exc
        time.sleep(0.2)
    raise RuntimeError(f"Timed out waiting for {url}: {error}")


def post_json(url: str, body: dict[str, object]) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def stop_children() -> None:
    global STOPPING
    if STOPPING:
        return
    STOPPING = True
    for child in reversed(CHILDREN):
        if child.poll() is None:
            child.terminate()
    deadline = time.monotonic() + 3
    for child in reversed(CHILDREN):
        remaining = max(0.0, deadline - time.monotonic())
        try:
            child.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-port", type=int, default=0)
    parser.add_argument("--web-port", type=int, default=0)
    parser.add_argument("--keep-home", action="store_true", help="Keep the disposable profile for debugging.")
    parser.add_argument("--no-stream", action="store_true", help="Start the preview without creating a stress stream.")
    args = parser.parse_args()

    if not (WEB_ROOT / "node_modules").exists():
        parser.error("Web dependencies are missing; run npm install in src/spark_cli/web first")

    spark_home = Path(tempfile.mkdtemp(prefix="spark-webui-stress-"))
    api_port = args.api_port or free_port()
    web_port = args.web_port or free_port()
    (spark_home / "config.yaml").write_text(
        "model:\n  default: test-model\n  provider: ollama\n  base_url: http://127.0.0.1:11434/v1\n",
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "src"),
        "SPARK_HOME": str(spark_home),
        "SPARK_WEB_FAKE_STREAMS": "1",
    }

    def handle_signal(signum: int, _frame: object) -> None:
        stop_children()
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        CHILDREN.append(
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "spark_cli.web_server:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(api_port),
                    "--log-level",
                    "warning",
                ],
                cwd=ROOT,
                env=env,
            )
        )
        CHILDREN.append(
            subprocess.Popen(
                ["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", str(web_port)],
                cwd=WEB_ROOT,
                env={**env, "SPARK_API_TARGET": f"http://127.0.0.1:{api_port}"},
            )
        )
        api_base = f"http://127.0.0.1:{api_port}"
        web_base = f"http://127.0.0.1:{web_port}"
        wait_for(f"{api_base}/api/status")
        wait_for(web_base)

        session_id = "preview_stress_stream"
        if not args.no_stream:
            chunk = "responsive-stream-check " * 640
            events: list[dict[str, object]] = [
                {"type": "reasoning", "text": "reasoning-bound-check " * 1200},
            ]
            events.extend(
                {"type": "token", "text": chunk, "delay_ms": 40}
                for _ in range(600)
            )
            post_json(
                f"{api_base}/api/dev/fake-streams",
                {
                    "session_id": session_id,
                    "title": "Disposable WebUI stress stream",
                    "message": "Verify rendering remains responsive, then press Stop.",
                    "events": events,
                },
            )

        print(f"Preview: {web_base}")
        print(f"API: {api_base}")
        print(f"Disposable SPARK_HOME: {spark_home}")
        if not args.no_stream:
            print(f"Session: {session_id} (open it and press Stop while it streams)")
        print("Press Ctrl-C to stop and clean up.")
        while all(child.poll() is None for child in CHILDREN):
            time.sleep(0.25)
        return next((child.returncode or 1 for child in CHILDREN if child.poll() is not None), 1)
    finally:
        stop_children()
        if args.keep_home:
            print(f"Kept disposable profile: {spark_home}")
        else:
            shutil.rmtree(spark_home, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
