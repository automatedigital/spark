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
  outDir: out, emptyOutDir: true, rollupOptions: { input: path.join(web, "e2e/model-catalogue-fixture.html") },
} });
const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url, "http://fixture");
    const file = path.join(out, url.pathname === "/" ? "e2e/model-catalogue-fixture.html" : url.pathname);
    const body = await readFile(file);
    res.setHeader("Content-Type", file.endsWith(".js") ? "application/javascript" : file.endsWith(".css") ? "text/css" : "text/html");
    res.end(body);
  } catch { res.writeHead(404).end(); }
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({ headless: true });

try {
 const page = await browser.newPage();
 const requests = [];
 await page.route("**/api/**", async route => {
  const pathname = new URL(route.request().url()).pathname;
  requests.push(pathname);
  let json = {};
  if (pathname === "/api/providers/catalogue") json = { providers: [{ id: "custom", label: "Fixture route", credential: { mechanism: "none", configured: false, env_vars: [] }, base_url: { policy: "editable", default: "" }, availability: "unknown", capabilities: {} }], selected_provider: "custom" };
  if (pathname === "/api/model/status") json = { smart_model: "namespace/typed-model", smart_provider: "custom", fast_model: "fast", fast_provider: "unknown-route", multi_model_enabled: true, selection: "explicit", auto_roles: {} };
  if (pathname === "/api/model/suggestions") json = { smart: ["other/model"], fast: [] };
  if (pathname === "/api/config") json = { model_provider: "custom", model: "typed-model", model_base_url: "http://synthetic.invalid" };
  if (pathname === "/api/config/schema") json = { fields: { model: { type: "string", category: "general" } }, category_order: ["general"] };
  if (pathname.includes("oauth")) json = { providers: [] };
  await route.fulfill({ json });
 });
 await page.goto(base);
 await page.getByRole("button", {name: /^Model and reasoning settings:/}).click();
 const popover = page.getByRole("dialog", {name: "Model and reasoning settings"});
 await popover.getByText("Fixture route", {exact: true}).waitFor();
 await popover.getByText("unknown-route", {exact: true}).waitFor();
 assert.equal(await popover.getByText("namespace", {exact: true}).count(), 0);
 await page.keyboard.press("Escape");
 await page.getByRole("button", {name: "Open settings fixture"}).click();
 await page.getByRole("button", {name: "Save changes"}).waitFor();
 await page.getByRole("button", {name: "Model: typed-model", exact: true}).click();
 await page.getByPlaceholder("Search or type a model name…").fill("offline-custom");
 await page.keyboard.press("Enter");
 await page.getByRole("button", {name: "Model: offline-custom", exact: true}).waitFor();
 assert.equal(requests.filter(p => p === "/api/model/available").length, 0);
 console.log("PASS active PromptBar catalogue labels, unknown route, Settings custom keyboard entry; zero live enumeration on open");
} finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
