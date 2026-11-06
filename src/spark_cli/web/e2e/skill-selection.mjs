// SP22: rendered Skills/PromptBar, real files/receipts, deterministic provider boundary.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, writeFile } from "node:fs/promises";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repo = path.resolve(web, "../../..");
const output = await mkdtemp(path.join(os.tmpdir(), "spark-sp22-browser-"));
const home = await mkdtemp(path.join(os.tmpdir(), "spark-sp22-home-"));
const env = { ...process.env, HOME: home, USERPROFILE: home, SPARK_HOME: home, PYTHONPATH: `${repo}/src:${repo}/tests/spark_cli` };
const freePort = () => new Promise((resolve) => {
  const server = net.createServer();
  server.listen(0, "127.0.0.1", () => { const port = server.address().port; server.close(() => resolve(port)); });
});
const apiPort = await freePort(), webPort = await freePort();
const api = `http://127.0.0.1:${apiPort}`, base = `http://127.0.0.1:${webPort}`;
const children = [], logs = [];
function start(command, args, cwd, extra = {}) {
  const child = spawn(command, args, { cwd, env: { ...env, ...extra }, stdio: ["ignore", "pipe", "pipe"] });
  child.stdout.on("data", (data) => logs.push(String(data)));
  child.stderr.on("data", (data) => logs.push(String(data)));
  children.push(child);
}
async function ready(url) {
  for (let i = 0; i < 100; i++) {
    try { if ((await fetch(url)).ok) return; } catch { /* wait for fixture server */ }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Server unavailable: ${url}`);
}
let browser;
try {
  start(process.env.PYTHON || "python", ["-m", "uvicorn", "skill_selection_fixture:app", "--host", "127.0.0.1", "--port", String(apiPort)], repo);
  start(process.execPath, ["node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", String(webPort)], web, { SPARK_API_TARGET: api });
  await Promise.all([ready(`${api}/api/status`), ready(base)]);
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 980 } });
  page.setDefaultTimeout(20_000);
  const submissions = [];
  page.on("request", (request) => { if (request.method() === "POST" && /conversations.*messages/.test(request.url())) submissions.push({ url: request.url(), body: request.postDataJSON() }); });
  await page.goto(`${base}/e2e/fixtures/skill-selection.html`);
  const composer = page.locator("textarea");
  await composer.fill("ALPHA_UNSENT");
  await page.getByRole("button", { name: "bravo", exact: true }).click();
  await composer.fill("BRAVO_UNSENT");
  await page.getByRole("button", { name: "Add fixture attachment" }).click();
  const started = performance.now();
  await page.getByRole("button", { name: "Browse skills" }).click();
  await page.getByRole("button", { name: "View indexed-0999", exact: true }).waitFor();
  const listReadyMs = performance.now() - started;
  const projectRead = page.waitForResponse((response) => response.url().includes("/api/skills/index") && response.url().includes("workspace_slug=project"));
  await page.getByRole("combobox", { name: "Skill target thread" }).selectOption("1");
  const metadata = await (await projectRead).json();
  assert.equal(metadata.length, 1002);
  assert.ok(metadata.every((row) => !("content" in row) && !("supporting_files" in row)));

  await page.getByRole("combobox", { name: "Skill scope", exact: true }).selectOption("project");
  await page.getByRole("button", { name: "View collision", exact: true }).click();
  await page.getByText("PROJECT_BODY", { exact: false }).waitFor();
  await page.getByRole("button", { name: "Use on next turn", exact: true }).click();
  assert.equal(submissions.length, 0);
  await page.screenshot({ path: path.join(output, "selected.png") });
  await page.getByRole("button", { name: "Close skill details", exact: true }).click();
  await page.getByRole("button", { name: "alpha", exact: true }).click();
  assert.equal(await composer.inputValue(), "ALPHA_UNSENT");
  assert.equal(await page.getByText("Skill: collision", { exact: true }).count(), 0);
  await page.getByRole("button", { name: "bravo", exact: true }).click();
  assert.equal(await composer.inputValue(), "BRAVO_UNSENT");
  await page.getByText("Skill: collision", { exact: true }).waitFor();
  await page.getByText("fixture.txt", { exact: true }).waitFor();
  // Refresh recovers the existing draft; there is no automatic submission.
  await page.reload();
  await page.getByRole("button", { name: "bravo", exact: true }).click();
  await page.getByText("Skill: collision", { exact: true }).waitFor();
  assert.equal(await composer.inputValue(), "BRAVO_UNSENT");
  assert.equal(submissions.length, 0);
  await composer.press("Enter");
  await page.locator("output").filter({ hasText: "Accepted" }).waitFor();
  const sent = submissions[0];
  assert.equal(sent.body.context_items.filter((item) => item.type === "skill").length, 1);
  const replay = await page.request.post(sent.url, { data: sent.body });
  assert.equal(replay.status(), 200);
  let evidence;
  const deadline = Date.now() + 20_000;
  do {
    evidence = await (await fetch(`${api}/fixture/captures`)).json();
    if (evidence.captures.length) break;
    await new Promise((resolve) => setTimeout(resolve, 100));
  } while (Date.now() < deadline);
  assert.equal(evidence.captures.length, 1, "one real provider-boundary invocation after explicit submit and replay");
  assert.equal(evidence.captures[0].thread, "bravo");
  assert.equal(evidence.captures[0].message.split("PROJECT_BODY").length - 1, 1);
  assert.ok(evidence.captures[0].message.includes("BRAVO_UNSENT"));
  assert.ok(!evidence.captures[0].message.includes("PROFILE_BODY"));
  assert.equal(evidence.setup_ran, false);
  assert.equal(await page.getByText("Skill: collision", { exact: true }).count(), 0);
  const benchmark = {};
  for (const [label, route] of [["baseline", "/fixture/baseline"], ["metadata", "/api/skills/index"]]) {
    const startTime = performance.now();
    const text = await (await fetch(api + route)).text();
    benchmark[label] = { milliseconds: performance.now() - startTime, bytes: Buffer.byteLength(text), rows: JSON.parse(text).length };
  }
  const baselinePage = await browser.newPage({ viewport: { width: 1440, height: 980 } });
  await baselinePage.route("**/api/skills/index*", async (route) => route.fulfill({ response: await baselinePage.request.get(`${api}/fixture/baseline`) }));
  await baselinePage.goto(`${base}/e2e/fixtures/skill-selection.html`);
  await baselinePage.locator("textarea").waitFor();
  const baselineStart = performance.now();
  await baselinePage.getByRole("button", { name: "Browse skills" }).click();
  await baselinePage.getByRole("button", { name: "View indexed-0999", exact: true }).waitFor();
  const baselineListReadyMs = performance.now() - baselineStart;
  await baselinePage.close();
  await writeFile(path.join(output, "evidence.json"), JSON.stringify({ listReadyMs, baselineListReadyMs, benchmark, ...evidence }, null, 2));
  console.log(JSON.stringify({ output, listReadyMs, baselineListReadyMs, benchmark, captures: evidence.captures.length, setupRan: evidence.setup_ran }));
} catch (error) {
  console.error(logs.join("").slice(-8000));
  throw error;
} finally {
  await browser?.close();
  for (const child of children) child.kill("SIGTERM");
}
