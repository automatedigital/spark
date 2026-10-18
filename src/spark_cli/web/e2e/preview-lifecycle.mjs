/** Exercise real React effects with controlled deferred preview responses. */
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, writeFile } from "node:fs/promises";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const output = await mkdtemp(path.join(os.tmpdir(), "spark-preview-lifecycle-"));
const port = await new Promise((resolve) => {
  const server = net.createServer();
  server.listen(0, "127.0.0.1", () => { const port = server.address().port; server.close(() => resolve(port)); });
});
const vite = spawn(path.join(web, "node_modules/.bin/vite"), [web, "--host", "127.0.0.1", "--port", String(port), "--strictPort"], { cwd: web, stdio: ["ignore", "pipe", "pipe"] });
let logs = "";
vite.stdout.on("data", (data) => { logs += data; });
vite.stderr.on("data", (data) => { logs += data; });
let browser;
try {
  const base = `http://127.0.0.1:${port}`;
  const deadline = Date.now() + 30000;
  while (true) {
    try { if ((await fetch(base)).ok) break; } catch { /* starting */ }
    if (Date.now() > deadline) throw new Error(logs);
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  page.setDefaultTimeout(5000);
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/__preview_lifecycle", (route) => route.fulfill({ contentType: "text/html", body: '<div id="root"></div><script type="module">import "/@vite/client"; import RefreshRuntime from "/@react-refresh"; RefreshRuntime.injectIntoGlobalHook(window); window.$RefreshReg$=()=>{}; window.$RefreshSig$=()=>type=>type; window.__vite_plugin_react_preamble_installed__=true;</script>' }));
  await page.goto(`${base}/__preview_lifecycle`);
  await page.evaluate(async () => {
    const { default: React } = await import("/node_modules/.vite/deps/react.js");
    const { default: { createRoot } } = await import("/node_modules/.vite/deps/react-dom_client.js");
    const { api } = await import("/src/lib/api.ts");
    const { WorkspacePreviewPanel } = await import("/src/components/workspace/WorkspacePreviewPanel.tsx");
    window.calls = []; window.streams = []; window.reads = []; window.frameStreams = []; window.frameRequests = 0;
    window.EventSource = class {
      constructor() { this.closed = false; window.frameStreams.push(this); }
      close() { this.closed = true; }
    };
    api.streamBrowserNavigate = async (slug, url) => { window.calls.push({ name: "navigate", slug }); return { url, title: "External" }; };
    api.streamBrowserViewport = async () => ({});
    api.streamBrowserTabs = async () => ({ tabs: [] });
    api.streamBrowserTakeoverState = async () => ({ paused: false });
    api.getWorkspacePreviewActionLog = async () => ({ actions: [] });
    api.streamBrowserConsole = async () => ({ entries: [] });
    api.streamBrowserFrameUrl = () => { window.frameRequests += 1; return "data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs="; };
    for (const name of ["detectDevServers", "getWorkspacePreviewStatus", "getWorkspacePreviewLogs"]) {
      api[name] = (slug, signal) => new Promise((resolve) => {
        window.calls.push({ name, slug }); window.reads.push({ name, slug, signal, resolve });
      });
    }
    api.streamWorkspacePreviewEvents = (slug) => {
      const source = { slug, closed: false, onmessage: null, close() { this.closed = true; } };
      window.streams.push(source); return source;
    };
    api.startWorkspacePreview = async (slug) => {
      window.calls.push({ name: "start", slug });
      return { slug, status: "running", url: "http://127.0.0.1:12345", logs: [] };
    };
    const root = createRoot(document.getElementById("root"));
    window.renderPreview = (slug, visible) => root.render(React.createElement(WorkspacePreviewPanel, { slug, visible }));
    window.renderPreview("project-a", false);
  });
  await page.waitForTimeout(100);
  assert.deepEqual(await page.evaluate(() => window.calls), [], "Initially hidden pane starts no requests");
  await page.evaluate(() => window.renderPreview("project-a", true));
  await page.waitForFunction(() => window.reads.length === 3 && window.streams.length === 1);
  await page.evaluate(() => window.renderPreview("project-a", false));
  await page.waitForFunction(() => window.reads.every((read) => read.signal.aborted) && window.streams.every((stream) => stream.closed));
  await page.evaluate(() => {
    for (const read of window.reads) read.resolve(read.name === "getWorkspacePreviewStatus" ? { slug: "project-a", status: "running", url: "http://127.0.0.1:12345/old" } : { logs: [], servers: [] });
    window.renderPreview("project-b", true);
  });
  await page.waitForFunction(() => window.reads.length === 6 && window.streams.length === 2);
  assert.equal(await page.getByTitle("Workspace browser").count(), 0, "Old response did not render iframe");
  await page.evaluate(() => window.streams[1].onmessage({ data: JSON.stringify({ type: "state", slug: "project-b", status: "running", url: "http://127.0.0.1:12345/current" }) }));
  await page.getByTitle("Workspace browser").waitFor({ state: "attached" });
  assert.equal(await page.getByTitle("Workspace browser").getAttribute("src"), "http://127.0.0.1:12345/current");
  assert.equal(await page.evaluate(() => window.streams.length), 2, "URL changes do not reconnect SSE");
  await page.evaluate(() => window.renderPreview("project-c", true));
  await page.waitForFunction(() => window.reads.length === 9 && window.streams.length === 3);
  assert.equal(await page.evaluate(() => window.reads.slice(0, 6).every((read) => read.signal.aborted)), true);
  assert.equal(await page.evaluate(() => window.streams.slice(0, 2).every((stream) => stream.closed)), true);
  assert.equal(await page.getByTitle("Workspace browser").count(), 0, "Switch resets project URL");
  await page.getByRole("button", { name: "Start App", exact: true }).click();
  await page.getByTitle("Workspace browser").waitFor({ state: "attached" });
  assert.equal(await page.evaluate(() => window.calls.filter((call) => call.name === "start").length), 1);
  await page.evaluate(() => window.renderPreview("project-c", false));
  await page.waitForFunction(() => window.reads.every((read) => read.signal.aborted));
  await page.evaluate(() => window.renderPreview("project-c", true));
  await page.waitForFunction(() => window.reads.length === 12 && window.streams.length === 4);
  await page.evaluate(() => window.streams[3].onmessage({ data: JSON.stringify({ type: "state", slug: "project-c", status: "running", url: "https://example.com" }) }));
  await page.waitForFunction(() => window.calls.filter((call) => call.name === "navigate").length === 1 && window.frameStreams.length === 1);
  await page.evaluate(() => window.renderPreview("project-c", false));
  await page.waitForFunction(() => window.frameStreams.every((stream) => stream.closed));
  const frameRequests = await page.evaluate(() => window.frameRequests);
  await page.waitForTimeout(650);
  assert.equal(await page.evaluate(() => window.frameRequests), frameRequests, "Hidden external fallback frame polling pauses");
  await page.evaluate(() => window.renderPreview("project-c", true));
  await page.waitForFunction(() => window.frameStreams.length === 2);
  await page.waitForTimeout(100);
  assert.equal(await page.evaluate(() => window.calls.filter((call) => call.name === "navigate").length), 1, "Reopen does not navigate/reset shared external browser");
  assert.deepEqual(errors, []);
  const result = { passed: true, checks: ["hidden: zero reads/SSE", "hide: abort/close", "late response fenced", "switch aborts and resets URL", "navigation retains SSE", "Start works", "reopen revalidates", "hidden external frame stream closes; reopen never re-navigates"] };
  await writeFile(path.join(output, "report.json"), JSON.stringify(result, null, 2));
  console.log(JSON.stringify({ ...result, output }));
} finally {
  if (browser) await browser.close();
  vite.kill("SIGTERM");
  await writeFile(path.join(output, "vite.log"), logs);
}
