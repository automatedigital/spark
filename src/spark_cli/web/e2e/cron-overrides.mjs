// F02: actual Schedule UI + HTTP cron routes + on-disk persistence; no provider calls.
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
const output = await mkdtemp(path.join(os.tmpdir(), "spark-f02-browser-"));
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
  start(process.env.PYTHON || "python", ["-m", "uvicorn", "cron_overrides_fixture:app", "--host", "127.0.0.1", "--port", String(apiPort)], repo);
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
  await page.locator("#cron-name").fill("F02 fixture job");
  await page.locator("#cron-prompt").fill("Summarize fixture");
  await page.getByRole("button", { name: "Advanced", exact: true }).click();
  const choose = async (selector, label) => {
    await page.locator(selector).getByRole("combobox").click();
    await page.getByRole("option", { name: label, exact: true }).click();
  };
  await choose("#cron-provider", "Fixture provider");
  await choose("#cron-model", "fixture-one");
  await choose("#cron-skill", "alpha");
  await choose("#cron-skill", "beta");
  await page.getByRole("button", { name: "Move beta up", exact: true }).click();
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByText("Provider: fixture · Model: fixture-one · Skills: beta → alpha", { exact: true }).waitFor();
  let jobs = await (await fetch(`${api}/api/cron/jobs`)).json();
  assert.deepEqual(jobs[0].skills, ["beta", "alpha"]);
  const id = jobs[0].id;
  await page.reload();
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await page.getByRole("button", { name: "Advanced", exact: true }).last().click();
  assert.equal(await page.locator(`#cron-${id}-model`).getByRole("combobox").innerText(), "fixture-one");
  await choose(`#cron-${id}-model`, "fixture-two");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await page.getByText("Provider: fixture · Model: fixture-two · Skills: beta → alpha", { exact: true }).waitFor();
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await page.getByRole("button", { name: "Advanced", exact: true }).last().click();
  await page.getByRole("button", { name: "Clear overrides", exact: true }).click();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await page.getByText("Provider: Profile default · Model: Profile default · Skills: None", { exact: true }).waitFor();
  await page.reload();
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await page.getByRole("button", { name: "Advanced", exact: true }).last().click();
  assert.equal(await page.locator(`#cron-${id}-provider`).getByRole("combobox").innerText(), "Profile default");
  assert.equal(await page.locator(`#cron-${id}-model`).getByRole("combobox").innerText(), "Profile default");
  jobs = await (await fetch(`${api}/api/cron/jobs`)).json();
  assert.equal(jobs[0].provider, null);
  assert.equal(jobs[0].model, null);
  assert.equal(jobs[0].skill, null);
  assert.deepEqual(jobs[0].skills, []);
  await page.screenshot({ path: path.join(output, "clear-reopened.png"), fullPage: true });
  assert.deepEqual(errors, []);
  await writeFile(path.join(output, "result.json"), JSON.stringify({ flow: "create/select/reorder/save/reload/edit/save/clear/reload/reopen", jobs, errors }, null, 2));
  console.log(`PASS F02 browser: ${output}`);
} finally {
  await browser?.close();
  for (const child of children) child.kill("SIGTERM");
  await writeFile(path.join(output, "servers.log"), logs.join(""));
}
