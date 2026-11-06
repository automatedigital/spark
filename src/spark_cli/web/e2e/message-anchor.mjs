// SP13: one production-build, real SQLite search -> anchor -> live-tail flow.
// SP13_DIST=/tmp/sp13-candidate-dist PYTHON=/tmp/spark-ci-fresh-20261106/bin/python node e2e/message-anchor.mjs
import { spawn } from "node:child_process";
import { mkdtemp, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import net from "node:net";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../../..");
const dist = process.env.SP13_DIST;
if (!dist) throw new Error("SP13_DIST must name the verified production build");
const home = await mkdtemp(path.join(os.tmpdir(), "spark-sp13-browser-"));
const port = await new Promise(resolve => { const server = net.createServer(); server.listen(0, "127.0.0.1", () => { const port = server.address().port; server.close(() => resolve(port)); }); });
await writeFile(path.join(home, "config.yaml"), "model:\n  default: fixture\n  provider: ollama\n  base_url: http://localhost:11434/v1\n");
const code = `
from pathlib import Path
from core.spark_state import SessionDB
db=SessionDB()
db.create_session('anchor-browser', 'web')
db.set_session_title('anchor-browser', 'Long search fixture')
db._conn.executemany("INSERT INTO messages (session_id,role,content,timestamp) VALUES ('anchor-browser',?,?,?)", [('user' if i%2==0 else 'assistant', 'equalneedle exact same snippet' if i in (100,5000) else f'History row {i}', i) for i in range(10000)])
db._conn.execute("UPDATE sessions SET message_count=10000 WHERE id='anchor-browser'")
db._conn.commit()
db.close()
import spark_cli.web_server as w
w.app.router.routes[:]=[r for r in w.app.router.routes if getattr(r,'name','') not in {'assets','serve_spa','no_frontend'}]
w.WEB_DIST=Path(${JSON.stringify(dist)})
w.mount_spa(w.app)
w.start_server('127.0.0.1',${port},False)
`;
const backend = spawn(process.env.PYTHON || path.join(root, ".venv/bin/python"), ["-c", code], { cwd: root, env: { ...process.env, PYTHONPATH: path.join(root, "src"), SPARK_HOME: home, SPARK_WEB_FAKE_STREAMS: "1" }, stdio: ["ignore", "pipe", "pipe"] });
let logs = "";
for (const stream of [backend.stdout, backend.stderr]) stream.on("data", chunk => { logs += chunk; });
const origin = `http://127.0.0.1:${port}`;
console.log(`SP13 browser origin=${origin} home=${home}`);
const report = { dist, home, origin, flow: [], windows: [], requests: [], errors: [] };
let browser, page;
try {
  let ready = false;
  for (let i=0;i<200;i++) { try { if ((await fetch(origin+"/api/status")).ok) { ready=true; break; } } catch {} await new Promise(resolve => setTimeout(resolve,150)); }
  if (!ready) throw new Error(logs.slice(-4000));
  browser = await chromium.launch({ headless: true });
  page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.on("pageerror", error => report.errors.push(error.message));
  page.on("request", request => { if (/\/api\/(sessions|conversations)/.test(request.url())) report.requests.push(request.url().replace(origin,"")); });
  page.on("response", async response => { if (response.url().includes("/recovery")) { const result = await response.json(); report.recovery = { active: result.turn_active, text: result.stream_text, mode: result.stream_text_mode, state: result.state }; } if (response.url().includes("/message-window/")) { const body = await response.json(); report.windows.push({ url: response.url(), count: body.messages?.length, before: body.before_id, after: body.after_id, bytes: (await response.body()).length }); } });
  const stream = await fetch(origin+"/api/dev/fake-streams", { method:"POST", headers:{"content-type":"application/json"}, body:JSON.stringify({ session_id:"anchor-browser", reuse_existing:true, message:"New active stream", events:[{type:"token",text:"SP13 current live tail"},{type:"token",text:" continues independently",delay_ms:8000},{type:"token",text:" complete",delay_ms:5000}] }) });
  assert(stream.ok, await stream.text());
  await page.goto(origin);
  await page.getByText("Spark", { exact: true }).first().waitFor({ timeout: 30000 });
  await page.waitForTimeout(500);
  await page.keyboard.press("Control+k");
  const dialog = page.getByRole("dialog", { name: "Command palette" });
  await dialog.getByRole("combobox").fill("equalneedle");
  const options = dialog.getByRole("option").filter({ hasText: "equalneedle exact same snippet" });
  await options.first().waitFor();
  assert.equal(await options.count(), 2, "both equal snippets must remain independently actionable");
  const began = performance.now();
  await dialog.locator('[id="command-palette-item-message:5001"]').click();
  const view = page.getByTestId("message-anchor-view");
  const match = view.locator('[data-anchor-highlight="true"]');
  await match.waitFor({ timeout: 15000 });
  assert.equal(await match.getAttribute("data-message-id"), "5001");
  await match.evaluate(node => { const box=node.getBoundingClientRect(); if (box.bottom<=0 || box.top>=innerHeight) throw new Error("anchor is outside viewport"); });
  await page.waitForFunction(() => document.activeElement?.getAttribute("data-anchor-highlight") === "true");
  report.clickToHighlightMs = performance.now()-began;
  assert.equal(await view.locator("article").count(), 50);
  report.flow.push("built palette searches two equal snippets; click opens exact middle ID 5001 in 50 rows with visible highlight and focus");
  await page.screenshot({ path: "/tmp/sp13-anchor-highlight.png" });
  const originalIds = await view.locator("article").evaluateAll(nodes => nodes.map(node => node.dataset.messageId));
  await view.getByRole("button", { name: "Load older context" }).click();
  await page.waitForFunction(() => document.querySelector('[data-testid="message-anchor-view"] article')?.getAttribute("data-message-id") === "4926");
  const olderIds = await view.locator("article").evaluateAll(nodes => nodes.map(node => node.dataset.messageId));
  assert(!olderIds.some(id => originalIds.includes(id)));
  await view.getByRole("button", { name: "Load newer context" }).click();
  await match.waitFor();
  assert.deepEqual(await view.locator("article").evaluateAll(nodes => nodes.map(node => node.dataset.messageId)), originalIds);
  report.flow.push("older/newer keyset pages return to identical 50 IDs without overlap or cursor loss");
  const panel = page.getByTestId("chat-panel");
  await page.waitForFunction(() => Number(document.querySelector('[data-testid="chat-panel"]')?.getAttribute("data-stream-visible-chars")) >= 45, undefined, { timeout: 15000 });
  assert.equal(await panel.getAttribute("data-streaming"), "true");
  assert.equal(await match.getAttribute("data-message-id"), "5001");
  assert.deepEqual(await view.locator("article").evaluateAll(nodes => nodes.map(node => node.dataset.messageId)), originalIds);
  report.flow.push("real SSE arrivals update independent live transcript while historical window and exact highlight remain unchanged");
  await view.getByRole("button", { name:"Return to latest" }).click();
  await view.waitFor({ state:"detached" });
  await panel.getByText(/SP13 current live tail continues independently/).first().waitFor();
  await page.waitForFunction(() => document.querySelector('[data-testid="chat-panel"]')?.getAttribute("data-streaming") === "false");
  const rows = await panel.locator("[data-row-id]").evaluateAll(nodes => nodes.map(node => node.dataset.rowId));
  assert.equal(new Set(rows).size, rows.length);
  await page.waitForFunction(() => document.activeElement?.getAttribute("data-testid") === "chat-scroll");
  report.flow.push("return latest displays current completed stream, unique rows and usable keyboard focus");
  assert(report.windows.every(window => window.count <= 50));
  assert(!report.requests.some(url => /\/messages(?:\?|$)/.test(url) && !/[?&]limit=(?:50|20)(?:&|$)/.test(url)), "no unbounded transcript read");
  assert.deepEqual(report.errors, []);
  report.success = true;
  console.log(JSON.stringify(report,null,2));
} catch (error) {
  report.success=false; report.failure=String(error); report.logs=logs.slice(-5000);
  if(page) { report.panel = await page.getByTestId("chat-panel").evaluate(node => ({ attributes: Object.fromEntries([...node.attributes].map(a => [a.name,a.value])), text: node.innerText.slice(-2500) })).catch(() => null); }
  if(page) await page.screenshot({path:"/tmp/sp13-anchor-failure.png"}).catch(()=>{});
  throw error;
} finally {
  await writeFile("/tmp/sp13-browser-report.json",JSON.stringify(report,null,2));
  await browser?.close();
  backend.kill("SIGTERM");
}
