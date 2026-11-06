// SP17: actual Schedule UI + HTTP cron routes + on-disk persistence; no provider calls.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, writeFile } from "node:fs/promises";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repo = path.resolve(web, "../../..");
const output = await mkdtemp(path.join(os.tmpdir(), "spark-sp17-browser-"));
const home = await mkdtemp(path.join(os.tmpdir(), "spark-f02-home-"));
const env = { ...process.env, HOME: home, USERPROFILE: home, SPARK_HOME: home, PYTHONPATH: `${repo}/src:${repo}/tests/spark_cli` };
const freePort = () => new Promise((resolve) => {
  const server = net.createServer();
  server.listen(0, "127.0.0.1", () => { const port = server.address().port; server.close(() => resolve(port)); });
});
const apiPort = await freePort(), webPort = await freePort();
const api = `http://127.0.0.1:${apiPort}`, base = `http://127.0.0.1:${webPort}`;
const children = [], logs = [];
function start(command, args, cwd, extra = {}) {
  const child = spawn(command, args, { cwd, env: { ...env, ...extra }, stdio: ["ignore", "pipe", "pipe"] });
  child.stdout.on("data", (data) => logs.push(String(data)));
  child.stderr.on("data", (data) => logs.push(String(data)));
  children.push(child);
}
async function ready(url) {
  for (let i = 0; i < 100; i++) {
    try { if ((await fetch(url)).ok) return; } catch { /* wait for fixture server */ }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Server unavailable: ${url}`);
}
let browser;
try {
  start(process.env.PYTHON || "python", ["-m", "uvicorn", "schedule_preview_fixture:app", "--host", "127.0.0.1", "--port", String(apiPort)], repo);
  start(process.execPath, ["node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", String(webPort)], web, { SPARK_API_TARGET: api });
  await Promise.all([ready(`${api}/api/cron/jobs`), ready(base)]);
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
  page.setDefaultTimeout(60_000);
  page.setDefaultNavigationTimeout(120_000);
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  // Render the real page in isolation, keeping the browser flow independent of chat services.
  await page.goto(`${base}/e2e/fixtures/cron-overrides.html`);
  page.on("console", (message) => { if (message.type() === "error") console.error(message.text()); });

  const preview = page.getByRole("region", { name: "Schedule preview" }).first();
  await page.locator("#cron-timezone").fill("Europe/London");
  await preview.getByText("2026-03-29T09:00:00+01:00", { exact: true }).waitFor();
  assert.equal(await preview.locator("time").count(), 5);
  assert.deepEqual(await (await fetch(`${api}/api/cron/jobs`)).json(), []);
  await page.locator("#cron-timezone").fill("Mars/Olympus");
  await preview.getByRole("alert").filter({ hasText: "timezone" }).waitFor();
  await page.locator("#cron-timezone").fill("Asia/Tokyo");
  await preview.getByText("2026-03-29T09:00:00+09:00", { exact: true }).waitFor();
  await page.locator("#cron-name").fill("SP17 fixture");
  await page.locator("#cron-prompt").fill("Fixture prompt");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByText("SP17 fixture", { exact: true }).waitFor();
  let stored = await (await fetch(`${api}/api/cron/jobs`)).json();
  assert.equal(stored.length, 1);
  const id = stored[0].id;
  assert.equal(stored[0].next_run_at, "2026-03-29T09:00:00+09:00");
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await page.locator(`#cron-timezone-${id}`).fill("UTC");
  const editPreview = page.getByRole("region", { name: "Schedule preview" }).last();
  await editPreview.getByText("2026-03-29T09:00:00+00:00", { exact: true }).waitFor();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  stored = await (await fetch(`${api}/api/cron/jobs`)).json();
  assert.equal(stored[0].id, id);
  assert.equal(stored[0].prompt, "Fixture prompt");
  assert.equal(stored[0].next_run_at, "2026-03-29T09:00:00+00:00");
  // Readiness errors are configuration facts, without contacting a provider.
  const readiness = await (await fetch(`${api}/api/cron/preview`, { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ schedule: "every 1h", provider: "unavailable-fixture", skills: ["missing"], deliver: "unknown" }),
  })).json();
  assert.equal(readiness.readiness.errors.length, 3);
  // The dedicated client must use the shared remote connection base too.
  await page.evaluate((remote) => {
    localStorage.setItem("spark-connection-mode", "remote");
    localStorage.setItem("spark-remote-base-url", remote);
  }, api);
  await page.reload();
  await page.locator("#cron-timezone").fill("Europe/London");
  await page.getByRole("region", { name: "Schedule preview" }).first().getByText("2026-03-29T09:00:00+01:00", { exact: true }).waitFor();
  assert.equal((await (await fetch(`${api}/api/cron/jobs`)).json()).length, 1);
  await page.locator("#cron-freq").getByRole("combobox").click();
  await page.getByRole("option", { name: "Custom (cron expression)", exact: true }).click();
  await page.locator("#cron-schedule").fill("every 0m");
  await page.getByRole("region", { name: "Schedule preview" }).first().getByRole("alert").waitFor();
  await fetch(`${api}/api/cron/jobs/${id}`, { method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ updates: { provider: "unavailable-fixture", skills: ["missing"] } }) });
  await page.reload();
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await page.getByRole("region", { name: "Schedule preview" }).last().getByRole("alert").filter({ hasText: "Skill unavailable: missing" }).waitFor();
  // Measure the bounded preview response over five fixture HTTP samples.
  const samples = [];
  for (let i = 0; i < 5; i++) {
    const start = performance.now();
    const response = await fetch(`${api}/api/cron/preview`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ schedule: "0 9 * * *", timezone: "UTC" }) });
    const text = await response.text();
    samples.push({ ms: performance.now() - start, bytes: Buffer.byteLength(text) });
  }
  console.log(JSON.stringify({ flow: "SP17 real storage preview/create/edit", samples }));
  assert.deepEqual(errors, []);
  await page.screenshot({ path: path.join(output, "schedule-preview.png"), fullPage: true });
  console.log(`SP17 browser PASS; artifact ${output}`);
} catch (error) {
  console.error(logs.join("\n"));
  throw error;
} finally {
  await browser?.close();
  for (const child of children) child.kill("SIGTERM");
}
