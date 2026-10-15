"""P06 real SQLite/Git navigation with provider-free temporary backend.

Only lost/late HTTP acknowledgements are controlled browser transports. No model
or task worker executes. Existing subagent-controls.py remains an independent gate.
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
from pathlib import Path

from playwright.async_api import async_playwright, expect

WEB = Path(__file__).resolve().parents[1]
ROOT = WEB.parents[2]
REPORTS = Path(os.environ.get("SPARK_E2E_REPORTS", "/tmp/spark-p06-navigation-browser"))


def git(directory, *args):
    return subprocess.check_output(["git", "-c", "core.hooksPath=/dev/null", *args], cwd=directory, text=True).strip()


def fixture_server(port):
    import spark_cli.web_server as server
    from core import kanban_db as kb
    from core.spark_constants import get_spark_home
    from core.spark_state import SessionDB
    from tools.subagent_worktree import create_subagent_worktree

    if os.environ.get("SPARK_E2E_ASSET_DIR"):
        from fastapi.staticfiles import StaticFiles
        server.WEB_DIST = Path(os.environ["SPARK_E2E_ASSET_DIR"])
        for route in server.app.routes:
            if getattr(route, "path", None) == "/assets":
                route.app = StaticFiles(directory=server.WEB_DIST / "assets")
    home = get_spark_home()
    repo = home / "fixture-repository"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "committed.txt").write_text("committed fixture\n")
    git(repo, "add", "committed.txt")
    git(repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture")
    (repo / "committed.txt").write_text("dirty parent retained\n")
    record = create_subagent_worktree(repo, "navigation_child")
    (Path(record.path) / "child-dirty.txt").write_text("actual checkout content\n")
    db = SessionDB()
    for marker in ("parent", "other"):
        sid = "navigation_" + marker
        db.create_session(sid, source="workspace:particles", model="fixture-only")
        db.set_session_title(sid, "Navigation " + marker)
        db.append_message(sid, "user", "Synthetic history " + marker)
        db.append_message(sid, "assistant", "Synthetic reply " + marker)
    db.create_subagent_run({
        "id": record.run_id, "parent_session_id": "navigation_parent", "status": "completed",
        "name": "Navigation child", "task": "Inspect actual fixture checkout", "summary": "Fixture result",
        "worktree": record.as_dict(),
    })
    db.close()
    task = kb.create_task(title="Actual navigation board task", assignee="fixture", board_slug="navigation-fixture")
    kb.patch_task(task["id"], status="ready")
    token, run_id = kb.claim_ready_task(task["id"], profile="fixture", claim_ttl_seconds=300)
    kb.record_worker_execution(task["id"], claim_token=token, run_id=run_id, execution={"session_id": "navigation_parent"})
    (home / "fixture.json").write_text(json.dumps({"task_id": task["id"], "run_id": run_id, "worktree": record.as_dict()}))

    @server.app.post("/api/dev/navigation-fixture/{action}")
    def mutate(action: str):
        from spark_cli.subagent_navigation import _project_slug
        entry = home / "workspace" / _project_slug(record)
        if action == "collision":
            entry.mkdir()
            (entry / "keep.txt").write_text("retain collision fixture")
        elif action == "clear-collision":
            assert (entry / "keep.txt").read_text() == "retain collision fixture"
            (entry / "keep.txt").unlink()
            entry.rmdir()
        elif action == "delete-task":
            kb.delete_task(task["id"])
        elif action == "remove-checkout":
            Path(record.path).rename(home / "retained-checkout")
        else:
            raise ValueError(action)
        return {"ok": True}

    server.start_server(host="127.0.0.1", port=port, open_browser=False)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def main():
    REPORTS.mkdir(parents=True, exist_ok=True)
    checks, errors = [], []
    api_port, web_port = free_port(), free_port()
    api, web = f"http://127.0.0.1:{api_port}", f"http://127.0.0.1:{web_port}"
    if os.environ.get("SPARK_E2E_BUILT_WEB") == "1":
        web = api
    with tempfile.TemporaryDirectory(prefix="spark-navigation-") as temporary:
        home = Path(temporary)
        (home / "workspace/particles").mkdir(parents=True)
        (home / "config.yaml").write_text("model:\n  default: fixture-only\n  provider: ollama\n  base_url: http://127.0.0.1:1/v1\n")
        env = {**os.environ, "SPARK_HOME": str(home), "PYTHONPATH": str(ROOT / "src")}
        processes, logs = [], []
        page = None
        browser = None
        async with async_playwright() as pw:
            try:
                for name in ("backend", "vite"):
                    logs.append(open(REPORTS / (name + ".log"), "w"))
                processes.append(subprocess.Popen([sys.executable, __file__, "--fixture-server", str(api_port)], cwd=ROOT, env=env, stdout=logs[0], stderr=subprocess.STDOUT))
                if web != api:
                    processes.append(subprocess.Popen([str(WEB / "node_modules/.bin/vite"), "--host", "127.0.0.1", "--port", str(web_port), "--strictPort"], cwd=WEB, env={**env, "SPARK_API_TARGET": api}, stdout=logs[1], stderr=subprocess.STDOUT))
                request = await pw.request.new_context()
                for target in (api + "/api/status", web):
                    for _ in range(160):
                        try:
                            if (await request.get(target, timeout=1000)).ok:
                                break
                        except Exception:
                            pass
                        await asyncio.sleep(0.25)
                    else:
                        raise AssertionError("Server unavailable: " + target)
                fixture = json.loads((home / "fixture.json").read_text())
                repo = home / "fixture-repository"
                parent_status = git(repo, "status", "--porcelain")
                browser = await pw.chromium.launch()
                page = await browser.new_page(viewport={"width": 1440, "height": 980}, reduced_motion="reduce")
                page.set_default_timeout(10000)
                page.on("pageerror", lambda error: errors.append(str(error)))
                await page.goto(web, wait_until="domcontentloaded")
                composer = page.get_by_role("textbox", name="Message composer")

                async def select(marker):
                    await page.get_by_role("button", name="Threads", exact=True).click()
                    folder = page.get_by_role("button", name="particles", exact=True)
                    await folder.wait_for(state="visible")
                    if await folder.get_attribute("aria-expanded") == "false":
                        await folder.click()
                    await page.get_by_role("button", name=re.compile("Navigation " + marker)).first.click()
                    await expect(page.get_by_test_id("chat-panel")).to_have_attribute("data-session-id", "navigation_" + marker)
                    await expect(composer).to_be_editable()

                async def detail():
                    row = page.locator('[data-subagent-row="navigation_child"]:visible')
                    back = page.get_by_role("button", name="Back to subagents").filter(visible=True)
                    await row.or_(back).first.wait_for(state="visible")
                    if await row.count():
                        await row.click()
                    await expect(back).to_be_visible()

                def nav_button(name):
                    return page.get_by_role("button", name=name, exact=True).filter(visible=True)

                async def retained():
                    await expect(composer).to_have_value("Retain navigation draft")
                    await expect(page.get_by_role("list", name="Attached context items")).to_contain_text("navigation-note.txt")
                    await expect(nav_button("Back to subagents")).to_be_visible()

                await expect(composer).to_be_editable()
                await select("parent")
                await composer.fill("Retain navigation draft")
                await page.locator('input[type="file"]').first.set_input_files({"name": "navigation-note.txt", "mimeType": "text/plain", "buffer": b"fixture attachment"})
                await expect(page.get_by_role("list", name="Attached context items")).to_contain_text("Ready")
                await detail()
                await expect(nav_button("Open linked task")).to_be_enabled()
                await expect(nav_button("Open worktree")).to_be_enabled()
                async with page.expect_response(lambda response: "/api/kanban/board?board=navigation-fixture" in response.url and response.status == 200):
                    await nav_button("Open linked task").click()
                await expect(page.get_by_role("heading", name="Actual navigation board task", exact=True)).to_be_visible()
                await expect(page.locator("aside").filter(has=page.get_by_role("heading", name="Actual navigation board task", exact=True))).to_contain_text("ID: " + fixture["task_id"])
                await expect(page.locator("aside").filter(has=page.get_by_role("heading", name="Actual navigation board task", exact=True))).to_contain_text("Board: navigation-fixture")
                await page.screenshot(path=str(REPORTS / "actual-task.png"))
                await select("parent")
                await retained()
                checks.append("real task_runs execution link opens the exact board task; returning retains parent draft, ready attachment and child selection")

                # Hold a real fresh task read until after a chat switch.
                started, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
                async def late_task(route):
                    response = await route.fetch()
                    started.set()
                    await release.wait()
                    await route.fulfill(response=response)
                    finished.set()
                pattern = "**/subagents/navigation_child/navigation"
                await page.route(pattern, late_task)
                await nav_button("Open linked task").click()
                await asyncio.wait_for(started.wait(), timeout=10)
                await select("other")
                release.set()
                await asyncio.wait_for(finished.wait(), timeout=10)
                await expect(page.get_by_test_id("chat-panel")).to_have_attribute("data-session-id", "navigation_other")
                assert not await page.get_by_role("heading", name="Actual navigation board task", exact=True).count()
                await page.unroute(pattern, late_task)
                await select("parent")
                await retained()
                checks.append("late task lookup after a chat switch cannot navigate the newly selected thread")

                # A real colliding directory is preserved and never imported.
                assert (await request.post(api + "/api/dev/navigation-fixture/collision")).ok
                before = (home / "workspace").stat().st_mtime_ns
                await nav_button("Refresh destinations").click()
                await expect(nav_button("Open worktree")).to_be_disabled()
                await expect(page.get_by_text("The worktree project name is already in use.", exact=True).filter(visible=True)).to_be_visible()
                assert (await request.post(api + "/api/conversations/navigation_parent/subagents/navigation_child/navigation/worktree")).status == 409
                assert (home / "workspace").stat().st_mtime_ns == before
                assert (await request.post(api + "/api/conversations/navigation_other/subagents/navigation_child/navigation/worktree")).status == 404
                assert (await request.post(api + "/api/dev/navigation-fixture/clear-collision")).ok
                await nav_button("Refresh destinations").click()
                await expect(nav_button("Open worktree")).to_be_enabled()
                checks.append("collision disables navigation with a reason; explicit POST rejects collision and unowned child without altering the workspace")

                # Server creates the actual link, then its acknowledgement is lost.
                lost = 0
                async def lose_ack(route):
                    nonlocal lost
                    lost += 1
                    await route.fetch()
                    await route.abort("failed")
                post_pattern = "**/subagents/navigation_child/navigation/worktree"
                await page.route(post_pattern, lose_ack)
                await nav_button("Open worktree").click()
                await expect(page.get_by_role("alert").filter(visible=True)).to_be_visible()
                await page.unroute(post_pattern, lose_ack)
                links = list((home / "workspace").glob("subagent-navigation_child-*"))
                assert len(links) == 1 and links[0].is_symlink()
                inode = links[0].lstat().st_ino
                await nav_button("Open worktree").click()
                await expect(page.get_by_role("button", name=links[0].name, exact=True)).to_be_visible()
                # The project action uses Chat's actual checkout file tree.
                await page.get_by_role("button", name="Files", exact=True).filter(visible=True).last.click()
                await page.get_by_role("menuitem", name=re.compile("^Files")).click()
                await expect(page.get_by_text("child-dirty.txt", exact=True).filter(visible=True)).to_be_visible()
                assert links[0].lstat().st_ino == inode
                assert links[0].resolve() == Path(fixture["worktree"]["path"]).resolve()
                assert git(repo, "status", "--porcelain") == parent_status
                assert (repo / "committed.txt").read_text() == "dirty parent retained\n"
                assert (links[0] / "child-dirty.txt").read_text() == "actual checkout content\n"
                assert git(links[0], "symbolic-ref", "--short", "HEAD") == fixture["worktree"]["branch"]
                assert json.loads((home / "subagent-worktrees/navigation_child.json").read_text())["active"] is True
                await page.screenshot(path=str(REPORTS / "actual-checkout.png"))
                await select("parent")
                await detail()
                await retained()
                checks.append("lost worktree acknowledgement retries the same symlink and opens actual checkout files; dirty parent, child files, branch and active ownership are retained")

                # A late successful worktree POST is equally scoped to its initiator.
                started, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
                async def late_worktree(route):
                    response = await route.fetch()
                    started.set()
                    await release.wait()
                    await route.fulfill(response=response)
                    finished.set()
                await page.route(post_pattern, late_worktree)
                await nav_button("Open worktree").click()
                await asyncio.wait_for(started.wait(), timeout=10)
                await select("other")
                release.set()
                await asyncio.wait_for(finished.wait(), timeout=10)
                await expect(page.get_by_test_id("chat-panel")).to_have_attribute("data-session-id", "navigation_other")
                await page.unroute(post_pattern, late_worktree)
                await select("parent")
                await detail()
                await retained()
                checks.append("late worktree acceptance after chat switch cannot change the active thread/project")

                assert (await request.post(api + "/api/dev/navigation-fixture/delete-task")).ok
                await nav_button("Open linked task").click()
                await expect(page.get_by_role("alert").filter(visible=True)).to_contain_text("No linked board task")
                assert (await request.post(api + "/api/dev/navigation-fixture/remove-checkout")).ok
                await nav_button("Open worktree").click()
                await expect(page.get_by_role("alert").filter(visible=True)).to_contain_text("no longer available")
                await nav_button("Refresh destinations").click()
                await expect(nav_button("Open linked task")).to_be_disabled()
                await expect(nav_button("Open worktree")).to_be_disabled()
                assert links[0].is_symlink() and links[0].lstat().st_ino == inode
                assert (home / "retained-checkout/child-dirty.txt").read_text() == "actual checkout content\n"
                await retained()
                await page.reload(wait_until="domcontentloaded")
                await expect(composer).to_be_editable()
                await detail()
                await retained()
                await page.screenshot(path=str(REPORTS / "unavailable-destinations.png"))
                checks.append("deleted task and removed checkout fail honestly on fresh activation, then disable after refresh; draft/attachment/child selection survive browser reload without replay")
                assert not errors, errors
            except Exception:
                if page:
                    await page.screenshot(path=str(REPORTS / "failure.png"))
                    (REPORTS / "failure-dom.txt").write_text(await page.locator("body").inner_text())
                raise
            finally:
                if browser:
                    await browser.close()
                for process in reversed(processes):
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                for log in logs:
                    log.close()
                report = {"checks": checks, "page_errors": errors, "built_web": web == api, "mode": "real temporary SQLite/Git; controlled late/lost HTTP acknowledgements; no providers or sends"}
                (REPORTS / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--fixture-server":
        fixture_server(int(sys.argv[2]))
    else:
        asyncio.run(main())
