// Actual ChatPage/ChatPanel behavior with deterministic, held HTTP boundaries.
// This is a correctness suite, never a heap/performance capture.
import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repo = path.resolve(web, "../../..");
const python = process.env.PYTHON || path.join(repo, ".venv/bin/python");
const output = process.env.PANEL_OWNERSHIP_OUTPUT || await mkdtemp(path.join(os.tmpdir(), "spark-panel-ownership-"));
await mkdir(output, { recursive: true });
const home = await mkdtemp(path.join(os.tmpdir(), "spark-panel-owner-home-"));
await writeFile(path.join(home, "config.yaml"), "model:\n  default: fixture\n  provider: openai\n  base_url: http://127.0.0.1:1/v1\n");
const env = { ...process.env, SPARK_HOME: home, PYTHONPATH: path.join(repo, "src"), SPARK_WEB_FAKE_STREAMS: "1" };
const children = [];
const logs = [];
const checks = [];
const errors = [];
const consoleErrors = [];
const httpErrors = [];
const handoffTrace = [];
const scopeEffects = [];
const refreshTrace = [];
const refreshReads = [];
const wait = async (test, label) => {
  for (let i = 0; i < 150; i++) {
    if (await test()) return;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Timed out: ${label}`);
};
const freePort = () => new Promise((resolve) => {
  const socket = net.createServer();
  socket.listen(0, "127.0.0.1", () => { const port = socket.address().port; socket.close(() => resolve(port)); });
});
const start = (command, args, options) => {
  const child = spawn(command, args, { ...options, detached: true, stdio: ["ignore", "pipe", "pipe"] });
  for (const stream of [child.stdout, child.stderr]) stream.on("data", (data) => logs.push(data.toString()));
  children.push(child);
};
const seed = spawnSync(python, ["-c", `
from core.spark_state import SessionDB
db = SessionDB()
for sid, title in [("owner_a", "Owner Alpha"), ("owner_b", "Owner Beta"), ("owner_next", "Owner Continuation"), ("owner_fork", "Owner Fork")]:
    db.create_session(sid, "e2e", model="fixture")
    db.set_session_title(sid, title)
    db.append_message(sid, "user", content=title + " prompt")
    db.append_message(sid, "assistant", content=title + " response")
db.create_session("owner_exact", "e2e", model="fixture")
db.set_session_title("owner_exact", "Owner Exact")
db.append_message("owner_exact", "user", content="Owner Exact prompt")
# Exceeds COMPLETED_TEXT_WINDOW_CHARS (128 KiB), exercising the exact loader.
db.append_message("owner_exact", "assistant", content="EXACT_BEGIN " + "exact content " * 12000 + " EXACT_END")
db.close()
`], { env, cwd: repo, encoding: "utf8" });
assert.equal(seed.status, 0, seed.stderr);
const apiPort = await freePort(), webPort = await freePort();
const api = `http://127.0.0.1:${apiPort}`, base = `http://127.0.0.1:${webPort}`;
start(python, ["-c", `from spark_cli.web_server import start_server; start_server('127.0.0.1', ${apiPort}, False)`], { cwd: repo, env });
start(process.execPath, process.env.PANEL_OWNERSHIP_REFRESH_PROBE === "1"
  ? ["/tmp/spark-panel-ownership-422f1487/refresh-vite.mjs", web, String(webPort)]
  : process.env.PANEL_OWNERSHIP_HANDOFF_TRACE === "1"
  ? ["/tmp/spark-panel-ownership-422f1487/handoff-vite.mjs", web, String(webPort)]
  : ["node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", String(webPort)], { cwd: web, env: { ...env, SPARK_API_TARGET: api } });
let browser;
let failure;
try {
  await wait(async () => { try { return (await fetch(`${api}/api/status`)).ok; } catch { return false; } }, "backend");
  await wait(async () => { try { return (await fetch(base)).ok; } catch { return false; } }, "frontend");
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.addInitScript(() => Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: async (text) => { window.__ownerClipboard = text; } } }));
  if (process.env.PANEL_OWNERSHIP_BUFFER_PROBE === "1") await page.addInitScript(() => {
    const nativeRAF = window.requestAnimationFrame.bind(window);
    const nativeCancel = window.cancelAnimationFrame.bind(window);
    const held = new Map();
    let serial = -1;
    window.requestAnimationFrame = (callback) => {
      if (!window.__ownerHoldRAF) return nativeRAF(callback);
      const id = serial--;
      held.set(id, callback);
      return id;
    };
    window.cancelAnimationFrame = (id) => { if (id < 0) held.delete(id); else nativeCancel(id); };
    window.__ownerHasBufferedFlush = () => [...held.values()].some((callback) => /flush\(["']manual/.test(String(callback)));
    window.__ownerReleaseRAF = () => {
      window.__ownerHoldRAF = false;
      for (const callback of held.values()) nativeRAF(callback);
      held.clear();
    };
    const NativeSource = window.EventSource;
    window.EventSource = class extends NativeSource {
      constructor(...args) {
        super(...args);
        this.addEventListener("message", (event) => {
          if (event.data.includes("BUFFERED_OWNER_TOKEN")) window.__ownerSawBufferedToken = true;
        });
      }
    };
  });
  page.on("pageerror", (error) => errors.push(String(error)));
  page.on("response", (response) => { if (response.status() >= 400) httpErrors.push({ path: new URL(response.url()).pathname, method: response.request().method(), status: response.status() }); });
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
  page.on("console", (message) => { if (message.text().startsWith("OWNER_TRACE ") && handoffTrace.length < 400) handoffTrace.push(JSON.parse(message.text().slice("OWNER_TRACE ".length))); });
  page.on("console", (message) => { if (message.text().startsWith("OWNER_REFRESH_TRACE ")) refreshTrace.push(JSON.parse(message.text().slice("OWNER_REFRESH_TRACE ".length))); });
  const pending = [];
  let uploads = [];
  let interrupts = 0;
  await page.route("**/api/conversations/*/messages", (route) => new Promise((resolve) => pending.push({ route, resolve })));
  await page.route("**/api/workspace/files/upload", (route) => new Promise((resolve) => uploads.push({ route, resolve })));
  await page.route("**/api/conversations/*/interrupt", async (route) => { interrupts++; await route.fulfill({ json: { ok: true } }); });
  const settle = async (queue, index, json, status = 200) => {
    await wait(() => queue.length > index, `request ${index}`);
    await queue[index].route.fulfill({ status, json });
    queue[index].resolve();
  };
  const panel = page.getByTestId("chat-panel");
  const input = () => panel.locator("textarea").last();
  const owner = () => panel.getAttribute("data-panel-owner");
  const open = async (id, title) => {
    await page.getByRole("button", { name: new RegExp(title) }).first().click();
    await page.waitForFunction((sid) => document.querySelector('[data-testid="chat-panel"]')?.getAttribute("data-session-id") === sid, id);
    await panel.locator("[data-row-id]").first().waitFor();
    await wait(() => input().isEnabled(), "draft identity ready");
  };
  const draft = (id) => page.evaluate((sid) => {
    const key = Object.keys(localStorage).find((key) => key.startsWith("spark.draft.v1:") && JSON.parse(key.slice("spark.draft.v1:".length))[3] === sid);
    return key ? JSON.parse(localStorage.getItem(key)) : null;
  }, id);
  const send = async (text, index) => {
    await input().fill(text);
    await panel.getByTitle("Send (Enter)", { exact: true }).click();
    await wait(() => pending.length > index, "held send");
  };
  await page.goto(base);
  await open("owner_a", "Owner Alpha");
  const firstA = await owner();
  await send("accepted after switch", 0);
  await open("owner_b", "Owner Beta");
  const b = await owner();
  assert.notEqual(b, firstA);
  await input().fill("Beta unsent");
  await settle(pending, 0, { ok: true, session_id: "owner_next" });
  await wait(async () => (await draft("owner_a"))?.text === "", "origin draft acknowledged");
  assert.equal(await panel.getAttribute("data-session-id"), "owner_b");
  assert.equal(await input().inputValue(), "Beta unsent");
  checks.push("late accepted send acknowledges original draft without selecting/adopting replacement");

  await open("owner_a", "Owner Alpha");
  assert.notEqual(await owner(), firstA);
  await send("rejected after switch", 1);
  await open("owner_b", "Owner Beta");
  await settle(pending, 1, { detail: "fixture rejected" }, 400);
  await open("owner_a", "Owner Alpha");
  assert.equal(await input().inputValue(), "rejected after switch");
  checks.push("late rejection preserves original draft and replacement view");

  await send("before editing", 2);
  await input().fill("edited after send");
  await open("owner_b", "Owner Beta");
  await settle(pending, 2, { ok: true, session_id: "owner_a" });
  await open("owner_a", "Owner Alpha");
  assert.equal(await input().inputValue(), "edited after send");
  checks.push("accepted old revision cannot clear edits after send");

  await panel.locator('input[type="file"]').setInputFiles({ name: "origin.txt", mimeType: "text/plain", buffer: Buffer.from("origin upload") });
  await wait(() => uploads.length === 1, "held upload");
  await open("owner_b", "Owner Beta");
  await settle(uploads, 0, { ok: true, saved: [{ filename: "origin.txt", path: "files/origin.txt" }] });
  await wait(async () => (await draft("owner_a"))?.contextItems?.[0]?.attachment_status === "ready", "origin upload settled");
  assert.equal((await draft("owner_b"))?.contextItems.length ?? 0, 0);
  await open("owner_a", "Owner Alpha");
  await panel.getByText("origin.txt", { exact: true }).first().waitFor();
  checks.push("upload completes in initiating draft after navigation");

  // Same panel must survive both the optimistic render and explicit ID adoption.
  const continuing = await owner();
  const node = await panel.elementHandle();
  await send("same owner continuation", 3);
  assert.equal(await owner(), continuing);
  if (process.env.PANEL_OWNERSHIP_BUFFER_PROBE === "1") {
    await page.route("**/api/conversations/owner_next/turn-status", (route) => route.fulfill({ json: {
      session_id: "owner_next", resolved_session_id: "owner_next", latest_session_id: "owner_next", active_turn_session_id: "owner_a",
      turn_active: true, state: "streaming", phase: "streaming", status: "Synthetic continuation", interrupt_requested: false,
    } }));
    await page.evaluate(() => { window.__ownerHoldRAF = true; });
    const response = await fetch(`${api}/api/dev/fake-streams`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({
      session_id: "owner_a", title: "Owner Alpha", message: "same owner continuation", reuse_existing: true,
      events: [{ type: "token", text: "BUFFERED_OWNER_TOKEN " }, { type: "token", text: "BUFFERED_OWNER_FINAL", delay_ms: 1500 }],
    }) });
    assert.ok(response.ok, await response.text());
    await page.waitForFunction(() => window.__ownerSawBufferedToken && window.__ownerHasBufferedFlush(), undefined, { polling: 20 });
    assert.equal(await panel.getByText("BUFFERED_OWNER_TOKEN", { exact: false }).count(), 0, "token must still be buffered before adoption");
  }
  await settle(pending, 3, { ok: true, session_id: "owner_next" });
  await page.waitForFunction(() => document.querySelector('[data-testid="chat-panel"]')?.getAttribute("data-session-id") === "owner_next", undefined, { polling: 20 });
  assert.equal(await owner(), continuing);
  assert.equal(await node.evaluate((element) => element.isConnected), true);
  if (process.env.PANEL_OWNERSHIP_BUFFER_PROBE !== "1") await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(resolve)))));
  assert.equal(await panel.getAttribute("data-session-id"), "owner_next", "continuation must stay settled across frames");
  await node.dispose();
  checks.push("acknowledged continuation keeps the same mounted panel");
  if (process.env.PANEL_OWNERSHIP_BUFFER_PROBE === "1") {
    await page.evaluate(() => window.__ownerReleaseRAF());
    await panel.getByText("BUFFERED_OWNER_TOKEN", { exact: false }).first().waitFor();
    assert.equal(await owner(), continuing);
    assert.equal((await panel.innerText()).match(/BUFFERED_OWNER_TOKEN/g)?.length, 1);
    checks.push("actual buffered token survives acknowledged ID adoption without remount or duplication");
    await page.unroute("**/api/conversations/owner_next/turn-status");
  }

  await open("owner_a", "Owner Alpha");
  const beforeFork = await owner();
  let releaseFork;
  await page.route("**/api/conversations/owner_a/fork", (route) => new Promise((resolve) => { releaseFork = async () => { await route.fulfill({ json: { ok: true, session_id: "owner_fork" } }); resolve(); }; }));
  const row = panel.locator("[data-row-id]").filter({ hasText: "Owner Alpha prompt" }).first();
  await row.hover();
  await row.getByTitle("Fork from here").click();
  await wait(() => Boolean(releaseFork), "held fork");
  await releaseFork();
  await page.waitForFunction(() => document.querySelector('[data-testid="chat-panel"]')?.getAttribute("data-session-id") === "owner_fork");
  assert.notEqual(await owner(), beforeFork);
  checks.push("fork creates a fresh panel owner");

  await open("owner_a", "Owner Alpha");
  releaseFork = null;
  await panel.locator("[data-row-id]").filter({ hasText: "Owner Alpha prompt" }).first().getByTitle("Fork from here").click();
  await wait(() => Boolean(releaseFork), "second held fork");
  await open("owner_b", "Owner Beta");
  const replacement = await owner();
  await releaseFork();
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  assert.equal(await panel.getAttribute("data-session-id"), "owner_b");
  assert.equal(await owner(), replacement);
  checks.push("late fork cannot select or adopt into replacement");

  const exactGates = [];
  await page.route("**/api/sessions/owner_exact/messages?**", (route) => {
    if (new URL(route.request().url()).searchParams.has("limit")) return route.continue();
    return new Promise((resolve) => exactGates.push({ route, resolve }));
  });
  const releaseExact = async (index) => {
    await wait(() => exactGates.length > index, "held exact origin request");
    const response = await exactGates[index].route.fetch();
    await exactGates[index].route.fulfill({ response });
    exactGates[index].resolve();
  };
  await open("owner_exact", "Owner Exact");
  await panel.getByTitle("Copy complete response").last().click();
  await wait(() => exactGates.length === 1, "exact copy request");
  await open("owner_b", "Owner Beta");
  await releaseExact(0);
  await page.waitForFunction(() => window.__ownerClipboard?.startsWith("EXACT_BEGIN ") && window.__ownerClipboard.endsWith(" EXACT_END") && window.__ownerClipboard.length > 150000);
  assert.equal(await panel.getAttribute("data-session-id"), "owner_b");
  checks.push("retired exact copy loads and copies complete origin content");

  await open("owner_exact", "Owner Exact");
  await panel.getByRole("button", { name: "Promote to brief", exact: true }).last().click();
  await wait(() => exactGates.length === 2, "exact promote request");
  await open("owner_b", "Owner Beta");
  const promoted = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/sessions/owner_exact/brief" && response.request().method() === "PUT");
  await releaseExact(1);
  const brief = await (await promoted).json();
  assert.ok(brief.text.startsWith("EXACT_BEGIN ") && brief.text.endsWith(" EXACT_END") && brief.text.length > 150000);
  assert.equal(await panel.getAttribute("data-session-id"), "owner_b");
  checks.push("retired promote completes in origin brief using exact origin loader");
  if (process.env.PANEL_OWNERSHIP_EXTENDED === "1") {
    let creation;
    await page.route("**/api/conversations", (route) => new Promise((resolve) => { creation = { route, resolve }; }));
    await page.getByRole("button", { name: "New chat", exact: true }).click();
    const heroInput = page.getByRole("textbox", { name: "Message composer", exact: true });
    await heroInput.fill("Hero null-draft handoff");
    await page.getByTitle("Send (Enter)", { exact: true }).click();
    await wait(() => Boolean(creation), "held hero creation");
    const response = await fetch(`${api}/api/dev/fake-streams`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({
      session_id: "owner_created", title: "Owner Created", message: "Hero null-draft handoff", events: [{ type: "token", text: "Hero creation final.", delay_ms: 500 }],
    }) });
    assert.ok(response.ok);
    await creation.route.fulfill({ json: { ok: true, session_id: "owner_created" } });
    creation.resolve();
    await page.waitForFunction(() => document.querySelector('[data-testid="chat-panel"]')?.getAttribute("data-session-id") === "owner_created");
    await wait(async () => (await draft(null))?.text === "", "acknowledged null draft");
    await wait(() => input().isEnabled(), "created draft identity");
    assert.equal(await input().inputValue(), "");
    assert.equal(pending.length, 4, "hero initial message must not post a second time");
    checks.push("hero acknowledges null draft and hands initial message to created panel without migration or repost");

    const forks = [];
    await page.route("**/api/conversations/owner_b/fork", (route) => new Promise((resolve) => forks.push({ route, resolve })));
    await open("owner_b", "Owner Beta");
    const fork = panel.locator("[data-row-id]").filter({ hasText: "Owner Beta prompt" }).first().getByTitle("Fork from here");
    await fork.click();
    await fork.click();
    await wait(() => forks.length === 2, "two superseding forks");
    await settle(forks, 0, { ok: true, session_id: "owner_next" });
    await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    assert.equal(await panel.getAttribute("data-session-id"), "owner_b", "older response must be fenced while its owner is still current");
    await settle(forks, 1, { ok: true, session_id: "owner_fork" });
    await page.waitForFunction(() => document.querySelector('[data-testid="chat-panel"]')?.getAttribute("data-session-id") === "owner_fork");
    checks.push("newer same-owner request supersedes an older fork before either response selects");
  }
  if (process.env.PANEL_OWNERSHIP_SCOPE_PROBE === "1") {
    const scopeMode = process.env.PANEL_OWNERSHIP_SCOPE_MODE || "change";
    const scopeBoundary = process.env.PANEL_OWNERSHIP_SCOPE_BOUNDARY || "exact";
    const scopeAction = process.env.PANEL_OWNERSHIP_SCOPE_ACTION || "promote";
    const originalScope = (await (await fetch(`${api}/api/sidebar/threads`)).json()).preference_scope;
    assert.equal(typeof originalScope, "string");
    await open("owner_exact", "Owner Exact");
    if (scopeAction === "copy") {
      await page.evaluate(() => { window.__ownerClipboard = "scope-copy-sentinel"; });
      await panel.getByTitle("Copy complete response").last().click({ force: true });
    } else await panel.getByRole("button", { name: "Promote to brief", exact: true }).last().click({ force: true });
    await wait(() => exactGates.length === 3, "exact promote held across backend/profile switch");
    // Keep current-view brief reads on another session, so every subsequent
    // owner_exact brief request is unambiguously the retired origin action.
    await open("owner_b", "Owner Beta");
    // A routed loopback URL represents another backend/profile; no network
    // access outside this provider-free fixture is possible.
    await page.route("**/scope-b/api/**", async (route) => {
      const request = route.request();
      if (request.url().includes("/api/events?")) return route.fulfill({ contentType: "text/event-stream", body: ": fixture\n\n" });
      if (request.url().includes("/brief")) scopeEffects.push({ url: request.url(), method: request.method(), body: request.postData() });
      try {
        const response = await route.fetch({ url: request.url().replace("/scope-b/api/", "/api/") });
        await route.fulfill({ response });
      } catch { /* Browser disposal cancels pending fixture reads. */ }
    });
    let scopeSwitched = false, heldBrief;
    await page.route("**/api/sessions/owner_exact/brief", (route) => {
      if (!scopeSwitched && scopeBoundary === "brief") return new Promise((resolve) => { heldBrief = { route, resolve }; });
      if (!scopeSwitched) return route.continue();
      const request = route.request();
      scopeEffects.push({ url: request.url(), method: request.method(), body: request.postData(), transition: scopeMode });
      // Same-origin APIs also change their active profile. The routed current
      // profile response makes a stale write observable without user state.
      return route.fulfill({ json: { session_id: "owner_exact", text: "replacement-profile brief" } });
    });
    if (scopeBoundary === "brief") {
      await releaseExact(2);
      await wait(() => Boolean(heldBrief), "origin brief read before scope transition");
    }
    await page.evaluate(async ({ newBase, scopeMode, originalScope }) => {
      const connection = await import("/src/lib/apiHelpers.ts");
      const preferences = await import("/src/lib/sidebarPrefs.ts");
      if (scopeMode === "credential-aba") {
        const original = connection.getDashboardToken();
        connection.setDashboardToken("fixture-held-action-identity");
        if (original) connection.setDashboardToken(original); else connection.clearDashboardToken();
      }
      if (scopeMode !== "profile-aba" && scopeMode !== "credential-aba") connection.setRemoteConnection(newBase, "");
      if (scopeMode !== "backend-aba" && scopeMode !== "backend-change" && scopeMode !== "credential-aba") preferences.setSidebarPreferenceScope("scope-B");
      if (scopeMode === "backend-aba") connection.setLocalConnection();
      if (scopeMode === "profile-aba") preferences.setSidebarPreferenceScope(originalScope);
    }, { newBase: `${base}/scope-b`, scopeMode, originalScope });
    scopeSwitched = true;
    if (scopeBoundary === "brief") {
      await heldBrief.route.fulfill({ json: { session_id: "owner_exact", text: "origin brief" } });
      heldBrief.resolve();
    } else await releaseExact(2);
    await page.waitForTimeout(500);
    assert.deepEqual(scopeEffects, [], "origin promotion must never read/write the replacement backend/profile");
    if (scopeAction === "copy") assert.equal(await page.evaluate(() => window.__ownerClipboard), "scope-copy-sentinel", "cross-scope exact copy must retire without copying a truncated fallback");
    checks.push(`held ${scopeAction} at ${scopeBoundary} boundary stays retired across ${scopeMode}`);
  }
  if (process.env.PANEL_OWNERSHIP_REFRESH_PROBE === "1") {
    await open("owner_a", "Owner Alpha");
    const response = await fetch(`${api}/api/dev/fake-streams`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({
      session_id: "owner_a", title: "Owner Alpha", message: "Owned approval refresh", reuse_existing: true,
      events: [{ type: "approval", args: { command: "fixture_noop", description: "Owned refresh approval" } }, { type: "stall", delay_ms: 30000 }],
    }) });
    assert.ok(response.ok, await response.text());
    const tray = panel.getByTestId("pending-action-tray");
    const article = tray.locator('[data-action-kind="approval"]').first();
    await article.waitFor();
    const actionId = await article.getAttribute("data-action-id");
    assert.ok(actionId);
    const realActions = await (await fetch(`${api}/api/conversations/owner_a/pending-actions`)).json();
    assert.ok(realActions.actions.some((action) => action.action_id === actionId && action.status === "pending"));
    const approvals = [];
    await page.route("**/api/conversations/owner_a/approval", (route) => new Promise((resolve) => approvals.push({ route, resolve })));
    let refreshPhase = "positive";
    const heldSurfaceReads = [];
    await page.route(/\/api\/conversations\/owner_a\/(turn-outcomes|plan|pending-actions)$/, async (route) => {
      const endpoint = new URL(route.request().url()).pathname.split("/").at(-1);
      const entry = refreshTrace.at(-1);
      refreshReads.push({ phase: refreshPhase, endpoint, method: route.request().method(), path: new URL(route.request().url()).pathname, entry });
      if (refreshPhase === "held-reads") return new Promise((resolve) => heldSurfaceReads.push({ route, resolve, endpoint }));
      if (refreshPhase === "positive") {
        const actual = await route.fetch();
        const body = await actual.json();
        if (endpoint === "pending-actions") for (const action of body.actions) action.payload.description = "SAME_SCOPE_REFRESH";
        return route.fulfill({ response: actual, json: body });
      }
      return route.fulfill({ json: endpoint === "turn-outcomes" ? { outcomes: [] } : endpoint === "plan" ? { plan: null } : { actions: [] } });
    });
    const choose = async () => {
      if (process.env.PANEL_OWNERSHIP_REFRESH_PATH === "inline") await panel.getByRole("button", { name: "Once", exact: true }).click({ force: true });
      else await article.getByRole("button", { name: "Allow once", exact: true }).click();
    };
    await choose();
    await wait(() => approvals.length === 1, "same-scope held approval");
    assert.equal(JSON.parse(approvals[0].route.request().postData()).action_id, actionId, "actual current action ID must be submitted");
    await settle(approvals, 0, { ok: true, session_id: "owner_a", resolved: 1 });
    await tray.getByText("SAME_SCOPE_REFRESH", { exact: true }).waitFor();
    assert.ok(new Set(refreshReads.filter((entry) => entry.phase === "positive").map((entry) => entry.endpoint)).size === 3);
    checks.push("same-scope approval refresh reads all three real surfaces and publishes current pending UI");
    const originalOwner = await owner();
    await choose();
    await wait(() => approvals.length === 2, "cross-scope held approval");
    if (process.env.PANEL_OWNERSHIP_REFRESH_BOUNDARY === "reads") {
      refreshPhase = "held-reads";
      await settle(approvals, 1, { ok: true, session_id: "owner_a", resolved: 1 });
      await wait(() => heldSurfaceReads.length === 3, "all three origin surface responses held");
    }
    refreshPhase = "foreign";
    await page.route("**/scope-refresh-b/api/**", async (route) => {
      if (/\/(turn-outcomes|plan|pending-actions)$/.test(new URL(route.request().url()).pathname)) return route.fallback();
      if (route.request().url().includes("/api/events?")) return route.fulfill({ contentType: "text/event-stream", body: ": fixture\n\n" });
      try { const result = await route.fetch({ url: route.request().url().replace("/scope-refresh-b/api/", "/api/") }); await route.fulfill({ response: result }); } catch { /* fixture disposal */ }
    });
    await page.evaluate(async (newBase) => { const connection = await import("/src/lib/apiHelpers.ts"); connection.setRemoteConnection(newBase, ""); }, `${base}/scope-refresh-b`);
    if (process.env.PANEL_OWNERSHIP_REFRESH_BOUNDARY === "reads") {
      for (const held of heldSurfaceReads) {
        const actions = realActions.actions.map((action) => ({ ...action, payload: { ...action.payload, description: "FOREIGN_SURFACE_SENTINEL" } }));
        await held.route.fulfill({ json: held.endpoint === "turn-outcomes" ? { outcomes: [] } : held.endpoint === "plan" ? { plan: null } : { actions } });
        held.resolve();
      }
    } else await settle(approvals, 1, { ok: true, session_id: "owner_a", resolved: 1 });
    await page.waitForTimeout(300);
    const retiredReads = refreshReads.filter((read) => read.phase === "foreign" && String(read.entry?.owner) === originalOwner && read.entry?.scopeCurrent === false);
    const foreignPublished = await panel.getByText("FOREIGN_SURFACE_SENTINEL", { exact: true }).count();
    await writeFile(path.join(output, "refresh-proof.json"), JSON.stringify({ path: process.env.PANEL_OWNERSHIP_REFRESH_PATH || "tray", boundary: process.env.PANEL_OWNERSHIP_REFRESH_BOUNDARY || "approval", actionId, originalOwner, refreshReads, refreshTrace, retiredReads, foreignPublished }, null, 2));
    assert.deepEqual(retiredReads, [], "retired scope approval completion must not launch surface reads through replacement transport");
    assert.equal(foreignPublished, 0, "surface responses crossing scope transition must not publish to original panel");
    checks.push("held current-action response cannot launch origin surface reads through replacement backend scope");
  }
  assert.equal(interrupts, 0, "navigation/unmount must never Stop backend work");
  if (process.env.PANEL_OWNERSHIP_MOUNTED_HANDOFF === "1") {
    const receipts = await page.evaluate(async () => {
      const { checkPendingHandoff } = await import("/e2e/panel-ownership-handoff.tsx");
      const host = document.createElement("div");
      document.body.append(host);
      try { return [await checkPendingHandoff(host, false), await checkPendingHandoff(host, true)]; }
      finally { host.remove(); }
    });
    await writeFile(path.join(output, "mounted-handoff.json"), JSON.stringify(receipts, null, 2));
    checks.push("mounted pending-effect handoff: unbuffered/buffered, one measure, no rollback, compression and fresh status");
  }
  assert.equal(consoleErrors.some((message) => /Maximum update depth|LazyLoadErrorBoundary|error occurred in the <ChatPanel>/.test(message)), false, "React boundary/maximum-depth errors must fail");
  assert.deepEqual(errors, []);
  await page.screenshot({ path: path.join(output, "final.png") });
} catch (error) {
  failure = String(error.stack || error);
  await writeFile(path.join(output, "failure-result.json"), JSON.stringify({ checks, errors, consoleErrors, httpErrors, handoffTrace, scopeEffects, failure }, null, 2));
  const page = browser?.contexts()[0]?.pages()[0];
  if (page) {
    await page.screenshot({ path: path.join(output, "failure.png") }).catch(() => {});
    await writeFile(path.join(output, "failure.txt"), await page.locator("body").innerText());
  }
} finally {
  await browser?.close();
  for (const child of children.reverse()) {
    if (child.exitCode !== null) continue;
    try { process.kill(-child.pid, "SIGTERM"); } catch { /* already exited */ }
    await new Promise((resolve) => setTimeout(resolve, 300));
    try { process.kill(-child.pid, "SIGKILL"); } catch { /* already exited */ }
  }
  await writeFile(path.join(output, "process.log"), logs.join(""));
  await writeFile(path.join(output, "result.json"), JSON.stringify({ node: process.version, execPath: process.execPath, source: repo, home, checks, errors, consoleErrors, httpErrors, handoffTrace, scopeEffects, failure: failure ?? null }, null, 2));
}
if (failure) throw new Error(failure);
console.log(JSON.stringify({ output, checks }));
