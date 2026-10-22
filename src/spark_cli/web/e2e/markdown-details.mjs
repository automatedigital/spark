// Run with Node 22: node e2e/markdown-details.mjs. No backend or provider needed.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, mkdir, rm } from "node:fs/promises";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const home = await mkdtemp(path.join(os.tmpdir(), "spark-details-"));
await mkdir(path.join(home, "spark"));
const port = await new Promise((resolve, reject) => {
  const server = net.createServer();
  server.on("error", reject);
  server.listen(0, "127.0.0.1", () => {
    const { port } = server.address();
    server.close(() => resolve(port));
  });
});
const origin = `http://127.0.0.1:${port}`;
const server = spawn(process.execPath, ["node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", String(port), "--strictPort"], {
  cwd: webRoot,
  env: { ...process.env, HOME: home, USERPROFILE: home, SPARK_HOME: path.join(home, "spark") },
  stdio: "ignore",
});
let browser;
try {
  const deadline = Date.now() + 60_000;
  while (true) {
    try { if ((await fetch(origin)).ok) break; } catch { /* wait for Vite */ }
    if (Date.now() > deadline) throw new Error("Vite did not start");
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  // Resolve the installed browser before HOME isolation redirects its cache lookup.
  const executablePath = chromium.executablePath();
  browser = await chromium.launch({ executablePath, env: { ...process.env, HOME: home, USERPROFILE: home, SPARK_HOME: path.join(home, "spark") } });
  const context = await browser.newContext({ permissions: ["clipboard-read", "clipboard-write"] });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(`${origin}/e2e/markdown-details.html`);
  const summary = page.locator("#closed summary");
  await summary.waitFor();
  assert.equal(await page.locator("#closed details").evaluate((el) => el.open), false);
  assert.equal(await page.locator("#open details").evaluate((el) => el.open), true);
  await page.evaluate(() => {
    window.transcriptMutations = 0;
    new MutationObserver((records) => { window.transcriptMutations += records.length; })
      .observe(document.querySelector("#other"), { subtree: true, childList: true, characterData: true, attributes: true });
  });
  await summary.focus();
  await page.keyboard.press("Enter");
  await page.waitForFunction(() => document.querySelector("#closed details").open);
  assert.equal(await page.locator("#closed pre").innerText(), "copy this evidence");
  await page.getByRole("button", { name: "Copy code" }).click();
  await page.waitForFunction(async () => (await navigator.clipboard.readText()) === "copy this evidence");
  await page.keyboard.press("Tab");
  await summary.click();
  await page.waitForFunction(() => !document.querySelector("#closed details").open);
  assert.equal(await page.evaluate(() => window.transcriptMutations), 0);
  // Native find/reveal is browser-dependent; record it without claiming support.
  console.log("native find/reveal:", await page.evaluate(() => {
    const found = window.find("Searchable supporting sentence");
    return { found, open: document.querySelector("#closed details").open, selected: window.getSelection().toString() };
  }));
  for (const mode of ["partial", "malicious", "safe"]) {
    await page.evaluate((mode) => window.renderDetailsFixture(mode), mode);
    await page.locator(`main[data-mode="${mode}"]`).waitFor();
    await page.waitForFunction(() => !document.querySelector("#closed details"));
    assert.match(await page.locator("#closed").innerText(), /<details/);
    assert.equal(await page.locator("#closed [onclick]").count(), 0);
    assert.equal(await page.evaluate(() => window.injected), undefined);
  }
  await page.evaluate(() => window.renderDetailsFixture());
  await summary.waitFor();
  await summary.click();
  await page.waitForFunction(() => document.querySelector("#closed details").open);
  const screenshot = path.join(os.tmpdir(), "spark-f07-details.png");
  await page.screenshot({ path: screenshot, fullPage: true });
  console.log("screenshot:", screenshot);
  assert.deepEqual(errors, []);
  console.log("PASS: default/open, keyboard/pointer toggle, copy, transcript stability, partial/malicious/safe fallbacks, completion recovery; no page errors");
} finally {
  await browser?.close();
  server.kill("SIGTERM");
  await new Promise((resolve) => server.exitCode !== null ? resolve() : server.once("exit", resolve));
  await rm(home, { recursive: true, force: true });
}
