import { spawn } from "node:child_process";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const webRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const repoRoot = path.resolve(webRoot, "../../..");
const python = process.env.PYTHON || path.join(repoRoot, ".venv/bin/python");
const port = () =>
  new Promise((resolve) => {
    const s = net.createServer();
    s.listen(0, "127.0.0.1", () => {
      const p = s.address().port;
      s.close(() => resolve(p));
    });
  });
const wait = async (url) => {
  for (let i = 0; i < 180; i++) {
    try {
      const r = await fetch(url);
      if (r.ok) return;
    } catch {}
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(`Timed out: ${url}`);
};
const start = (cmd, args, opts) => {
  const child = spawn(cmd, args, {
    ...opts,
    stdio: ["ignore", "pipe", "pipe"],
  });
  child.stdout.on("data", (b) => {
    if (process.env.E2E_VERBOSE) process.stderr.write(b);
  });
  child.stderr.on("data", (b) => {
    if (process.env.E2E_VERBOSE) process.stderr.write(b);
  });
  return child;
};
const stop = async (p) => {
  if (!p || p.exitCode !== null) return;
  p.kill("SIGTERM");
  await new Promise((r) => setTimeout(r, 700));
  if (p.exitCode === null) p.kill("SIGKILL");
};
// Provider replay only: no live model calls or user profile access.
const apiPort = await port();
const webPort = await port();
const home = await mkdtemp(path.join(os.tmpdir(), "spark-root-submissions-"));
await mkdir(path.join(home, "workspace"), { recursive: true });
await writeFile(path.join(home, "config.yaml"), "model:\n  default: replay\n  provider: ollama\n");
const backend = start(python, ["-c", `
from types import SimpleNamespace
import spark_cli.web_server as w
w._new_web_agent = lambda **kw: SimpleNamespace(session_id=kw["session_id"])
w._get_web_cached_agent = lambda *a: None
w._run_web_agent_turn = lambda *a, **kw: {"final_response": "SP01 replay answer"}
w._maybe_auto_title_web = lambda *a, **kw: None
w.start_server(host="127.0.0.1", port=${apiPort}, open_browser=False)
`], { cwd: repoRoot, env: { ...process.env, SPARK_HOME: home, PYTHONPATH: path.join(repoRoot, "src") } });
const vite = start("npm", ["run", "dev", "--", "--host", "127.0.0.1", "--port", String(webPort)], {
  cwd: webRoot, env: { ...process.env, SPARK_API_TARGET: `http://127.0.0.1:${apiPort}` },
});
let browser;
let page;
try {
  await wait(`http://127.0.0.1:${apiPort}/api/status`);
  await wait(`http://127.0.0.1:${webPort}`);
  browser = await chromium.launch({ headless: true });
  page = await browser.newPage();
  const submissions = [];
  let dropped = false;
  await page.route(/\/api\/conversations(?:\/[^/]+\/messages)?$/, async route => {
    if (route.request().method() !== "POST") return route.continue();
    submissions.push(route.request().postDataJSON());
    const response = await route.fetch();
    if (!dropped) { dropped = true; await route.abort("failed"); }
    else await route.fulfill({ response });
  });
  await page.goto(`http://127.0.0.1:${webPort}`);
  const composer = page.locator("textarea").last();
  await composer.fill("SP01 lost response prompt");
  await composer.press("Enter");
  await page.getByText(/Could not confirm submission|Failed to fetch|Load failed|fetch failed|NetworkError/i).first().waitFor();
  if (await composer.inputValue() !== "SP01 lost response prompt") throw new Error("Origin draft lost");
  await page.reload();
  await page.waitForFunction(() => [...document.querySelectorAll("textarea")].some(el => el.value === "SP01 lost response prompt"));
  await composer.press("Enter");
  await page.waitForFunction(() => [...document.querySelectorAll("textarea")].some(el => el.value === ""));
  if (submissions.length !== 2 || !submissions[0].submission_id || submissions[0].submission_id !== submissions[1].submission_id) throw new Error("Retry changed submission ID");
  const accepted = await page.request.post(`http://127.0.0.1:${apiPort}/api/conversations`, { data: submissions[1] });
  const receipt = await accepted.json();
  const messages = await page.request.get(`http://127.0.0.1:${apiPort}/api/sessions/${receipt.session_id}/messages`);
  const history = await messages.json();
  if (history.messages.filter(m => m.role === "user").length !== 1 || history.messages.filter(m => m.role === "assistant").length !== 1) throw new Error(`Duplicated history: ${JSON.stringify(history)}`);
  console.log(JSON.stringify({ submissions: submissions.length, sameID: true, receipt, historyStatus: messages.status() }));
  await page.reload();
  await page.getByRole("button", { name: /SP01 lost response prompt/ }).first().click();
  await page.getByText("SP01 replay answer", { exact: true }).first().waitFor();
  dropped = false;
  submissions.length = 0;
  await composer.fill("SP01 follow-up lost response");
  await composer.press("Enter");
  await page.getByText(/Could not confirm submission|Failed to fetch|Load failed|fetch failed|NetworkError/i).first().waitFor();
  if (await composer.inputValue() !== "SP01 follow-up lost response") throw new Error("Follow-up draft lost");
  await composer.press("Enter");
  await page.waitForFunction(() => [...document.querySelectorAll("textarea")].some(el => el.value === ""));
  if (submissions.length !== 2 || submissions[0].submission_id !== submissions[1].submission_id) throw new Error("Follow-up retry changed ID");
  const followupHistory = await (await page.request.get(`http://127.0.0.1:${apiPort}/api/sessions/${receipt.session_id}/messages`)).json();
  if (followupHistory.messages.filter(m => m.role === "user").length !== 2 || followupHistory.messages.filter(m => m.role === "assistant").length !== 2) throw new Error(`Duplicated follow-up: ${JSON.stringify(followupHistory)}`);
  await page.getByText("SP01 follow-up lost response", { exact: true }).first().waitFor();
  console.log("PASS: create and follow-up lost responses, same draft retries, acknowledgement, persisted output, refresh recovery");
} catch (error) {
  console.error(await page?.locator("body").innerText());
  await page?.screenshot({ path: "/tmp/sp01-browser-failure.png" });
  throw error;
} finally {
  await browser?.close();
  await stop(vite);
  await stop(backend);
  if (!process.env.SPARK_E2E_KEEP_HOME) await rm(home, { recursive: true, force: true });
}
