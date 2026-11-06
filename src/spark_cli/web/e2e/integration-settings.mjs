// Combined SP14/SP23/SP24/SP25 destinations, built source and synthetic APIs.
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "vite";
import { chromium } from "playwright";
const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = await mkdtemp(path.join(tmpdir(), "spark-integration-settings-"));
await build({ root: web, logLevel: "warn", build: { outDir: out, emptyOutDir: true, rollupOptions: { input: path.join(web, "e2e/settings-fixture.html") } } });
const server = createServer(async (req, res) => {
  try {
    const pathname = new URL(req.url, "http://fixture").pathname;
    const file = path.join(out, pathname === "/" ? "e2e/settings-fixture.html" : pathname);
    res.setHeader("Content-Type", file.endsWith(".js") ? "application/javascript" : file.endsWith(".css") ? "text/css" : "text/html");
    res.end(await readFile(file));
  } catch { res.writeHead(404).end(); }
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => { if (message.type() === "error") console.log(message.text()); });
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    let json = { targets: {}, items: [], status: "missing" };
    if (url.pathname.includes("oauth")) json = { providers: [] };
    if (url.pathname === "/api/config") json = { model: "fixture", model_auto: { roles: {} }, compression: { threshold: 0.5 } };
    if (url.pathname === "/api/config/schema") json = { fields: { model: { type: "string", category: "general" }, model_auto: { type: "object", category: "general" }, "compression.threshold": { type: "number", category: "compression" } } };
    if (url.pathname === "/api/model/routing") json = { roles: {} };
    if (url.pathname === "/api/providers/catalogue") json = { schema_version: 1, providers: [] };
    if (url.pathname === "/api/mcp/servers") json = { servers: {} };
    if (url.pathname === "/api/mcp/readiness") json = { servers: {}, readiness: {} };
    await route.fulfill({ json });
  });
  await page.goto(`http://127.0.0.1:${server.address().port}`);
  await page.getByRole("button", { name: "Open settings fixture" }).click();
  const search = page.getByRole("searchbox", { name: "Search settings" });
  for (const [query, key] of [["Auto role mappings", "model_auto"], ["Context pressure", "compression.threshold"], ["MCP readiness", "mcp-readiness"]]) {
    await search.fill(query);
    await page.locator("[data-settings-result]").filter({ hasText: query }).first().click();
    const field = page.locator(`[data-setting-key="${key}"]`);
    await field.waitFor({ state: "visible", timeout: 10000 }).catch(async (error) => { console.log(await page.locator("body").innerText()); throw error; });
    await page.waitForFunction((key) => {
      const field = [...document.querySelectorAll('[data-setting-key]')].find((el) => el.dataset.settingKey === key);
      return field && (field === document.activeElement || field.contains(document.activeElement));
    }, key);
  }
  assert.deepEqual(errors, []);
  console.log("PASS: role mappings, context pressure and MCP readiness search reach and focus their rendered destinations");
} finally { await browser.close(); await new Promise((resolve) => server.close(resolve)); }
