/** Isolated P05 acceptance. Run from web/: node src/components/sidebar/sidebarMetadata.e2e.mjs
 * Uses the repository Playwright installation, real SQLite/auth/SSE, fake streams,
 * and Vite source. No live providers, production assets or user profile writes.
 */
import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const repoRoot = path.resolve(webRoot, "../../..");
const python = process.env.PYTHON || path.join(repoRoot, ".venv/bin/python");
const home = await mkdtemp(path.join(tmpdir(), "spark-p05-"));
const env = { ...process.env, PYTHONPATH: path.join(repoRoot, "src"), SPARK_HOME: home, SPARK_WEB_FAKE_STREAMS: "1" };
const children = [];
let browser;
let page;
function start(command, args, extraEnv = {}) {
  const child = spawn(command, args, { cwd: webRoot, env: { ...env, ...extraEnv }, stdio: ["ignore", "pipe", "pipe"] });
  child.logs = "";
  child.stdout.on("data", (data) => { child.logs += data; });
  child.stderr.on("data", (data) => { child.logs += data; });
  children.push(child);
  return child;
}
async function port() {
  const server = net.createServer();
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const port = server.address().port;
  await new Promise((resolve) => server.close(resolve));
  return port;
}
async function waitFor(url) {
  for (let attempt = 0; attempt < 150; attempt++) {
    if (await fetch(url).then((r) => r.ok).catch(() => false)) return;
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error(`Server unavailable: ${url}`);
}
try {
  await writeFile(path.join(home, "config.yaml"), "model:\n  default: fixture-model\n  provider: ollama\n  base_url: http://127.0.0.1:1/v1\n");
  await mkdir(path.join(home, "workspace", "alpha"), { recursive: true });
  const seed = spawnSync(python, ["-c", `
import time
from core.spark_state import SessionDB
from spark_cli.sidebar_metadata import SidebarMetadata
db = SessionDB()
now = time.time()
for index in range(1000):
    sid = f"p05-{index:03d}"
    db.create_session(sid, "workspace:alpha" if index % 2 == 0 else "web", model="fixture-model")
    db.set_session_title(sid, f"P05 thread {index:03d}")
    db._conn.execute("UPDATE sessions SET started_at = ? WHERE id = ?", (now-index, sid))
store = SidebarMetadata(db)
for index in range(3):
    store.patch(f"p05-{index:03d}", 0, {"pinned": True, "position": index*1024})
for index in range(3, 10):
    store.patch(f"p05-{index:03d}", 0, {"settled": True})
store.patch("p05-999", 0, {"settled": True})
db.create_web_pending_action(action_id="pending-fixture", session_id="p05-999", turn_id="decision-run", kind="approval", payload={"question": "Approve fixture?"})
db.append_message("p05-997", "user", "hidden full history needle")
db._conn.execute("UPDATE messages SET timestamp = ? WHERE session_id = 'p05-997'", (now-997,))
db.close()
`], { env, encoding: "utf8" });
  assert.equal(seed.status, 0, seed.stderr);
  const apiPort = await port();
  const vitePort = await port();
  const apiBase = `http://127.0.0.1:${apiPort}`;
  const webBase = `http://127.0.0.1:${vitePort}`;
  start(python, ["-c", `
from spark_cli import web_server
web_server.start_server("127.0.0.1", ${apiPort}, False)
`]);
  start(path.join(webRoot, "node_modules/.bin/vite"), [webRoot, "--host", "127.0.0.1", "--port", String(vitePort)], { SPARK_API_TARGET: apiBase });
  await Promise.all([waitFor(`${apiBase}/api/status`), waitFor(webBase)]);
  browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const scope = (await (await fetch(`${apiBase}/api/sidebar/threads`)).json()).preference_scope;
  await context.addInitScript(({ key }) => localStorage.setItem(key, "threads"), { key: `spark-sidebar-view:v1:${encodeURIComponent(webBase)}:${scope}` });
  page = await context.newPage();
  const errors = [];
  const sessionPageOffsets = [];
  page.on("response", (response) => {
    const url = new URL(response.url());
    if (url.pathname === "/api/sessions" && response.ok()) sessionPageOffsets.push(Number(url.searchParams.get("offset")));
  });
  page.on("pageerror", (error) => errors.push(error.message));
  const startAt = performance.now();
  await page.goto(webBase);
  await page.getByTitle("Actions for P05 thread 000", { exact: true }).first().waitFor();
  const firstUsefulMs = Math.round(performance.now() - startAt);
  const action = async (title, name) => {
    await page.getByTitle(`Actions for ${title}`, { exact: true }).first().click();
    const dialog = page.getByRole("dialog", { name: `Organize ${title}`, exact: true });
    await dialog.getByRole("button", { name, exact: true }).click();
  };
  const entries = async () => (await (await fetch(`${apiBase}/api/sidebar/threads`)).json()).entries;
  const waitMeta = async (id, predicate) => {
    for (let i = 0; i < 100; i++) {
      if (predicate((await entries())[id])) return;
      await page.waitForTimeout(30);
    }
    throw new Error(`Metadata condition failed for ${id}`);
  };
  const pinnedOrder = () => page.locator('[data-sidebar-session-row]').evaluateAll((rows) => rows.slice(0, 3).map((row) => row.dataset.sidebarSessionRow));
  assert.deepEqual(await pinnedOrder(), ["p05-000", "p05-001", "p05-002"]);
  await action("P05 thread 001", "Move up");
  await waitMeta("p05-001", (meta) => meta.position < 0);
  await page.waitForTimeout(100);
  assert.deepEqual(await pinnedOrder(), ["p05-001", "p05-000", "p05-002"]);

  // A second client agrees after refresh and receives the normal live event.
  const second = await context.newPage();
  await second.goto(webBase);
  await second.getByTitle("Actions for P05 thread 001", { exact: true }).first().waitFor();
  assert.deepEqual(await second.locator('[data-sidebar-session-row]').evaluateAll((rows) => rows.slice(0, 3).map((row) => row.dataset.sidebarSessionRow)), ["p05-001", "p05-000", "p05-002"]);
  const live = await fetch(`${apiBase}/api/dev/fake-streams`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ session_id: "p05-000", title: "P05 thread 000", source: "workspace:alpha", message: "fixture stream", events: [{ type: "token", text: "fixture response", delay_ms: 1000 }, { type: "token", text: " complete", delay_ms: 1000 }] }) });
  assert.equal(live.status, 200);
  await page.waitForTimeout(300);
  assert.deepEqual(await pinnedOrder(), ["p05-001", "p05-000", "p05-002"]);
  await page.getByTitle("Actions for P05 thread 000", { exact: true }).first().click();
  assert.equal(await page.getByRole("dialog").getByRole("button", { name: "Settle", exact: true }).isDisabled(), true);
  await page.keyboard.press("Escape");
  await page.waitForTimeout(2200);
  assert.deepEqual(await pinnedOrder(), ["p05-001", "p05-000", "p05-002"]);
  await action("P05 thread 002", "Unpin");
  await waitMeta("p05-002", (meta) => !meta.pinned);
  await second.waitForFunction(() => !document.querySelector('[data-sidebar-session-row="p05-002"]'));
  await action("P05 thread 001", "Settle");
  await waitMeta("p05-001", (meta) => meta.settled);
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await waitMeta("p05-001", (meta) => !meta.settled);

  // Stale Undo refuses a newer concurrent edit, preserving both versions.
  await action("P05 thread 001", "Settle");
  await waitMeta("p05-001", (meta) => meta.settled);
  const current = (await entries())["p05-001"];
  const response = await fetch(`${apiBase}/api/sidebar/threads/p05-001`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ expected_revision: current.revision, pinned: false }) });
  assert.equal(response.status, 200);
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await page.getByRole("alert").filter({ hasText: "Metadata changed" }).waitFor();
  assert.equal((await entries())["p05-001"].settled, true);
  assert.equal((await entries())["p05-001"].pinned, false);

  // A pending decision outside the loaded page is hydrated and cannot settle.
  const search = page.getByPlaceholder("Search projects and chats…");
  await search.fill("P05 thread 999");
  await page.getByRole("button", { name: "P05 thread 999, Needs you", exact: true }).waitFor();
  await page.getByTitle("Actions for P05 thread 999", { exact: true }).click();
  const decisionDialog = page.getByRole("dialog", { name: "Organize P05 thread 999", exact: true });
  // Existing settled metadata may be cleared, but cannot hide the decision.
  await decisionDialog.getByRole("button", { name: "Unsettle", exact: true }).click();
  await waitMeta("p05-999", (meta) => !meta.settled);
  await page.getByTitle("Actions for P05 thread 999", { exact: true }).click();
  assert.equal(await page.getByRole("dialog").getByRole("button", { name: "Settle", exact: true }).isDisabled(), true);
  await page.keyboard.press("Escape");
  assert.equal(await page.getByTitle("Actions for P05 thread 999", { exact: true }).evaluate((el) => document.activeElement === el), true);
  await search.fill("hidden full history needle");
  await page.getByRole("button", { name: /P05 thread 997, Ready/ }).waitFor();
  await search.fill("");

  // Project creation entry opens its folder and keeps compose context explicit.
  const project = page.getByRole("button", { name: "alpha", exact: true });
  await project.click();
  await page.locator('[data-sidebar-session-row="p05-000"]').last().waitFor();
  await page.getByTitle("New thread in this project").first().click();
  await page.locator('[data-sidebar-session-row="p05-000"]').last().waitFor();

  await page.getByRole("button", { name: /^P05 thread 000, (Ready|Unread), pinned$/ }).first().click();
  const composer = page.getByRole("textbox", { name: "Message composer", exact: true });
  await composer.fill("Keep this draft and attachment");
  await page.locator('input[type="file"]').first().setInputFiles({ name: "p05-draft.txt", mimeType: "text/plain", buffer: Buffer.from("attachment fixture") });
  await page.getByText("p05-draft.txt", { exact: true }).first().waitFor();
  await page.waitForTimeout(350);
  await page.getByRole("button", { name: "P05 thread 002, Ready", exact: true }).click();
  await composer.fill("Separate second chat draft");
  await page.getByRole("button", { name: "P05 thread 000, Ready, pinned", exact: true }).first().click();
  assert.equal(await composer.inputValue(), "Keep this draft and attachment");
  await page.getByText("p05-draft.txt", { exact: true }).first().waitFor();

  const mountedRows = await page.locator('[data-sidebar-session-row]').count();
  assert.ok(mountedRows < 60, `Virtualization mounted ${mountedRows} rows`);
  // Keyboard alternatives remain usable inside virtualized rows.
  const row = page.getByRole("button", { name: "P05 thread 000, Ready, pinned", exact: true }).first();
  // Let the existing chat selection/composer autofocus finish before testing
  // deliberate keyboard navigation in the sidebar.
  await page.waitForTimeout(300);
  await row.focus();
  await page.keyboard.press("ArrowDown");
  await page.waitForTimeout(100);
  assert.equal(await page.evaluate(() => document.activeElement?.getAttribute("role")), "button");
  const scroll = page.getByTestId("session-sidebar-scroll");
  await scroll.evaluate((element) => { element.scrollTop = element.scrollHeight; });
  for (let attempt = 0; attempt < 100 && !sessionPageOffsets.some((offset) => offset > 0); attempt++) await page.waitForTimeout(30);
  assert.ok(sessionPageOffsets.some((offset) => offset > 0), `Paging requests: ${sessionPageOffsets}`);
  await page.waitForTimeout(250);
  assert.ok(await page.locator('[data-sidebar-session-row]').count() < 60);
  await scroll.evaluate((element) => { element.scrollTop = 500; });
  await page.waitForTimeout(150);
  const anchor = () => scroll.evaluate((element) => {
    const top = element.getBoundingClientRect().top;
    const row = [...element.querySelectorAll("[data-sidebar-row]")].find((candidate) => candidate.getBoundingClientRect().bottom > top + 1);
    return row ? `${row.dataset.sidebarRow}:${row.dataset.sidebarSessionRow ?? ""}` : null;
  });
  const before = await anchor();
  const meta = (await entries())["p05-002"];
  await fetch(`${apiBase}/api/sidebar/threads/p05-002`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ expected_revision: meta.revision, pinned: true }) });
  await page.waitForTimeout(400);
  assert.equal(await anchor(), before, "Metadata updates preserve the sidebar scroll anchor");
  await page.reload();
  await page.locator('[data-sidebar-session-row="p05-000"]').last().waitFor();
  await page.waitForFunction(() => document.querySelector('textarea[aria-label="Message composer"]')?.value === "Keep this draft and attachment");
  await page.getByText("p05-draft.txt", { exact: true }).first().waitFor();
  assert.equal((await entries())["p05-001"].settled, true);
  await page.getByRole("button", { name: "Inbox", exact: true }).click();
  await page.getByRole("tab", { name: /Running/ }).click();
  await page.getByRole("region", { name: "Pending decisions" }).waitFor();
  assert.equal(errors.length, 0, errors.join("\n"));
  console.log(JSON.stringify({ fixtureSessions: 1000, firstUsefulMs, mountedRows, sessionPageOffsets, checks: ["manual order during fake stream", "live-work guard", "draft/attachment isolation", "second-client SSE", "settle/undo", "stale Undo conflict", "pending-decision guard", "full-history search", "project expansion", "keyboard menu/focus", "refresh persistence with draft/attachment", "paging", "scroll anchor", "Inbox attention"] }));
} catch (error) {
  if (page) console.error((await page.locator("body").innerText().catch(() => "")).slice(0, 5000));
  for (const child of children) console.error(child.logs.slice(-4000));
  throw error;
} finally {
  await browser?.close();
  for (const child of children) child.kill("SIGTERM");
  await Promise.all(children.map((child) => new Promise((resolve) => {
    if (child.exitCode !== null) return resolve();
    const timer = setTimeout(() => { child.kill("SIGKILL"); resolve(); }, 2000);
    child.once("exit", () => { clearTimeout(timer); resolve(); });
  })));
  await rm(home, { recursive: true, force: true });
}
