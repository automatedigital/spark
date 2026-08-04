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
  const collect = (stream, prefix) => {
    stream.on("data", (chunk) => {
      const text = chunk.toString();
      logs.push(`${prefix}${text}`);
      if (process.env.E2E_VERBOSE) process.stderr.write(`${prefix}${text}`);
    });
  };
  collect(child.stdout, "");
  collect(child.stderr, "");
  child.on("exit", (code, signal) => logs.push(`\n[exit code=${code} signal=${signal}]\n`));
  return { child, logs };
}

async function stopProcess(proc) {
  if (!proc || proc.child.exitCode !== null) return;
  proc.child.kill("SIGTERM");
  await new Promise((resolve) => setTimeout(resolve, 750));
  if (proc.child.exitCode === null) proc.child.kill("SIGKILL");
}

async function waitFor(url, timeoutMs = 45_000) {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return response;
      lastError = new Error(`${response.status} ${response.statusText}`);
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error(`Timed out waiting for ${url}: ${lastError?.message ?? "unknown error"}`);
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function seedSessions(sparkHome) {
  const script = String.raw`
from core.spark_state import SessionDB

db = SessionDB()
try:
    db.create_session("contracts_actions", "e2e", model="fake-model")
    db.set_session_title("contracts_actions", "Contract actions")
    db.append_message("contracts_actions", "user", content="Original user prompt")
    db.append_message("contracts_actions", "assistant", content="Original assistant response")

    for session_id, title in (
        ("contracts_tool", "Contract tool result"),
        ("contracts_approval", "Contract approval"),
    ):
        db.create_session(session_id, "e2e", model="fake-model")
        db.set_session_title(session_id, title)
        db.append_message(session_id, "user", content=f"{title} prompt")
        if session_id == "contracts_tool":
            db.append_message(
                session_id,
                "tool",
                content="FULL_TOOL_OUTPUT_SENTINEL " + ("tool output " * 240),
                tool_name="fake_lookup",
                tool_call_id="contract_tool_1",
            )
            db.append_message(session_id, "assistant", content="Tool contract response")

    db.create_session("contracts_history", "e2e", model="fake-model")
    db.set_session_title("contracts_history", "Contract history")
    for index in range(120):
        role = "user" if index % 2 == 0 else "assistant"
        content = f"History row {index + 1:03d}: deterministic contract fixture"
        db.append_message("contracts_history", role, content=content)
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

async function createFakeStream(apiBase, {
  sessionId,
  title,
  message,
  events,
  reuseExisting = false,
}) {
  const response = await fetch(`${apiBase}/api/dev/fake-streams`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      title,
      message: message || `${title} prompt`,
      reuse_existing: reuseExisting,
      events,
    }),
  });
  if (!response.ok) throw new Error(`Fake stream ${sessionId} failed: ${response.status} ${await response.text()}`);
}

async function waitForTurnIdle(apiBase, sessionId, timeoutMs = 15_000) {
  const deadline = Date.now() + timeoutMs;
  let lastStatus;
  while (Date.now() < deadline) {
    const response = await fetch(`${apiBase}/api/conversations/${encodeURIComponent(sessionId)}/turn-status`);
    if (response.ok) {
      lastStatus = await response.json();
      if (!lastStatus.turn_active) return lastStatus;
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Timed out waiting for ${sessionId}: ${JSON.stringify(lastStatus)}`);
}

async function openChat(page, sessionId, title) {
  const button = page.getByRole("button", { name: new RegExp(escapeRegExp(title)) }).first();
  await button.waitFor({ timeout: 15_000 });
  await button.click();
  await page.waitForFunction(
    (id) => document.querySelector('[data-testid="chat-panel"]')?.getAttribute("data-session-id") === id,
    sessionId,
  );
  await page.locator('[data-testid="chat-panel"] [data-row-id]').first().waitFor({ timeout: 15_000 });
}

async function waitForText(page, text, timeout = 10_000) {
  await page.getByText(text, { exact: false }).first().waitFor({ timeout });
}

async function waitForRequestPayload(payloads, predicate, timeout = 10_000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const payload = payloads.find(predicate);
    if (payload) return payload;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error(`Timed out waiting for request payload; received ${JSON.stringify(payloads)}`);
}

async function loadEarlier(page) {
  const button = page.getByRole("button", { name: "Load earlier messages" });
  await button.waitFor({ timeout: 10_000 });
  await button.evaluate((element) => element.click());
  await page.waitForFunction(() => {
    const candidate = [...document.querySelectorAll("button")]
      .find((element) => /^(Load earlier messages|Loading…)$/.test(element.textContent?.trim() ?? ""));
    return !candidate || (!candidate.disabled && candidate.textContent?.trim() === "Load earlier messages");
  }, undefined, { timeout: 10_000 });
}

function installClipboard(context) {
  return context.addInitScript(() => {
    window.__e2eClipboard = "";
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: {
        writeText: async (text) => { window.__e2eClipboard = String(text); },
        readText: async () => window.__e2eClipboard,
      },
    });
  });
}

async function run() {
  const apiPort = await freePort();
  const webPort = await freePort();
  const sparkHome = await mkdtemp(path.join(os.tmpdir(), "spark-web-contracts-"));
  await mkdir(path.join(sparkHome, "workspace", "particles"), { recursive: true });
  await writeFile(
    path.join(sparkHome, "config.yaml"),
    "model:\n  default: test-model\n  provider: ollama\n  base_url: http://localhost:11434/v1\n",
  );
  seedSessions(sparkHome);

  const backend = startProcess(
    pythonBin,
    [
      "-c",
      "from spark_cli.web_server import start_server; import sys; start_server('127.0.0.1', int(sys.argv[1]), False)",
      String(apiPort),
    ],
    {
      cwd: repoRoot,
      env: { ...process.env, SPARK_HOME: sparkHome, SPARK_WEB_FAKE_STREAMS: "1" },
    },
  );
  const vite = startProcess(
    "npm",
    ["run", "dev", "--", "--host", "127.0.0.1", "--port", String(webPort)],
    {
      cwd: webRoot,
      env: { ...process.env, SPARK_API_TARGET: `http://127.0.0.1:${apiPort}` },
    },
  );

  let browser;
  try {
    const apiBase = `http://127.0.0.1:${apiPort}`;
    const webBase = `http://127.0.0.1:${webPort}`;
    await waitFor(`${apiBase}/api/status`);
    await waitFor(webBase);

    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    await installClipboard(context);
    const page = await context.newPage();
    const retryPayloads = [];
    const forkPayloads = [];
    const approvalPayloads = [];
    const interruptPayloads = [];

    page.on("request", (request) => {
      const url = new URL(request.url());
      if (url.pathname.endsWith("/interrupt")) {
        try { interruptPayloads.push(JSON.parse(request.postData() || "{}")); } catch { interruptPayloads.push({}); }
      }
    });

    await page.route("**/api/conversations/*/retry", async (route) => {
      const url = new URL(route.request().url());
      if (!url.pathname.endsWith("/contracts_actions/retry")) return route.continue();
      const payload = JSON.parse(route.request().postData() || "{}");
      retryPayloads.push(payload);
      await createFakeStream(apiBase, {
        sessionId: "contracts_actions",
        title: "Contract actions",
        message: payload.message || "Retry prompt",
        reuseExisting: true,
        events: [{ type: "token", text: "Retry result visible" }],
      });
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, session_id: "contracts_actions" }) });
    });

    await page.route("**/api/conversations/*/fork", async (route) => {
      const url = new URL(route.request().url());
      if (!url.pathname.endsWith("/contracts_actions/fork")) return route.continue();
      forkPayloads.push(JSON.parse(route.request().postData() || "{}"));
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ok: true, session_id: "contracts_forked", source_session_id: "contracts_actions" }),
      });
    });

    await page.route("**/api/conversations/*/approval", async (route) => {
      const url = new URL(route.request().url());
      if (!url.pathname.endsWith("/contracts_approval/approval")) return route.continue();
      approvalPayloads.push(JSON.parse(route.request().postData() || "{}"));
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ok: true, session_id: "contracts_approval", resolved: 1 }),
      });
    });

    await page.route("**/api/sessions/contracts_forked/messages**", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          session_id: "contracts_forked",
          messages: [
            { id: "fork-user", message_index: 0, role: "user", content: "Forked prompt" },
            { id: "fork-assistant", message_index: 1, role: "assistant", content: "Fork result visible" },
          ],
          has_earlier: false,
        }),
      });
    });
    await page.route("**/api/sessions/contracts_forked/forks", async (route) => {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ forks: [], fork_count: 0 }) });
    });

    await page.goto(webBase, { waitUntil: "domcontentloaded" });
    await page.getByText("Spark").first().waitFor({ timeout: 15_000 });

    // Exact assistant copy, edit/retry request + visible response, and fork payload/result.
    await openChat(page, "contracts_actions", "Contract actions");
    const assistantRow = page.locator('[data-row-id]').filter({ hasText: "Original assistant response" }).first();
    await assistantRow.hover();
    await assistantRow.getByTitle("Copy complete response").click();
    const copied = await page.evaluate(() => window.__e2eClipboard);
    if (copied !== "Original assistant response") throw new Error(`Exact assistant copy mismatch: ${copied}`);

    const userRow = page.locator('[data-row-id]').filter({ hasText: "Original user prompt" }).first();
    await userRow.hover();
    await userRow.getByTitle("Edit & retry").click();
    const editBox = page.locator("textarea").first();
    await editBox.fill("Edited contract prompt");
    await page.getByRole("button", { name: "Retry with edited message" }).click();
    const retryPayload = await waitForRequestPayload(retryPayloads, (payload) => payload.message === "Edited contract prompt");
    if (retryPayload.message_index !== 0) throw new Error(`Unexpected retry index: ${JSON.stringify(retryPayload)}`);
    await waitForText(page, "Retry result visible");
    await waitForTurnIdle(apiBase, "contracts_actions");
    await page.reload({ waitUntil: "domcontentloaded" });
    await openChat(page, "contracts_actions", "Contract actions");

    const originalUserRow = page.locator('[data-row-id]').filter({ hasText: "Original user prompt" }).first();
    await originalUserRow.hover();
    const forkButton = originalUserRow.getByTitle("Fork from here");
    await page.waitForFunction(() => {
      const button = [...document.querySelectorAll('[data-row-id]')]
        .find((row) => row.textContent?.includes("Original user prompt"))
        ?.querySelector('[title="Fork from here"]');
      return Boolean(button && !(button instanceof HTMLButtonElement) || (button instanceof HTMLButtonElement && !button.disabled));
    }, undefined, { timeout: 8_000 });
    await forkButton.click();
    const forkPayload = await waitForRequestPayload(forkPayloads, () => true);
    if (forkPayload.from_message_index !== 0) throw new Error(`Unexpected fork payload: ${JSON.stringify(forkPayload)}`);
    await page.waitForFunction(
      () => document.querySelector('[data-testid="chat-panel"]')?.getAttribute("data-session-id") === "contracts_forked",
    );
    await waitForText(page, "Fork result visible");

    // Tool-result expansion fetches the full result rather than rendering the unbounded history payload.
    await page.reload({ waitUntil: "domcontentloaded" });
    await openChat(page, "contracts_tool", "Contract tool result");
    const toolButton = page.getByRole("button", { name: /fake_lookup/ }).first();
    await toolButton.click();
    await waitForText(page, "FULL_TOOL_OUTPUT_SENTINEL");

    // Approval payload and resolved/disabled state.
    await openChat(page, "contracts_approval", "Contract approval");
    await createFakeStream(apiBase, {
      sessionId: "contracts_approval",
      title: "Contract approval",
      reuseExisting: true,
      events: [
        {
          type: "approval",
          delay_ms: 500,
          args: { command: "rm -rf /tmp/contract-fixture", description: "Approval contract fixture" },
        },
        { type: "approval_resolved", delay_ms: 2_000, args: { choice: "once", resolved: 1 } },
        { type: "token", text: "Approval contract response" },
      ],
    });
    await waitForText(page, "Approval contract fixture");
    await page.getByRole("button", { name: "Once", exact: true }).click({ force: true });
    const approvalPayload = await waitForRequestPayload(approvalPayloads, () => true);
    if (approvalPayload.choice !== "once" || approvalPayload.resolve_all !== false) {
      throw new Error(`Unexpected approval payload: ${JSON.stringify(approvalPayload)}`);
    }
    await page.waitForFunction(() => {
      const button = [...document.querySelectorAll("button")]
        .find((candidate) => candidate.textContent?.trim() === "Once");
      return button instanceof HTMLButtonElement && button.disabled;
    }, undefined, { timeout: 8_000 });

    // Paged history preserves an existing row's screen position when earlier rows are prepended.
    await openChat(page, "contracts_history", "Contract history");
    const panel = page.locator('[data-testid="chat-panel"]');
    const scrollBox = panel.getByTestId("chat-scroll");
    await page.waitForFunction(() => {
      const scroll = document.querySelector('[data-testid="chat-panel"] [data-testid="chat-scroll"]');
      if (!(scroll instanceof HTMLElement)) return false;
      const scrollRect = scroll.getBoundingClientRect();
      return [...scroll.querySelectorAll("[data-row-id][data-index]")].some((candidate) => {
        const rect = candidate.getBoundingClientRect();
        return rect.bottom > scrollRect.top && rect.top < scrollRect.bottom;
      });
    }, undefined, { timeout: 3_000 });
    const anchor = await page.evaluate(() => {
      const panel = document.querySelector('[data-testid="chat-panel"]');
      if (!panel) throw new Error("Chat panel missing");
      const scroll = panel.querySelector('[data-testid="chat-scroll"]');
      if (!(scroll instanceof HTMLElement)) throw new Error("Chat scroll element missing");
      const scrollRect = scroll.getBoundingClientRect();
      const rows = [...scroll.querySelectorAll("[data-row-id][data-index]")];
      const row = rows.find((candidate) => {
          const rect = candidate.getBoundingClientRect();
          return rect.bottom > scrollRect.top && rect.top < scrollRect.bottom;
        });
      if (!row) throw new Error(`No visible history row to anchor: ${JSON.stringify({
        scroll: { top: scrollRect.top, bottom: scrollRect.bottom, height: scrollRect.height, scrollTop: scroll.scrollTop },
        rows: rows.map((candidate) => {
          const rect = candidate.getBoundingClientRect();
          return { id: candidate.getAttribute("data-row-id"), top: rect.top, bottom: rect.bottom };
        }),
      })}`);
      return { id: row.getAttribute("data-row-id"), top: row.getBoundingClientRect().top };
    });
    await loadEarlier(page);
    const anchoredRow = panel.locator(`[data-row-id="${anchor.id}"]`);
    await anchoredRow.waitFor();
    await page.waitForFunction(({ id, top }) => {
      const element = document.querySelector(`[data-row-id="${CSS.escape(id)}"]`);
      return element instanceof HTMLElement
        && Math.abs(element.getBoundingClientRect().top - top) <= 12;
    }, anchor, { timeout: 3_000 });
    const anchoredTop = await anchoredRow.evaluate((element) => element.getBoundingClientRect().top);
    if (Math.abs(anchoredTop - anchor.top) > 12) throw new Error(`History anchor drifted by ${anchoredTop - anchor.top}px`);
    await waitForText(page, "History row 001");

    // Minimap marker navigation changes the scroll position to the selected row.
    const beforeJump = await scrollBox.evaluate((element) => element.scrollTop);
    await page.getByRole("button", { name: "user row 1", exact: true }).click();
    await page.waitForTimeout(150);
    const afterJump = await scrollBox.evaluate((element) => element.scrollTop);
    if (afterJump >= beforeJump - 5) throw new Error(`Minimap did not navigate upward: ${beforeJump} -> ${afterJump}`);

    // Refresh/reconnect: reload during a live fake stream, then verify the final text is recovered once.
    await createFakeStream(apiBase, {
      sessionId: "contracts_reconnect",
      title: "Contract reconnect",
      events: [
        { type: "token", text: "Reconnect first. " },
        { type: "token", text: "Reconnect final.", delay_ms: 1_500 },
      ],
    });
    await openChat(page, "contracts_reconnect", "Contract reconnect");
    await waitForText(page, "Reconnect first.");
    await page.reload({ waitUntil: "domcontentloaded" });
    await openChat(page, "contracts_reconnect", "Contract reconnect");
    await waitForText(page, "Reconnect final.", 12_000);
    const reconnectText = await panel.innerText();
    if ((reconnectText.match(/Reconnect final\./g) || []).length !== 1) throw new Error("Reconnect final response duplicated");

    // Switching while responses are delayed must not bleed one session into another.
    await Promise.all([
      createFakeStream(apiBase, {
        sessionId: "contracts_switch_a",
        title: "Contract switch A",
        events: [{ type: "token", text: "SWITCH_A first. " }, { type: "token", text: "SWITCH_A final.", delay_ms: 1_200 }],
      }),
      createFakeStream(apiBase, {
        sessionId: "contracts_switch_b",
        title: "Contract switch B",
        events: [{ type: "token", text: "SWITCH_B first. " }, { type: "token", text: "SWITCH_B final.", delay_ms: 1_200 }],
      }),
    ]);
    await openChat(page, "contracts_switch_a", "Contract switch A");
    await waitForText(page, "SWITCH_A first.");
    await openChat(page, "contracts_switch_b", "Contract switch B");
    await waitForText(page, "SWITCH_B first.");
    await waitForTurnIdle(apiBase, "contracts_switch_a");
    await waitForTurnIdle(apiBase, "contracts_switch_b");
    await openChat(page, "contracts_switch_a", "Contract switch A");
    const aBody = await panel.innerText();
    if (aBody.includes("SWITCH_B")) throw new Error("Delayed response from switch B leaked into switch A");
    await openChat(page, "contracts_switch_b", "Contract switch B");
    const bBody = await panel.innerText();
    if (bBody.includes("SWITCH_A")) throw new Error("Delayed response from switch A leaked into switch B");

    // Stop and redirect each submit exactly once while a turn is active.
    await createFakeStream(apiBase, {
      sessionId: "contracts_stop",
      title: "Contract stop",
      events: [{ type: "token", text: "Stop first. " }, { type: "token", text: "Stop delayed.", delay_ms: 10_000 }],
    });
    await openChat(page, "contracts_stop", "Contract stop");
    await waitForText(page, "Stop first.");
    const stopButton = page.getByRole("button", { name: "Stop", exact: true });
    await stopButton.click();
    if (await stopButton.count()) await stopButton.click({ force: true }).catch(() => {});
    await waitForTurnIdle(apiBase, "contracts_stop");
    if (interruptPayloads.length !== 1) throw new Error(`Stop submitted ${interruptPayloads.length} times`);

    await createFakeStream(apiBase, {
      sessionId: "contracts_redirect",
      title: "Contract redirect",
      events: [{ type: "token", text: "Redirect first. " }, { type: "token", text: "Redirect delayed.", delay_ms: 10_000 }],
    });
    await openChat(page, "contracts_redirect", "Contract redirect");
    await waitForText(page, "Redirect first.");
    const redirectBox = page.locator('textarea[placeholder*="redirect"]').first();
    await redirectBox.fill("Redirect contract message");
    const redirectButton = page.getByTitle("Redirect (interrupt with this message)");
    await redirectButton.click();
    if (await redirectButton.count()) await redirectButton.click({ force: true }).catch(() => {});
    await waitForTurnIdle(apiBase, "contracts_redirect");
    if (interruptPayloads.length !== 2) throw new Error(`Redirect/stop submitted ${interruptPayloads.length - 1} redirect requests`);
    const redirectPayload = interruptPayloads[1];
    if (redirectPayload.message !== "Redirect contract message") throw new Error(`Unexpected redirect payload: ${JSON.stringify(redirectPayload)}`);

    await context.close();
  } catch (error) {
    if (browser) {
      const pages = browser.contexts().flatMap((item) => item.pages());
      if (pages[0]) {
        await pages[0].screenshot({ path: path.join(os.tmpdir(), "spark-chat-contracts-failure.png"), fullPage: true });
        console.error("\n--- visible buttons ---\n", await pages[0].locator("button").allTextContents());
        console.error("\n--- body excerpt ---\n", (await pages[0].locator("body").innerText()).slice(0, 4000));
      }
    }
    console.error("\n--- backend logs ---\n", backend.logs.join("").slice(-12_000));
    console.error("\n--- vite logs ---\n", vite.logs.join("").slice(-12_000));
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
