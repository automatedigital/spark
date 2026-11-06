// Real routes + SQLite/Markdown persistence; only failure injection uses interception.
// SP21_SOURCE_WEB allows the same built fixture to measure the committed baseline.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createServer } from "node:net";
import { mkdtemp, readFile, writeFile, realpath } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "vite";
import { chromium } from "playwright";
const here = path.dirname(fileURLToPath(import.meta.url));
const web = await realpath(process.env.SP21_SOURCE_WEB || path.resolve(here, ".."));
const output = await mkdtemp(path.join(tmpdir(), "spark-sp21-built-"));
const home = await mkdtemp(path.join(tmpdir(), "spark-sp21-profile-"));
await build({ root: web, configFile: path.join(web, "vite.config.ts"), logLevel: "warn", build: {
  outDir: output, emptyOutDir: true, rollupOptions: { input: path.join(web, "e2e/memory-review-fixture.html") },
} });
const probe = createServer();
await new Promise(resolve => probe.listen(0, "127.0.0.1", resolve));
const port = probe.address().port;
await new Promise(resolve => probe.close(resolve));
const server = spawn(process.env.PYTHON || "python", [path.join(here, "memory-review-backend.py")], {
  env: { ...process.env, SPARK_HOME: home, SP21_BUILT: output, SP21_PORT: String(port) }, stdio: ["ignore", "pipe", "pipe"],
});
let logs = "";
server.stdout.on("data", data => { logs += data; });
server.stderr.on("data", data => { logs += data; });
const base = `http://127.0.0.1:${port}`;
let browser;
try {
  for (let i = 0; i < 160; i++) {
    try { if ((await fetch(`${base}/api/memory`)).ok) break; } catch { /* bounded readiness */ }
    if (i === 159) throw new Error(`Backend readiness: ${logs}`);
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
  const reads = [];
  const responses = [];
  page.on("response", response => {
    if (response.request().method() === "GET" && new URL(response.url()).pathname.startsWith("/api/memory")) {
      responses.push(response.body().then(body => reads.push({ path: new URL(response.url()).pathname, bytes: body.length })));
    }
  });
  await page.goto(`${base}/e2e/memory-review-fixture.html`);
  await page.getByText("Original project fact", { exact: true }).waitFor();
  await page.getByText("Prefers concise answers", { exact: true }).waitFor();
  if (!process.env.SP21_BASELINE) await page.getByRole("button", { name: "2026-11-06-explicit.md", exact: true }).waitFor();
  await Promise.all(responses);
  const initial = [...reads];
  console.log(JSON.stringify({ initialReads: initial, count: initial.length, bytes: initial.reduce((sum, row) => sum + row.bytes, 0) }));
  if (process.env.SP21_BASELINE) {
    assert.equal(initial.filter(row => row.path === "/api/memory").length, 2);
  } else {
    assert.equal(initial.filter(row => row.path === "/api/memory").length, 1);
    assert.equal(initial.length, 3);
    await page.getByTitle("Edit", { exact: true }).first().click();
    await page.locator("textarea").fill("Updated project fact");
    await page.route("**/api/memory/memory/replace", route => route.fulfill({ status: 503, json: { detail: "Synthetic save unavailable" } }), { times: 1 });
    await page.getByTitle("Save", { exact: true }).click();
    await page.getByRole("alert").filter({ hasText: "503" }).waitFor();
    assert.equal(await page.locator("textarea").inputValue(), "Updated project fact");
    await page.getByTitle("Save", { exact: true }).click();
    await page.getByText("Updated project fact", { exact: true }).waitFor();
    assert.match(await readFile(path.join(home, "memories/MEMORY.md"), "utf8"), /Updated project fact/);
    await page.getByPlaceholder("Add an entry…").first().fill("Unsent draft");
    await page.route("**/api/memory", route => route.fulfill({ status: 503, json: { detail: "Synthetic read unavailable" } }), { times: 1 });
    await page.getByRole("button", { name: "Refresh Markdown", exact: true }).click();
    await page.getByRole("alert").filter({ hasText: "Synthetic read unavailable" }).waitFor();
    assert.equal(await page.getByPlaceholder("Add an entry…").first().inputValue(), "Unsent draft");
    await page.getByRole("button", { name: "Retry read", exact: true }).click();
    await page.getByRole("alert").waitFor({ state: "hidden" });
    await page.getByLabel("Search local facts").fill("telescope");
    await page.getByRole("button", { name: "Search", exact: true }).click();
    await page.locator("details summary").first().waitFor();
    assert.equal(await page.locator("details").count(), 20);
    await page.locator("details summary").first().click();
    await page.getByText(/Source: unknown · Category: project/).first().waitFor();
    await page.getByRole("button", { name: "Next facts", exact: true }).click();
    await page.locator("details summary").filter({ hasText: "Local fact 21 telescope" }).waitFor();
    await page.getByRole("button", { name: "2026-11-06-explicit.md", exact: true }).click();
    await page.getByRole("article", { name: "Dream review" }).getByText(/Human review required/).waitFor();
    assert.equal(await page.evaluate(() => window.memoryXss), undefined);
    assert.equal(await page.getByPlaceholder("Add an entry…").first().inputValue(), "Unsent draft");
    await page.screenshot({ path: "/tmp/sp21-memory-browser.png", fullPage: true });
    await writeFile("/tmp/sp21-memory-browser.json", JSON.stringify({ initial, output, home, passed: ["failed save preserves draft and retry persists", "bounded literal fact search and pagination", "unknown provenance", "real Dream file", "safe text rendering"] }, null, 2));
    console.log("PASS SP21 built browser: one Markdown read, failed-save retry, real local fact pagination and Dream review, safe rendering");
  }
} finally { await browser?.close(); server.kill("SIGTERM"); }
