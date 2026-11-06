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
const output = await mkdtemp(path.join(os.tmpdir(), "spark-sp18-browser-"));
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
  start(process.env.PYTHON || "python", ["-m", "uvicorn", "cron_history_fixture:app", "--host", "127.0.0.1", "--port", String(apiPort)], repo);
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

  let outputReads = 0;
  page.on("request", (request) => { if (/outputs\/[^/?]+\.md/.test(request.url())) outputReads++; });
  await page.getByRole("button", { name: "Execution history", exact: true }).click();
  const drawer = page.getByRole("dialog", { name: "Execution history", exact: true });
  await drawer.getByText("Delivery: error", { exact: true }).waitFor();
  await drawer.getByText("Delivery: unknown", { exact: true }).waitFor();
  assert.equal(await drawer.locator("article").count(), 20);
  assert.equal(outputReads, 0);
  await drawer.getByRole("button", { name: "Load older attempts" }).click();
  await page.waitForFunction(() => document.querySelectorAll("article").length === 25);
  assert.equal(outputReads, 0);
  await drawer.getByRole("button", { name: "Open saved output" }).click();
  const saved = page.getByRole("dialog", { name: "Saved output history" });
  await saved.getByText("# SP18 safe saved result", { exact: false }).waitFor();
  assert.equal(outputReads, 1);
  await saved.getByRole("button", { name: "Close", exact: true }).click();
  await drawer.getByRole("button", { name: "Close", exact: true }).click();
  await page.reload();
  await page.getByRole("button", { name: "Execution history", exact: true }).click();
  await drawer.getByText("Delivery error: fixture offline", { exact: true }).waitFor();
  assert.equal(await drawer.locator("article").count(), 20);
  await page.screenshot({ path: path.join(output, "cron-history.png"), fullPage: true });
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ output, outputReads, attempts: 25, refresh: true }));
} catch (error) {
  console.error(logs.join("\n"));
  throw error;
} finally {
  await browser?.close();
  for (const child of children) child.kill("SIGTERM");
}
