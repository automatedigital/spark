import { spawn, spawnSync } from "node:child_process";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

const fixtureWebRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const webRoot = process.env.SPARK_E2E_WEB_ROOT
  ? path.resolve(process.env.SPARK_E2E_WEB_ROOT)
  : fixtureWebRoot;
const repoRoot = path.resolve(webRoot, "../../..");
const pythonBin = process.env.PYTHON || path.join(repoRoot, ".venv", "bin", "python");
const viteBin = path.join(fixtureWebRoot, "node_modules", ".bin", "vite");
const baseline = process.env.SPARK_E2E_BASELINE === "1";

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
  child.stdout.on("data", (chunk) => logs.push(chunk.toString()));
  child.stderr.on("data", (chunk) => logs.push(chunk.toString()));
  return { child, logs };
}

async function stopProcess(proc) {
  if (!proc || proc.child.exitCode !== null) return;
  proc.child.kill("SIGTERM");
  await new Promise((resolve) => setTimeout(resolve, 500));
  if (proc.child.exitCode === null) proc.child.kill("SIGKILL");
}

async function waitFor(url, timeoutMs = 45_000) {
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
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error(`Timed out waiting for ${url}: ${lastError?.message ?? "unknown error"}`);
}

async function run() {
  const apiPort = await freePort();
  const webPort = await freePort();
  const sparkHome = await mkdtemp(path.join(os.tmpdir(), "spark-sidebar-scale-"));
  await writeFile(
    path.join(sparkHome, "config.yaml"),
    "model:\n  default: test-model\n  provider: ollama\n  base_url: http://localhost:11434/v1\n",
  );
  for (let index = 0; index < 10; index += 1) {
    await mkdir(path.join(sparkHome, "workspace", `project-${index}`), { recursive: true });
  }

  const seed = spawnSync(pythonBin, ["-c", String.raw`
import time
from core.spark_state import SessionDB

db = SessionDB()
now = time.time()
for index in range(500):
    sid = f"scale-{index:03d}"
    source = f"workspace:project-{index % 10}"
    db.create_session(sid, source, model="test-model")
    db.set_session_title(sid, f"Scale chat {index:03d}")
    db._conn.execute("UPDATE sessions SET started_at = ? WHERE id = ?", (now - index, sid))
db.append_message("scale-499", "user", "ancient needle full history result")
db._conn.execute("UPDATE messages SET timestamp = ? WHERE session_id = ?", (now - 499, "scale-499"))
db._conn.commit()
db.close()
`], {
    cwd: repoRoot,
    env: { ...process.env, SPARK_HOME: sparkHome, PYTHONPATH: path.join(repoRoot, "src") },
    encoding: "utf8",
  });
  if (seed.status !== 0) throw new Error(`Fixture seed failed: ${seed.stderr}`);

  const backend = startProcess(
    pythonBin,
    ["-m", "spark_cli.main", "dashboard", "--host", "127.0.0.1", "--port", String(apiPort), "--no-open"],
    {
      cwd: repoRoot,
      env: {
        ...process.env,
        PYTHONPATH: path.join(repoRoot, "src"),
        SPARK_HOME: sparkHome,
        SPARK_WEB_FAKE_STREAMS: "1",
      },
    },
  );
  const vite = startProcess(viteBin, [webRoot, "--host", "127.0.0.1", "--port", String(webPort)], {
    cwd: webRoot,
    env: { ...process.env, SPARK_API_TARGET: `http://127.0.0.1:${apiPort}` },
  });

  let browser;
  let page;
  try {
    const apiBase = `http://127.0.0.1:${apiPort}`;
    const webBase = `http://127.0.0.1:${webPort}`;
    await waitFor(`${apiBase}/api/status`);
    await waitFor(webBase);
    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    await context.addInitScript(() => {
      localStorage.setItem(
        "spark-chat-expanded",
        JSON.stringify(Array.from({ length: 10 }, (_, index) => `project-${index}`)),
      );
    });
    page = await context.newPage();
    const sessionRequests = [];
    page.on("request", (request) => {
      const url = new URL(request.url());
      if (url.pathname === "/api/sessions") {
        sessionRequests.push({
          limit: Number(url.searchParams.get("limit")),
          offset: Number(url.searchParams.get("offset")),
        });
      }
    });

    const startupAt = performance.now();
    await page.goto(webBase);
    await page.getByRole("button", { name: /Scale chat 000/ }).waitFor({ timeout: 15_000 });
    const firstUsefulMs = performance.now() - startupAt;
    await page.waitForTimeout(150);
    const sessionButtons = page.locator('[role="button"]').filter({ hasText: /^Scale chat \d{3}/ });
    const mountedSessionRows = baseline
      ? await sessionButtons.count()
      : await page.locator("[data-sidebar-session-row]").count();
    const startupRequests = [...sessionRequests];

    const selected = page.getByRole("button", { name: /Scale chat 000/ }).first();
    const selectedElement = await selected.elementHandle();
    await selected.evaluate((element) => {
      window.__sparkSelectionStartedAt = performance.now();
      element.click();
    });
    await page.waitForFunction(
      (element) => element?.className.includes("bg-primary/12"),
      selectedElement,
    );
    const selectionMs = await page.evaluate(() => performance.now() - window.__sparkSelectionStartedAt);
    await page.getByText("Scale chat 000", { exact: true }).last().waitFor();

    const search = page.getByPlaceholder("Search projects and chats…");
    const searchMs = await search.evaluate((element) => new Promise((resolve, reject) => {
      const startedAt = performance.now();
      const timeout = window.setTimeout(() => {
        observer.disconnect();
        reject(new Error("Timed out waiting for full-history search result"));
      }, 5000);
      const observer = new MutationObserver(() => {
        if (!document.querySelector('[data-sidebar-session-row="scale-499"]')) return;
        window.clearTimeout(timeout);
        observer.disconnect();
        resolve(performance.now() - startedAt);
      });
      observer.observe(document.body, { childList: true, subtree: true });
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
      setter.call(element, "ancient needle");
      element.dispatchEvent(new Event("input", { bubbles: true }));
    }));
    await page.getByRole("button", { name: /Scale chat 499/ }).waitFor({ timeout: 5000 });
    await page.getByRole("button", { name: /Scale chat 499/ }).click();
    await page.getByText("Scale chat 499", { exact: true }).last().waitFor();

    await search.fill("");
    await page.getByRole("button", { name: /Scale chat 000/ }).waitFor();
    if (!baseline) {
      const scroll = page.getByTestId("session-sidebar-scroll");
      await scroll.evaluate((element) => { element.scrollTop = element.scrollHeight; });
      await page.waitForFunction(() => performance.getEntriesByType("resource")
        .some((entry) => entry.name.includes("/api/sessions?limit=50&offset=50")));
      const pagedMountedRows = await page.locator("[data-sidebar-session-row]").count();
      if (pagedMountedRows > 60) throw new Error(`Mounted ${pagedMountedRows} session rows after paging`);

      await scroll.evaluate((element) => { element.scrollTop = 600; });
      await page.waitForTimeout(100);
      const anchorBefore = await scroll.evaluate((element) => {
        const bounds = element.getBoundingClientRect();
        const candidates = [...element.querySelectorAll("[data-sidebar-row]")];
        const first = candidates.find((candidate) => candidate.getBoundingClientRect().bottom > bounds.top + 1);
        return first
          ? `${first.getAttribute("data-sidebar-row")}:${first.getAttribute("data-sidebar-session-row") ?? ""}`
          : null;
      });
      const liveResponse = await fetch(`${apiBase}/api/dev/fake-streams`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          session_id: "scale-live",
          title: "Scale live insertion",
          source: "workspace:project-0",
          message: "live sidebar insertion",
          events: [
            { type: "token", text: "live response", delay_ms: 150 },
          ],
        }),
      });
      if (!liveResponse.ok) throw new Error(`Fake live insert failed: ${liveResponse.status}`);
      await page.waitForTimeout(500);
      const anchorAfter = await scroll.evaluate((element) => {
        const bounds = element.getBoundingClientRect();
        const candidates = [...element.querySelectorAll("[data-sidebar-row]")];
        const first = candidates.find((candidate) => candidate.getBoundingClientRect().bottom > bounds.top + 1);
        return first
          ? `${first.getAttribute("data-sidebar-row")}:${first.getAttribute("data-sidebar-session-row") ?? ""}`
          : null;
      });
      if (anchorBefore !== anchorAfter) {
        throw new Error(`Scroll anchor changed after SSE insert: ${anchorBefore} -> ${anchorAfter}`);
      }

      await scroll.evaluate((element) => { element.scrollTop = 0; });
      await page.getByRole("button", { name: /Scale live insertion/ }).waitFor({ timeout: 5000 });
      const liveRow = page.locator('[data-sidebar-session-row="scale-live"]');
      if (await liveRow.locator(".bg-primary").count() === 0) {
        throw new Error("Live non-selected session did not retain its unread marker");
      }
      await liveRow.first().hover();
      await liveRow.first().locator('button[aria-label="Delete thread"]').click();
      await page.waitForFunction(() => !document.querySelector('[data-sidebar-session-row="scale-live"]'));

      const chatZero = page.locator('[data-sidebar-session-row="scale-000"] [role="button"]').last();
      await page.keyboard.down("Shift");
      await chatZero.click();
      await page.keyboard.up("Shift");
      await page.waitForFunction(() => JSON.parse(localStorage.getItem("spark-pinned-sessions") ?? "[]").includes("scale-000"));
      if (await page.locator('[data-sidebar-session-row="scale-000"]').count() < 2) {
        throw new Error("Pinned session was not rendered in both pinned and project placements");
      }

      const projectZero = page.getByRole("button", { name: /project-0/ }).first();
      await projectZero.click();
      await page.waitForFunction(() => !document.querySelector('[data-sidebar-session-row="scale-010"]'));
      await projectZero.click();
      await page.locator('[data-sidebar-session-row="scale-010"]').waitFor();

      const projectChatZero = page.locator('[data-sidebar-session-row="scale-000"] [role="button"]').last();
      const projectOne = page.getByRole("button", { name: /project-1/ }).first();
      await projectChatZero.dragTo(projectOne);
      await page.waitForFunction(async () => {
        const response = await fetch("/api/sessions/scale-000");
        return response.ok && (await response.json()).source === "workspace:project-1";
      });
    }

    const metrics = {
      mode: baseline ? "baseline" : "virtualized",
      firstUsefulMs: Math.round(firstUsefulMs),
      selectionMs: Math.round(selectionMs),
      searchMs: Math.round(searchMs),
      mountedSessionRows,
      startupRequests,
      secondPageRequests: sessionRequests.filter((request) => request.offset === 50).length,
    };
    process.stdout.write(`${JSON.stringify(metrics)}\n`);

    if (!baseline) {
      if (sessionRequests[0]?.limit !== 50 || sessionRequests[0]?.offset !== 0) {
        throw new Error(`Unexpected initial request ${JSON.stringify(sessionRequests[0])}`);
      }
      if (mountedSessionRows > 60) throw new Error(`Mounted ${mountedSessionRows} initial session rows`);
      if (metrics.secondPageRequests !== 1) {
        throw new Error(`Expected one single-flight second page request, got ${metrics.secondPageRequests}`);
      }
      if (selectionMs >= 100) throw new Error(`Selection took ${selectionMs.toFixed(1)} ms`);
      if (searchMs >= 100) throw new Error(`Search took ${searchMs.toFixed(1)} ms including hydration`);
    }
  } catch (error) {
    const body = page ? await page.locator("body").innerText().catch(() => "") : "";
    throw new Error(`${error.message}\nbody:\n${body.slice(0, 4000)}\nbackend:\n${backend.logs.join("")}\nvite:\n${vite.logs.join("")}`);
  } finally {
    if (browser) await browser.close();
    await stopProcess(vite);
    await stopProcess(backend);
    await rm(sparkHome, { recursive: true, force: true });
  }
}

await run();
