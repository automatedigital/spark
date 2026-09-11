"""Provider-free browser acceptance for draft and recovery behavior.

Run from the repository root with its activated .venv:
    python src/spark_cli/web/e2e/work-recovery.py
Uses isolated state and ephemeral ports; never contacts a model provider.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from playwright.async_api import async_playwright, expect

WEB = Path(__file__).resolve().parents[1]
ROOT = WEB.parents[2]
REPORTS = WEB / "screenshots" / "work-recovery"


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def ready(request, url):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        try:
            if (await request.get(url, timeout=1000)).ok:
                return
        except Exception:
            pass
        await asyncio.sleep(0.2)
    raise AssertionError(f"Server did not become ready: {url}")


async def main():
    REPORTS.mkdir(parents=True, exist_ok=True)
    api_port, web_port = free_port(), free_port()
    api_url, web_url = f"http://127.0.0.1:{api_port}", f"http://127.0.0.1:{web_port}"
    if os.environ.get("SPARK_E2E_BUILT_WEB") == "1":
        web_url = api_url
    checks = []
    with tempfile.TemporaryDirectory(prefix="spark-work-recovery-") as temporary:
        home = Path(temporary)
        (home / "workspace" / "particles").mkdir(parents=True)
        (home / "config.yaml").write_text(
            "model:\n  default: fixture-only\n  provider: ollama\n  base_url: http://127.0.0.1:1/v1\n"
        )
        logs = [open(home / name, "w+") for name in ("backend.log", "vite.log")]
        processes = []
        try:
            processes.append(subprocess.Popen(
                [sys.executable, "-c", f"from spark_cli.web_server import start_server; start_server(host='127.0.0.1', port={api_port}, open_browser=False)"],
                cwd=ROOT, env={**os.environ, "SPARK_HOME": str(home), "SPARK_WEB_FAKE_STREAMS": "1"},
                stdout=logs[0], stderr=subprocess.STDOUT,
            ))
            if web_url != api_url:
                processes.append(subprocess.Popen(
                    [str(WEB / "node_modules/.bin/vite"), "--host", "127.0.0.1", "--port", str(web_port), "--strictPort"],
                    cwd=WEB, env={**os.environ, "SPARK_API_TARGET": api_url}, stdout=logs[1], stderr=subprocess.STDOUT,
                ))
            async with async_playwright() as playwright:
                request = await playwright.request.new_context()
                await ready(request, api_url + "/api/status")
                await ready(request, web_url)
                for marker in ("alpha", "bravo", "charlie"):
                    response = await request.post(api_url + "/api/dev/fake-streams", data={
                        "session_id": "recovery_" + marker,
                        "title": "Recovery " + marker,
                        "message": "Fixture prompt " + marker,
                        "source": "workspace:particles" if marker == "bravo" else "web",
                        "events": [{"type": "token", "text": "Fixture answer " + marker}],
                    })
                    assert response.ok, await response.text()
                browser = await playwright.chromium.launch()
                context = await browser.new_context(viewport={"width": 1440, "height": 980})
                page = await context.new_page()
                # The dashboard keeps an SSE connection open, so networkidle
                # is never a valid readiness signal for this app.
                await page.goto(web_url, wait_until="domcontentloaded")
                await expect(page.get_by_text("Spark").first).to_be_visible()
                await page.screenshot(path=str(REPORTS / "initial.png"))
                composer = page.get_by_role("textbox", name="Message composer")

                async def select(marker, target=page):
                    await target.get_by_role("button", name=re.compile("Recovery " + marker)).first.click()
                    await expect(target.get_by_test_id("chat-panel")).to_contain_text("Fixture answer " + marker)
                    await expect(target.get_by_role("textbox", name="Message composer")).to_be_editable()

                await select("alpha")
                await composer.fill("Alpha unsent draft")
                await select("charlie")
                await composer.fill("Charlie separate draft")
                await select("alpha")
                await expect(composer).to_have_value("Alpha unsent draft")
                await page.reload()
                await select("alpha")
                await expect(composer).to_have_value("Alpha unsent draft")
                checks.append("draft survives immediate chat switch and browser refresh")

                async def failed_send(route):
                    await route.fulfill(status=503, content_type="application/json", body='{"detail":"Fixture submission unavailable"}')

                message_route = "**/api/conversations/recovery_alpha/messages"
                await page.route(message_route, failed_send)
                await page.get_by_role("button", name="Send message", exact=True).click()
                await expect(composer).to_have_value("Alpha unsent draft")
                await page.reload()
                await select("alpha")
                await expect(composer).to_have_value("Alpha unsent draft")
                await page.unroute(message_route, failed_send)
                checks.append("failed send preserves draft through refresh")

                # A response arriving after a switch must not clear the destination
                # draft or navigate back to the originating thread.
                received, release = asyncio.Event(), asyncio.Event()

                async def delayed_send(route):
                    received.set()
                    await release.wait()
                    await route.fulfill(status=200, content_type="application/json", body='{"ok":true,"session_id":"recovery_alpha"}')

                await page.route(message_route, delayed_send)
                await page.get_by_role("button", name="Send message", exact=True).click()
                await asyncio.wait_for(received.wait(), timeout=5)
                await select("charlie")
                await expect(composer).to_have_value("Charlie separate draft")
                release.set()
                await page.wait_for_timeout(400)
                await expect(composer).to_have_value("Charlie separate draft")
                await expect(page.get_by_test_id("chat-panel")).to_contain_text("Fixture answer charlie")
                await page.unroute(message_route, delayed_send)
                await select("alpha")
                await expect(composer).to_have_value("")
                checks.append("late acknowledgement clears only submitted draft without switching chat")

                # Storage events must surface concurrent editing rather than
                # overwrite the text that this tab is currently composing.
                await composer.fill("Alpha first tab")
                await page.wait_for_timeout(500)
                other = await context.new_page()
                await other.goto(web_url)
                await select("alpha", other)
                other_composer = other.get_by_role("textbox", name="Message composer")
                await expect(other_composer).to_have_value("Alpha first tab")
                await other_composer.fill("Alpha second tab")
                await other.wait_for_timeout(500)
                await expect(composer).to_have_value("Alpha first tab")
                await expect(page.get_by_text(re.compile("another tab", re.I)).first).to_be_visible()
                await page.screenshot(path=str(REPORTS / "draft-conflict.png"))
                checks.append("concurrent tab edit preserves local input and exposes conflict")
                await other.close()

                await select("charlie")
                await expect(composer).to_have_value("Charlie separate draft")
                checks.append("thread drafts remain isolated across refresh and switching")

                # Upload a real synthetic file, then recover its server reference.
                file_picker = page.get_by_test_id("chat-panel").locator('input[type="file"]').last
                await file_picker.set_input_files({"name": "draft-attachment.txt", "mimeType": "text/plain", "buffer": b"synthetic attachment"})
                attachments = page.get_by_role("list", name="Attached context items")
                await expect(attachments).to_contain_text("Ready")
                await page.reload()
                await select("charlie")
                attachments = page.get_by_role("list", name="Attached context items")
                await expect(attachments).to_contain_text("draft-attachment.txt")
                await expect(attachments).to_contain_text("Ready")
                checks.append("uploaded file reference and context selection survive refresh")

                # Simulate restart before a browser File upload has finished.
                await page.evaluate("""() => {
                    for (const key of Object.keys(localStorage)) {
                        if (!key.startsWith('spark.draft.v1') || !key.includes('recovery_charlie')) continue;
                        const value = JSON.parse(localStorage.getItem(key));
                        value.contextItems[0].attachment_status = 'uploading';
                        localStorage.setItem(key, JSON.stringify(value));
                    }
                }""")
                await page.reload()
                await select("charlie")
                attachments = page.get_by_role("list", name="Attached context items")
                await expect(attachments).to_contain_text("Missing")
                await expect(page.get_by_role("button", name="Send message", exact=True)).to_be_disabled()
                await attachments.get_by_title("Remove", exact=True).click()
                await expect(page.get_by_role("button", name="Send message", exact=True)).to_be_enabled()
                checks.append("interrupted upload recovers as missing and blocks send until removed")

                async def failed_upload(route):
                    await route.fulfill(status=503, body="Fixture upload unavailable")

                await page.route("**/api/workspace/files/upload", failed_upload)
                await page.get_by_test_id("chat-panel").locator('input[type="file"]').last.set_input_files({"name": "failed.txt", "mimeType": "text/plain", "buffer": b"synthetic"})
                attachments = page.get_by_role("list", name="Attached context items")
                await expect(attachments).to_contain_text("Upload failed")
                await expect(composer).to_have_value("Charlie separate draft")
                await expect(page.get_by_role("button", name="Send message", exact=True)).to_be_disabled()
                await attachments.get_by_title("Remove", exact=True).click()
                await page.unroute("**/api/workspace/files/upload", failed_upload)
                checks.append("failed attachment remains visible without losing typed text")

                # Simulate a different profile behind the same origin. Status is
                # otherwise real and all conversation data remains synthetic.
                async def different_profile(route):
                    response = await route.fetch()
                    data = await response.json()
                    data["spark_home"] = str(home / "different-profile")
                    await route.fulfill(response=response, json=data)

                await page.route("**/api/status", different_profile)
                await page.reload()
                await select("charlie")
                await expect(composer).to_have_value("")
                await page.unroute("**/api/status", different_profile)
                await page.reload()
                await select("charlie")
                await expect(composer).to_have_value("Charlie separate draft")
                checks.append("profile identity isolates stored drafts at same browser origin")

                for theme in ("codex", "daylight"):
                    await page.set_viewport_size({"width": 1440, "height": 980})
                    await page.evaluate("theme => localStorage.setItem('spark-webui-theme', theme)", theme)
                    await page.reload()
                    await select("charlie")
                    for width in (1440, 1024, 768, 390):
                        await page.set_viewport_size({"width": width, "height": 980})
                        assert await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), f"Overflow at {width}"
                        await page.screenshot(path=str(REPORTS / f"draft-{theme}-{width}.png"))
                await page.screenshot(path=str(REPORTS / "verified.png"))
                await browser.close()
                await request.dispose()
        except Exception:
            for log in logs:
                log.flush()
                log.seek(0)
                print(log.read()[-6000:], file=sys.stderr)
            raise
        finally:
            for process in reversed(processes):
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            for log in logs:
                log.close()
            (REPORTS / "report.json").write_text(json.dumps({"checks": checks}, indent=2) + "\n")
    print(json.dumps({"passed": len(checks), "checks": checks}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
