// Provider-free F01 path through the real ChatPanel, SQLite and replay stream backend.
import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repo = path.resolve(web, "../../..");
const python = process.env.PYTHON || path.join(repo, ".venv/bin/python");
const output = process.env.COMPOSER_HISTORY_OUTPUT || await mkdtemp(path.join(os.tmpdir(), "spark-f01-proof-"));
const home = await mkdtemp(path.join(os.tmpdir(), "spark-f01-home-"));
await mkdir(output, { recursive: true });
await writeFile(path.join(home, "config.yaml"), "model:\n  default: fixture\n  provider: openai\n  base_url: http://127.0.0.1:1/v1\n");
const env = { ...process.env, HOME: home, USERPROFILE: home, SPARK_HOME: home, PYTHONPATH: path.join(repo, "src"), SPARK_WEB_FAKE_STREAMS: "1" };
const logs = [], children = [], checks = [], errors = [], sent = [];
const wait = async (test, label) => {
  for (let i = 0; i < 600; i++) {
    if (await test()) return;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Timed out: ${label}`);
};
const freePort = () => new Promise((resolve) => {
  const server = net.createServer();
  server.listen(0, "127.0.0.1", () => { const port = server.address().port; server.close(() => resolve(port)); });
});
const start = (command, args, cwd, extra = {}) => {
  const child = spawn(command, args, { cwd, env: { ...env, ...extra }, detached: true, stdio: ["ignore", "pipe", "pipe"] });
  children.push(child);
  for (const stream of [child.stdout, child.stderr]) stream.on("data", (data) => logs.push(data.toString()));
};
const seed = spawnSync(python, ["-c", `
from core.spark_state import SessionDB
db = SessionDB()
for sid, title in [("f01_a", "Recall Alpha"), ("f01_b", "Recall Beta")]:
    db.create_session(sid, "e2e", model="fixture")
    db.set_session_title(sid, title)
    db.append_message(sid, "user", content=title + " first\\nsecond line")
    db.append_message(sid, "assistant", content="ASSISTANT_ONLY_CONTEXT")
    db.append_message(sid, "user", content=title + " latest")
db.close()
`], { cwd: repo, env, encoding: "utf8" });
assert.equal(seed.status, 0, seed.stderr);
const apiPort = await freePort(), webPort = await freePort();
const api = `http://127.0.0.1:${apiPort}`, base = `http://127.0.0.1:${webPort}`;
start(python, ["-c", `from spark_cli.web_server import start_server; start_server('127.0.0.1', ${apiPort}, False)`], repo);
start(process.execPath, ["node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", String(webPort)], web, { SPARK_API_TARGET: api });
let browser, failure;
try {
  await wait(async () => { try { return (await fetch(`${api}/api/status`)).ok; } catch { return false; } }, "backend");
  await wait(async () => { try { return (await fetch(base)).ok; } catch { return false; } }, "frontend");
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  page.on("pageerror", (error) => errors.push(String(error)));
  // Intercept the provider boundary only. Acceptance and streaming use the real replay backend.
  await page.route("**/api/conversations/*/messages", async (route) => {
    const sid = new URL(route.request().url()).pathname.split("/")[3];
    const body = route.request().postDataJSON();
    sent.push({ sid, ...body });
    const response = await fetch(`${api}/api/dev/fake-streams`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({
      session_id: sid, title: "Recall Alpha", message: body.message,
      events: [{ type: "token", text: "REPLAY_RECALL_OK", delay_ms: 500 }],
    }) });
    assert.ok(response.ok, await response.clone().text());
    await route.fulfill({ json: await response.json() });
  });
  const panel = page.getByTestId("chat-panel");
  const input = panel.locator("textarea").last();
  const open = async (id, title) => {
    await page.getByRole("button", { name: new RegExp(title) }).first().click();
    await page.waitForFunction((sid) => document.querySelector('[data-testid="chat-panel"]')?.getAttribute("data-session-id") === sid, id);
    await wait(() => input.isEnabled(), "draft ready");
    await wait(() => panel.getByRole("button", { name: "Loaded prompt history", exact: true }).isEnabled(), "loaded history");
  };
  const value = async (text) => wait(async () => (await input.inputValue()) === text, `input ${text}`);
  const caret = (start, end = start) => input.evaluate((el, [a, b]) => { el.focus(); el.setSelectionRange(a, b); }, [start, end]);
  await page.goto(base);
  await open("f01_a", "Recall Alpha");
  await input.press("ArrowUp"); await value("Recall Alpha latest");
  assert.equal(sent.length, 0);
  await caret(0); await input.press("ArrowUp"); await value("Recall Alpha first\nsecond line");
  await caret(4); await input.press("ArrowUp"); await value("Recall Alpha first\nsecond line");
  await caret(0, 4); await input.press("ArrowDown"); await value("Recall Alpha first\nsecond line");
  await caret(0); await input.press("Shift+ArrowUp"); await value("Recall Alpha first\nsecond line");
  checks.push("empty Up recalls newest; Up at start steps older; multiline/selection/modifier guards preserve input; no send");
  await input.fill("unsent draft\nkeep me");
  await panel.getByRole("button", { name: "Restore draft", exact: true }).click(); await value("");
  await input.fill("unsent draft\nkeep me");
  await panel.getByRole("button", { name: "Loaded prompt history", exact: true }).click();
  const dialog = panel.getByRole("dialog", { name: "Loaded prompt history" });
  await wait(() => dialog.getByRole("button", { name: "Recall Alpha latest", exact: true }).evaluate((el) => el === document.activeElement), "picker keyboard focus");
  await page.keyboard.press("Escape");
  assert.equal(await dialog.count(), 0);
  await panel.getByRole("button", { name: "Loaded prompt history", exact: true }).click();
  await page.screenshot({ path: path.join(output, "history-picker.png") });
  assert.equal(await dialog.getByRole("button").count(), 3);
  assert.equal(await dialog.getByText("ASSISTANT_ONLY_CONTEXT").count(), 0);
  await dialog.getByRole("button", { name: "Recall Alpha latest", exact: true }).click();
  await input.fill("edited recall"); await caret(13); await input.press("ArrowDown"); await value("unsent draft\nkeep me");
  checks.push("picker lists only loaded user text; edited recall Down restores original multiline draft");
  await input.fill("/hel"); await page.getByRole("button", { name: /help/ }).first().waitFor();
  await caret(0); await input.press("ArrowUp"); await value("/hel"); await input.press("Escape");
  await input.fill(""); await input.press("ArrowUp"); await value("Recall Alpha latest");
  await open("f01_b", "Recall Beta");
  assert.equal(await panel.getByRole("button", { name: "Restore draft", exact: true }).count(), 0);
  await input.fill(""); await input.press("ArrowUp"); await value("Recall Beta latest");
  await open("f01_a", "Recall Alpha");
  assert.equal(await panel.getByRole("button", { name: "Restore draft", exact: true }).count(), 0);
  await input.fill(""); await input.press("ArrowDown"); await value("");
  checks.push("slash menu retains arrows; A→B→A retires history ownership and never restores another thread's draft");
  await input.press("ArrowUp"); await value("Recall Alpha latest");
  await input.fill("Recall Alpha latest edited before send");
  assert.equal(sent.length, 0);
  await input.press("Enter");
  await wait(() => sent.length === 1, "explicit send");
  assert.equal(sent[0].message, "Recall Alpha latest edited before send");
  assert.equal(sent[0].sid, "f01_a");
  assert.deepEqual(sent[0].context_items ?? [], []);
  await panel.getByText("REPLAY_RECALL_OK", { exact: true }).waitFor();
  await panel.getByRole("button", { name: "Stop", exact: true }).waitFor({ state: "hidden" });
  checks.push("explicit Enter sends edited text exactly once to correct session; replay stream completes with no provider");
  assert.deepEqual(errors, []);
  await page.screenshot({ path: path.join(output, "final.png") });
} catch (error) {
  failure = String(error.stack || error);
  const page = browser?.contexts()[0]?.pages()[0];
  if (page) {
    await page.screenshot({ path: path.join(output, "failure.png") }).catch(() => {});
    await writeFile(path.join(output, "failure.txt"), await page.locator("body").innerText());
  }
} finally {
  await browser?.close();
  for (const child of children.reverse()) { try { process.kill(-child.pid, "SIGTERM"); } catch { /* exited */ } }
  await writeFile(path.join(output, "process.log"), logs.join(""));
  await writeFile(path.join(output, "result.json"), JSON.stringify({ node: process.version, executable: process.execPath, repo, home, checks, errors, sent, failure: failure ?? null }, null, 2));
}
if (failure) throw new Error(failure);
console.log(JSON.stringify({ output, checks }));
