"""P06/P07 provider-free browser contracts.

Real temporary SQLite/backend/SSE; only capability/control HTTP boundaries use
explicit schema-v1 fixtures (no inference and no claimed real worker execution).
Run with the repository .venv active and PYTHONPATH pointing at this checkout/src.
SPARK_E2E_BUILT_WEB=1 verifies an independently built bundle served by Python.
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
from urllib.parse import parse_qs, urlparse

from playwright.async_api import async_playwright, expect

WEB = Path(__file__).resolve().parents[1]
ROOT = WEB.parents[2]
REPORTS = Path(os.environ.get("SPARK_E2E_REPORTS", "/tmp/spark-p06-p07-browser"))


def fixture_server(port):
    import spark_cli.web_server as server
    from core.spark_state import SessionDB

    if os.environ.get("SPARK_E2E_ASSET_DIR"):
        server.WEB_DIST = Path(os.environ["SPARK_E2E_ASSET_DIR"])
        # The server mounts StaticFiles during import, before this fixture can
        # select an external build. Keep that mount and the SPA index aligned.
        from fastapi.staticfiles import StaticFiles
        for route in server.app.routes:
            if getattr(route, "path", None) == "/assets":
                route.app = StaticFiles(directory=server.WEB_DIST / "assets")
    db = SessionDB()
    for marker in ("alpha", "bravo", "charlie"):
        sid = "inspector_" + marker
        if db.get_session(sid):
            continue
        db.create_session(sid, source="workspace:particles", model="fixture-only")
        db.set_session_title(sid, "Inspector " + marker)
        for index in range(40):
            db.append_message(sid, "user", f"{marker} prompt {index}")
            db.append_message(sid, "assistant", f"{marker} answer {index}\n\n" + "Synthetic history paragraph. " * 15)
        db.create_session("child_" + marker, source="subagent", model="fixture-only", parent_session_id=sid)
        db.append_message("child_" + marker, "assistant", f"Child transcript {marker}")
        db.commit_subagent_lifecycle({
            "id": "run_" + marker, "parent_session_id": sid, "child_session_id": "child_" + marker,
            "root_run_id": "root_" + marker, "attempt_id": "attempt_" + marker,
            "name": "Child " + marker + (" long inspector title" * 8 if marker == "bravo" else ""),
            "task": "Inspect " + marker + ("\n\n" + "LongUnbrokenReference" * 80 if marker == "bravo" else ""), "status": "running",
            "execution_mode": "async", "workspace_path": "/synthetic/workspace/" + marker,
            "worktree": {"run_id": "worktree-" + marker, "repository": "/synthetic/repository", "base_commit": "abc123", "branch": "feat/synthetic-" + marker, "path": "/synthetic/worktree/" + marker, "setup_status": "ready"},
        }, {"event_id": "start_" + marker, "event": "started"})
    if not db.get_subagent_run("run_alpha_sibling"):
        db.commit_subagent_lifecycle({
            "id": "run_alpha_sibling", "parent_session_id": "inspector_alpha",
            "name": "Unsupported sibling", "task": "Synthetic sibling", "status": "running",
        }, {"event_id": "start-sibling", "event": "started"})
    db.close()

    @server.app.post("/api/dev/inspector-update")
    async def update(body: dict):
        database = SessionDB()
        try:
            run = database.get_subagent_run(body["id"])
            if run is None:
                raise ValueError("Fixture child not found")
            server._persist_and_publish_subagent_event(run["parent_session_id"], {
                "event_id": body["event_id"], "event": body.get("event", "status"),
                "id": run["id"], "run_id": run["id"],
                "payload": {"status": body["status"], "summary": body.get("summary")},
                "subagent_run": {**run, "status": body["status"], "summary": body.get("summary")},
            })
            return {"ok": True}
        finally:
            database.close()
    server.start_server(host="127.0.0.1", port=port, open_browser=False)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def main():
    REPORTS.mkdir(parents=True, exist_ok=True)
    for name in ("failure.png", "failure-dom.txt"):
        (REPORTS / name).unlink(missing_ok=True)
    checks, browser_errors, asset_responses = [], [], []
    api_port, web_port = free_port(), free_port()
    api, web = f"http://127.0.0.1:{api_port}", f"http://127.0.0.1:{web_port}"
    if os.environ.get("SPARK_E2E_BUILT_WEB") == "1":
        web = api
    with tempfile.TemporaryDirectory(prefix="spark-inspector-") as temporary:
        home = Path(temporary)
        (home / "workspace/particles").mkdir(parents=True)
        (home / "config.yaml").write_text("model:\n  default: fixture-only\n  provider: ollama\n  base_url: http://127.0.0.1:1/v1\n")
        logs, processes = [], []
        browser = None
        pw = None
        page = None
        try:
            for name in ("backend", "vite"):
                logs.append(open(REPORTS / f"{name}.log", "w"))
            env = {**os.environ, "SPARK_HOME": str(home), "SPARK_WEB_FAKE_STREAMS": "1", "PYTHONPATH": str(ROOT / "src")}
            processes.append(subprocess.Popen([sys.executable, __file__, "--fixture-server", str(api_port)], cwd=ROOT, env=env, stdout=logs[0], stderr=subprocess.STDOUT))
            if web != api:
                processes.append(subprocess.Popen([str(WEB / "node_modules/.bin/vite"), "--host", "127.0.0.1", "--port", str(web_port), "--strictPort"], cwd=WEB, env={**env, "SPARK_API_TARGET": api}, stdout=logs[1], stderr=subprocess.STDOUT))
            pw = await async_playwright().start()
            request = await pw.request.new_context()
            for target in (api + "/api/status", web):
                for _ in range(180):
                    try:
                        if (await request.get(target, timeout=1000)).ok:
                            break
                    except Exception:
                        pass
                    await asyncio.sleep(0.25)
                else:
                    raise AssertionError("Server unavailable: " + target)
            browser = await pw.chromium.launch()
            context = await browser.new_context(viewport={"width": 1440, "height": 980}, permissions=["clipboard-read", "clipboard-write"], reduced_motion="reduce")
            page = await context.new_page()
            page.set_default_timeout(10000)
            page.on("pageerror", lambda error: browser_errors.append(str(error)))
            page.on("response", lambda response: asset_responses.append({"url": response.url.split("/assets/")[-1], "status": response.status}) if "/assets/" in response.url else None)
            await page.goto(web, wait_until="domcontentloaded")
            await page.screenshot(path=str(REPORTS / "initial.png"))
            (REPORTS / "initial-dom.txt").write_text(await page.locator("body").inner_text())
            composer = page.get_by_role("textbox", name="Message composer")

            async def reload():
                started = time.time() * 1000
                async with page.expect_response(lambda response: response.url.endswith("/api/sidebar/threads") and response.status == 200 and response.request.timing["startTime"] >= started) as hydration:
                    await page.reload()
                await hydration.value
                await expect(composer).to_be_editable()

            async def select(marker):
                current = page.get_by_test_id("chat-panel")
                if await current.count() and await current.get_attribute("data-session-id") == "inspector_" + marker:
                    await expect(composer).to_be_editable()
                    return
                await page.get_by_role("button", name="Threads", exact=True).click()
                folder = page.get_by_role("button", name="particles", exact=True)
                await folder.wait_for(state="visible")
                if await folder.get_attribute("aria-expanded") == "false":
                    await folder.click()
                try:
                    await page.get_by_role("button", name=re.compile("Inspector " + marker)).first.click(timeout=10000)
                except Exception:
                    (REPORTS / "failure-dom.txt").write_text(await page.locator("body").inner_text())
                    await page.screenshot(path=str(REPORTS / "failure.png"))
                    raise
                await expect(page.get_by_test_id("chat-panel")).to_have_attribute("data-session-id", "inspector_" + marker)
                await expect(composer).to_be_editable()

            async def child_detail(marker):
                row = page.locator(f'[data-subagent-row="run_{marker}"]:visible')
                back = page.get_by_role("button", name="Back to subagents").filter(visible=True)
                await row.or_(back).first.wait_for(state="visible")
                if await row.count():
                    await row.click()
                await expect(back).to_be_visible()

            await reload()
            await select("alpha")
            await composer.fill("Unsent alpha")
            await page.locator('input[type="file"]').first.set_input_files({"name": "retained.txt", "mimeType": "text/plain", "buffer": b"synthetic attachment"})
            await expect(page.get_by_role("list", name="Attached context items")).to_contain_text("Ready")

            # Three real synthetic streams stay live while switching chats.
            for marker in ("alpha", "bravo", "charlie"):
                response = await request.post(api + "/api/dev/fake-streams", data={
                    "session_id": "inspector_" + marker, "title": "Inspector " + marker,
                    "message": "Live fixture " + marker, "source": "workspace:particles",
                    "events": [{"type": "token", "text": "live " + marker}, {"type": "token", "text": " still live", "delay_ms": 60000}, {"type": "token", "text": " third minute", "delay_ms": 60000}, {"type": "token", "text": " final", "delay_ms": 60000}],
                })
                assert response.ok, await response.text()
            await reload()
            await page.wait_for_timeout(500)
            (REPORTS / "after-reload-dom.txt").write_text(await page.locator("body").inner_text())
            await page.screenshot(path=str(REPORTS / "after-reload.png"))
            await select("alpha")
            await page.locator('[data-subagent-row="run_alpha"] .animate-spin').evaluate_all("elements => { if (elements.some(e => getComputedStyle(e).animationName !== 'none')) throw new Error('Reduced motion ignored'); }")
            await child_detail("alpha")
            await expect(page.get_by_text("No live owned child is available", exact=True).filter(visible=True)).to_be_visible()
            await expect(page.get_by_role("button", name="Stop subagent").filter(visible=True)).to_be_disabled()
            checks.append("real runtime capability disables unsupported Stop with reason")
            scroll = page.get_by_test_id("chat-scroll")
            # Wait for initial history reconciliation/clamping to finish before
            # deliberately detaching. A zero->zero comparison proves nothing.
            for _ in range(40):
                await scroll.evaluate("e => { e.scrollTop = 1000; e.dispatchEvent(new Event('scroll')); }")
                await page.wait_for_timeout(100)
                if await scroll.evaluate("e => e.scrollTop > 500 && e.scrollHeight - e.scrollTop - e.clientHeight > 240") and await page.get_by_role("button", name="Jump to latest", exact=True).is_visible():
                    break
            else:
                raise AssertionError("Parent history did not permit a detached viewport within four seconds")
            before = await scroll.evaluate("e => e.scrollTop")
            for marker in ("bravo", "charlie"):
                await select(marker)
                await composer.fill("Unsent " + marker)
                await child_detail(marker)
            await select("alpha")
            await expect(composer).to_have_value("Unsent alpha")
            await expect(page.get_by_role("list", name="Attached context items")).to_contain_text("retained.txt")
            await expect(page.get_by_text("Attempt:", exact=True).filter(visible=True)).to_be_visible()
            await expect(page.get_by_text("attempt_alpha", exact=True).filter(visible=True)).to_be_visible()
            await page.wait_for_timeout(1000)
            after = await scroll.evaluate("e => e.scrollTop")
            assert abs(before - after) < 100, (before, after)
            checks.append(f"three live chat switches retain selection/draft/attachment and detached scroll ({before:.1f} -> {after:.1f}px)")

            # Explicit v1 transport fixtures exercise controls without a model worker.
            async def supported(route):
                sid = route.request.url.split("/conversations/")[1].split("/")[0]
                rows = (await (await request.get(api + f"/api/conversations/{sid}/subagents")).json())["subagents"]
                children = {}
                for run in rows:
                    interruptible = run["status"] not in {"completed", "failed", "cancelled", "interrupted", "uncertain", "stale"} and run["id"] != "run_alpha_sibling"
                    retryable = run.get("execution_mode") == "async" and run["status"] in {"failed", "cancelled", "interrupted"}
                    children[run["id"]] = {"controls": {
                        "inspect": {"supported": True, "reason": None},
                        "interrupt": {"supported": interruptible, "reason": None if interruptible else "No live owned child is available"},
                        "retry": {"supported": retryable, "reason": None if retryable else "This child has no acknowledged retryable attempt"},
                    }}
                await route.fulfill(json={"schema_version": 1, "controls": {name: {"supported": True, "reason": None} for name in ("inspect", "interrupt", "retry")}, "children": children, "runtime": {"available": True, "async_enabled": True, "worker_kind": "process_local", "completion_delivery": "next_explicit_parent_turn"}})
            async def paged_events(route):
                response = await route.fetch()
                value = await response.json()
                after = int(parse_qs(urlparse(route.request.url).query).get("event_after_id", ["0"])[0])
                ids = [1, 2] if after == 0 else [3, 4] if after == 2 else []
                events = [{"id": number, "event_id": f"cursor-{number}", "event_type": "output", "timestamp": 1000 + number, "data": {"event": "output", "payload": {"preview": f"Cursor event {number}"}}} for number in ids]
                value["subagent"].update(events=events, transcript=events)
                value.update(events=events, has_more_events=after == 0, next_event_after_id=2 if after == 0 else None)
                await route.fulfill(json=value)
            async def paged_messages(route):
                response = await route.fetch()
                value = await response.json()
                older = "before_id" in parse_qs(urlparse(route.request.url).query)
                ids = [99, 100] if older else [101, 102]
                value.update(messages=[{"id": number, "role": "assistant", "content": f"Cursor message {number}"} for number in ids], total=4, offset=0 if older else 2, has_earlier=not older, next_before_id=None if older else 101)
                await route.fulfill(json=value)
            await page.route(re.compile(r"/subagents/run_bravo(?:\?.*)?$"), paged_events)
            await page.route(re.compile(r"/subagents/run_bravo/messages(?:\?.*)?$"), paged_messages)
            await page.route("**/subagents/capabilities", supported)
            await reload()
            await select("alpha")
            stop_ids = []
            async def stop(route):
                stop_ids.append(route.request.post_data_json["request_id"])
                if len(stop_ids) == 1:
                    await route.abort("failed")
                else:
                    await route.fulfill(json={"ok": True, "session_id": "inspector_alpha", "subagent_id": "run_alpha", "status": "stopping"})
            await page.route("**/run_alpha/interrupt", stop)
            await expect(page.get_by_role("button", name="Stop subagent").filter(visible=True)).to_be_enabled()
            await page.get_by_role("button", name="Stop subagent").filter(visible=True).click()
            await expect(page.get_by_text(re.compile("Stop acceptance is unconfirmed")).filter(visible=True)).to_be_visible()
            # Close/reopen proves the request ID is retained beyond component state.
            await page.get_by_role("button", name="Back to subagents").filter(visible=True).click()
            await child_detail("alpha")
            await page.get_by_role("button", name="Check Stop request").filter(visible=True).click()
            assert len(stop_ids) == 2 and stop_ids[0] == stop_ids[1], stop_ids
            await expect(page.get_by_text("Cancel requested. Waiting for terminal confirmation.").filter(visible=True)).to_be_visible()
            await expect(page.get_by_role("button", name="Stop subagent").filter(visible=True)).to_be_disabled()
            await request.post(api + "/api/dev/inspector-update", data={"id": "run_alpha", "event_id": "terminal-alpha", "status": "cancelled", "event": "interrupted"})
            await expect(page.get_by_text("Cancel requested. Waiting for terminal confirmation.").filter(visible=True)).to_have_count(0)
            retry_ids = []
            retry_received, release_retry = asyncio.Event(), asyncio.Event()
            async def retry(route):
                retry_ids.append(route.request.post_data_json["request_id"])
                if len(retry_ids) == 1:
                    await route.abort("failed")
                else:
                    retry_received.set()
                    await release_retry.wait()
                    await route.fulfill(json={"mode": "async", "status": "accepted", "handles": [{"id": "retry-alpha", "attempt_id": "new-attempt", "status": "created"}]})
            await page.route("**/run_alpha/retry", retry)
            await page.get_by_role("button", name="Retry as new attempt").filter(visible=True).click()
            await page.get_by_role("button", name="Check retry request").filter(visible=True).click()
            await asyncio.wait_for(retry_received.wait(), timeout=5)
            assert retry_ids[0] == retry_ids[1]
            await select("bravo")
            await child_detail("bravo")
            release_retry.set()
            await expect(composer).to_have_value("Unsent bravo")
            await expect(page.get_by_text("retry-alpha", exact=True).filter(visible=True)).to_have_count(0)
            await select("alpha")
            await child_detail("alpha")
            await expect(page.get_by_text("retry-alpha", exact=True).filter(visible=True)).to_be_visible()
            checks.append("exact per-child capabilities permit the owned child beside an unsupported live sibling; transport receipts reuse Stop/Retry IDs after uncertain responses; Stop waits for real terminal SSE; retry retains earlier attempt")

            # Hold every list snapshot at its old value while a committed SSE
            # terminal event arrives. Releasing HTTP must not erase that event.
            await select("charlie")
            await child_detail("charlie")
            stop_received, release_stop = asyncio.Event(), asyncio.Event()
            async def late_stop(route):
                stop_received.set()
                await release_stop.wait()
                await route.fulfill(json={"ok": True, "session_id": "inspector_charlie", "subagent_id": "run_charlie", "status": "stopping"})
            await page.route("**/run_charlie/interrupt", late_stop)
            await page.get_by_role("button", name="Stop subagent").filter(visible=True).click()
            await asyncio.wait_for(stop_received.wait(), timeout=5)
            await select("bravo")
            await child_detail("bravo")
            release_stop.set()
            await expect(composer).to_have_value("Unsent bravo")
            await expect(page.get_by_text("Cancel requested. Waiting for terminal confirmation.").filter(visible=True)).to_have_count(0)
            await select("charlie")
            await child_detail("charlie")
            await expect(page.get_by_text("Cancel requested. Waiting for terminal confirmation.").filter(visible=True)).to_be_visible()
            checks.append("late Stop and Retry acknowledgements stay with their initiating child across chat switches")
            snapshot_received, release_snapshot = asyncio.Event(), asyncio.Event()
            async def old_snapshot(route):
                response = await route.fetch()
                snapshot_received.set()
                await release_snapshot.wait()
                try:
                    await route.fulfill(response=response)
                except Exception:
                    pass  # Superseded HTTP loads are intentionally aborted.
            snapshot_url = "**/api/conversations/inspector_charlie/subagents"
            await page.route(snapshot_url, old_snapshot)
            reloading = asyncio.create_task(reload())
            await asyncio.wait_for(snapshot_received.wait(), timeout=10)
            await request.post(api + "/api/dev/inspector-update", data={"id": "run_charlie", "event_id": "snapshot-race", "status": "failed", "event": "failed", "summary": "Result arrived during snapshot"})
            await expect(page.get_by_text("Result arrived during snapshot", exact=True).filter(visible=True).first).to_be_visible()
            release_snapshot.set()
            await reloading
            await page.unroute(snapshot_url, old_snapshot)
            await expect(page.get_by_text("Result arrived during snapshot", exact=True).filter(visible=True).first).to_be_visible()
            await expect(page.get_by_test_id("chat-panel")).to_have_attribute("data-streaming", "true")
            checks.append("committed child result arriving during an older HTTP snapshot survives reconciliation; child failure leaves parent streaming")

            await request.post(api + "/api/dev/inspector-update", data={"id": "run_bravo", "event_id": "done-bravo", "status": "completed", "event": "completed", "summary": "Copyable child result"})
            await select("bravo")
            await page.get_by_role("button", name="Copy result").filter(visible=True).click()
            assert await page.evaluate("navigator.clipboard.readText()") == "Copyable child result"
            await page.get_by_role("region", name="Child transcript").filter(visible=True).wait_for()
            await page.get_by_role("button", name="Load more child events", exact=True).filter(visible=True).click()
            await expect(page.get_by_text("Cursor event 4", exact=True).filter(visible=True)).to_be_visible()
            await expect(page.get_by_text("Cursor event 1", exact=True).filter(visible=True)).to_be_visible()
            await page.get_by_role("button", name="Load older child messages", exact=True).filter(visible=True).click()
            await expect(page.get_by_text("Cursor message 99", exact=True).filter(visible=True)).to_be_visible()
            await expect(page.get_by_text("Cursor message 102", exact=True).filter(visible=True)).to_be_visible()
            await expect(page.get_by_text("feat/synthetic-bravo", exact=True).filter(visible=True)).to_be_visible()
            checks.append("cursor event pages append and older message pages prepend without losing existing history; actual worktree refs render")
            await page.screenshot(path=str(REPORTS / "desktop-dark.png"))
            checks.append("real completed snapshot renders result, child transcript and app-owned parent/root/attempt references; result copies")

            # Expired epoch must replace stale child status and keep selection/draft.
            await context.set_offline(True)
            await page.wait_for_timeout(300)
            await expect(page.get_by_role("button", name="Retry as new attempt").filter(visible=True)).to_be_disabled()
            await context.set_offline(False)
            await page.evaluate("window.dispatchEvent(new Event('online'))")
            await expect(composer).to_have_value("Unsent bravo")
            await expect(page.get_by_text("attempt_bravo", exact=True).filter(visible=True)).to_be_visible()
            await expect(page.get_by_text("Cursor message 99", exact=True).filter(visible=True)).to_be_visible()
            await expect(page.get_by_text("Cursor event 4", exact=True).filter(visible=True)).to_be_visible()
            checks.append("offline/reconnect keeps loaded event/message pages, child selection and parent draft without resubmission")

            await page.evaluate("localStorage.setItem('spark-webui-theme','daylight')")
            await reload()
            await select("bravo")
            await page.screenshot(path=str(REPORTS / "desktop-light.png"))
            await page.get_by_role("button", name="Back to subagents").filter(visible=True).click()
            await page.set_viewport_size({"width": 390, "height": 844})
            # The mobile entry must remain available even if the desktop panel was open.
            trigger = page.get_by_role("button", name=re.compile("Show .* subagents"))
            await trigger.click()
            dialog = page.get_by_role("dialog", name="Subagent detail")
            await expect(dialog).to_be_visible()
            await expect(dialog.get_by_role("button", name="Back to subagents")).to_be_focused()
            await page.keyboard.press("Shift+Tab")
            assert await dialog.evaluate("e => e.contains(document.activeElement)")
            if await dialog.get_by_role("button", name="Show more", exact=True).count():
                await dialog.get_by_role("button", name="Show more", exact=True).click()
            assert await dialog.evaluate("e => e.scrollWidth <= e.clientWidth"), "mobile horizontal overflow"
            assert await dialog.locator("p").evaluate_all("elements => elements.every(e => e.scrollWidth <= e.clientWidth)"), "long task text overflows"
            assert await dialog.evaluate("e => e.getBoundingClientRect().top === 0"), "overlay is not full viewport"
            await page.screenshot(path=str(REPORTS / "mobile-light.png"))
            await page.keyboard.press("Escape")
            await expect(dialog).to_have_count(0)
            await expect(trigger).to_be_focused()
            checks.append("390px daylight overlay fits, traps keyboard focus, Escape returns focus, reduced motion enabled")
            await page.set_viewport_size({"width": 1440, "height": 980})
            await child_detail("bravo")
            await page.unroute("**/subagents/capabilities", supported)
            old_epoch = (await (await request.get(api + "/api/web-state/snapshot")).json())["server_epoch"]
            submissions = []
            page.on("request", lambda req: submissions.append(req.url) if req.method == "POST" and "/conversations" in req.url else None)
            backend = processes[0]
            backend.terminate()
            try:
                backend.wait(timeout=5)
            except subprocess.TimeoutExpired:
                backend.kill()
                backend.wait()
            processes.append(subprocess.Popen([sys.executable, __file__, "--fixture-server", str(api_port)], cwd=ROOT, env=env, stdout=logs[0], stderr=subprocess.STDOUT))
            for _ in range(180):
                try:
                    if (await request.get(api + "/api/status", timeout=1000)).ok:
                        break
                except Exception:
                    pass
                await asyncio.sleep(0.25)
            else:
                raise AssertionError("Restarted backend did not become ready")
            new_epoch = (await (await request.get(api + "/api/web-state/snapshot")).json())["server_epoch"]
            assert new_epoch != old_epoch
            await page.evaluate("window.dispatchEvent(new Event('online'))")
            await expect(page.get_by_test_id("chat-panel")).to_have_attribute("data-streaming", "false", timeout=5000)
            await expect(composer).to_have_value("Unsent bravo")
            await expect(page.get_by_text("attempt_bravo", exact=True).filter(visible=True)).to_be_visible()
            await expect(page.get_by_role("button", name="Stop subagent").filter(visible=True)).to_be_disabled()
            assert not submissions, submissions
            checks.append("real backend restart changes epoch; selected child and draft survive, parent stops streaming within 5s, no prompt/control is replayed")

            await page.get_by_role("button", name="Threads", exact=True).click()
            await page.get_by_title("New thread in this project", exact=True).first.click()
            await expect(page.get_by_role("button", name="particles", exact=True)).to_have_attribute("aria-expanded", "true")
            await composer.fill("Keep failed project creation")
            await page.locator('input[type="file"]').first.set_input_files({"name": "project-draft.txt", "mimeType": "text/plain", "buffer": b"synthetic project draft"})
            await expect(page.get_by_role("list", name="Attached context items")).to_contain_text("Ready")
            async def fail_creation(route):
                await route.fulfill(status=503, json={"detail": "Synthetic creation failure"})
            await page.route("**/api/workspace/projects/particles/conversations", fail_creation)
            await page.get_by_role("button", name="Send message", exact=True).click()
            await expect(page.get_by_text("Could not confirm submission. Your draft is kept; check the thread before retrying.", exact=True)).to_be_visible()
            await expect(composer).to_have_value("Keep failed project creation")
            await select("charlie")
            await page.get_by_title("New thread in this project", exact=True).first.click()
            await expect(composer).to_have_value("Keep failed project creation")
            await expect(page.get_by_role("list", name="Attached context items")).to_contain_text("project-draft.txt")
            await reload()
            await page.get_by_role("button", name="Threads", exact=True).click()
            await page.get_by_title("New thread in this project", exact=True).first.click()
            await expect(composer).to_have_value("Keep failed project creation")
            await expect(page.get_by_role("list", name="Attached context items")).to_contain_text("project-draft.txt")
            await page.screenshot(path=str(REPORTS / "failed-project-create.png"))
            checks.append("project compose opens folder; failed creation preserves draft and attachment across chat switch and refresh")
            assert not browser_errors, browser_errors
            assert all(asset["status"] == 200 for asset in asset_responses), asset_responses
            if web == api:
                assert asset_responses, "No production assets were observed"
            await browser.close()
            browser = None
        except Exception:
            if page and browser:
                try:
                    await page.screenshot(path=str(REPORTS / "failure.png"))
                    (REPORTS / "failure-dom.txt").write_text(await page.locator("body").inner_text())
                except Exception:
                    pass
            raise
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
            if pw:
                await pw.stop()
            for process in reversed(processes):
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            for log in logs:
                log.close()
            (REPORTS / "report.json").write_text(json.dumps({"checks": checks, "page_errors": browser_errors, "asset_responses": asset_responses, "built_web": web == api}, indent=2))
    print(json.dumps({"checks": checks, "report": str(REPORTS / "report.json")}, indent=2))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--fixture-server":
        fixture_server(int(sys.argv[2]))
    else:
        asyncio.run(main())
