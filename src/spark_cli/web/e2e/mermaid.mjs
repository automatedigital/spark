// Source fixture + real persisted Chat path. No providers, live HOME or Spark state.
import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import net from "node:net";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import { chromium } from "playwright";

const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repo = path.resolve(web, "../../..");
const python = process.env.PYTHON || path.join(repo, ".venv/bin/python");
const output = process.env.MERMAID_OUTPUT || await mkdtemp(path.join(os.tmpdir(), "spark-mermaid-report-"));
const home = await mkdtemp(path.join(os.tmpdir(), "spark-mermaid-home-"));
await mkdir(output, { recursive: true });
const env = { ...process.env, HOME: home, USERPROFILE: home, SPARK_HOME: path.join(home, "spark"), PYTHONPATH: path.join(repo, "src"), SPARK_WEB_FAKE_STREAMS: "1" };
Object.assign(process.env, { HOME: home, USERPROFILE: home, SPARK_HOME: env.SPARK_HOME });
const valid = "flowchart LR\n  A[Start] --> B[Finish]";
const fence = (source) => `\`\`\`mermaid\n${source}\n\`\`\``;
const seeded = spawnSync(python, ["-c", `
from pathlib import Path
import os
assert str(Path.home()) == os.environ['HOME']
from core.spark_state import SessionDB
assert __import__('spark_cli.web_server', fromlist=['']).__file__.startswith(${JSON.stringify(repo)})
db = SessionDB()
for sid, title, content in [('mermaid-a', 'Mermaid Alpha', ${JSON.stringify(fence(valid))}), ('mermaid-b', 'Mermaid Beta', ${JSON.stringify(fence('sequenceDiagram\nAlice->>Bob: Hello'))})]:
    db.create_session(sid, 'web', model='fixture')
    db.set_session_title(sid, title)
    if sid == 'mermaid-a':
        for i in range(24):
            db.append_message(sid, 'user' if i % 2 == 0 else 'assistant', content=f'History {i}: ' + 'Synthetic conversation context. ' * 50)
    db.append_message(sid, 'user', content='Show a diagram')
    db.append_message(sid, 'assistant', content=content)
db.close()
`], { cwd: repo, env, encoding: "utf8" });
assert.equal(seeded.status, 0, seeded.stderr);
const freePort = () => new Promise((resolve) => {
  const server = net.createServer();
  server.listen(0, "127.0.0.1", () => { const port = server.address().port; server.close(() => resolve(port)); });
});
const apiPort = await freePort();
const api = spawn(python, ["-c", `from spark_cli.web_server import start_server; start_server('127.0.0.1', ${apiPort}, False)`], { cwd: repo, env, stdio: ["ignore", "pipe", "pipe"] });
let logs = "";
api.stdout.on("data", (chunk) => { logs += chunk; });
api.stderr.on("data", (chunk) => { logs += chunk; });
const server = await createServer({ root: web,
  plugins: [{ name: "mermaid-test-fixture", configureServer(vite) {
    vite.middlewares.use("/mermaid-fixture", async (_req, res) => {
      const html = await vite.transformIndexHtml("/mermaid-fixture", '<html><head></head><body><div id="fixture"></div><script type="module">import "/src/index.css"; import * as fixture from "/e2e/mermaid-fixture.tsx"; window.fixture = fixture;</script></body></html>');
      res.setHeader("Content-Type", "text/html");
      res.end(html);
    });
  } }],
  server: { host: "127.0.0.1", port: await freePort(), strictPort: true, proxy: { "/api": `http://127.0.0.1:${apiPort}` } },
});
await server.listen();
const base = `http://127.0.0.1:${server.httpServer.address().port}`;
console.log(`Fixture: ${base}/mermaid-fixture`);
let browser;
let page;
const checks = [];
const errors = [];
try {
  for (let i = 0; i < 150; i++) {
    try { if ((await fetch(`http://127.0.0.1:${apiPort}/api/status`)).ok) break; } catch { /* startup */ }
    if (i === 149) throw new Error("Backend startup timeout");
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  browser = await chromium.launch({ headless: true });
  page = await browser.newPage({ viewport: { width: 1200, height: 850 } });
  page.setDefaultTimeout(30000);
  page.on("pageerror", (error) => errors.push(error.message));
  const requests = [];
  page.on("request", (request) => requests.push(request.url()));
  await page.addInitScript(() => {
    localStorage.setItem("spark-onboarding-complete", "true");
    Object.defineProperty(navigator, "clipboard", { value: { writeText: async (text) => { window.copied = text; } } });
  });
  await page.goto(`${base}/mermaid-fixture`);
  await page.waitForFunction(() => window.fixture);
  const render = async (content, streaming = false, safeMode = false) => {
    await page.evaluate((args) => window.fixture.renderMarkdown(...args), [content, streaming, safeMode]);
    await page.waitForTimeout(80);
  };
  await render("```mermaid\n" + valid, true);
  assert.equal(await page.locator('section[aria-label="Mermaid diagram"]').count(), 0);
  assert.equal(requests.some((url) => /mermaid.*(?:core|dist)|mermaid\.js\?/.test(url)), false);
  checks.push("partial streaming stays code; Mermaid not requested");
  await render(fence(valid), false, true);
  assert.equal(await page.locator("svg").count(), 0);
  checks.push("safeMode stays plain");
  await render(fence(valid));
  await page.getByRole("img", { name: "Rendered Mermaid diagram" }).locator("svg").waitFor();
  const darkSvg = await page.locator('[role="img"]').innerHTML();
  assert.match(darkSvg, /Start/);
  await page.getByRole("button", { name: "Copy source", exact: true }).click();
  assert.equal(await page.evaluate(() => window.copied), valid);
  await page.evaluate(() => { navigator.clipboard.writeText = async () => { throw new Error("Clipboard denied"); }; });
  await page.getByRole("button", { name: "Copy source", exact: true }).click();
  await page.getByText("Copy failed", { exact: true }).waitFor();
  await page.getByRole("button", { name: "Source", exact: true }).click();
  assert.equal(await page.locator("pre").innerText(), valid);
  await page.getByRole("button", { name: "Diagram", exact: true }).click();
  await page.locator('[role="img"] svg').waitFor();
  await page.evaluate(() => { document.documentElement.dataset.webuiTheme = "daylight"; });
  await page.waitForFunction((before) => {
    const svg = document.querySelector('[role="img"]')?.innerHTML;
    return svg && svg !== before;
  }, darkSvg);
  checks.push("SVG, copy success/denial, Source/Diagram and dark/daylight rerender");
  await page.screenshot({ path: path.join(output, "diagram.png") });
  await render(fence("not a diagram"));
  await page.getByText("Could not render diagram. Check the Mermaid source.").waitFor();
  assert.equal(await page.locator("pre").innerText(), "not a diagram");
  checks.push("invalid syntax readable fallback and no Mermaid error nodes");
  for (const hostile of [
    'graph LR\nA[<img src=x onerror="window.pwned=1">]',
    'graph LR\nclick A "javascript:window.pwned=1"',
    '%%{init: {"securityLevel":"loose"}}%%\ngraph LR\nA-->B',
    '---\nconfig:\n securityLevel: loose\n---\ngraph LR\nA-->B',
    'graph LR\nstyle A fill:url(https://evil.test)',
    'graph LR\nA@{ img: "https://evil.test" }',
  ]) {
    await render(fence(hostile));
    await page.getByText("Diagram contains unsupported HTML, links, styling or configuration.").waitFor();
    assert.equal(await page.locator("svg, img, iframe, foreignObject, a[href]").count(), 0);
    assert.equal(await page.evaluate(() => window.pwned), undefined);
  }
  assert.equal(requests.some((url) => url.includes("evil.test")), false);
  checks.push("HTML, links, config, styling and assets blocked; no external requests");
  await render(fence("graph LR\n" + "A".repeat(8001)));
  await page.getByText("Diagram exceeds the size limit", { exact: false }).waitFor();
  await render(fence(valid) + "x".repeat(20001));
  assert.equal(await page.locator("svg").count(), 0);
  checks.push("diagram cap and existing large response plain fallback");
  await render(fence(valid) + "\n\n" + fence("sequenceDiagram\nAlice->>Bob: Hello"));
  await page.waitForFunction(() => document.querySelectorAll('[role="img"] svg').length === 2);
  checks.push("concurrent flowchart and sequence diagram render through shared queue");
  await page.evaluate(() => {
    const observer = new MutationObserver(() => {
      if (!document.querySelector('[id^="spark-diagram-"]')) return;
      observer.disconnect();
      window.fixture.unmountMarkdown();
      window.cancelledDuringRender = true;
    });
    observer.observe(document.body, { childList: true, subtree: true });
    window.fixture.renderMarkdown("```mermaid\ngraph LR\nA-->Cancelled\n```");
  });
  await page.waitForFunction(() => window.cancelledDuringRender);
  await page.waitForFunction(() => !document.querySelector('[id^="spark-diagram-"]'));
  assert.equal(await page.locator('[id^="spark-diagram-"]').count(), 0);
  checks.push("unmount cancels pending render and cleans measurement nodes");

  await page.goto(base);
  await page.getByText("Mermaid Alpha", { exact: true }).first().click();
  // Landing may already follow the latest row. Establish a detached scroll
  // state before requiring the conditional user-facing jump action.
  const chatScroll = page.locator('[data-session-id="mermaid-a"] [data-testid="chat-scroll"]');
  await chatScroll.waitFor();
  await page.locator('[data-session-id="mermaid-a"] [data-row-id]').first().waitFor();
  await chatScroll.hover();
  await page.mouse.wheel(0, -1500);
  await page.getByTitle("Jump to latest", { exact: true }).click();
  await page.locator('[role="img"][aria-label="Rendered Mermaid diagram"] svg').waitFor();
  await page.getByText("Mermaid Beta", { exact: true }).first().click();
  await page.locator('[data-testid="chat-panel"][data-session-id="mermaid-b"] [role="img"] svg').waitFor();
  await page.waitForFunction(() => document.querySelector('[data-session-id="mermaid-b"] [role="img"] svg')?.textContent.includes("Alice"));
  assert.match(await page.locator('[aria-label="Mermaid diagram"]').innerText(), /mermaid/);
  await page.reload();
  // Match the existing multi-chat fixture: reopen the saved chat after refresh.
  await page.getByText("Mermaid Beta", { exact: true }).first().click();
  await page.locator('[data-testid="chat-panel"][data-session-id="mermaid-b"] [role="img"] svg').waitFor();
  await page.screenshot({ path: path.join(output, "chat.png") });
  checks.push("persisted long Chat Alpha (24 history messages)/Beta navigation; refresh and reopen saved Beta render diagrams");
  const streaming = await fetch(`http://127.0.0.1:${apiPort}/api/dev/fake-streams`, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ session_id: "mermaid-a", title: "Mermaid Alpha", source: "web", reuse_existing: true,
      message: "Stream a diagram", events: [
        { type: "token", text: "```mermaid\n" + valid },
        { type: "token", text: "\n```", delay_ms: 2000 },
      ] }),
  });
  assert.equal(streaming.ok, true, await streaming.text());
  await page.getByText("Mermaid Alpha", { exact: true }).first().click();
  await page.locator('[data-testid="chat-panel"][data-session-id="mermaid-a"]').waitFor();
  await page.getByText("Mermaid Beta", { exact: true }).first().click();
  await page.locator('[data-testid="chat-panel"][data-session-id="mermaid-b"] [role="img"] svg').waitFor();
  await page.waitForTimeout(2500);
  await page.getByText("Mermaid Alpha", { exact: true }).first().click();
  await page.locator('[data-testid="chat-panel"][data-session-id="mermaid-a"]').waitFor();
  await page.waitForFunction(() => document.querySelectorAll('[role="img"] svg').length === 2);
  checks.push("switch away during provider-free fake diagram stream and return to completed SVG");
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ checks, errors, base, output, home }, null, 2));
  await writeFile(path.join(output, "result.json"), JSON.stringify({ checks, errors, base, output, home }, null, 2));
} catch (error) {
  await page?.screenshot({ path: path.join(output, "failure.png") });
  await writeFile(path.join(output, "failure.json"), JSON.stringify({ checks, errors, body: await page?.locator("body").innerText(), error: String(error) }, null, 2));
  throw error;
} finally {
  await browser?.close();
  await server.close();
  api.kill("SIGTERM");
  await writeFile(path.join(output, "backend.log"), logs);
}
