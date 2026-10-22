// Component browser contract with synthetic SSE and Web Audio boundaries; no providers.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, mkdir, rm } from "node:fs/promises";
import os from "node:os";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const isolated = await mkdtemp(path.join(os.tmpdir(), "spark-f08-"));
const home = path.join(isolated, "home");
await mkdir(home);
const port = await new Promise((resolve, reject) => {
  const probe = net.createServer();
  probe.on("error", reject);
  probe.listen(0, "127.0.0.1", () => { const port = probe.address().port; probe.close(() => resolve(port)); });
});
const url = `http://127.0.0.1:${port}/e2e/fixtures/notification-sounds.html`;
const server = spawn(process.execPath, ["node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", String(port), "--strictPort"], {
  cwd: webRoot, env: { ...process.env, SPARK_API_TARGET: "http://127.0.0.1:1", HOME: home, USERPROFILE: home, SPARK_HOME: path.join(isolated, "spark") }, stdio: "pipe",
});
let logs = "";
server.stdout.on("data", b => { logs += b; });
server.stderr.on("data", b => { logs += b; });
let browser;
try {
  for (let i = 0; ; i++) {
    try { const response = await fetch(url); if (response.ok && (await response.text()).includes("Notification sounds fixture")) break; } catch { /* startup */ }
    if (i >= 100) throw new Error(`Vite startup failed: ${logs}`);
    await new Promise(r => setTimeout(r, 100));
  }
  browser = await chromium.launch({ headless: true });
  for (const desktop of [false, true]) {
    const context = await browser.newContext();
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", e => errors.push(e.message));
    await page.route("**/api/conversations/*/turn-outcome", route => route.fulfill({ json: { workspace_slug: "muted" } }));
    await page.addInitScript(({ desktop }) => {
      window.audioFixture = { plays: 0, deny: false, sources: [], now: 0, native: 0 };
      const f = window.audioFixture;
      performance.now = () => f.now;
      class FakeAudioContext {
        state = "suspended";
        currentTime = 0;
        destination = {};
        async resume() { if (f.deny) throw new Error("NotAllowedError"); this.state = "running"; }
        createOscillator() { return { frequency: { setValueAtTime() {} }, connect() {}, disconnect() {}, start() { f.plays++; }, stop() { this.onended?.(); } }; }
        createGain() { return { gain: { setValueAtTime() {}, linearRampToValueAtTime() {}, exponentialRampToValueAtTime() {} }, connect() {}, disconnect() {} }; }
      }
      window.AudioContext = FakeAudioContext;
      window.EventSource = class {
        constructor(url) { this.url = url; f.sources.push(this); }
        close() { f.sources = f.sources.filter(s => s !== this); }
      };
      if (desktop) {
        window.__TAURI_INTERNALS__ = { invoke: async () => { f.native++; } };
        document.hasFocus = () => false;
      }
    }, { desktop });
    await page.goto(url);
    await page.getByRole("button", { name: "Notifications", exact: true }).click();
    assert.equal(await page.getByRole("checkbox", { name: "Completion sounds", exact: true }).isChecked(), false);
    assert.equal(await page.getByRole("checkbox", { name: "Input request sounds" }).isChecked(), false);
    const playCount = () => page.evaluate(() => window.audioFixture.plays);
    const emit = async (topic, data, id) => {
      await page.evaluate(({ topic, data, id }) => {
        const f = window.audioFixture;
        f.now += 3001;
        for (const source of f.sources) source.onmessage?.({ data: JSON.stringify({ topic, data, id, ts: 1, session_id: "session" }) });
      }, { topic, data, id });
      await page.waitForTimeout(75);
    };
    const completed = { turn_outcome: { status: "completed", turn_id: "turn", workspace_slug: "active" } };
    await emit("chat.turn_done", completed, "off");
    assert.equal(await playCount(), 0);
    await page.getByRole("checkbox", { name: "Completion alerts", exact: true }).check();
    await page.getByRole("checkbox", { name: "Completion sounds", exact: true }).check();
    await page.getByRole("checkbox", { name: "Input request sounds" }).check();
    await page.evaluate(() => { const key = "spark-notification-preferences"; const p = JSON.parse(localStorage.getItem(key)); p.quietStart = ""; p.quietEnd = ""; localStorage.setItem(key, JSON.stringify(p)); });
    await emit("chat.turn_done", { ...completed, turn_outcome: { ...completed.turn_outcome, turn_id: "blocked" } }, "blocked");
    assert.equal(await playCount(), 0); // No autoplay resume outside gesture.
    await page.evaluate(() => { window.audioFixture.deny = true; });
    await page.getByRole("button", { name: "Preview completion sound" }).click();
    await page.getByRole("status").filter({ hasText: "Sound unavailable" }).waitFor();
    await page.evaluate(() => { window.audioFixture.deny = false; window.audioFixture.now += 3001; });
    await page.getByRole("button", { name: "Preview completion sound" }).click();
    await page.getByRole("status").filter({ hasText: "Preview played" }).waitFor();
    assert.equal(await playCount(), 1);
    await emit("chat.turn_done", { turn_outcome: { ...completed.turn_outcome, turn_id: "success" } }, "success");
    assert.equal(await playCount(), 2);
    await emit("chat.turn_done", { turn_outcome: { ...completed.turn_outcome, turn_id: "success" } }, "replayed-new-sequence");
    assert.equal(await playCount(), 2);
    await emit("chat.token", { t: "hello" }, "token");
    assert.equal(await playCount(), 2);
    await emit("chat.input_requested", { input: { action_id: "question" } }, "input");
    assert.equal(await playCount(), 3);
    // Two different simultaneous completions share one cooldown reservation.
    await page.evaluate(() => { const f = window.audioFixture; f.now += 3001; for (const id of ["a", "b"]) for (const source of f.sources) source.onmessage?.({ data: JSON.stringify({ id, topic: "notifications.job_complete", ts: 1, data: { success: true, job_id: id, job_name: id } }) }); });
    assert.equal(await playCount(), 4);
    await page.evaluate(() => { const key = "spark-notification-preferences"; const p = JSON.parse(localStorage.getItem(key)); p.mutedProjects = ["muted"]; localStorage.setItem(key, JSON.stringify(p)); });
    await emit("chat.input_requested", { input: { action_id: "muted-question" } }, "muted-question");
    await emit("notifications.job_complete", { success: true, job_id: "muted", project_slug: "muted" }, "muted-job");
    assert.equal(await playCount(), 4);
    await page.evaluate(() => { const key = "spark-notification-preferences"; const p = JSON.parse(localStorage.getItem(key)); p.quietStart = "00:00"; p.quietEnd = "23:59"; localStorage.setItem(key, JSON.stringify(p)); });
    await emit("chat.approval_requested", { approval: { id: "quiet" } }, "quiet");
    assert.equal(await playCount(), 4);
    await page.reload();
    await page.getByRole("button", { name: "Notifications", exact: true }).click();
    assert.equal(await page.getByRole("checkbox", { name: "Completion sounds", exact: true }).isChecked(), true);
    assert.equal(await page.getByRole("checkbox", { name: "Input request sounds" }).isChecked(), true);
    assert.deepEqual(errors, []);
    console.log(`PASS ${desktop ? "Tauri bridge simulated" : "web"}: default off, preference persistence, gesture preview/denial, semantic completion/input, no token sound, dedupe, cooldown, quiet hours, project mute`);
    await context.close();
  }
} finally {
  await browser?.close();
  server.kill("SIGTERM");
  await rm(isolated, { recursive: true, force: true });
}
