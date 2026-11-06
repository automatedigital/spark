// Built, isolated settings fixture. No profile, credentials or provider requests.
// SPARK_SETTINGS_SOURCE may point at a baseline archive containing the same fixture.
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, mkdtemp, writeFile, realpath } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "vite";
import { chromium } from "playwright";

const web = await realpath(process.env.SPARK_SETTINGS_SOURCE || path.resolve(path.dirname(fileURLToPath(import.meta.url)), ".."));
const out = await mkdtemp(path.join(tmpdir(), "spark-settings-built-"));
await build({ root: web, configFile: path.join(web, "vite.config.ts"), logLevel: "warn", build: {
  outDir: out, emptyOutDir: true, rollupOptions: { input: path.join(web, "e2e/settings-fixture.html") },
} });
const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url, "http://fixture");
    const file = path.join(out, url.pathname === "/" ? "e2e/settings-fixture.html" : url.pathname);
    const body = await readFile(file);
    res.setHeader("Content-Type", file.endsWith(".js") ? "application/javascript" : file.endsWith(".css") ? "text/css" : "text/html");
    res.end(body);
  } catch { res.writeHead(404).end(); }
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({ headless: true });
const samples = [];
try {
  for (let run = 0; run < 5; run++) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();
    page.on("pageerror", (error) => console.error(error));
    page.on("console", (message) => { if (message.type() === "error") console.error(message.text()); });
    const requests = [];
    await page.route("**/api/**", async (route) => {
      const url = new URL(route.request().url());
      requests.push(url.pathname);
      if (url.pathname.includes("analytics")) return route.fulfill({ status: 503, json: { detail: "Synthetic analytics unavailable" } });
      let json = {};
      if (url.pathname === "/api/config") json = { model_provider: "custom", model: "fixture-model", model_base_url: "http://synthetic.invalid", timezone: "UTC" };
      if (url.pathname === "/api/config/schema") json = { fields: { model: { type: "string", category: "general" }, timezone: { type: "string", category: "general" } }, category_order: ["general"] };
      if (url.pathname.includes("available")) json = { models: ["fixture-model"], strict: false };
      if (url.pathname.includes("oauth")) json = { providers: [] };
      if (url.pathname === "/api/providers/catalogue") json = { schema_version: 1, providers: [], selected_provider: "custom" };
      if (url.pathname === "/api/config/raw") json = { yaml: "model: fixture-model\n" };
      if (url.pathname === "/api/logs") json = { lines: ["synthetic log"], total: 1 };
      await route.fulfill({ json });
    });
    const cdp = await context.newCDPSession(page);
    await cdp.send("Network.enable");
    await cdp.send("Network.emulateNetworkConditions", { offline: false, latency: 80, downloadThroughput: 200 * 1024, uploadThroughput: 200 * 1024 });
    await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });
    await page.goto(base);
    const opener = page.getByRole("button", { name: "Open settings fixture" });
    await opener.focus();
    const start = Date.now();
    await opener.click();
    await page.getByRole("button", { name: "Save changes" }).waitFor();
    await page.locator('input[value="http://synthetic.invalid"]').waitFor();
    const interactiveMs = Date.now() - start;
    const scripts = await page.evaluate(() => performance.getEntriesByType("resource").filter((r) => r.name.endsWith(".js")).map((r) => ({ name: r.name, bytes: r.transferSize })));
    const bytes = scripts.reduce((sum, r) => sum + r.bytes, 0);
    assert(!requests.some((url) => /analytics|logs|admin/.test(url)), requests.join(","));
    if (!process.env.SPARK_SETTINGS_BASELINE) assert(!scripts.some((r) => /AnalyticsPage|LogsPage|AdminPage/.test(r.name)));
    samples.push({ interactiveMs, bytes, requests: [...requests], scripts });
    if (run === 0 && !process.env.SPARK_SETTINGS_BASELINE) {
      const tab = (name) => page.getByRole("tab", { name, exact: true }).filter({ visible: true });
      const endpoint = page.locator('input[value="http://synthetic.invalid"]');
      await endpoint.fill("http://unsaved.synthetic.invalid");
      await tab("Chat").click();
      await tab("Model").click();
      await page.locator('input[value="http://unsaved.synthetic.invalid"]').waitFor();
      await tab("MCP").click();
      await page.getByPlaceholder("filesystem").fill("unsaved-server");
      await tab("Model").click();
      await tab("MCP").click();
      assert.equal(await page.getByPlaceholder("filesystem").inputValue(), "unsaved-server");
      // A same-window backend/credential epoch change is fenced before another action.
      await page.getByRole("button", { name: "Switch fixture remote" }).evaluate((el) => el.click());
      await tab("MCP").click(); // retired input is consumed by the ownership fence
      await tab("MCP").click();
      assert.equal(await page.getByPlaceholder("filesystem").inputValue(), "");
      await page.getByPlaceholder("filesystem").fill("remote-profile-draft");
      // Retire the entire draft owner while an old scope's config is in flight.
      let releaseOldConfig, observeOldConfig;
      const oldConfigGate = new Promise((resolve) => { releaseOldConfig = resolve; });
      const oldConfigSeen = new Promise((resolve) => { observeOldConfig = resolve; });
      let heldConfig = false;
      await page.route("**/api/config", async (route) => {
        if (heldConfig) return route.fallback();
        heldConfig = true;
        observeOldConfig();
        await oldConfigGate;
        await route.fulfill({ json: { model_provider: "custom", model: "retired-model", model_base_url: "http://retired-scope.invalid" } });
      });
      await tab("Model").click();
      await oldConfigSeen;
      await page.getByRole("button", { name: "Switch fixture profile" }).evaluate((el) => el.click());
      await page.locator('input[value="http://synthetic.invalid"]').waitFor();
      const oldConfigReturned = page.waitForResponse((response) => response.url().endsWith("/api/config") && response.request().method() === "GET");
      releaseOldConfig();
      await oldConfigReturned;
      await tab("Chat").click();
      await tab("Model").click();
      await page.locator('input[value="http://synthetic.invalid"]').waitFor();
      assert.equal(await page.locator('input[value="http://retired-scope.invalid"]').count(), 0);
      await tab("MCP").click();
      assert.equal(await page.getByPlaceholder("filesystem").inputValue(), "");
      await page.getByRole("button", { name: "Close settings" }).click();
      await opener.waitFor();
      assert.equal(await opener.evaluate((el) => document.activeElement === el), true);
      await opener.click();
      await page.locator('input[value="http://synthetic.invalid"]').waitFor();
      await tab("MCP").click();
      assert.equal(await page.getByPlaceholder("filesystem").inputValue(), "");
      let releaseConfig;
      const configGate = new Promise((resolve) => { releaseConfig = resolve; });
      await page.route("**/ConfigPage-*.js", async (route) => { await configGate; await route.continue(); });
      await tab("Advanced").click();
      await page.getByRole("status").filter({ hasText: "Loading Config" }).waitFor();
      assert.equal(await tab("Advanced").evaluate((el) => document.activeElement === el), true);
      releaseConfig();
      // Config is lazy and its unsaved raw draft survives unmount, including empty text.
      const yaml = page.getByRole("button", { name: /YAML/i });
      await yaml.click();
      const editor = page.locator("textarea");
      await page.waitForFunction(() => document.querySelector("textarea")?.value === "model: fixture-model\n");
      await editor.fill("");
      await tab("Model").click();
      await tab("Advanced").click();
      assert.equal(await page.locator("textarea").inputValue(), "");
      await page.getByRole("button", { name: "Logs", exact: true }).first().click();
      await page.getByText("Auto-refresh", { exact: false }).first().waitFor();
      // Enable polling, then retire the tab. Virtual time proves no inactive interval.
      await page.clock.install();
      await page.getByRole("switch").click();
      const polled = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/logs");
      await page.clock.fastForward(6000);
      await polled;
      await tab("Model").click();
      const logCount = requests.filter((url) => url === "/api/logs").length;
      await page.clock.fastForward(16000);
      assert.equal(requests.filter((url) => url === "/api/logs").length, logCount);

      await page.screenshot({ path: path.join(out, "settings-model.png") });
      // A real built chunk fetch fails; the existing reload action clears the ES module failure cache.
      await page.route("**/AnalyticsPage-*.js", (route) => route.abort());
      await tab("Advanced").click();
      await page.getByRole("button", { name: "Analytics", exact: true }).first().click();
      await page.getByRole("alert").filter({ hasText: "could not be loaded" }).waitFor();
      await page.unroute("**/AnalyticsPage-*.js");
      await page.getByRole("button", { name: "Reload and retry" }).click();
      await opener.waitFor();
      await opener.click();
      await tab("Advanced").click();
      await page.getByRole("button", { name: "Analytics", exact: true }).first().click();
      await page.getByRole("button", { name: "7d", exact: true }).waitFor();
      assert.equal(await page.getByText("Analytics could not be loaded.").count(), 0);
    }
    await context.close();
  }
  const sorted = (key) => samples.map((s) => s[key]).sort((a, b) => a - b);
  const report = { node: process.version, web, samples, medianMs: sorted("interactiveMs")[2], p95Ms: sorted("interactiveMs")[4], medianBytes: sorted("bytes")[2], out };
  await writeFile(process.env.SPARK_SETTINGS_REPORT || path.join(out, "report.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report));
} finally { await browser.close(); await new Promise((resolve) => server.close(resolve)); }
