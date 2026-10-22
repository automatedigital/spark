"""F09 provider-free dashboard edits against real temporary-profile storage.

Run with the checkout src on PYTHONPATH and .venv active. Uses Vite source;
optionally set SPARK_E2E_ASSET_DIR to a separately built frontend directory.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
ROOT = WEB.parents[2]
REPORTS = Path(os.environ.get("SPARK_E2E_REPORTS", "/tmp/spark-packets-20261022/F09-browser"))


def fixture_server(port):
    from fastapi.staticfiles import StaticFiles

    import spark_cli.web_server as server
    import tools.skills_sync as sync
    from core.spark_constants import get_spark_home
    sync.sync_skills = lambda **kwargs: {}
    skill = get_spark_home() / "skills" / "history-demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: history-demo\ndescription: History fixture\n---\n\nInitial instructions.\n")
    if os.environ.get("SPARK_E2E_ASSET_DIR"):
        server.WEB_DIST = Path(os.environ["SPARK_E2E_ASSET_DIR"])
        for route in server.app.routes:
            if getattr(route, "path", None) == "/assets":
                route.app = StaticFiles(directory=server.WEB_DIST / "assets")
    server.start_server(host="127.0.0.1", port=port, open_browser=False)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def main():
    from playwright.async_api import async_playwright, expect
    REPORTS.mkdir(parents=True, exist_ok=True)
    api_port, web_port = free_port(), free_port()
    with tempfile.TemporaryDirectory(prefix="spark-f09-") as directory:
        home = Path(directory)
        env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home), "SPARK_HOME": str(home / "profile"), "PYTHONPATH": str(ROOT / "src")}
        processes = []
        errors = []
        with (REPORTS / "server.log").open("w") as log:
            try:
                processes.append(subprocess.Popen([sys.executable, __file__, "--fixture-server", str(api_port)], cwd=ROOT, env=env, stdout=log, stderr=log))
                url = f"http://127.0.0.1:{api_port}"
                if not env.get("SPARK_E2E_ASSET_DIR"):
                    processes.append(subprocess.Popen([str(WEB / "node_modules/.bin/vite"), "--host", "127.0.0.1", "--port", str(web_port), "--strictPort"], cwd=WEB, env={**env, "SPARK_API_TARGET": url}, stdout=log, stderr=log))
                    url = f"http://127.0.0.1:{web_port}"
                async with async_playwright() as pw:
                    browser = await pw.chromium.launch()
                    page = await browser.new_page(viewport={"width": 1440, "height": 980})
                    await page.add_init_script("localStorage.setItem('spark-onboarding-complete', 'true'); localStorage.setItem('spark-active-page', 'skillsTools');")
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    for _attempt in range(60):
                        try:
                            response = await page.request.get(url + "/api/skills")
                            if response.ok:
                                break
                        except Exception:
                            pass
                        await asyncio.sleep(0.5)
                    else:
                        raise RuntimeError("Fixture server did not become ready")
                    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    await page.get_by_role("button", name="Skills", exact=True).click()
                    await page.get_by_role("button", name="View history-demo", exact=True).click()
                    await page.get_by_role("button", name="History", exact=True).click()
                    await expect(page.get_by_text("No retained dashboard edits for this skill.")).to_be_visible()
                    await expect(page.get_by_text("Dashboard SKILL.md edits only.", exact=False)).to_be_visible()
                    await page.get_by_role("button", name="Close history").click()
                    for body in ("First dashboard edit.", "Second dashboard edit."):
                        await page.get_by_role("button", name="Edit", exact=True).click()
                        await page.get_by_role("textbox", name="Edit SKILL.md").fill(f"---\nname: history-demo\ndescription: History fixture\n---\n\n{body}\n")
                        await page.get_by_role("button", name="Save changes", exact=True).click()
                        await expect(page.get_by_role("button", name="Edit", exact=True)).to_be_visible()
                    await page.get_by_role("button", name="History", exact=True).click()
                    drawer = page.get_by_role("dialog", name="Dashboard skill edit history", exact=True)
                    await expect(drawer.locator("details")).to_have_count(2)
                    await drawer.locator("summary").first.click()
                    await expect(drawer.locator("pre").nth(0)).to_contain_text("First dashboard edit.")
                    await expect(drawer.locator("pre").nth(1)).to_contain_text("Second dashboard edit.")
                    await page.screenshot(path=str(REPORTS / "history.png"))
                    await page.reload()
                    await page.get_by_role("button", name="Skills", exact=True).click()
                    await page.get_by_role("button", name="View history-demo", exact=True).click()
                    await page.get_by_role("button", name="History", exact=True).click()
                    await expect(page.locator("details")).to_have_count(2)
                    await page.get_by_role("button", name="Close history").click()
                    (home / "profile" / "skill-history.json").write_text("broken")
                    await page.get_by_role("button", name="History", exact=True).click()
                    await expect(page.get_by_role("alert")).to_contain_text("History could not be loaded")
                    assert errors == [], errors
                    await browser.close()
            finally:
                for process in reversed(processes):
                    process.terminate()
                    process.wait(timeout=15)
    report = {"checks": ["empty state", "coverage label", "two real dashboard saves", "before/after pair", "reload persistence", "unavailable history error"], "page_errors": errors, "providers": "none", "isolated_home": True}
    (REPORTS / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == "__main__":
    if "--fixture-server" in sys.argv:
        fixture_server(int(sys.argv[-1]))
    else:
        asyncio.run(main())
