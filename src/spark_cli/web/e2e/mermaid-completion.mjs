// Narrow F05/F06/F07 integration probe. Mounts real Markdown; no backend/providers.
// Run with the shared venv active, Node 22 and Playwright browsers installed.
import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import { chromium } from "playwright";

const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const output = process.env.MERMAID_COMPLETION_OUTPUT || await mkdtemp(path.join(os.tmpdir(), "spark-mermaid-completion-"));
const syntheticHome = await mkdtemp(path.join(os.tmpdir(), "spark-mermaid-completion-home-"));
await mkdir(output, { recursive: true });
const browserEnv = { ...process.env, HOME: syntheticHome, USERPROFILE: syntheticHome, SPARK_HOME: path.join(syntheticHome, "spark"), PYTHONPATH: path.resolve(web, "../../..", "src") };
const server = await createServer({ root: web,
  plugins: [{ name: "mermaid-completion-fixture", configureServer(vite) {
    vite.middlewares.use("/completion-fixture", async (_req, res) => {
      const html = await vite.transformIndexHtml("/completion-fixture", '<html><head></head><body><div id="fixture"></div><script type="module">import "/src/index.css"; import * as fixture from "/e2e/mermaid-fixture.tsx"; window.fixture = fixture;</script></body></html>');
      res.setHeader("Content-Type", "text/html");
      res.end(html);
    });
  } }],
  server: { host: "127.0.0.1", port: 0, strictPort: true },
});
let browser;
const checks = [];
const errors = [];
const requests = [];
const partial = "```mermaid\ngraph LR\nA-->B";
const complete = partial + "\n```";
const ordinary = "```text\nplain\n```";
const details = (body) => `<details open>\n<summary>Evidence</summary>\n${body}\n</details>`;
const callout = (body) => `> [!NOTE]\n${body.split("\n").map((line) => `> ${line}`).join("\n")}`;
try {
  await server.listen();
  browser = await chromium.launch({ headless: true, env: browserEnv });
  const page = await browser.newPage();
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => requests.push(request.url()));
  await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/completion-fixture`);
  await page.waitForFunction(() => window.fixture);
  const check = async (name, content, expected, { streaming = false, safeMode = false, sections = expected } = {}) => {
    await page.evaluate(async ({ content, streaming, safeMode }) => {
      window.fixture.renderMarkdown(content, streaming, safeMode);
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    }, { content, streaming, safeMode });
    // No diagram component may mount at all for an ineligible block. This
    // catches dispatch immediately instead of relying on a delayed SVG count.
    assert.equal(await page.locator('#fixture section[aria-label="Mermaid diagram"]').count(), sections, name + ": diagram dispatch");
    if (expected) await page.waitForFunction((count) => document.querySelectorAll('#fixture [aria-label="Rendered Mermaid diagram"] svg').length === count, expected);
    assert.equal(await page.locator('#fixture [aria-label="Rendered Mermaid diagram"] svg').count(), expected, name + ": SVG count");
    checks.push({ name, expected, streaming, safeMode });
  };
  await check("incomplete control", partial, 0);
  await check("details then incomplete", details(ordinary) + "\n\n" + partial, 0);
  assert.equal(requests.some((url) => /mermaid.*(?:core|dist)|mermaid\.js\?/.test(url)), false, "ineligible blocks must not load Mermaid");
  for (const [name, prefix] of [
    ["details code", details(ordinary)],
    ["malformed details literal", details(ordinary).replace("<details open>", '<details onclick="evil()">')],
    ["nested details literal", details(details(ordinary))],
    ["callout code", callout(ordinary)],
    ["details containing callout code", details(callout(ordinary))],
    ["callout containing details code", callout(details(ordinary))],
  ]) {
    await check(name + " then incomplete", prefix + "\n\n" + partial, 0);
    await check(name + " then malformed", prefix + "\n\n" + partial + "\n```bad", 0);
    await check(name + " then complete", prefix + "\n\n" + complete, 1);
  }
  const combined = details(callout(ordinary)) + "\n\n" + partial;
  for (const end of [partial.length - 5, partial.length, partial.length + 2, partial.length + 4]) {
    await check("stream prefix " + end, details(callout(ordinary)) + "\n\n" + complete.slice(0, end), 0, { streaming: true });
  }
  await check("virtually closed live tail", combined, 0, { streaming: true });
  await check("finished stream without closing fence", combined, 0);
  await check("real closing fence in live tail", combined + "\n```", 0, { streaming: true });
  await check("real closing fence after stream ends", combined + "\n```", 1);
  await check("completed segment commits during stream", details(ordinary) + "\n\n" + complete + "\n\n" + "tail ".repeat(180), 1, { streaming: true });
  await check("independent duplicate code blocks", details(ordinary) + "\n\n" + complete + "\n\n" + partial, 1);
  await check("safe mode", combined + "\n```", 0, { safeMode: true });
  await check("giant committed response", combined + "\n```\n" + "x".repeat(20_001), 0);
  await check("giant streamed tail", combined + "x".repeat(20_001), 0, { streaming: true });
  // Nested Mermaid retains the existing ordinary-code rendering policy.
  await check("nested Mermaid stays readable code", details(complete) + "\n\n" + callout(complete), 0);
  await check("hostile source sanction", details(ordinary) + '\n\n```mermaid\ngraph LR\nclick A callback\n```', 0, { sections: 1 });
  assert.match(await page.locator("#fixture").innerText(), /unsupported HTML, links, styling or configuration/);
  await check("Mermaid character limit", '```mermaid\n' + 'x'.repeat(8_001) + '\n```', 0, { sections: 1 });
  assert.match(await page.locator("#fixture").innerText(), /size limit/);
  await check("Mermaid line limit", '```mermaid\n' + 'x\n'.repeat(150) + '\n```', 0, { sections: 1 });
  assert.match(await page.locator("#fixture").innerText(), /size limit/);
  await check("final combined diagram", details(callout(ordinary)) + "\n\n" + complete, 1);
  await page.screenshot({ path: path.join(output, "combined.png"), fullPage: true });
  assert.deepEqual(errors, []);
  assert.equal(requests.some((url) => !url.startsWith("http://127.0.0.1:")), false, "only fixture-local requests");
} finally {
  await writeFile(path.join(output, "result.json"), JSON.stringify({ checks, errors, syntheticHome, providerCalls: 0 }, null, 2));
  await browser?.close();
  await server.close();
  console.log(`Mermaid completion evidence: ${output}; ${checks.length} checks`);
}
