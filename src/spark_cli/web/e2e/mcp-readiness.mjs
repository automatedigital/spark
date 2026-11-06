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
let posts = 0;
let gets = 0;
let releaseSavedRead;
let holdSavedRead = false;
const savedReadGate = new Promise((resolve) => { releaseSavedRead = resolve; });
let state = "unknown";
const value = () => ({ state, last_test_at: state === "unknown" ? null : 1700000000,
  duration_ms: state === "unknown" ? null : 25, tool_count: state === "ready" ? 2 : null,
  error: state === "failed" ? "connection_failed" : null, run_id: posts ? "fixture-run" : null });
try {
  const page = await browser.newPage();
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    let json = {};
    if (url.pathname === "/api/config") json = { model_provider: "custom", model: "fixture" };
    if (url.pathname.includes("oauth")) json = { providers: [] };
    if (url.pathname === "/api/mcp/servers") {
      if (route.request().method() === "POST") state = "unknown";
      else {
        gets++;
        if (holdSavedRead) await savedReadGate;
      }
      json = { ok: true, servers: { fixture: { configured: true } }, readiness: { fixture: value() } };
    }
    if (url.pathname === "/api/mcp/servers/fixture/test") {
      posts++;
      state = posts === 1 ? "ready" : "failed";
      json = { run_id: "fixture-run", status: "queued" };
    }
    await route.fulfill({ json });
  });
  await page.goto(base);
  await page.getByRole("button", { name: "Open settings fixture" }).click();
  await page.getByRole("tab", { name: "MCP", exact: true }).filter({ visible: true }).click();
  await page.getByText("Saved · Verification unknown").waitFor();
  assert.equal(posts, 0, "Opening MCP Settings must not probe");
  assert.equal(gets, 1, "Opening MCP Settings must use one passive GET");
  await page.getByRole("button", { name: "Test", exact: true }).click();
  await page.getByText("Saved · Verified ready").waitFor();
  await page.getByText(/2 tools/).waitFor();
  assert.equal(posts, 1);
  await page.getByRole("button", { name: "Test", exact: true }).click();
  await page.getByText("Saved · Test failed").waitFor();
  await page.getByRole("alert").getByText(/Connection or discovery failed/).waitFor();
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  assert.equal(posts, 3);
  await page.getByPlaceholder("filesystem").fill("fixture");
  await page.locator("textarea").fill('{"command":"fixture"}');
  holdSavedRead = true;
  await page.getByRole("button", { name: "Save server", exact: true }).click();
  await page.getByText("Saved · Verification unknown").waitFor();
  assert.equal(posts, 3, "Saving must invalidate before its refresh returns, without probing");
  releaseSavedRead();
  assert(!(await page.locator("body").innerText()).includes("SYNTHETIC_SECRET"));
  console.log("SP23 MCP Settings: saved/unknown, explicit Test, verified tools/time, failed/Retry, save invalidation, no open/save probe passed");
} finally {
  releaseSavedRead();
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
