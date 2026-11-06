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
 let releaseA, observeA;
 let offline = false;
 let empty = false;
 const heldA = new Promise(resolve => { releaseA = resolve; });
 const seenA = new Promise(resolve => { observeA = resolve; });
 let holdA = true;
 await page.route("**/api/**", async route => {
  const pathname = new URL(route.request().url()).pathname;
  requests.push(pathname);
  let json = {};
  if (pathname === "/api/model/available") {
    const endpoint = new URL(route.request().url()).searchParams.get("base_url");
    if (holdA && endpoint === "http://synthetic.invalid") {
      holdA = false;
      observeA();
      await heldA;
      await route.fulfill({json: { models: ["retired-a-model"], live: true }}).catch(() => {});
      return;
    }
    if (offline) return route.abort("internetdisconnected");
    return route.fulfill({ json: {models: empty ? [] : ["current-b-model"], live: true} });
  }
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

 const refresh = page.getByTitle("Refresh model list from provider", {exact: true});
 await refresh.click();
 await seenA;
 await page.getByText("Loading models…", {exact: true}).waitFor();
 await page.locator('input[value="http://synthetic.invalid"]').fill("http://b.synthetic.invalid");
 await refresh.click();
 await page.getByText("Pulled live from custom.", {exact: true}).waitFor();
 releaseA();
 await page.getByRole("button", {name: "Model: offline-custom", exact: true}).click();
 await page.getByRole("button", {name: "current-b-model", exact: true}).waitFor();
 assert.equal(await page.getByRole("button", {name: "retired-a-model", exact: true}).count(), 0);
 const before = requests.filter(p => p === "/api/model/available").length;
 // Reopening only reads the short-TTL cache and never invokes discovery.
 await page.getByRole("button", {name: "Model: offline-custom", exact: true}).click();
 await page.getByRole("button", {name: "Model: offline-custom", exact: true}).click();
 assert.equal(requests.filter(p => p === "/api/model/available").length, before);
 await page.keyboard.press("Escape");
 await page.getByRole("tab", {name: "Chat", exact: true}).filter({visible:true}).click();
 await page.getByRole("tab", {name: "Model", exact: true}).filter({visible:true}).click();
 await page.getByRole("button", {name: "Model: offline-custom", exact: true}).click();
 await page.getByRole("button", {name: "current-b-model", exact: true}).waitFor();
 assert.equal(requests.filter(p => p === "/api/model/available").length, before);
 await page.keyboard.press("Escape");
 offline = true;
 await refresh.click();
 await page.getByText("Model discovery failed. Your selected ID is preserved. Refresh to retry.", {exact: true}).waitFor();
 await page.getByRole("button", {name: "Model: offline-custom", exact: true}).click();
 const search = page.getByPlaceholder("Search or type a model name…");
 await search.fill("offline-keyboard-id");
 await page.keyboard.press("Enter");
 await page.getByRole("button", {name: "Model: offline-keyboard-id", exact: true}).waitFor();
 offline = false;
 await refresh.click();
 await page.getByText("Pulled live from custom.", {exact: true}).waitFor();
 assert.equal(requests.filter(p => p === "/api/model/available").length, before + 2);
 await page.getByRole("button", {name: "Model: offline-keyboard-id", exact: true}).waitFor();
 // Advance only the clock used for freshness; no sleep or provider call.
 await page.evaluate(() => { const now = Date.now; Date.now = () => now() + 31_000; });
 await page.getByRole("button", {name: "Model: offline-keyboard-id", exact: true}).click();
 await page.getByText("Cached models are stale. Refresh to update.", {exact: true}).waitFor();
 await page.keyboard.press("Escape");
 empty = true;
 await refresh.click();
 await page.getByText("Provider returned no models. Type a custom ID.", {exact: true}).waitFor();
 await page.getByRole("button", {name: "Model: offline-keyboard-id", exact: true}).waitFor();
 console.log("PASS current URL only after deferred reverse completion; native abort; TTL reopen no call; explicit Refresh bypass; offline custom keyboard selection and retry");

} finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
