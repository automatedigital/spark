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
let rejectSend = false;
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
  let acceptConfirmation = true;
  page.on("dialog", (dialog) => acceptConfirmation ? dialog.accept() : dialog.dismiss());
  page.on("pageerror", (error) => errors.push(String(error)));
  // Intercept the provider boundary only. Acceptance and streaming use the real replay backend.
  await page.route("**/api/conversations/*/messages", async (route) => {
    const sid = new URL(route.request().url()).pathname.split("/")[3];
    const body = route.request().postDataJSON();
    sent.push({ sid, ...body });
    if (rejectSend) { await route.fulfill({ status: 503, json: { detail: "Fixture rejected submission" } }); return; }
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
  // A nonempty draft and an edited recall must both remain recoverable after
  // real ChatPanel navigation/unmount and a full browser reload.
  const original = "unsent draft\nkeep me";
  const recallLatest = async () => {
    const dialog = panel.getByRole("dialog", { name: "Loaded prompt history" });
    if (!await dialog.isVisible()) await panel.getByRole("button", { name: "Loaded prompt history", exact: true }).click();
    await dialog.getByRole("button", { name: "Recall Alpha latest", exact: true }).click();
  };
  await panel.getByRole("button", { name: "Restore draft", exact: true }).click(); await value("");
  await input.fill("/hel"); await page.getByRole("button", { name: /help/ }).first().waitFor();
  await caret(0); await input.press("ArrowUp"); await value("/hel"); await input.press("Escape");
  await input.fill(original);
  await input.evaluate((el) => { el.focus(); el.setSelectionRange(0, 0); el.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowUp", isComposing: true, bubbles: true })); });
  await value(original);
  await panel.getByRole("button", { name: "Loaded prompt history", exact: true }).click();
  const historyDialog = panel.getByRole("dialog", { name: "Loaded prompt history" });
  await wait(() => historyDialog.getByRole("button", { name: "Recall Alpha latest", exact: true }).evaluate((el) => el === document.activeElement), "picker keyboard focus");
  assert.equal(await historyDialog.getByRole("button").count(), 3);
  assert.equal(await historyDialog.getByText("ASSISTANT_ONLY_CONTEXT").count(), 0);
  await page.screenshot({ path: path.join(output, "history-picker.png") });
  await page.keyboard.press("Escape");
  assert.equal(await historyDialog.count(), 0);
  acceptConfirmation = false;
  await recallLatest(); await value(original);
  acceptConfirmation = true;
  await recallLatest();
  await input.fill("edited recall survives reload");
  await caret((await input.inputValue()).length); await input.press("ArrowDown"); await value(original);
  await panel.getByRole("button", { name: "Restore draft", exact: true }).click(); await value("edited recall survives reload");
  checks.push("IME and slash menu retain arrows; cancel new browse preserves text; edited recall Down and Restore draft preserve both texts");
  await open("f01_b", "Recall Beta");
  await input.fill("Beta nonempty private draft");
  assert.equal(await panel.getByRole("button", { name: "Restore draft", exact: true }).count(), 0);
  await open("f01_a", "Recall Alpha");
  await panel.getByRole("button", { name: "Restore draft", exact: true }).click(); await value(original);
  await page.screenshot({ path: path.join(output, `original-recovered-${checks.length}-${sent.length}.png`) });
  await panel.getByRole("button", { name: "Restore draft", exact: true }).click(); await value("edited recall survives reload");
  await page.reload();
  await open("f01_a", "Recall Alpha");
  await value("edited recall survives reload");
  await panel.getByRole("button", { name: "Restore draft", exact: true }).click(); await value(original);
  await page.screenshot({ path: path.join(output, `original-recovered-${checks.length}-${sent.length}.png`) });
  await panel.getByRole("button", { name: "Restore draft", exact: true }).click(); await value("edited recall survives reload");
  await open("f01_b", "Recall Beta"); await value("Beta nonempty private draft");
  await open("f01_a", "Recall Alpha");
  checks.push("nonempty A/recall/edit/B/nonempty B/A and reload preserve original and edited recall through Restore draft; B remains untouched");

  // Failed explicit send retains the edit and original; successful send consumes
  // only the submitted current draft, leaving the original recovery available.
  rejectSend = true;
  await input.press("Enter");
  await wait(() => sent.length === 1, "failed explicit send");
  await panel.getByText("Fixture rejected submission", { exact: false }).waitFor();
  await value("edited recall survives reload");
  await page.reload(); await open("f01_a", "Recall Alpha");
  await panel.getByRole("button", { name: "Restore draft", exact: true }).click(); await value(original);
  await page.screenshot({ path: path.join(output, `original-recovered-${checks.length}-${sent.length}.png`) });
  await panel.getByRole("button", { name: "Restore draft", exact: true }).click(); await value("edited recall survives reload");
  rejectSend = false;
  await input.press("Enter");
  await wait(() => sent.length === 2, "successful explicit send");
  await panel.getByText("REPLAY_RECALL_OK", { exact: true }).waitFor();
  await panel.getByRole("button", { name: "Stop", exact: true }).waitFor({ state: "hidden" });
  await value("");
  await page.reload(); await open("f01_a", "Recall Alpha");
  await panel.getByRole("button", { name: "Restore draft", exact: true }).click(); await value(original);
  await page.screenshot({ path: path.join(output, `original-recovered-${checks.length}-${sent.length}.png`) });
  assert.equal(sent[0].message, "edited recall survives reload");
  assert.equal(sent[1].message, "edited recall survives reload");
  assert.equal(sent[1].sid, "f01_a");
  assert.deepEqual(sent[1].context_items ?? [], []);
  checks.push("failed send and reload retain both drafts; accepted explicit send consumes only submitted text, original survives reload; exactly two explicit requests and no provider");

  // Existing F04 restore is an explicit replacement. Retire history browsing so
  // Down cannot replace the newly restored stash text.
  await input.fill("Saved stash text Ω\nline 2");
  await panel.getByRole("button", { name: "Saved prompts", exact: true }).click();
  let stash = page.getByRole("dialog", { name: "Saved prompts" });
  await stash.getByRole("button", { name: "Save current prompt", exact: true }).click();
  await stash.getByRole("button", { name: "Close saved prompts", exact: true }).click();
  await input.fill(""); await input.press("ArrowUp");
  const recalled = await input.inputValue();
  await panel.getByRole("button", { name: "Saved prompts", exact: true }).click();
  stash = page.getByRole("dialog", { name: "Saved prompts" });
  await input.evaluate((el) => el.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true })));
  await value(recalled);
  await stash.getByRole("button", { name: "Restore prompt", exact: true }).click();
  await stash.getByRole("button", { name: "Replace draft text", exact: true }).click();
  await value("Saved stash text Ω\nline 2");
  await caret((await input.inputValue()).length); await input.press("ArrowDown"); await value("Saved stash text Ω\nline 2");
  await open("f01_b", "Recall Beta"); await value("Beta nonempty private draft");
  await open("f01_a", "Recall Alpha"); await value("Saved stash text Ω\nline 2");
  await caret((await input.inputValue()).length); await input.press("ArrowDown"); await value("Saved stash text Ω\nline 2");
  checks.push("recall → stash restore → Down → B/A → Down preserves newly restored stash; modal guards history keyboard events");
  assert.equal(sent.length, 2);
  await open("f01_b", "Recall Beta");
  await page.evaluate(() => {
    const originalSetItem = Storage.prototype.setItem;
    window.__restoreStorage = () => { Storage.prototype.setItem = originalSetItem; };
    Storage.prototype.setItem = function(key, value) {
      if (key.endsWith(":composer-history")) throw new DOMException("Fixture quota", "QuotaExceededError");
      return originalSetItem.call(this, key, value);
    };
  });
  await panel.getByRole("button", { name: "Loaded prompt history", exact: true }).click();
  await panel.getByRole("dialog", { name: "Loaded prompt history" }).getByRole("button", { name: "Recall Beta latest", exact: true }).click();
  await panel.getByText("Could not save draft recovery. Your current text is unchanged.", { exact: true }).waitFor();
  await value("Beta nonempty private draft");
  await page.evaluate(() => window.__restoreStorage());
  await page.reload(); await open("f01_b", "Recall Beta"); await value("Beta nonempty private draft");
  checks.push("quota-failed recovery blocks destructive recall, reports failure and retains current draft across reload");
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
