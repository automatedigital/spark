import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

const fixtureWebRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const webRoot = process.env.SPARK_E2E_WEB_ROOT
  ? path.resolve(process.env.SPARK_E2E_WEB_ROOT)
  : fixtureWebRoot;
const repoRoot = path.resolve(webRoot, "../../..");
const pythonBin = process.env.PYTHON || path.join(repoRoot, ".venv", "bin", "python");
const viteBin = path.join(fixtureWebRoot, "node_modules", ".bin", "vite");
const outputDir = process.env.SPARK_E2E_OUTPUT_DIR ? path.resolve(process.env.SPARK_E2E_OUTPUT_DIR) : null;
const sessionCount = Number(process.env.SPARK_E2E_SESSION_COUNT || 1000);
if (!Number.isInteger(sessionCount) || sessionCount < 500) {
  throw new Error("SPARK_E2E_SESSION_COUNT must be an integer >= 500");
}

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close(() => resolve(port));
    });
  });
}

function startProcess(command, args, options) {
  const child = spawn(command, args, { ...options, stdio: ["ignore", "pipe", "pipe"] });
  const logs = [];
  child.stdout.on("data", (chunk) => logs.push(chunk.toString()));
  child.stderr.on("data", (chunk) => logs.push(chunk.toString()));
  return { child, logs };
}

async function stopProcess(proc) {
  if (!proc || proc.child.exitCode !== null) return;
  proc.child.kill("SIGTERM");
  await new Promise((resolve) => setTimeout(resolve, 500));
  if (proc.child.exitCode === null) proc.child.kill("SIGKILL");
}

async function waitFor(url, timeoutMs = 45_000) {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
      lastError = new Error(`${response.status} ${response.statusText}`);
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error(`Timed out waiting for ${url}: ${lastError?.message ?? "unknown error"}`);
}

async function measureSearchResult(input, value, selector) {
  return input.evaluate((element, args) => new Promise((resolve, reject) => {
    const startedAt = performance.now();
    const timeout = window.setTimeout(() => {
      observer.disconnect();
      reject(new Error(`Timed out waiting for search result ${args.selector}`));
    }, 5000);
    const observer = new MutationObserver(() => {
      if (!document.querySelector(args.selector)) return;
      if (args.value.startsWith("Scale chat") && document.querySelectorAll('[role="button"][aria-label^="Scale chat "]').length >= 50) return;
      window.clearTimeout(timeout);
      observer.disconnect();
      resolve(performance.now() - startedAt);
    });
    observer.observe(document.body, { childList: true, subtree: true });
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    setter.call(element, args.value);
    element.dispatchEvent(new Event("input", { bubbles: true }));
  }), { value, selector });
}

async function run() {
  const apiPort = await freePort();
  const webPort = await freePort();
  const sparkHome = await mkdtemp(path.join(os.tmpdir(), "spark-sidebar-scale-"));
  await writeFile(
    path.join(sparkHome, "config.yaml"),
    "model:\n  default: test-model\n  provider: ollama\n  base_url: http://127.0.0.1:1/v1\n",
  );
  for (let index = 0; index < 10; index += 1) {
    await mkdir(path.join(sparkHome, "workspace", `project-${index}`), { recursive: true });
  }

  const seed = spawnSync(pythonBin, ["-c", String.raw`
import time
from core.spark_state import SessionDB

db = SessionDB()
now = time.time()
for index in range(${sessionCount}):
    sid = f"scale-{index:03d}"
    source = f"workspace:project-{index % 10}"
    db.create_session(sid, source, model="test-model")
    db.set_session_title(sid, f"Scale chat {index:03d}")
    db._conn.execute("UPDATE sessions SET started_at = ? WHERE id = ?", (now - index, sid))
db.append_message("scale-499", "user", "ancient needle full history result")
db._conn.execute("UPDATE messages SET timestamp = ? WHERE session_id = ?", (now - 499, "scale-499"))
db._conn.commit()
db.close()
`], {
    cwd: repoRoot,
    env: { ...process.env, SPARK_HOME: sparkHome, PYTHONPATH: path.join(repoRoot, "src") },
    encoding: "utf8",
  });
  if (seed.status !== 0) throw new Error(`Fixture seed failed: ${seed.stderr}`);

  const backendStartedAt = performance.now();
  const backend = startProcess(
    pythonBin,
    [
      "-c",
      "from spark_cli.web_server import start_server; import sys; start_server('127.0.0.1', int(sys.argv[1]), False)",
      String(apiPort),
    ],
    {
      cwd: repoRoot,
      env: {
        ...process.env,
        PYTHONPATH: path.join(repoRoot, "src"),
        SPARK_HOME: sparkHome,
        SPARK_WEB_FAKE_STREAMS: "1",
      },
    },
  );
  const vite = startProcess(viteBin, [webRoot, "--host", "127.0.0.1", "--port", String(webPort)], {
    cwd: webRoot,
    env: { ...process.env, SPARK_API_TARGET: `http://127.0.0.1:${apiPort}` },
  });

  const apiBase = `http://127.0.0.1:${apiPort}`;
  const webBase = `http://127.0.0.1:${webPort}`;
  const sessionRequests = [];
  const rawRequests = [];
  const titleProbeRequests = [];
  const activeRequests = new Set();
  const networkTrace = [];
  let browser;
  let page;
  const extraProcesses = [];
  let secondHome;
  const metrics = { sessionCount, projects: 10, viewport: { width: 1440, height: 900 }, theme: "dark", mode: "dev", checks: [], correctnessFailures: [] };
  try {
    await waitFor(`${apiBase}/api/status`);
    metrics.backendReadyMs = performance.now() - backendStartedAt;
    await waitFor(webBase);
    browser = await chromium.launch({ headless: true, args: outputDir ? [`--log-net-log=${path.join(outputDir, "netlog.json")}`] : [] });
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const snapshot = async () => (await (await fetch(`${apiBase}/api/sidebar/threads`)).json());
    const scope = (await snapshot()).preference_scope;
    await context.addInitScript(({ webBase, scope }) => {
      localStorage.setItem("spark-webui-theme", "codex");
      window.__sparkGateEvents = [];
      const NativeEventSource = window.EventSource;
      window.EventSource = class extends NativeEventSource {
        constructor(url, options) {
          super(url, options);
          this.addEventListener("message", (event) => {
            try {
              const value = JSON.parse(event.data);
              window.__sparkGateEvents.push({ at: performance.now(), url: String(url), ...value });
              if (window.__sparkGateEvents.length > 200) window.__sparkGateEvents.shift();
            } catch { /* raw invalid frame is not app state */ }
          });
        }
      };
      // Old unscoped data must never silently import into the active profile.
      localStorage.setItem("spark-pinned-sessions", '["scale-049","scale-048","missing-legacy-session",17,null]');
      localStorage.setItem(`spark-chat-expanded:v1:${encodeURIComponent(webBase)}:${scope}`, JSON.stringify(Array.from({ length: 10 }, (_, index) => `project-${index}`)));
    }, { webBase, scope });
    page = await context.newPage();
    const cdp = await context.newCDPSession(page);
    await cdp.send("Network.enable");
    const networkIds = new Set();
    cdp.on("Network.requestWillBeSent", (event) => {
      if (!event.request.url.includes("/api/")) return;
      networkIds.add(event.requestId);
      networkTrace.push({ phase: "request", requestId: event.requestId, url: event.request.url, method: event.request.method, timestamp: event.timestamp, wallTime: event.wallTime });
    });
    cdp.on("Network.responseReceived", (event) => {
      if (!networkIds.has(event.requestId)) return;
      const { url, status, protocol, connectionId, connectionReused, timing } = event.response;
      networkTrace.push({ phase: "response", requestId: event.requestId, timestamp: event.timestamp, url, status, protocol, connectionId, connectionReused, timing });
    });
    cdp.on("Network.loadingFailed", (event) => {
      if (networkIds.has(event.requestId)) networkTrace.push({ phase: "failed", ...event });
    });
    cdp.on("Network.loadingFinished", (event) => {
      if (networkIds.has(event.requestId)) networkTrace.push({ phase: "finished", ...event });
    });
    const initialSnapshots = [];
    const waitRequest = async (predicate) => {
      const deadline = Date.now() + 15_000;
      while (!sessionRequests.some(predicate) && Date.now() < deadline) await page.waitForTimeout(25);
      assert.ok(sessionRequests.some(predicate), `Missing session page; requests=${JSON.stringify(sessionRequests)}`);
    };
    const searchRequests = [];
    page.on("response", async (response) => {
      const url = new URL(response.url());
      if (url.pathname === "/api/web-state/snapshot" && response.ok()) {
        const body = await response.json();
        initialSnapshots.push({ sessionLimit: Number(url.searchParams.get("session_limit")), sessionCount: body.shells?.length, total: body.total, limits: body.limits });
      }
    });
    page.on("request", (request) => {
      activeRequests.add(request);
      rawRequests.push(request.url());
      const url = new URL(request.url());
      if (url.pathname === "/api/sessions") {
        sessionRequests.push({
          limit: Number(url.searchParams.get("limit")),
          offset: Number(url.searchParams.get("offset")),
        });
      }
      if (url.pathname === "/api/sessions/search") searchRequests.push(url.searchParams.get("q"));
    });
    page.on("requestfinished", (request) => {
      activeRequests.delete(request);
      const pathname = new URL(request.url()).pathname;
      if (pathname.endsWith("/title") || pathname === "/api/web-state/snapshot") {
        titleProbeRequests.push({ pathname, method: request.method(), ...request.timing() });
      }
    });
    page.on("requestfailed", (request) => activeRequests.delete(request));

    page.setDefaultTimeout(15_000);
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const row = (id) => page.getByRole("button", { name: new RegExp(`^Scale chat ${id},`) }).first();
    const startupAt = performance.now();
    await page.goto(webBase, { waitUntil: "domcontentloaded" });
    await row("000").waitFor();
    metrics.firstUsefulMs = performance.now() - startupAt;
    const bootstrapDeadline = Date.now() + 5000;
    while (!initialSnapshots.length && Date.now() < bootstrapDeadline) await page.waitForTimeout(25);
    metrics.initialSnapshots = initialSnapshots;
    metrics.startupRequests = [...sessionRequests];
    assert.equal(initialSnapshots[0]?.sessionLimit, 50, "Initial snapshot must request bounded first page");
    assert.equal(initialSnapshots[0]?.sessionCount, 50, "Initial snapshot contains exactly 50 shells");
    assert.equal((await snapshot()).entries["scale-049"].pinned, false, "Legacy pins require explicit import");
    const select = async (id) => {
      await row(id).click();
      await page.waitForFunction((id) => document.querySelector('[data-testid="chat-selection"]')?.getAttribute("data-session-id") === `scale-${id}`, id);
    };
    await row("000").evaluate((element) => {
      const expectedSession = "scale-000";
      window.__sparkSelectionObservation = {
        expectedSession,
        initialSession: document.querySelector('[data-testid="chat-selection"]')?.getAttribute("data-session-id") ?? null,
        committedAt: null,
      };
      const observer = new MutationObserver(() => {
        if (document.querySelector('[data-testid="chat-selection"]')?.getAttribute("data-session-id") !== expectedSession) return;
        window.__sparkSelectionObservation.committedAt = performance.now();
        observer.disconnect();
      });
      observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["data-session-id"] });
      window.__sparkSelectionStartedAt = performance.now();
      element.click();
    });
    await page.waitForFunction(() => document.querySelector('[data-testid="chat-selection"]')?.getAttribute("data-session-id") === "scale-000");
    assert.equal(await row("000").getAttribute("aria-current"), "page");
    // Retain the old endpoint, including automation polling/protocol trips.
    // The budget below now uses the same DOM-identity boundary on browser time.
    metrics.selectionLegacyObservedMs = await page.evaluate(() => performance.now() - window.__sparkSelectionStartedAt);
    metrics.selectionObservation = await page.evaluate(() => ({
      ...window.__sparkSelectionObservation,
      startedAt: window.__sparkSelectionStartedAt,
      definition: "inline-click-to-session-dom-commit",
    }));
    const selection = metrics.selectionObservation;
    assert.notEqual(selection.initialSession, selection.expectedSession, "Selection measurement must observe a real session transition");
    assert.ok(Number.isFinite(selection.committedAt) && selection.committedAt >= selection.startedAt,
      "Selection measurement did not observe the expected session DOM commit");
    metrics.selectionMs = selection.committedAt - selection.startedAt;
    metrics.selectionObservation.legacyObservationTailMs = metrics.selectionLegacyObservedMs - metrics.selectionMs;
    await page.waitForFunction(() => Boolean(document.querySelector('[data-testid="chat-panel"]')));
    metrics.panelReadyMs = await page.evaluate(() => performance.now() - window.__sparkSelectionStartedAt);
    await select("000");
    let search = page.getByPlaceholder("Search", { exact: true });
    metrics.localSearchMs = await measureSearchResult(search, "Scale chat 049", '[role="button"][aria-label^="Scale chat 049,"]');
    await search.fill("");
    await row("000").waitFor();
    metrics.fullHistorySearchMs = await measureSearchResult(search, "ancient needle", '[role="button"][aria-label^="Scale chat 499,"]');
    await select("499");
    await page.getByTestId("chat-panel").getByText("ancient needle full history result", { exact: true }).waitFor();
    await search.fill("");
    await row("000").waitFor();
    metrics.checks.push("Inbox semantic selection/local/full-history search", "legacy pins do not cross profile boundary");
    await select("000");
    await page.waitForTimeout(250);
    metrics.titleProbePendingRequests = [...activeRequests].map((request) => request.url());
    try {
      metrics.sidebarUpdateMs = await page.evaluate(() => new Promise((resolve, reject) => {
        const started = performance.now();
        window.__sparkTitleProbe = { started, startedWallTime: Date.now() };
        const timeout = setTimeout(() => { observer.disconnect(); reject(new Error("Title SSE update missing")); }, 5000);
        const observer = new MutationObserver(() => {
          if (!document.querySelector('[role="button"][aria-label^="Scale measured update,"]')) return;
          window.__sparkTitleProbe.rendered = performance.now();
          clearTimeout(timeout); observer.disconnect(); resolve(performance.now() - started);
        });
        observer.observe(document.body, { childList: true, subtree: true, attributes: true, characterData: true });
        fetch("/api/sessions/scale-000/title", { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ title: "Scale measured update" }) }).then((response) => { window.__sparkTitleProbe.response = performance.now(); if (!response.ok) reject(new Error(`Title PATCH ${response.status}`)); }, reject);
      }));

    } catch (error) {
      metrics.correctnessFailures.push(`Title PATCH was not rendered within 5000ms: ${error.message}`);
    }
    const restoreTitle = await fetch(`${apiBase}/api/sessions/scale-000/title`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ title: "Scale chat 000" }) });
    assert.equal(restoreTitle.status, 200);
    await row("000").waitFor();
    metrics.titleProbe = await page.evaluate(() => ({
      ...window.__sparkTitleProbe,
      events: window.__sparkGateEvents.filter((event) => event.topic === "sessions.changed" && event.data?.session?.title === "Scale measured update"),
    }));
    // Inbox uses an explicit older-page control. Threads must also exercise its
    // actual scroll-triggered paging and bounded mounted-row contract.
    await page.getByRole("button", { name: "Threads", exact: true }).click();
    search = page.getByPlaceholder("Search projects and chats…");
    await row("000").waitFor();
    metrics.mountedSessionRows = await page.locator("[data-sidebar-session-row]").count();
    assert.ok(metrics.mountedSessionRows > 0 && metrics.mountedSessionRows <= 60);
    const scroll = page.getByTestId("session-sidebar-scroll");
    await scroll.evaluate((el) => { el.scrollTop = el.scrollHeight; });
    await waitRequest((request) => request.offset === 50);
    await page.waitForTimeout(250);
    assert.ok(await page.locator("[data-sidebar-session-row]").count() <= 60);
    assert.equal(sessionRequests.filter((request) => request.offset === 50).length, 1, "Single-flight second page");
    metrics.secondPageRequests = sessionRequests.filter((request) => request.offset === 50).length;
    metrics.checks.push(`${sessionCount} sessions / 10 projects; real offset-50 paging and bounded virtual rows`);

    await scroll.evaluate((el) => { el.scrollTop = 600; });
    await page.waitForTimeout(150);
    const anchor = () => scroll.evaluate((element) => {
      const top = element.getBoundingClientRect().top;
      const first = [...element.querySelectorAll("[data-sidebar-row]")].find((el) => el.getBoundingClientRect().bottom > top + 1);
      return first ? `${first.dataset.sidebarRow}:${first.dataset.sidebarSessionRow ?? ""}` : null;
    });
    const before = await anchor();
    assert.ok(before, "Scroll anchor exists");
    const liveResponse = await fetch(`${apiBase}/api/dev/fake-streams`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ session_id: "scale-live", title: "Scale live insertion", source: "workspace:project-0", message: "live sidebar insertion", events: [{ type: "token", text: "live response", delay_ms: 150 }] }),
    });
    assert.ok(liveResponse.ok);
    await page.waitForTimeout(700);
    const after = await anchor();
    metrics.anchor = { before, after };
    assert.equal(after, before, "SSE insertion preserves scroll anchor");
    await scroll.evaluate((el) => { el.scrollTop = 0; });
    const liveRow = page.locator('[data-sidebar-session-row="scale-live"]');
    await liveRow.waitFor();
    await liveRow.getByTitle("New response", { exact: true }).waitFor();
    metrics.checks.push("SSE insertion scroll anchor and nonselected unread marker");

    const action = async (title, name) => {
      await page.getByTitle(`Actions for ${title}`, { exact: true }).first().click();
      await page.getByRole("dialog", { name: `Organize ${title}`, exact: true }).getByRole("button", { name, exact: true }).click();
    };
    await action("Scale live insertion", "Delete thread");
    await liveRow.waitFor({ state: "detached" });
    // Use server acknowledgement; localStorage is no longer metadata authority.
    await row("000").click({ modifiers: ["Shift"] });
    await page.waitForFunction(async () => (await (await fetch("/api/sidebar/threads")).json()).entries["scale-000"].pinned);
    assert.equal(await page.locator('[data-sidebar-session-row="scale-000"]').count(), 2, "Pinned and project placements");
    const projectZero = page.getByRole("button", { name: "project-0", exact: true });
    await projectZero.click();
    await page.locator('[data-sidebar-session-row="scale-010"]').waitFor({ state: "detached" });
    await projectZero.click();
    await page.locator('[data-sidebar-session-row="scale-010"]').waitFor();
    await page.locator('[data-sidebar-session-row="scale-000"] [role="button"]').last().dragTo(page.getByRole("button", { name: "project-1", exact: true }));
    await page.waitForFunction(async () => (await (await fetch("/api/sessions/scale-000")).json()).source === "workspace:project-1");
    metrics.checks.push("server pin; duplicate placements; collapse/expand; drag to project");
    await page.waitForTimeout(250);
    const focused = row("000");
    await focused.focus();
    const focusIndex = await focused.evaluate((el) => el.closest("[data-index]")?.getAttribute("data-index"));
    await page.keyboard.press("ArrowDown");
    await page.waitForFunction((previous) => {
      const el = document.activeElement;
      return el?.getAttribute("role") === "button" && el.closest("[data-index]")?.getAttribute("data-index") !== previous;
    }, focusIndex);
    metrics.checks.push("virtualized ArrowDown moves keyboard focus to the next row");

    // Menu keyboard focus and a stale second-client edit must remain fenced.
    await page.getByTitle("Actions for Scale chat 000", { exact: true }).first().click();
    await page.keyboard.press("Escape");
    assert.ok(await page.getByTitle("Actions for Scale chat 000", { exact: true }).first().evaluate((el) => document.activeElement === el));
    const entry = (await snapshot()).entries["scale-000"];
    const patch = (body) => fetch(`${apiBase}/api/sidebar/threads/scale-000`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
    const updateStarted = performance.now();
    assert.equal((await patch({ expected_revision: entry.revision, pinned: false })).status, 200);
    await page.waitForFunction(() => [...document.querySelectorAll('[role="button"][aria-label^="Scale chat 000,"]')].every((el) => !el.getAttribute("aria-label").includes(", pinned")));
    metrics.metadataUpdateMs = performance.now() - updateStarted;
    assert.equal((await patch({ expected_revision: entry.revision, settled: true })).status, 409);
    assert.equal((await snapshot()).entries["scale-000"].settled, false);
    metrics.checks.push("menu Escape returns focus; stale CAS rejected and newer SSE metadata retained");

    await page.getByRole("button", { name: "Inbox", exact: true }).click();
    const previousMaxOffset = Math.max(...sessionRequests.map((request) => request.offset));
    await page.getByRole("button", { name: "Load older chats", exact: true }).click();
    await waitRequest((request) => request.offset === previousMaxOffset + 50);
    metrics.checks.push("Inbox explicit next-page paging");

    // Explicit migration must import only existing, never-edited metadata in
    // this profile. Keep this functional flow after the timing observations.
    const defaults = { pinned: false, settled: false, position: null, revision: 0 };
    assert.deepEqual((await snapshot()).entries["scale-049"], defaults);
    assert.equal((await (await fetch(`${apiBase}/api/sessions/scale-049`)).json()).message_count, 0);
    const editedResponse = await fetch(`${apiBase}/api/sidebar/threads/scale-048`, {
      method: "PATCH", headers: { "content-type": "application/json" },
      body: JSON.stringify({ expected_revision: 0, pinned: false, position: 48 }),
    });
    assert.equal(editedResponse.status, 200);
    await page.reload({ waitUntil: "domcontentloaded" });
    const importPins = page.getByRole("button", { name: "Import this browser’s old pins into this profile", exact: true });
    await importPins.waitFor();
    const beforeImport = await snapshot();
    const importRequests = [];
    const recordImport = (request) => {
      if (request.method() === "PATCH" && new URL(request.url()).pathname.startsWith("/api/sidebar/threads/")) {
        importRequests.push({ path: new URL(request.url()).pathname, body: request.postDataJSON() });
      }
    };
    page.on("request", recordImport);
    await importPins.click();
    await importPins.waitFor({ state: "detached" });
    page.off("request", recordImport);
    assert.deepEqual(importRequests, [{ path: "/api/sidebar/threads/scale-049", body: { expected_revision: 0, pinned: true } }]);
    const imported = await snapshot();
    assert.equal(imported.entries["scale-049"].pinned, true);
    assert.equal(imported.entries["scale-049"].revision, 1);
    const unchangedBefore = Object.fromEntries(Object.entries(beforeImport.entries).filter(([id]) => id !== "scale-049"));
    const unchangedAfter = Object.fromEntries(Object.entries(imported.entries).filter(([id]) => id !== "scale-049"));
    assert.deepEqual(unchangedAfter, unchangedBefore, "Import preserves edited and unrelated metadata; missing/nonstring IDs create no entries");
    const importMarker = `spark-sidebar-pin-import:v1:${encodeURIComponent(webBase)}:${scope}`;
    assert.equal(await page.evaluate((key) => localStorage.getItem(key), importMarker), "v1");
    await page.reload({ waitUntil: "domcontentloaded" });
    const importedRow = page.getByRole("region", { name: "Pinned threads" }).getByRole("button", { name: /^Scale chat 049/ }).first();
    await importedRow.waitFor();
    assert.equal(await importPins.count(), 0);
    assert.deepEqual((await snapshot()).entries, imported.entries);
    await importedRow.click();
    await page.getByTestId("chat-panel").getByText("Start a conversation", { exact: true }).waitFor();
    assert.equal(await page.getByTestId("chat-panel").getAttribute("data-session-id"), "scale-049");
    metrics.legacyPinImport = { eligible: "scale-049", edited: "scale-048", requests: importRequests, marker: importMarker, persistedAfterRefresh: true };
    metrics.checks.push("explicit legacy pin import pins only revision-zero eligible ID; edited/missing/nonstring IDs skipped; scoped marker and refresh persistence", "empty session has default sidebar metadata and zero messages");

    await page.getByRole("button", { name: "Threads", exact: true }).click();
    const emptySearch = page.getByPlaceholder("Search projects and chats…");
    const emptySearchResponse = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return url.pathname === "/api/sessions/search" && url.searchParams.get("q") === "p09-no-matching-thread" && response.status() === 200;
    });
    await emptySearch.fill("p09-no-matching-thread");
    await emptySearchResponse;
    await page.getByText('No results for "p09-no-matching-thread"', { exact: true }).waitFor();
    await emptySearch.fill("");
    metrics.checks.push("empty thread search renders its no-results row and clears");
    // Same session identity in another real profile database must have separate
    // metadata and preference keys. No runtime profile-switching is simulated.
    secondHome = await mkdtemp(path.join(os.tmpdir(), "spark-sidebar-profile-"));
    await writeFile(path.join(secondHome, "config.yaml"), "model:\n  default: test-model\n  provider: ollama\n  base_url: http://127.0.0.1:1/v1\n");
    const otherEnv = { ...process.env, SPARK_HOME: secondHome, PYTHONPATH: path.join(repoRoot, "src"), SPARK_WEB_FAKE_STREAMS: "1" };
    const seeded = spawnSync(pythonBin, ["-c", 'from core.spark_state import SessionDB; d=SessionDB(); d.create_session("scale-000", "web", model="test-model"); d.set_session_title("scale-000", "Other profile thread"); d.close()'], { env: otherEnv, encoding: "utf8" });
    assert.equal(seeded.status, 0, seeded.stderr);
    const otherPort = await freePort();
    const otherWebPort = await freePort();
    const otherApi = `http://127.0.0.1:${otherPort}`;
    const otherWeb = `http://127.0.0.1:${otherWebPort}`;
    extraProcesses.push(startProcess(pythonBin, ["-c", `from spark_cli.web_server import start_server; start_server('127.0.0.1', ${otherPort}, False)`], { cwd: repoRoot, env: otherEnv }));
    extraProcesses.push(startProcess(viteBin, [webRoot, "--host", "127.0.0.1", "--port", String(otherWebPort), "--strictPort"], { cwd: webRoot, env: { ...otherEnv, SPARK_API_TARGET: otherApi } }));
    await waitFor(`${otherApi}/api/status`); await waitFor(otherWeb);
    const otherSnapshot = await (await fetch(`${otherApi}/api/sidebar/threads`)).json();
    assert.notEqual(otherSnapshot.preference_scope, scope);
    const latest = (await snapshot()).entries["scale-000"];
    assert.equal((await patch({ expected_revision: latest.revision, pinned: true })).status, 200);
    const otherPage = await context.newPage();
    await otherPage.goto(otherWeb, { waitUntil: "domcontentloaded" });
    await otherPage.getByRole("button", { name: /^Other profile thread,/ }).waitFor();
    const otherImportMarker = `spark-sidebar-pin-import:v1:${encodeURIComponent(otherWeb)}:${otherSnapshot.preference_scope}`;
    assert.equal(await otherPage.evaluate((key) => localStorage.getItem(key), otherImportMarker), null, "Import marker does not cross profile/backend scope");
    assert.equal((await (await fetch(`${otherApi}/api/sidebar/threads`)).json()).entries["scale-000"].pinned, false);
    assert.equal(await otherPage.getByRole("region", { name: "Pinned threads" }).count(), 0);
    assert.equal((await snapshot()).entries["scale-000"].pinned, true);
    await otherPage.close();
    metrics.checks.push("two real isolated profile databases with duplicate session ID; metadata and preference scopes differ");
    metrics.fullHistoryRequests = searchRequests;
    metrics.titleProbeRequests = titleProbeRequests;
    assert.equal(sessionRequests[0]?.limit, 50);
    assert.equal(sessionRequests[0]?.offset, 50);
    assert.deepEqual(searchRequests, ["ancient needle", "p09-no-matching-thread"]);
    assert.ok(metrics.selectionMs < 100, `Selection took ${metrics.selectionMs}ms`);
    assert.ok(metrics.localSearchMs < 100, `Local search took ${metrics.localSearchMs}ms`);
    assert.ok(metrics.fullHistorySearchMs < 600, `Full-history search took ${metrics.fullHistorySearchMs}ms`);
    assert.deepEqual(errors, []);
    assert.deepEqual(metrics.correctnessFailures, [], "Every correctness failure remains a blocking gate");
    if (outputDir) {
      await mkdir(outputDir, { recursive: true });
      await page.screenshot({ path: path.join(outputDir, "sidebar.png") });
      await writeFile(path.join(outputDir, "report.json"), JSON.stringify(metrics, null, 2));
    }
    process.stdout.write(`${JSON.stringify(metrics)}\n`);
  } catch (error) {
    if (outputDir) {
      metrics.sessionRequests = sessionRequests;
      metrics.titleProbeRequests = titleProbeRequests;
      metrics.requests = rawRequests;
      metrics.events = page ? await page.evaluate(() => window.__sparkGateEvents).catch(() => null) : null;
      metrics.backendTitle = await fetch(`${apiBase}/api/sessions/scale-000`).then((response) => response.json()).catch(() => null);
      await mkdir(outputDir, { recursive: true });
      await writeFile(path.join(outputDir, "failure.json"), JSON.stringify({ ...metrics, error: error.stack }, null, 2));
      if (page) await page.screenshot({ path: path.join(outputDir, "failure.png") }).catch(() => {});
    }
    const body = page ? await page.locator("body").innerText().catch(() => "") : "";
    throw new Error(`${error.message}\nbody:\n${body.slice(0, 4000)}\nbackend:\n${backend.logs.join("")}\nvite:\n${vite.logs.join("")}`);
  } finally {
    if (browser) await browser.close();
    if (outputDir) await writeFile(path.join(outputDir, "network-trace.json"), JSON.stringify(networkTrace, null, 2));
    for (const process of extraProcesses) await stopProcess(process);
    if (secondHome) await rm(secondHome, { recursive: true, force: true });
    await stopProcess(vite);
    await stopProcess(backend);
    await rm(sparkHome, { recursive: true, force: true });
  }
}

await run();
