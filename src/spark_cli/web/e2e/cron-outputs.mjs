// Real cron API + filesystem, mounted CronPage. No app startup/provider calls.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, mkdir, writeFile, unlink, rm } from "node:fs/promises";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repo = path.resolve(web, "../../..");
const python = process.env.PYTHON || path.join(repo, ".venv/bin/python");
const temp = await mkdtemp(path.join(os.tmpdir(), "spark-cron-output-"));
const fixture = path.join(web, ".cron-output-fixture.html");
const children = [];
const logs = [];
let browser;
async function port() {
  const server = net.createServer();
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const value = server.address().port;
  await new Promise((resolve) => server.close(resolve));
  return value;
}
async function ready(url) {
  for (let i = 0; i < 100; i++) {
    try { if ((await fetch(url)).ok) return; } catch { /* starting */ }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Server did not start: ${url}\n${logs.join("")}`);
}
function start(command, args, env) {
  const child = spawn(command, args, { cwd: web, env, stdio: ["ignore", "pipe", "pipe"] });
  children.push(child);
  child.stdout.on("data", (data) => logs.push(String(data)));
  child.stderr.on("data", (data) => logs.push(String(data)));
}
try {
  const apiPort = await port(), webPort = await port();
  const home = path.join(temp, "home"), profile = path.join(temp, "profile");
  const output = path.join(profile, "cron/output/abcdef123456");
  await mkdir(home, { recursive: true });
  await mkdir(output, { recursive: true });
  const jobs = [
    { id: "abcdef123456", name: "Fixture outputs", prompt: "Fixture", state: "paused", enabled: false, schedule_display: "0 9 * * *" },
    { id: "123456abcdef", name: "Empty history", prompt: "Fixture", state: "paused", enabled: false, schedule_display: "0 9 * * *" },
  ];
  await writeFile(path.join(profile, "cron/jobs.json"), JSON.stringify({ jobs }));
  for (let day = 1; day <= 22; day++) {
    await writeFile(path.join(output, `2026-10-${String(day).padStart(2, "0")}_09-00-00.md`),
      day === 22 ? "# Newest output\n<script>window.outputExecuted=true</script>\nSaved fixture ✓" : `# Output day ${day}`);
  }
  await writeFile(path.join(output, "2026-10-01_09-00-00.md"), "A".repeat(300000));
  const backend = path.join(temp, "backend.py");
  await writeFile(backend, "from fastapi import FastAPI\nfrom spark_cli.cron_routes import register_cron_routes\napp = FastAPI()\nregister_cron_routes(app)\n");
  const env = { ...process.env, HOME: home, USERPROFILE: home, SPARK_HOME: profile, PYTHONPATH: `${repo}/src` };
  start(python, ["-m", "uvicorn", "backend:app", "--app-dir", temp, "--port", String(apiPort), "--host", "127.0.0.1"], env);
  // The fixture mounts the real page and translation provider, excluding shell
  // background services. All cron traffic goes to the actual registered routes.
  await writeFile(fixture, `<html><body><div id="root"></div><script type="module">
import React from 'react';
import {createRoot} from 'react-dom/client';
import CronPage from '/src/pages/CronPage.tsx';
import {I18nProvider} from '/src/i18n/index.ts';
import '/src/index.css';
createRoot(document.getElementById('root')).render(React.createElement(I18nProvider,null,React.createElement(CronPage)));
</script></body></html>`);
  start(process.execPath, [path.join(web, "node_modules/vite/bin/vite.js"), "--host", "127.0.0.1", "--port", String(webPort)], { ...env, SPARK_API_TARGET: `http://127.0.0.1:${apiPort}` });
  await ready(`http://127.0.0.1:${apiPort}/api/cron/jobs`);
  await ready(`http://127.0.0.1:${webPort}`);
  browser = await chromium.launch({ headless: true, env });
  const context = await browser.newContext({ viewport: { width: 1200, height: 900 }, permissions: ["clipboard-read", "clipboard-write"] });
  const page = await context.newPage();
  await page.goto(`http://127.0.0.1:${webPort}/.cron-output-fixture.html`);
  await page.getByRole("button", { name: "Outputs", exact: true }).first().click();
  const drawer = page.getByRole("dialog", { name: "Saved output history" });
  await drawer.getByText("Saved fixture ✓", { exact: false }).waitFor();
  assert.equal(await page.evaluate(() => window.outputExecuted), undefined);
  assert.equal(await drawer.getByRole("button", { name: /^2026-/ }).first().innerText(), "2026-10-22_09-00-00.md");
  await drawer.getByRole("button", { name: "Copy Markdown", exact: true }).click();
  assert.match(await page.evaluate(() => navigator.clipboard.readText()), /Saved fixture ✓/);
  await drawer.getByRole("button", { name: "Load older outputs" }).click();
  await drawer.getByRole("button", { name: "2026-10-01_09-00-00.md" }).click();
  await drawer.getByText(/Showing the first/).waitFor();
  await drawer.getByRole("button", { name: "Copy displayed text" }).click();
  assert.equal((await page.evaluate(() => navigator.clipboard.readText())).length, 262144);
  await unlink(path.join(output, "2026-10-21_09-00-00.md"));
  await drawer.getByRole("button", { name: "2026-10-21_09-00-00.md" }).click();
  await drawer.getByRole("alert").filter({ hasText: "pruned" }).waitFor();
  await drawer.getByRole("button", { name: "2026-10-20_09-00-00.md" }).click();
  await drawer.getByText("# Output day 20", { exact: true }).waitFor();
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await drawer.evaluate((element) => element.getBoundingClientRect().width <= window.innerWidth), true);
  const screenshot = process.env.SCREENSHOT || path.join(os.tmpdir(), "spark-F10-output-drawer.png");
  await page.screenshot({ path: screenshot });
  await page.keyboard.press("Escape");
  await drawer.waitFor({ state: "detached" });
  assert.equal(await page.getByRole("button", { name: "Outputs", exact: true }).first().evaluate((element) => element === document.activeElement), true);
  await page.getByRole("button", { name: "Outputs", exact: true }).nth(1).click();
  await page.getByText("No saved outputs. Files may have been pruned.", { exact: true }).waitFor();
  console.log(`PASS: newest/read/copy, older page, truncated read/copy, pruned/recovery, mobile drawer, Escape/focus, empty history; screenshot=${screenshot}`);
} finally {
  await browser?.close();
  for (const child of children) child.kill("SIGTERM");
  await Promise.all(children.map((child) => child.exitCode === null ? new Promise((resolve) => child.once("exit", resolve)) : undefined));
  await rm(fixture, { force: true });
  await rm(temp, { recursive: true, force: true });
}
