// Provider-free browser flow against this checkout's real backend and composer.
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
const output = process.env.STASH_OUTPUT || await mkdtemp(path.join(os.tmpdir(), "spark-stash-evidence-"));
await mkdir(output, { recursive: true });
const home = await mkdtemp(path.join(os.tmpdir(), "spark-stash-home-"));
const env = { ...process.env, HOME: home, USERPROFILE: home, SPARK_HOME: path.join(home, "spark"), PYTHONPATH: path.join(repo, "src") };
await mkdir(env.SPARK_HOME);
await writeFile(path.join(env.SPARK_HOME, "config.yaml"), "model:\n  default: fixture\n  provider: openai\n  base_url: http://127.0.0.1:1/v1\n");
const python = process.env.PYTHON || path.join(repo, ".venv/bin/python");
const seed = spawnSync(python, ["-c", `from core.spark_state import SessionDB
db = SessionDB()
db.create_session("stash_fixture", "e2e", model="fixture")
db.set_session_title("stash_fixture", "Stash fixture")
db.append_message("stash_fixture", "user", content="Fixture prompt")
db.append_message("stash_fixture", "assistant", content="Fixture response")
db.close()
`], { cwd: repo, env, encoding: "utf8" });
assert.equal(seed.status, 0, seed.stderr);
const port = () => new Promise((resolve) => { const s = net.createServer(); s.listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => resolve(p)); }); });
const apiPort = await port(), webPort = await port();
const base = `http://127.0.0.1:${webPort}`;
const logs = [], children = [];
const start = (cmd, args, cwd, extra = {}) => {
  const child = spawn(cmd, args, { cwd, env: { ...env, ...extra }, stdio: ["ignore", "pipe", "pipe"] });
  children.push(child);
  child.stdout.on("data", (d) => logs.push(String(d)));
  child.stderr.on("data", (d) => logs.push(String(d)));
};
start(python, ["-c", `from spark_cli.web_server import start_server; start_server('127.0.0.1', ${apiPort}, False)`], repo);
start(process.execPath, ["node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", String(webPort)], web, { SPARK_API_TARGET: `http://127.0.0.1:${apiPort}` });
const wait = async (url) => { for (let n = 0; n < 150; n++) { try { if ((await fetch(url)).ok) return; } catch {} await new Promise((r) => setTimeout(r, 200)); } throw new Error(`Not ready: ${url}`); };
let browser;
const checks = [];
try {
  await wait(`http://127.0.0.1:${apiPort}/api/status`); await wait(base);
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  let providerCalls = 0;
  await page.route("**/api/chat", (route) => { providerCalls++; return route.abort(); });
  page.setDefaultTimeout(60_000);
  await page.goto(base, { waitUntil: "domcontentloaded", timeout: 90_000 });
  await page.getByRole("button", { name: /Stash fixture/ }).first().click();
  const input = page.locator("textarea").first();
  await input.fill("Reusable\n你好 🚀");
  await page.getByRole("button", { name: "Saved prompts", exact: true }).click();
  await page.getByRole("button", { name: "Save current prompt" }).click();
  await page.getByRole("status").filter({ hasText: "Prompt saved in this browser." }).waitFor();
  await page.getByRole("button", { name: "Close saved prompts" }).click();
  await input.fill("Keep this draft");
  await page.waitForTimeout(450);
  await page.reload();
  await page.getByRole("button", { name: /Stash fixture/ }).first().click();
  await page.getByRole("button", { name: "Saved prompts", exact: true }).click();
  await page.getByRole("button", { name: "Restore prompt", exact: true }).click();
  await page.getByRole("button", { name: "Keep current draft" }).click();
  assert.equal(await input.inputValue(), "Keep this draft"); checks.push("reload persistence and cancel preserves draft");
  await page.getByRole("button", { name: "Restore prompt", exact: true }).click();
  await page.getByRole("button", { name: "Replace draft text" }).click();
  assert.equal(await input.inputValue(), "Reusable\n你好 🚀"); checks.push("explicit replacement restores editable exact text");
  await input.fill("");
  await page.getByRole("button", { name: "Saved prompts", exact: true }).click();
  await page.getByRole("button", { name: "Restore prompt", exact: true }).click();
  assert.equal(await input.inputValue(), "Reusable\n你好 🚀"); checks.push("empty draft restore");
  await page.getByRole("button", { name: "Saved prompts", exact: true }).click();
  await page.evaluate(() => { window.__stashSetItem = Storage.prototype.setItem; Storage.prototype.setItem = function(k, v) { if (k.startsWith("spark.prompt-stash")) throw new DOMException("quota", "QuotaExceededError"); return window.__stashSetItem.call(this, k, v); }; });
  await page.getByRole("button", { name: "Delete prompt", exact: true }).click();
  await page.getByRole("alert").filter({ hasText: "The change was not saved" }).waitFor();
  assert.equal(await page.getByRole("button", { name: "Restore prompt", exact: true }).count(), 1);
  await page.getByRole("button", { name: "Save current prompt" }).click();
  await page.getByRole("alert").filter({ hasText: "The change was not saved" }).waitFor();
  checks.push("quota save/delete are honest and preserve saved item/draft");
  await page.screenshot({ path: path.join(output, "storage-failure.png") });
  await page.evaluate(() => { Storage.prototype.setItem = window.__stashSetItem; });
  await page.getByRole("button", { name: "Delete prompt", exact: true }).click();
  await page.getByText("No saved prompts yet.", { exact: true }).waitFor();
  await page.getByRole("button", { name: "Close saved prompts" }).click();
  await page.waitForTimeout(450);
  await page.reload();
  await page.getByRole("button", { name: /Stash fixture/ }).first().click();
  await page.getByRole("button", { name: "Saved prompts", exact: true }).click();
  await page.getByText("No saved prompts yet.", { exact: true }).waitFor();
  checks.push("deletion persists across reload");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Close saved prompts" }).click();
  await page.getByRole("button", { name: "Saved prompts", exact: true }).click();
  await page.screenshot({ path: path.join(output, "mobile-chooser.png") });
  await page.keyboard.press("Escape");
  assert.equal(await page.getByRole("dialog", { name: "Saved prompts" }).count(), 0);
  checks.push("compact viewport access and keyboard dismissal");
  assert.equal(providerCalls, 0);
  console.log(JSON.stringify({ checks, providerCalls, home, output }, null, 2));
} finally {
  await browser?.close();
  for (const child of children) child.kill("SIGTERM");
  await writeFile(path.join(output, "server.log"), logs.join(""));
}
