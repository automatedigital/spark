// Built-bundle SP12 acceptance. Run once per dist (same machine/fixture):
// SP12_DIST=/tmp/sp12-candidate-dist node e2e/palette.mjs
// SP12_BASELINE=1 SP12_DIST=/tmp/sp12-baseline-dist node e2e/palette.mjs
import { spawn } from "node:child_process";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import net from "node:net";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";
import { chromium } from "playwright";
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../../..");
const dist = process.env.SP12_DIST;
if (!dist) throw new Error("SP12_DIST must name a verified production build");
const baseline = process.env.SP12_BASELINE === "1";
const home = await mkdtemp(path.join(os.tmpdir(), "spark-sp12-browser-"));
const port = await new Promise((resolve) => { const s = net.createServer(); s.listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => resolve(p)); }); });
await writeFile(path.join(home, "config.yaml"), "model:\n  default: fixture\n  provider: ollama\n  base_url: http://localhost:11434/v1\n");
await mkdir(path.join(home, "skills", "palette-fixture"), { recursive: true });
await writeFile(path.join(home, "skills", "palette-fixture", "SKILL.md"), "---\nname: palette-fixture\ndescription: Palette test skill\n---\nFixture only.\n");
const code = `
from pathlib import Path
import os
from core.spark_state import SessionDB
db=SessionDB()
db._conn.executemany("INSERT INTO sessions (id,source,title,started_at) VALUES (?, 'web', ?, ?)", [(f'palette-{i:05}', f'Thread {i}', i) for i in range(10000)])
db._conn.commit()
db.set_session_title('palette-00000', 'Ancientneedle thread')
db.append_message('palette-00000','user','ancientneedle message content')
db.close()
from cron.jobs import create_job
create_job('Palette fixture task', '0 9 * * *', name='palette-fixture-job')
import spark_cli.web_server as w
from spark_cli.workspace_routes import _workspace_root
(_workspace_root()/'palette-fixture-project').mkdir()
w.app.router.routes[:] = [r for r in w.app.router.routes if getattr(r,'name','') not in {'assets','serve_spa','no_frontend'}]
w.WEB_DIST=Path(${JSON.stringify(dist)})
w.mount_spa(w.app)
w.start_server(host='127.0.0.1',port=${port},open_browser=False)
`;
const server = spawn(process.env.PYTHON || path.join(root, ".venv/bin/python"), ["-c", code], { cwd: root, env: { ...process.env, PYTHONPATH: path.join(root, "src"), SPARK_HOME: home, SPARK_WEB_FAKE_STREAMS: "1" }, stdio: ["ignore", "pipe", "pipe"] });
let logs = "";
for (const stream of [server.stdout, server.stderr]) stream.on("data", (chunk) => { logs += chunk; });
const origin = `http://127.0.0.1:${port}`;
console.log(`SP12 browser: ${origin}; synthetic home: ${home}`);
let browser;
let currentPage;
const report = { baseline, dist, home, fixtureSessions: 10000, repeats: [], flows: [] };
try {
  let ready = false;
  for (let i = 0; i < 240; i++) { try { if ((await fetch(origin + "/api/status")).ok) { ready = true; break; } } catch {} await new Promise((r) => setTimeout(r, 250)); }
  if (!ready) throw new Error(`Backend failed: ${logs.slice(-4000)}`);
  browser = await chromium.launch({ headless: true });
  for (let i = 0; i < 5; i++) {
    const context = await browser.newContext();
    const page = await context.newPage();
    currentPage = page;
    await page.goto(origin);
    await page.getByText("Spark", { exact: true }).first().waitFor({ timeout: 30000 });
    // Let profile identity resolve before measuring a user opening the palette.
    await page.waitForTimeout(750);
    const reads = [];
    const openRequests = [];
    let opening = true;
    let measuring = true;
    const relevant = (url) => /\/api\/(palette\/|sessions\?|sessions\/search|skills(?:\?|$)|cron\/jobs|workspace\/projects(?:\?|$))/.test(url);
    page.on("request", (req) => { if (measuring && relevant(req.url())) { reads.push(req.url().replace(origin, "")); if (opening) openRequests.push(req); } });
    const dialog = page.getByRole("dialog", { name: "Command palette" });
    // Browser-clock event-to-DOM timing excludes Playwright transport/locator overhead.
    const actionableMs = await page.evaluate(() => new Promise((resolve) => {
      const start = performance.now();
      const observer = new MutationObserver(() => {
        if (document.querySelector('[aria-label="Command palette"] [role="option"]')) {
          observer.disconnect(); resolve(performance.now() - start);
        }
      });
      observer.observe(document.body, { childList: true, subtree: true });
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", ctrlKey: true, bubbles: true }));
    }));
    await page.waitForTimeout(600);
    const openReads = [...reads];
    opening = false;
    if (!baseline) {
      const paletteReads = openReads.filter((url) => url.startsWith("/api/palette/"));
      assert(paletteReads.length <= 1, JSON.stringify(openReads));
      assert(paletteReads.every((url) => url.startsWith("/api/palette/recent?")), JSON.stringify(openReads));
      assert(!openReads.some((url) => /limit=500|\/api\/skills|\/api\/cron\/jobs/.test(url)), JSON.stringify(openReads));
    }
    reads.length = 0;
    const queryStart = performance.now();
    await dialog.getByRole("combobox").fill("ancientneedle");
    await dialog.getByRole("option", { name: /Ancientneedle thread/ }).first().waitFor({ timeout: 30000 });
    const queryMs = performance.now() - queryStart;
    const openBytes = (await Promise.all(openRequests.map(async (request) => {
      try { const response = await request.response(); return response ? (await response.body()).length : 0; } catch { return 0; }
    }))).reduce((a, b) => a + b, 0);
    const completedQueryReadMs = await page.evaluate(() => performance.getEntriesByType("resource")
      .filter((entry) => entry.name.includes("q=ancientneedle"))
      .map((entry) => ({ url: new URL(entry.name).pathname, duration: entry.duration })));
    report.repeats.push({ actionableMs, queryMs, openReads, openBytes, queryReads: [...reads], completedQueryReadMs });
    console.log(`repeat ${i + 1}: actionable=${actionableMs.toFixed(1)}ms query=${queryMs.toFixed(1)}ms openReads=${openReads.length}`);
    measuring = false;
    await page.keyboard.press("Escape");
    const warmMs = await page.evaluate(() => new Promise((resolve) => {
      const start = performance.now();
      const observer = new MutationObserver(() => {
        if (document.querySelector('[aria-label="Command palette"] [role="option"]')) {
          observer.disconnect(); resolve(performance.now() - start);
        }
      });
      observer.observe(document.body, { childList: true, subtree: true });
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", ctrlKey: true, bubbles: true }));
    }));
    report.repeats.at(-1).warmMs = warmMs;
    if (!baseline && i === 0) {
      const input = dialog.getByRole("combobox");
      await input.fill("palette-fixture");
      await dialog.getByRole("option", { name: /palette-fixture-project/ }).waitFor();
      await dialog.getByRole("option", { name: /palette-fixture-job/ }).waitFor();
      await dialog.getByRole("option", { name: /^palette-fixture / }).waitFor();
      report.flows.push("project/job/skill explicit queries");
      for (const [kind, label] of [["project", /palette-fixture-project/], ["scheduled-task", /palette-fixture-job/], ["skill", /^palette-fixture /]]) {
        await page.evaluate(() => {
          window.__paletteTarget = null;
          window.addEventListener("spark-global-nav", (event) => { window.__paletteTarget = event.detail; }, { once: true });
        });
        await dialog.getByRole("option", { name: label }).click();
        await page.waitForFunction((kind) => window.__paletteTarget?.type === kind, kind);
        const target = await page.evaluate(() => window.__paletteTarget);
        assert(target.id, `Missing ${kind} destination`);
        await page.keyboard.press("Control+k");
        await dialog.getByRole("combobox").fill("palette-fixture");
        await dialog.getByRole("option", { name: label }).waitFor();
      }
      report.flows.push("project/job/skill global navigation contracts");

      await input.fill("Thread");
      await page.waitForTimeout(400);
      await dialog.getByRole("button", { name: "More threads", exact: true }).waitFor();
      const first = await dialog.getByRole("option").first().innerText();
      await dialog.getByRole("button", { name: "More threads", exact: true }).click();
      await page.waitForTimeout(300);
      assert.notEqual(await dialog.getByRole("option").first().innerText(), first);
      report.flows.push("bounded title pages");
      // Deferred replies exercise retirement and partial failures in the actual built component.
      await page.route("**/api/palette/*", async (route) => {
        const url = new URL(route.request().url());
        if (url.searchParams.get("q") === "slow") {
          await new Promise((r) => setTimeout(r, 900));
          await route.fulfill({ json: { items: [{ kind: "thread", id: "retired", label: "Retired result", description: "" }], next: null } }).catch(() => {});
        } else if (url.pathname.endsWith("/skills") && url.searchParams.get("q") === "partial") {
          await route.fulfill({ status: 500, json: { detail: "fixture category failure" } });
        } else if (url.searchParams.get("q") === "partial") {
          const delay = url.pathname.endsWith("/jobs") ? 50 : 500;
          await new Promise((r) => setTimeout(r, delay));
          await route.fulfill({ json: { items: [{ kind: "thread", id: url.pathname, label: url.pathname, description: "partial" }], next: null } }).catch(() => {});
        } else await route.continue();
      });
      await input.fill("slow");
      await page.waitForTimeout(220);
      await page.keyboard.press("Escape");
      await page.keyboard.press("Control+k");
      await page.waitForTimeout(1100);
      assert.equal(await page.getByText("Retired result").count(), 0);
      report.flows.push("close/reopen retires slow replies");
      await dialog.getByRole("combobox").fill("partial");
      await dialog.getByRole("option").first().waitFor();
      await page.keyboard.press("ArrowDown");
      const selected = await dialog.getByRole("combobox").getAttribute("aria-activedescendant");
      assert(selected?.includes("/jobs"), `Expected first-arriving job category, got ${selected}`);
      await page.waitForTimeout(650);
      assert.equal(await dialog.getByRole("combobox").getAttribute("aria-activedescendant"), selected);
      await dialog.getByRole("status").filter({ hasText: "skills" }).waitFor();
      report.flows.push("partial category failure; selection stable as categories arrive");
      await page.keyboard.press("Escape");
      await context.setOffline(true);
      await page.keyboard.press("Control+k");
      await dialog.getByRole("option", { name: /Settings/ }).waitFor();
      await dialog.getByRole("option", { name: /Thread 9999/ }).waitFor();
      report.flows.push("offline static actions and scoped recent snapshot");
      await context.setOffline(false);
      await page.route("**/remote/api/**", async (route) => {
        await route.fulfill({ json: route.request().url().includes("/palette/")
          ? { items: [{ kind: "thread", id: "remote-only", label: "Remote recent", description: "" }], next: null }
          : {} });
      });
      await page.evaluate((origin) => {
        localStorage.setItem("spark-connection-mode", "remote");
        localStorage.setItem("spark-remote-base-url", origin + "/remote");
        window.dispatchEvent(new Event("storage"));
      }, origin);
      await dialog.getByRole("option", { name: /Remote recent/ }).waitFor();
      assert.equal(await dialog.getByRole("option", { name: /Thread 9999/ }).count(), 0);
      await page.evaluate(() => {
        localStorage.setItem("spark-connection-mode", "local");
        localStorage.removeItem("spark-remote-base-url");
        window.dispatchEvent(new Event("storage"));
      });
      await dialog.getByRole("option", { name: /Thread 9999/ }).waitFor();
      assert.equal(await dialog.getByRole("option", { name: /Remote recent/ }).count(), 0);
      report.flows.push("backend A/B/A retires cached scope");
      await page.route("**/api/sidebar/threads", async (route) => {
        const response = await route.fetch();
        const snapshot = await response.json();
        await route.fulfill({ json: { ...snapshot, preference_scope: "palette-replay-profile" } });
      });
      await page.route("**/api/palette/recent?*", (route) => route.fulfill({ json: { items: [{ kind: "thread", id: "profile-only", label: "Other profile recent", description: "" }], next: null } }));
      await page.evaluate(() => window.dispatchEvent(new Event("focus")));
      await dialog.getByRole("option", { name: /Other profile recent/ }).waitFor();
      assert.equal(await dialog.getByRole("option", { name: /Thread 9999/ }).count(), 0);
      report.flows.push("profile projection replay retires cached scope");

    }
    await context.close();
  }
  await mkdir(path.join(root, "src/spark_cli/web/e2e/reports"), { recursive: true });
  const output = process.env.SP12_REPORT || path.join(os.tmpdir(), `sp12-${baseline ? "baseline" : "candidate"}-browser.json`);
  await writeFile(output, JSON.stringify(report, null, 2) + "\n");
  console.log(JSON.stringify(report, null, 2));
} catch (error) {
  console.error("Palette failure:", error);
  if (currentPage && !currentPage.isClosed()) {
    console.error("Visible palette:", await currentPage.locator('[aria-label="Command palette"]').innerText().catch(() => "closed"));
    console.error("Palette network:", await currentPage.evaluate(() => performance.getEntriesByType("resource").filter((entry) => entry.name.includes("/palette/")).map((entry) => ({ url: entry.name, duration: entry.duration }))));
    await currentPage.screenshot({ path: path.join(os.tmpdir(), "sp12-palette-failure.png") }).catch(() => {});
  }
  console.error("Backend tail:", logs.slice(-3000));
  throw error;
} finally {
  await browser?.close();
  server.kill("SIGTERM");
}
