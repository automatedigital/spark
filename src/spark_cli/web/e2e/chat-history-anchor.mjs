import { spawn, spawnSync } from "node:child_process";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(webRoot, "../../..");
const pythonBin = process.env.PYTHON || path.join(repoRoot, ".venv", "bin", "python");

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
  const child = spawn(command, args, { ...options, stdio: ["ignore", "pipe", "pipe"] });
  const logs = [];
  for (const stream of [child.stdout, child.stderr]) {
    stream.on("data", (chunk) => logs.push(chunk.toString()));
  }
  child.on("exit", (code, signal) => logs.push(`[exit code=${code} signal=${signal}]`));
  return { child, logs };
}

async function stopProcess(proc) {
  if (!proc || proc.child.exitCode !== null) return;
  proc.child.kill("SIGTERM");
  await new Promise((resolve) => setTimeout(resolve, 300));
  if (proc.child.exitCode === null) proc.child.kill("SIGKILL");
}

async function waitFor(url, timeoutMs = 15_000) {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
      lastError = new Error(`${response.status} ${response.statusText}`);
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Timed out waiting for ${url}: ${lastError?.message ?? "unknown error"}`);
}

function seedHistory(sparkHome) {
  const script = String.raw`
from core.spark_state import SessionDB

db = SessionDB()
try:
    db.create_session("history_anchor", "e2e", model="fake-model")
    db.set_session_title("history_anchor", "History anchor")
    for index in range(120):
        role = "user" if index % 2 == 0 else "assistant"
        db.append_message(
            "history_anchor",
            role,
            content=f"History anchor row {index + 1:03d}: deterministic fixture",
        )
finally:
    db.close()
`;
  const result = spawnSync(pythonBin, ["-c", script], {
    cwd: repoRoot,
    env: { ...process.env, PYTHONPATH: path.join(repoRoot, "src"), SPARK_HOME: sparkHome },
    encoding: "utf8",
  });
  if (result.status !== 0) {
    throw new Error(`Fixture seed failed (${result.status}): ${result.stderr || result.stdout}`);
  }
}

async function loadEarlier(page) {
  const button = page.getByRole("button", { name: "Load earlier messages" });
  await button.waitFor({ timeout: 8_000 });
  await button.click();
  await page.waitForFunction(() => {
    const candidate = [...document.querySelectorAll("button")]
      .find((element) => /^(Load earlier messages|Loading…)$/.test(element.textContent?.trim() ?? ""));
    return !candidate || (!candidate.disabled && candidate.textContent?.trim() === "Load earlier messages");
  }, undefined, { timeout: 8_000 });
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}

async function readAnchor(page) {
  return page.evaluate(() => {
    const panel = document.querySelector('[data-testid="chat-panel"]');
    const scroll = panel?.querySelector('[data-testid="chat-scroll"]');
    if (!(panel instanceof HTMLElement) || !(scroll instanceof HTMLElement)) {
      throw new Error("Chat panel scroll element missing");
    }
    const scrollRect = scroll.getBoundingClientRect();
    const rows = [...scroll.querySelectorAll("[data-row-id][data-index]")]
      .map((element) => {
        const rect = element.getBoundingClientRect();
        return {
          id: element.getAttribute("data-row-id"),
          index: Number(element.getAttribute("data-index")),
          top: rect.top,
          bottom: rect.bottom,
        };
      })
      .filter((row) => row.bottom > scrollRect.top && row.top < scrollRect.bottom)
      .sort((left, right) => left.index - right.index);
    const anchor = rows[0];
    if (!anchor?.id) {
      const allRows = [...scroll.querySelectorAll("[data-row-id][data-index]")]
        .map((element) => ({
          id: element.getAttribute("data-row-id"),
          index: Number(element.getAttribute("data-index")),
          top: element.getBoundingClientRect().top,
          bottom: element.getBoundingClientRect().bottom,
        }))
        .slice(0, 12);
      throw new Error(`No visible row to anchor: ${JSON.stringify({
        scrollRect,
        scrollTop: scroll.scrollTop,
        scrollHeight: scroll.scrollHeight,
        clientHeight: scroll.clientHeight,
        listHeight: panel.querySelector('[data-index]')?.parentElement?.getBoundingClientRect().height ?? null,
        rows,
        allRows,
      })}`);
    }
    return {
      ...anchor,
      scrollTop: scroll.scrollTop,
      scrollHeight: scroll.scrollHeight,
      clientHeight: scroll.clientHeight,
      listHeight: panel.querySelector('[data-index]')?.parentElement?.getBoundingClientRect().height ?? null,
      visibleRows: rows,
    };
  });
}

async function openHistory(page, webBase) {
  await page.goto(webBase, { waitUntil: "domcontentloaded" });
  await page.getByText("Spark").first().waitFor({ timeout: 8_000 });
  const session = page.getByRole("button", { name: /History anchor/ }).first();
  await session.waitFor({ timeout: 8_000 });
  await session.click();
  await page.waitForFunction(
    () => document.querySelector('[data-testid="chat-panel"]')?.getAttribute("data-session-id") === "history_anchor",
  );
  await page.locator('[data-testid="chat-panel"] [data-row-id]').first().waitFor({ timeout: 8_000 });
}

async function runTrial(browser, webBase, trial) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  try {
    await openHistory(page, webBase);
    const before = await readAnchor(page);
    await loadEarlier(page);
    try {
      await page.evaluate(({ id, top }) => new Promise((resolve, reject) => {
        let remainingFrames = 120;
        let stableFrames = 0;
        const check = () => requestAnimationFrame(() => {
          const element = document.querySelector(`[data-row-id="${CSS.escape(id)}"]`);
          const drift = element instanceof HTMLElement
            ? element.getBoundingClientRect().top - top
            : null;
          stableFrames = drift !== null && Math.abs(drift) <= 1 ? stableFrames + 1 : 0;
          remainingFrames -= 1;
          if (stableFrames >= 5) {
            resolve(undefined);
            return;
          }
          if (remainingFrames <= 0) {
            reject(new Error(`anchor did not settle: ${JSON.stringify({ id, drift })}`));
            return;
          }
          check();
        });
        check();
      }), { id: before.id, top: before.top });
    } catch (error) {
      const current = await readAnchor(page).catch((readError) => ({
        readError: readError instanceof Error ? readError.message : String(readError),
      }));
      throw new Error(
        `${error instanceof Error ? error.message : String(error)}; anchor diagnostics: ${JSON.stringify({ before, current })}`,
      );
    }
    const after = await page.evaluate((id) => {
      const element = document.querySelector(`[data-row-id="${CSS.escape(id)}"]`);
      if (!(element instanceof HTMLElement)) throw new Error(`Anchor row ${id} disappeared`);
      const rect = element.getBoundingClientRect();
      const scroll = element.closest('[data-testid="chat-scroll"]');
      if (!(scroll instanceof HTMLElement)) throw new Error("Anchor scroll element disappeared");
      return { id, top: rect.top, scrollTop: scroll.scrollTop, scrollHeight: scroll.scrollHeight };
    }, before.id);
    const drift = after.top - before.top;
    console.log(JSON.stringify({ trial, before, after, drift }));
    if (Math.abs(drift) > 12) {
      throw new Error(`History anchor drifted by ${drift}px on trial ${trial}`);
    }
  } finally {
    await page.close();
  }
}

async function run() {
  const apiPort = await freePort();
  const webPort = await freePort();
  const sparkHome = await mkdtemp(path.join(os.tmpdir(), "spark-history-anchor-"));
  await mkdir(path.join(sparkHome, "workspace"), { recursive: true });
  await writeFile(
    path.join(sparkHome, "config.yaml"),
    "model:\n  default: test-model\n  provider: ollama\n  base_url: http://localhost:11434/v1\n",
  );
  seedHistory(sparkHome);

  const backend = startProcess(
    pythonBin,
    [
      "-c",
      "from spark_cli.web_server import start_server; import sys; start_server('127.0.0.1', int(sys.argv[1]), False)",
      String(apiPort),
    ],
    { cwd: repoRoot, env: { ...process.env, SPARK_HOME: sparkHome } },
  );
  const vite = startProcess(
    "npm",
    ["run", "dev", "--", "--host", "127.0.0.1", "--port", String(webPort)],
    { cwd: webRoot, env: { ...process.env, SPARK_API_TARGET: `http://127.0.0.1:${apiPort}` } },
  );

  let browser;
  try {
    const apiBase = `http://127.0.0.1:${apiPort}`;
    const webBase = `http://127.0.0.1:${webPort}`;
    await waitFor(`${apiBase}/api/status`);
    await waitFor(webBase);
    browser = await chromium.launch({ headless: true });
    const failures = [];
    for (const trial of [1, 2]) {
      try {
        await runTrial(browser, webBase, trial);
      } catch (error) {
        failures.push(error instanceof Error ? error.message : String(error));
      }
    }
    if (failures.length > 0) throw new Error(failures.join("\n"));
    console.log("history anchor repro: PASS (2 trials)");
  } catch (error) {
    const details = `${error instanceof Error ? error.stack : error}\n\nBackend:\n${backend.logs.join("")}\n\nVite:\n${vite.logs.join("")}`;
    throw new Error(details);
  } finally {
    await browser?.close();
    await stopProcess(vite);
    await stopProcess(backend);
    if (!process.env.SPARK_E2E_KEEP_HOME) await rm(sparkHome, { recursive: true, force: true });
  }
}

run().catch((error) => {
  console.error(error instanceof Error ? error.stack : error);
  process.exitCode = 1;
});
