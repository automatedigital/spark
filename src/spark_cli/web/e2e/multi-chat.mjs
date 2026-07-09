import { spawn } from "node:child_process";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(webRoot, "../../..");
const pythonBin = process.env.PYTHON || path.join(repoRoot, ".venv", "bin", "python");
const screenshotsDir = path.join(webRoot, "screenshots", "e2e");

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close(() => resolve(port));
    });
  });
}

function startProcess(command, args, options) {
  const child = spawn(command, args, {
    ...options,
    stdio: ["ignore", "pipe", "pipe"],
  });
  const logs = [];
  const collect = (stream, prefix) => {
    stream.on("data", (chunk) => {
      const text = chunk.toString();
      logs.push(`${prefix}${text}`);
      if (process.env.E2E_VERBOSE) process.stderr.write(`${prefix}${text}`);
    });
  };
  collect(child.stdout, "");
  collect(child.stderr, "");
  child.on("exit", (code, signal) => {
    logs.push(`\n[exit code=${code} signal=${signal}]\n`);
  });
  return { child, logs };
}

async function waitFor(url, { timeoutMs = 45_000 } = {}) {
  const deadline = Date.now() + timeoutMs;
  let lastError = null;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(url);
      if (res.ok) return res;
      lastError = new Error(`${res.status} ${res.statusText}`);
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Timed out waiting for ${url}: ${lastError?.message ?? "unknown error"}`);
}

async function stopProcess(proc) {
  if (!proc || proc.child.exitCode !== null) return;
  proc.child.kill("SIGTERM");
  await new Promise((resolve) => setTimeout(resolve, 750));
  if (proc.child.exitCode === null) proc.child.kill("SIGKILL");
}

async function createFakeStream(apiBase, { sessionId, title, source, marker }) {
  const res = await fetch(`${apiBase}/api/dev/fake-streams`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      title,
      source,
      message: `${title}: e2e active switching test`,
      events: [
        { type: "status", kind: "initializing_agent", text: `Preparing ${marker}` },
        { type: "reasoning", text: `Reasoning for ${marker}` },
        { type: "tool_start", tool_call_id: `tool_${marker}`, name: "fake_lookup", args: { marker } },
        { type: "tool_end", tool_call_id: `tool_${marker}`, name: "fake_lookup", result: { ok: true } },
        { type: "token", text: `${marker} chunk 1. ` },
        { type: "stall", text: `Holding ${marker}`, phase: "api" },
        { type: "token", text: `${marker} chunk 2. `, delay_ms: 3000 },
        { type: "recover", kind: "recovering", text: `Recovering ${marker}` },
        { type: "token", text: `${marker} chunk 3.`, delay_ms: 3000 },
      ],
    }),
  });
  if (!res.ok) throw new Error(`fake stream ${sessionId} failed: ${res.status} ${await res.text()}`);
}

async function createFakeCompactionFailure(apiBase) {
  const res = await fetch(`${apiBase}/api/dev/fake-streams`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      session_id: "e2e_compaction_failure",
      title: "E2E compaction failure chat",
      message: "E2E long-thread compaction failure",
      events: [
        { type: "token", text: "context before compaction. " },
        {
          type: "compact_fail",
          kind: "context_compression",
          name: "ContextCompactionError",
          text: "Context compression failed; retry this message to continue.",
          delay_ms: 3000,
        },
      ],
    }),
  });
  if (!res.ok) throw new Error(`fake compaction failure failed: ${res.status} ${await res.text()}`);
}

async function status(apiBase, sessionId) {
  const res = await fetch(`${apiBase}/api/conversations/${encodeURIComponent(sessionId)}/turn-status`);
  if (!res.ok) throw new Error(`turn-status ${sessionId} failed: ${res.status}`);
  return res.json();
}

async function clickChat(page, title, marker) {
  await page.getByRole("button", { name: new RegExp(title) }).click();
  await page.getByText(`${marker} chunk 1.`).waitFor({ timeout: 5000 });
  const body = await page.locator("body").innerText();
  if (body.includes("LOADING LLM RESPONSE") && !body.includes(`${marker} chunk 1.`)) {
    throw new Error(`${title} showed stale loading without stream text`);
  }
  for (const other of ["alpha", "bravo", "charlie"].filter((item) => item !== marker)) {
    if (body.includes(`${other} chunk 1.`)) {
      throw new Error(`${title} contains token bleed from ${other}`);
    }
  }
  return body;
}

async function run() {
  const apiPort = await freePort();
  const webPort = await freePort();
  const sparkHome = await mkdtemp(path.join(os.tmpdir(), "spark-web-e2e-"));
  await mkdir(path.join(sparkHome, "workspace", "particles"), { recursive: true });
  await writeFile(
    path.join(sparkHome, "config.yaml"),
    "model:\n  default: test-model\n  provider: ollama\n  base_url: http://localhost:11434/v1\n",
  );
  await mkdir(screenshotsDir, { recursive: true });

  const backend = startProcess(
    pythonBin,
    ["-m", "spark_cli.main", "dashboard", "--host", "127.0.0.1", "--port", String(apiPort), "--no-open"],
    {
      cwd: repoRoot,
      env: {
        ...process.env,
        SPARK_HOME: sparkHome,
        SPARK_WEB_FAKE_STREAMS: "1",
      },
    },
  );
  const vite = startProcess("npm", ["run", "dev", "--", "--host", "127.0.0.1", "--port", String(webPort)], {
    cwd: webRoot,
    env: {
      ...process.env,
      SPARK_API_TARGET: `http://127.0.0.1:${apiPort}`,
    },
  });

  let browser;
  try {
    const apiBase = `http://127.0.0.1:${apiPort}`;
    const webBase = `http://127.0.0.1:${webPort}`;
    await waitFor(`${apiBase}/api/status`);
    await waitFor(webBase);

    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1440, height: 980 } });
    await page.goto(webBase);
    await page.getByText("Spark").first().waitFor({ timeout: 15_000 });

    await Promise.all([
      createFakeStream(apiBase, {
        sessionId: "e2e_multi_alpha",
        title: "E2E alpha chat",
        marker: "alpha",
      }),
      createFakeStream(apiBase, {
        sessionId: "e2e_multi_bravo",
        title: "E2E bravo project chat",
        source: "workspace:particles",
        marker: "bravo",
      }),
      createFakeStream(apiBase, {
        sessionId: "e2e_multi_charlie",
        title: "E2E charlie chat",
        marker: "charlie",
      }),
    ]);

    await page.reload({ waitUntil: "domcontentloaded" });
    await page.getByText("Spark").first().waitFor({ timeout: 15_000 });
    await page.getByRole("button", { name: /E2E alpha chat/ }).waitFor({ timeout: 10_000 });
    await page.getByRole("button", { name: /E2E charlie chat/ }).waitFor({ timeout: 10_000 });
    await page.getByRole("button", { name: /particles/i }).click();
    await page.getByRole("button", { name: /E2E bravo project chat/ }).waitFor({ timeout: 10_000 });

    await clickChat(page, "E2E alpha chat", "alpha");
    await clickChat(page, "E2E bravo project chat", "bravo");
    await clickChat(page, "E2E charlie chat", "charlie");

    await page.reload({ waitUntil: "domcontentloaded" });
    await page.getByRole("button", { name: /E2E alpha chat/ }).click();
    const recovered = await clickChat(page, "E2E alpha chat", "alpha");
    const alphaOccurrences = (recovered.match(/alpha chunk 1\./g) || []).length;
    if (alphaOccurrences !== 1) {
      throw new Error(`alpha stream text duplicated after refresh: ${alphaOccurrences} occurrences`);
    }

    for (const sessionId of ["e2e_multi_alpha", "e2e_multi_bravo", "e2e_multi_charlie"]) {
      const current = await status(apiBase, sessionId);
      if (!current.turn_active) throw new Error(`${sessionId} unexpectedly completed during active-switch test`);
    }

    await new Promise((resolve) => setTimeout(resolve, 6500));
    for (const sessionId of ["e2e_multi_alpha", "e2e_multi_bravo", "e2e_multi_charlie"]) {
      const current = await status(apiBase, sessionId);
      if (current.turn_active) throw new Error(`${sessionId} still active after completion window`);
    }
    const finalBody = await page.locator("body").innerText();
    if (finalBody.includes("LOADING LLM RESPONSE")) {
      throw new Error("stale Loading LLM response remained after fake turns completed");
    }

    await createFakeCompactionFailure(apiBase);
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.getByRole("button", { name: /E2E compaction failure chat/ }).click();
    await page.getByText("context before compaction.").waitFor({ timeout: 5000 });
    await page.getByText("Context compression failed; retry this message to continue.").waitFor({ timeout: 8000 });
    const deadline = Date.now() + 10_000;
    let compactionTurnCleared = false;
    while (Date.now() < deadline) {
      const current = await status(apiBase, "e2e_compaction_failure");
      if (!current.turn_active) {
        compactionTurnCleared = true;
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    if (!compactionTurnCleared) throw new Error("compaction failure turn stayed active");
    const compactionBody = await page.locator("body").innerText();
    if (compactionBody.includes("LOADING LLM RESPONSE")) {
      throw new Error("compaction failure left stale Loading LLM response visible");
    }
  } catch (error) {
    if (browser) {
      const pages = browser.contexts().flatMap((context) => context.pages());
      if (pages[0]) {
        await pages[0].screenshot({ path: path.join(screenshotsDir, "multi-chat-failure.png"), fullPage: true });
      }
    }
    console.error("\n--- backend logs ---\n", backend.logs.join("").slice(-8000));
    console.error("\n--- vite logs ---\n", vite.logs.join("").slice(-8000));
    throw error;
  } finally {
    if (browser) await browser.close();
    await stopProcess(vite);
    await stopProcess(backend);
    if (!process.env.SPARK_E2E_KEEP_HOME) await rm(sparkHome, { recursive: true, force: true });
  }
}

run().catch((error) => {
  console.error(error);
  process.exit(1);
});
