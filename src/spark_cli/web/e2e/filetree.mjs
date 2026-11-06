/** SP20: matched browser fixture. No live profile, provider or account. */
import assert from "node:assert/strict";
import { spawn, execFileSync } from "node:child_process";
import { mkdtemp, writeFile, rm } from "node:fs/promises";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const baselinePath = path.join(web, "e2e/.sp20-baseline.tsx");
const baseCommit = "a12205a5737d7539875d6af16b3bb58c194e8edb";
await writeFile(baselinePath, execFileSync("git", ["show", `${baseCommit}:src/spark_cli/web/src/components/workspace/FileTreePane.tsx`], { cwd: web }));
const output = await mkdtemp(path.join(os.tmpdir(), "spark-sp20-browser-"));
const port = await new Promise(resolve => {
  const server = net.createServer();
  server.listen(0, "127.0.0.1", () => { const value = server.address().port; server.close(() => resolve(value)); });
});
const vite = spawn(path.join(web, "node_modules/.bin/vite"), [web, "--host", "127.0.0.1", "--port", String(port), "--strictPort"], { cwd: web, stdio: ["ignore", "pipe", "pipe"] });
let logs = "";
vite.stdout.on("data", data => { logs += data; });
vite.stderr.on("data", data => { logs += data; });
let browser;
const dirs = Array.from({ length: 100 }, (_, i) => {
  const name = `folder-${String(i).padStart(3, "0")}`;
  return { name, path: name, type: "dir", children: Array.from({ length: 1000 }, (_, j) => ({ name: `file-${String(j).padStart(4, "0")}.txt`, path: `${name}/file-${String(j).padStart(4, "0")}.txt`, type: "file" })) };
});
let requests = [];
let delayed = false;
let added = false;
let rootFiles = [];
const mutations = [];
try {
  const base = `http://127.0.0.1:${port}`;
  const deadline = Date.now() + 30000;
  while (true) {
    try { if ((await fetch(base)).ok) break; } catch { /* Vite starting */ }
    if (Date.now() > deadline) throw new Error(logs);
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  page.setDefaultTimeout(10000);
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("**/__sp20", route => route.fulfill({ contentType: "text/html", body: '<div id="root"></div><script type="module">import "/@vite/client"; import RefreshRuntime from "/@react-refresh"; RefreshRuntime.injectIntoGlobalHook(window); window.$RefreshReg$=()=>{}; window.$RefreshSig$=()=>type=>type; window.__vite_plugin_react_preamble_installed__=true;</script>' }));
  await page.route("**/api/workspace/projects/**", async route => {
    const url = new URL(route.request().url());
    const slug = url.pathname.split("/")[4];
    if (route.request().method() !== "GET") {
      const request = route.request();
      mutations.push({ method: request.method(), path: url.pathname, query: url.search });
      const file = url.searchParams.get("path");
      if (request.method() === "DELETE") rootFiles = rootFiles.filter(node => node.path !== file);
      else if (url.pathname.endsWith("/rename")) {
        const { src, dst } = request.postDataJSON();
        rootFiles = rootFiles.map(node => node.path === src ? { ...node, name: dst, path: dst } : node);
      } else if (url.pathname.endsWith("/upload")) rootFiles.push({ name: "uploaded.txt", path: "uploaded.txt", type: "file" });
      else rootFiles.push({ name: file, path: file, type: url.pathname.endsWith("/mkdir") ? "dir" : "file" });
      await route.fulfill({ contentType: "application/json", body: '{"ok":true,"saved":[]}' });
      return;
    }
    let response;
    if (url.pathname.endsWith("/tree")) response = { slug, tree: dirs };
    else {
      const directory = url.searchParams.get("path") || "";
      const start = Number(url.searchParams.get("cursor") || 0);
      const entries = slug === "replacement" ? [{ name: "replacement.txt", path: "replacement.txt", type: "file" }]
        : directory ? [...(dirs.find(dir => dir.path === directory)?.children || []), ...(added && directory === "folder-000" ? [{ name: "new.txt", path: "folder-000/new.txt", type: "file" }] : [])]
        : [...dirs.map(({ children: _children, ...entry }) => entry), ...rootFiles];
      response = { path: directory, revision: String(added), entries: entries.slice(start, start + 200), next_cursor: start + 200 < entries.length ? String(start + 200) : null };
    }
    const body = JSON.stringify(response);
    requests.push({ path: url.pathname, directory: url.searchParams.get("path"), bytes: Buffer.byteLength(body), entries: response.entries?.length });
    if (delayed && slug === "old") await new Promise(resolve => setTimeout(resolve, 400));
    await route.fulfill({ contentType: "application/json", body }).catch(() => {});
  });
  await page.goto(`${base}/__sp20`);
  await page.evaluate(async () => {
    const { default: React } = await import("/node_modules/.vite/deps/react.js");
    const { default: { createRoot } } = await import("/node_modules/.vite/deps/react-dom_client.js");
    const { FileTreePane } = await import("/src/components/workspace/FileTreePane.tsx");
    const { FileTreePane: Baseline } = await import("/e2e/.sp20-baseline.tsx");
    window.EventSource = class { close() {} };
    const root = createRoot(document.getElementById("root"));
    let key = 0;
    window.opened = [];
    window.streamTicks = [0, 0];
    window.frameDeltas = [];
    let lastFrame = performance.now();
    const frame = now => { window.frameDeltas.push(now - lastFrame); lastFrame = now; requestAnimationFrame(frame); };
    requestAnimationFrame(frame);
    function Streams() {
      const [ticks, setTicks] = React.useState([0, 0]);
      React.useEffect(() => {
        const timers = [0, 1].map(index => setInterval(() => setTicks(previous => {
          const next = [...previous]; next[index]++; window.streamTicks = next; return next;
        }), 20));
        return () => timers.forEach(clearInterval);
      }, []);
      return React.createElement("div", { id: "streams" }, ticks.map((tick, index) => React.createElement("span", { key: index }, `${index}:${tick} `)));
    }
    window.renderTree = (mode, slug = "fixture", retain = false) => {
      localStorage.clear();
      if (!retain) key++;
      root.render(React.createElement(React.Fragment, null, React.createElement(Streams), React.createElement(mode === "baseline" ? Baseline : FileTreePane, { key, slug, activePath: null, onOpenFile: node => window.opened.push(node.path) })));
    };
  });
  const metrics = {};
  for (const mode of ["baseline", "candidate"]) {
    const samples = [];
    for (let i = 0; i < 10; i++) {
      requests = [];
      const start = performance.now();
      await page.evaluate(mode => window.renderTree(mode), mode);
      await page.getByText("folder-099", { exact: true }).waitFor();
      samples.push({ ms: performance.now() - start, bytes: requests.reduce((n, request) => n + request.bytes, 0), requests: requests.length });
      assert.equal(requests.length, 1);
      if (mode === "candidate") assert(requests[0].entries <= 200);
    }
    metrics[mode] = { samples, p95_ms: [...samples].sort((a, b) => a.ms - b.ms)[9].ms };
  }
  requests = [];
  await page.evaluate(() => { window.frameDeltas = []; window.streamTicks = [0, 0]; });
  await page.getByText("folder-000", { exact: true }).click();
  await page.getByText("file-0199.txt", { exact: true }).waitFor();
  assert.equal(requests.length, 1);
  for (let i = 0; i < 4; i++) {
    await page.getByRole("button", { name: "Load more in folder-000" }).click();
    await page.getByText(`file-${String((i + 2) * 200 - 1).padStart(4, "0")}.txt`, { exact: true }).waitFor();
  }
  await page.getByText("file-0999.txt", { exact: true }).click();
  assert.deepEqual(await page.evaluate(() => window.opened), ["folder-000/file-0999.txt"]);
  added = true;
  await page.getByTitle("Refresh", { exact: true }).click();
  await page.getByText("file-0999.txt", { exact: true }).waitFor({ state: "detached" });
  await page.getByRole("button", { name: "Load more in folder-000" }).waitFor();
  for (let i = 0; i < 5; i++) {
    await page.getByRole("button", { name: "Load more in folder-000" }).click();
    await page.getByText(i === 4 ? "new.txt" : `file-${String((i + 2) * 200 - 1).padStart(4, "0")}.txt`, { exact: true }).waitFor();
  }
  await page.getByPlaceholder("Filter files…").fill("folder-099/file-0999");
  for (let i = 0; i < 30; i++) {
    await Promise.race([page.getByRole("button", { name: "Continue search" }).waitFor(), page.getByText("file-0999.txt", { exact: true }).waitFor()]);
    if (await page.getByText("file-0999.txt", { exact: true }).count()) break;
    await page.getByRole("button", { name: "Continue search" }).click();
  }
  await page.getByText("file-0999.txt", { exact: true }).waitFor();
  await page.getByTitle("Clear", { exact: true }).click();
  await page.getByTitle("New file", { exact: true }).click();
  await page.getByPlaceholder("path/to/file.txt").fill("created.txt");
  await page.getByPlaceholder("path/to/file.txt").press("Enter");
  await page.getByText("created.txt", { exact: true }).waitFor();
  const row = page.getByText("created.txt", { exact: true }).locator("..");
  await row.hover();
  await row.getByTitle("Rename", { exact: true }).click();
  await page.locator("input.font-mono-ui").fill("renamed.txt");
  await page.locator("input.font-mono-ui").press("Enter");
  const renamed = page.getByText("renamed.txt", { exact: true }).locator("..");
  await renamed.hover();
  await renamed.getByTitle("Delete", { exact: true }).click();
  await renamed.getByTitle("Confirm delete", { exact: true }).click();
  await page.getByText("renamed.txt", { exact: true }).waitFor({ state: "detached" });
  await page.locator('input[type="file"]').setInputFiles({ name: "uploaded.txt", mimeType: "text/plain", buffer: Buffer.from("fixture") });
  await page.getByText("uploaded.txt", { exact: true }).waitFor();
  await page.getByTitle("New folder", { exact: true }).click();
  await page.getByPlaceholder("path/to/folder").fill("created-folder");
  await page.getByPlaceholder("path/to/folder").press("Enter");
  const folderRow = page.getByText("created-folder", { exact: true }).locator("..");
  await folderRow.click();
  await folderRow.locator("..").getByText("empty", { exact: true }).waitFor();
  requests = [];
  await folderRow.hover();
  await folderRow.getByTitle("Delete", { exact: true }).click();
  await folderRow.getByTitle("Confirm delete", { exact: true }).click();
  await page.getByText("created-folder", { exact: true }).waitFor({ state: "detached" });
  assert(!requests.some(request => request.directory === "created-folder"), "Deleted folder must not be refetched");
  assert.equal(mutations.length, 6);
  metrics.twoSimulatedReactStreams = await page.evaluate(() => {
    const samples = window.frameDeltas.slice().sort((a, b) => a - b);
    return { ticks: window.streamTicks, frames: samples.length, p95_frame_ms: samples[Math.ceil(samples.length * .95) - 1], max_frame_ms: samples.at(-1) };
  });
  assert(metrics.twoSimulatedReactStreams.ticks.every(count => count > 5));
  assert(metrics.twoSimulatedReactStreams.p95_frame_ms < 100);
  delayed = true;
  await page.evaluate(() => window.renderTree("candidate", "old"));
  await page.waitForRequest("**/projects/old/list?*");
  await page.evaluate(() => window.renderTree("candidate", "replacement", true));
  await page.getByText("replacement.txt", { exact: true }).waitFor();
  await page.waitForTimeout(500);
  assert.equal(await page.getByText("folder-000", { exact: true }).count(), 0);
  assert.deepEqual(errors, []);
  await writeFile(path.join(output, "metrics.json"), JSON.stringify(metrics, null, 2));
  console.log(JSON.stringify({ output, metrics, passed: "100k matched initial read, expansion, all pages, selection, refresh, search continuation, stale project fencing" }));
} finally {
  await browser?.close();
  vite.kill("SIGTERM");
  await rm(baselinePath, { force: true });
}
