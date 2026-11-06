"""SP07 built-browser / real 10 MB SQLite result and fake SSE acceptance."""
from __future__ import annotations

import asyncio
import hashlib
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
REPORTS = Path(os.environ.get("SPARK_E2E_REPORTS", "/tmp/sp07-browser"))
CONTENT = ("a" * 65533 + "🙂漢é\n") * 160


def fixture_server(port):
    from fastapi.staticfiles import StaticFiles

    import spark_cli.web_server as server
    from core.spark_state import SessionDB

    server.WEB_DIST = Path(os.environ["SPARK_E2E_ASSET_DIR"])
    for route in server.app.routes:
        if getattr(route, "path", None) == "/assets":
            route.app = StaticFiles(directory=server.WEB_DIST / "assets")
    db = SessionDB()
    for sid in ("result_alpha", "result_bravo"):
        db.create_session(sid, source="web", model="fixture-only")
        db.set_session_title(sid, sid)
        for index in range(50):
            db.append_message(sid, "user", f"Question {index}")
            db.append_message(sid, "assistant", "Long history. " * 100)
        db.append_message(sid, "user", "Read large results")
        for call in ("large_one", "large_two"):
            db.append_message(sid, "assistant", "", tool_calls=[{
                "id": call, "type": "function", "function": {"name": call, "arguments": "{}"},
            }])
            db.append_message(sid, "tool", CONTENT, tool_call_id=call, tool_name=call)
        db.append_message(sid, "assistant", "Results ready")
    db.close()
    server.start_server(host="127.0.0.1", port=port, open_browser=False)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def main():
    REPORTS.mkdir(parents=True, exist_ok=True)
    api = f"http://127.0.0.1:{free_port()}"
    with tempfile.TemporaryDirectory(prefix="sp07-home-") as temporary:
        home = Path(temporary)
        (home / "config.yaml").write_text("model:\n  default: fixture-only\n  provider: ollama\n  base_url: http://127.0.0.1:1/v1\n")
        env = {**os.environ, "SPARK_HOME": str(home), "SPARK_WEB_FAKE_STREAMS": "1", "PYTHONPATH": str(ROOT / "src")}
        with (REPORTS / "backend.log").open("w") as log:
            process = subprocess.Popen([sys.executable, __file__, "--server", api.rsplit(":", 1)[1]], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                async with async_playwright() as pw:
                    request = await pw.request.new_context()
                    for _ in range(120):
                        try:
                            if (await request.get(api + "/api/status")).ok:
                                break
                        except Exception:
                            pass
                        await asyncio.sleep(.25)
                    else:
                        raise AssertionError("Fixture unavailable")
                    measurements = {"baseline": [], "candidate": []}
                    path = api + "/api/sessions/result_alpha/tool-results/large_one"
                    for kind, suffix in (("baseline", ""), ("candidate", "?paged=true")):
                        for _ in range(5):
                            start = time.perf_counter()
                            response = await request.get(path + suffix)
                            raw = await response.body()
                            assert response.ok
                            measurements[kind].append({"bytes": len(raw), "ms": (time.perf_counter()-start)*1000, "requests": 1})
                    (REPORTS / "measurements.json").write_text(json.dumps(measurements, indent=2))
                    browser = await pw.chromium.launch()
                    context = await browser.new_context(permissions=["clipboard-read", "clipboard-write"], viewport={"width": 1440, "height": 980})
                    page = await context.new_page()
                    requests = []
                    errors = []
                    page.on("request", lambda req: requests.append(req.url) if "/tool-results/" in req.url else None)
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    await page.goto(api)
                    await expect(page.get_by_role("textbox", name="Message composer")).to_be_editable()

                    async def select(sid):
                        await page.get_by_role("button", name="Threads", exact=True).click()
                        await page.get_by_role("button", name=re.compile(sid)).first.click()
                        await expect(page.get_by_test_id("chat-panel")).to_have_attribute("data-session-id", sid)

                    await select("result_alpha")
                    # Settled work is deliberately folded. Open its summary first.
                    groups = page.locator("[data-turn-work-group]")
                    await groups.last.locator("button").first.click()
                    one = page.get_by_role("button", name=re.compile(r"^large_one"))
                    two = page.get_by_role("button", name=re.compile(r"^large_two"))
                    for sid in ("result_alpha", "result_bravo"):
                        response = await request.post(api + "/api/dev/fake-streams", data={
                            "session_id": sid, "title": sid, "reuse_existing": True, "message": "stream while paging",
                            "events": [{"type": "token", "text": f"{sid} token {i}. ", "delay_ms": 200} for i in range(150)],
                        })
                        assert response.ok, await response.text()
                    await expect(page.get_by_text(re.compile("result_alpha token")).last).to_be_visible(timeout=15000)
                    await one.click()
                    await expect(page.get_by_role("button", name="Next page", exact=True)).to_be_visible()
                    assert requests and all("paged=true" in url for url in requests)
                    before = len(requests)
                    await page.get_by_role("button", name="Copy preview", exact=True).click()
                    assert len(requests) == before
                    assert len((await page.evaluate("navigator.clipboard.readText()" )).encode()) <= 65536
                    await page.get_by_role("button", name="Next page", exact=True).click()
                    await expect(page.locator("text=/65533–/" )).to_be_visible()
                    async with page.expect_download() as pending:
                        await page.get_by_role("button", name="Download full output", exact=True).click()
                    download = await pending.value
                    await download.save_as(REPORTS / "tool-result.txt")
                    assert hashlib.sha256((REPORTS / "tool-result.txt").read_bytes()).hexdigest() == hashlib.sha256(CONTENT.encode()).hexdigest()
                    await two.click()
                    await expect(page.get_by_role("button", name="Download full output", exact=True)).to_have_count(2)
                    await one.click()
                    await two.click()
                    # Delayed response must not reopen or adopt a collapsed result.
                    async def delayed(route):
                        await asyncio.sleep(.3)
                        await route.continue_()
                    await page.route("**/tool-results/*?*", delayed)
                    await one.click()
                    await one.click()
                    await asyncio.sleep(.5)
                    assert await page.get_by_role("button", name="Next page", exact=True).count() == 0
                    await page.unroute("**/tool-results/*?*", delayed)
                    await select("result_bravo")
                    await select("result_alpha")
                    await page.reload()
                    await expect(page.get_by_role("textbox", name="Message composer")).to_be_editable()
                    try:
                        await expect(page.get_by_text(re.compile("result_alpha token")).last).to_be_visible(timeout=15000)
                    except Exception:
                        await page.screenshot(path=str(REPORTS / "refresh-failure.png"))
                        (REPORTS / "refresh-failure-dom.txt").write_text(await page.locator("body").inner_text())
                        snapshot = await request.get(api + "/api/web-state/snapshot?selected_session_id=result_alpha&session_limit=10&message_limit=10")
                        (REPORTS / "refresh-failure-snapshot.json").write_text(await snapshot.text())
                        raise
                    assert not errors, errors
                    await page.screenshot(path=str(REPORTS / "final.png"))
                    (REPORTS / "measurements.json").write_text(json.dumps(measurements, indent=2))
                    await browser.close()
                    await request.dispose()
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    if "--server" in sys.argv:
        fixture_server(int(sys.argv[-1]))
    else:
        asyncio.run(main())
