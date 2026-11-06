import { spawn } from "node:child_process";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";
import { chromium } from "playwright";
const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repo = path.resolve(web, "../../..");
const python = process.env.PYTHON || path.join(repo, ".venv/bin/python");
const home = await mkdtemp(path.join(os.tmpdir(), "spark-terminal-e2e-"));
const port = () => new Promise((resolve) => { const s = net.createServer(); s.listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => resolve(p)); }); });
const apiPort = await port(), webPort = await port();
const processes = [];
const launch = (cmd, args, env) => {
  const p = spawn(cmd, args, { cwd: repo, env: { ...process.env, ...env }, stdio: ["ignore", "pipe", "pipe"] });
  let log = ""; p.stdout.on("data", (x) => { log += x; }); p.stderr.on("data", (x) => { log += x; });
  processes.push(p); return () => log;
};
async function until(fn, description) {
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) { try { if (await fn()) return; } catch {} await new Promise((r) => setTimeout(r, 100)); }
  throw new Error(`Timed out: ${description}`);
}
const alive = (pid) => { try { process.kill(pid, 0); return true; } catch { return false; } };
let browser;
const pids = [];
const began = Date.now();
try {
  for (const slug of ["alpha", "bravo"]) await mkdir(path.join(home, "workspace", slug), { recursive: true });
  await writeFile(path.join(home, "config.yaml"), "model:\n  default: test-model\n  provider: ollama\n");
  const backendLog = launch(python, ["-u", "-c", "from spark_cli.web_server import start_server; import sys; start_server('127.0.0.1', int(sys.argv[1]), False)", String(apiPort)], { HOME: home, SPARK_HOME: home, PYTHONPATH: path.join(repo, "src") });
  const viteLog = launch(path.join(web, "node_modules/.bin/vite"), [web, "--host", "127.0.0.1", "--port", String(webPort)], { SPARK_API_TARGET: `http://127.0.0.1:${apiPort}` });
  await until(async () => (await fetch(`http://127.0.0.1:${apiPort}/api/status`)).ok, "backend ready").catch((e) => { throw new Error(`${e}\n${backendLog()}`); });
  await until(async () => (await fetch(`http://127.0.0.1:${webPort}`)).ok, "Vite ready");
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  await page.goto(`http://127.0.0.1:${webPort}`);
  await page.getByText("Spark").first().waitFor();
  page.on("framenavigated", () => console.log("navigation", page.url()));
  page.on("pageerror", (error) => console.error("pageerror", error.message));
  await page.evaluate(async () => {
    const reactModule = await import("/node_modules/.vite/deps/react.js");
    const React = reactModule.default || reactModule;
    const clientModule = await import("/node_modules/.vite/deps/react-dom_client.js");
    const createRoot = clientModule.createRoot || clientModule.default.createRoot;
    const { WorkspaceTerminalPanel } = await import("/src/components/workspace/WorkspaceTerminalPanel.tsx");
    const { WebUIThemeProvider } = await import("/src/lib/theme.tsx");
    const { api } = await import("/src/lib/api.ts");
    const start = api.runWorkspaceTerminalCommand.bind(api);
    const stream = api.streamWorkspaceTerminalRun.bind(api);
    window.terminalFixture = { pending: [], streams: [], starts: 0, stops: [], stopResults: [] };
    const f = window.terminalFixture;
    const stop = api.stopWorkspaceTerminalRun.bind(api);
    api.stopWorkspaceTerminalRun = (slug, id) => { f.stops.push(id); return stop(slug, id).then((result) => { f.stopResults.push(result); return result; }); };
    api.runWorkspaceTerminalCommand = async (slug) => {
      f.starts++;
      const run = await start(slug);
      return new Promise((resolve) => f.pending.push({ slug, run, release: () => resolve(run) }));
    };
    api.streamWorkspaceTerminalRun = (slug, id) => { const s = stream(slug, id); f.streams.push(s); return s; };
    const host = document.createElement("div"); host.style.cssText = "height:400px;display:flex"; document.body.replaceChildren(host);
    let root = createRoot(host);
    f.mount = (slug) => root.render(React.createElement(WebUIThemeProvider, null, React.createElement(WorkspaceTerminalPanel, { slug })));
    f.unmount = () => { root.unmount(); root = createRoot(host); };
    f.mount("alpha");
  });
  const pending = async (n) => { await until(() => page.evaluate((n) => window.terminalFixture.pending.length >= n, n), `start ${n}`); return page.evaluate((n) => { const p = window.terminalFixture.pending[n - 1]; return { slug: p.slug, id: p.run.run_id }; }, n); };
  const marker = async ({ slug, id }, name) => {
    const file = path.join(home, "workspace", slug, `${name}.pid`);
    // The shell PID itself is a harmless process marker, no child workload.
    await until(async () => {
      const response = await fetch(`http://127.0.0.1:${apiPort}/api/workspace/projects/${slug}/terminal/runs/${id}/input`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ input: `echo $$ > ${name}.pid\n` }) });
      return response.ok;
    }, "shell input ready");
    await until(async () => Number(await readFile(file, "utf8")) > 0, "PID marker");
    const pid = Number(await readFile(file, "utf8")); pids.push(pid); assert(alive(pid)); return pid;
  };
  const release = (n) => page.evaluate((n) => window.terminalFixture.pending[n - 1].release(), n);
  const old = await pending(1), oldPid = await marker(old, "old");
  await page.evaluate(() => { window.terminalFixture.unmount(); window.terminalFixture.mount("bravo"); });
  const replacement = await pending(2), replacementPid = await marker(replacement, "replacement");
  await release(2); await release(1);
  if (process.env.TERMINAL_BASELINE) {
    await new Promise((r) => setTimeout(r, 1000));
    assert(alive(oldPid), "baseline should reproduce the orphan");
    console.log(JSON.stringify({ baseline: "late acknowledgement leaked shell", orphanPid: oldPid, replacementPid }));
  } else {
    await until(() => !alive(oldPid), "retired shell process cleanup").catch(async (error) => {
      console.error(JSON.stringify({ oldPid, replacementPid, stops: await page.evaluate(() => window.terminalFixture?.stops), stopResults: await page.evaluate(() => window.terminalFixture?.stopResults), oldRun: old.id, vite: viteLog(), backend: backendLog() }));
      throw error;
    });
    assert(alive(replacementPid), "replacement survives late ack");
    // Force stream failures through the real component; no start is allowed.
    for (let i = 0; i < 3; i++) {
      await until(() => page.evaluate((i) => window.terminalFixture.streams.length > i, i), "reattach stream");
      await page.evaluate((i) => window.terminalFixture.streams[i].onerror?.(new Event("error")), i);
    }
    await page.getByRole("button", { name: "Reconnect", exact: true }).waitFor();
    await page.getByRole("button", { name: "Reconnect", exact: true }).click();
    assert.equal(await page.evaluate(() => window.terminalFixture.starts), 2);
    assert(alive(replacementPid));
    // Two explicit restarts acknowledged backwards.
    await page.getByTitle("Kill & restart shell").click();
    const third = await pending(3), thirdPid = await marker(third, "third");
    await page.getByTitle("Kill & restart shell").click();
    const fourth = await pending(4), fourthPid = await marker(fourth, "fourth");
    await release(4); await release(3);
    await until(() => !alive(thirdPid) && !alive(replacementPid), "superseded restart cleanup");
    assert(alive(fourthPid));
    await page.evaluate(() => window.terminalFixture.unmount());
    await until(() => !alive(fourthPid), "close cleanup");
    const stops = await page.evaluate(() => window.terminalFixture.stops);
    assert.equal(stops.length, 4); assert.equal(new Set(stops).size, 4);
    console.log(JSON.stringify({ result: "passed", realShells: 4, survivingAfterClose: 0, stopRequests: stops.length, elapsedMs: Date.now() - began }));
  }
} finally {
  await browser?.close();
  for (const pid of pids) if (alive(pid)) { try { process.kill(-pid, "SIGKILL"); } catch {} }
  for (const p of processes) p.kill("SIGTERM");
  await rm(home, { recursive: true, force: true });
}
