import { spawn, spawnSync } from "node:child_process";
import { access, cp, mkdir, mkdtemp, rename, rm, writeFile } from "node:fs/promises";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";
import { parseArgs } from "node:util";

const { values: options } = parseArgs({ options: {
  repeat: { type: "string", default: process.env.SPARK_E2E_REPEAT || "1" },
  "output-dir": { type: "string", default: process.env.SPARK_E2E_OUTPUT_DIR },
  case: { type: "string", default: process.env.SPARK_E2E_BASELINE_CASE },
} });
const repeat = Number(options.repeat);
if (!Number.isInteger(repeat) || repeat < 1 || repeat > 10) throw new Error("--repeat must be 1..10");
if (repeat > 1 && !options["output-dir"]) throw new Error("--repeat requires --output-dir");

const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(webRoot, "../../..");
const pythonBin = process.env.PYTHON || path.join(repoRoot, ".venv", "bin", "python");
const viteBin = path.join(webRoot, "node_modules", ".bin", "vite");
const screenshotsRoot = path.join(webRoot, "screenshots", "baseline", "thread");
const reportsRoot = path.join(webRoot, "e2e", "reports");
const fixtureSizes = [50, 500, 2000];
const viewports = [1440, 1024, 768];
const themes = [
  { id: "codex", name: "dark" },
  { id: "daylight", name: "light" },
];
const viewportHeight = 900;
const baselineSessionPrefix = "baseline_thread";
const historyPageSize = 50;
const streamTokenCount = 16;

function parseCaseFilter(value) {
  if (!value?.trim()) return null;
  const selected = new Set();
  for (const rawCase of value.split(",")) {
    const [theme, sizeText, viewportText] = rawCase.trim().split(":");
    const size = Number(sizeText);
    const viewport = Number(viewportText);
    if (!themes.some((candidate) => candidate.name === theme)
      || !fixtureSizes.includes(size)
      || !viewports.includes(viewport)) {
      throw new Error(
        `Invalid SPARK_E2E_BASELINE_CASE "${rawCase}"; expected theme:size:viewport`,
      );
    }
    selected.add(`${theme}:${size}:${viewport}`);
  }
  return selected;
}

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

function seedFixtures(sparkHome) {
  const script = String.raw`
from core.spark_state import SessionDB

base_timestamp = 1700000000.0
db = SessionDB()
try:
    for size in (50, 500, 2000):
        session_id = f"baseline_thread_{size}"
        db.create_session(session_id, "baseline", model="test-model")
        db.set_session_title(session_id, f"Baseline thread {size} rows")
        for index in range(size):
            if index % 2 == 0:
                content = f"Prompt {index + 1:04d}: inspect the deterministic baseline row."
                role = "user"
            else:
                content = (
                    f"Response {index + 1:04d}: this is a deterministic assistant row "
                    f"for the {size}-row transcript.\n\n"
                    + ("Additional measured text. " * (1 + index % 5))
                )
                if index % 10 == 1:
                    content += (
                        "\n" + chr(96) * 3 + "python\n"
                        "def measured_row(index):\n    return index * 2\n"
                        + chr(96) * 3 + "\n"
                    )
                role = "assistant"
            db.append_message(session_id, role, content=content)

        rows = db._conn.execute(
            "SELECT id FROM messages WHERE session_id = ? ORDER BY id", (session_id,)
        ).fetchall()
        db._conn.execute(
            "UPDATE sessions SET started_at = ? WHERE id = ?",
            (base_timestamp + size, session_id),
        )
        for offset, row in enumerate(rows):
            db._conn.execute(
                "UPDATE messages SET timestamp = ? WHERE id = ?",
                (base_timestamp + size + offset / 1000, row["id"]),
            )
    stream_session_id = "baseline_thread_stream"
    db.create_session(stream_session_id, "baseline", model="test-model")
    db.set_session_title(stream_session_id, "Baseline stream probe")
    db.append_message(stream_session_id, "user", content="Ready for the deterministic stream probe.")
    db._conn.commit()
finally:
    db.close()
`;
  const result = spawnSync(pythonBin, ["-c", script], {
    cwd: repoRoot,
    env: {
      ...process.env,
      PYTHONPATH: path.join(repoRoot, "src"),
      SPARK_HOME: sparkHome,
    },
    encoding: "utf8",
  });
  if (result.status !== 0) {
    throw new Error(`Fixture seed failed (${result.status}): ${result.stderr || result.stdout}`);
  }
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
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
  throw new Error(`Timed out waiting for ${sessionId} to become idle: ${JSON.stringify(lastStatus)}`);
}

async function createEmptyStreamSession(apiBase, sessionId, title) {
  const response = await fetch(`${apiBase}/api/dev/fake-streams`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      title,
      message: `Prepare ${title}`,
      events: [],
    }),
  });
  if (!response.ok) {
    throw new Error(`Stream session setup failed: ${response.status} ${await response.text()}`);
  }
  await waitForTurnIdle(apiBase, sessionId);
}

async function createStreamProbe(apiBase, sessionId, title, marker) {
  const events = Array.from({ length: streamTokenCount }, (_, index) => ({
    type: "token",
    text: `${marker} token ${index + 1}. `,
    delay_ms: 60,
  }));
  const response = await fetch(`${apiBase}/api/dev/fake-streams`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      title,
      message: `Stream probe ${marker}`,
      reuse_existing: true,
      events,
    }),
  });
  if (!response.ok) {
    throw new Error(`Stream probe failed: ${response.status} ${await response.text()}`);
  }
}

async function waitForChatSession(page, sessionId, title) {
  const titleButton = page.getByRole("button", {
    name: new RegExp(escapeRegExp(title)),
  }).first();
  await titleButton.waitFor({ timeout: 15_000 });
  await titleButton.click();
  await page.locator('[data-testid="chat-panel"]').waitFor({ timeout: 15_000 });
  await page.waitForFunction(
    (id) => document.querySelector('[data-testid="chat-panel"]')?.getAttribute("data-session-id") === id,
    sessionId,
  );
  await page.locator('[data-testid="chat-panel"] [data-row-id]').first().waitFor({ timeout: 15_000 });
}

async function loadEarlierMessages(page, { sessionId, title, expectedRows }) {
  const initialUrl = page.url();
  const seenBeforeIds = new Set();
  let pagesLoaded = 0;
  let attempts = 0;
  let sameUrlReloads = 0;
  let mainFrameNavigations = 0;
  const onFrameNavigated = (frame) => {
    if (frame === page.mainFrame()) mainFrameNavigations += 1;
  };
  page.on("framenavigated", onFrameNavigated);

  const recoverSameUrlReload = async () => {
    if (page.url() !== initialUrl) {
      throw new Error(`History paging navigated away: ${initialUrl} -> ${page.url()}`);
    }
    sameUrlReloads += 1;
    if (sameUrlReloads > 2) {
      throw new Error(`History paging reloaded ${sameUrlReloads} times at ${initialUrl}`);
    }
    await page.waitForLoadState("domcontentloaded");
    await waitForChatSession(page, sessionId, title);
    seenBeforeIds.clear();
    pagesLoaded = 0;
  };

  try {
    let handledNavigations = mainFrameNavigations;
    while (true) {
      if (mainFrameNavigations > handledNavigations) {
        handledNavigations = mainFrameNavigations;
        await recoverSameUrlReload();
        handledNavigations = mainFrameNavigations;
      }

      // A history refresh briefly hides the paging control. Its absence alone
      // cannot establish completion; require settled state and all fixture rows.
      await page.waitForFunction(({ sessionId, expectedRows }) => {
        const panel = document.querySelector('[data-testid="chat-panel"]');
        if (panel?.getAttribute("data-session-id") !== sessionId
          || panel.getAttribute("data-history-loading") !== "false") return false;
        return panel.getAttribute("data-history-has-earlier") === "true"
          || Number(panel.getAttribute("data-history-message-count")) >= expectedRows;
      }, { sessionId, expectedRows }, { timeout: 15_000 });
      const complete = await page.locator('[data-testid="chat-panel"]').evaluate((panel, expectedRows) => (
        panel.getAttribute("data-history-has-earlier") === "false"
        && Number(panel.getAttribute("data-history-message-count")) >= expectedRows
      ), expectedRows);
      if (complete) break;
      const button = page.getByRole("button", { name: "Load earlier messages", exact: true });
      await button.first().waitFor({ state: "visible", timeout: 15_000 });
      await page.waitForFunction(() => {
        const candidate = [...document.querySelectorAll("button")]
          .find((element) => element.textContent?.trim() === "Load earlier messages");
        return Boolean(candidate && !candidate.disabled);
      });

      attempts += 1;
      if (attempts > 150) throw new Error("History pagination exceeded 150 attempts");
      const navigationBeforeClick = mainFrameNavigations;
      let removeNavigationListener;
      const navigation = new Promise((resolve) => {
        const listener = (frame) => {
          if (frame !== page.mainFrame()) return;
          page.off("framenavigated", listener);
          resolve({ type: "navigation" });
        };
        removeNavigationListener = () => page.off("framenavigated", listener);
        page.on("framenavigated", listener);
      });
      const response = page.waitForResponse((candidate) => {
        const url = new URL(candidate.url());
        return url.pathname.endsWith(`/api/sessions/${sessionId}/messages`)
          && Boolean(url.searchParams.get("before_id"));
      }, { timeout: 15_000 }).then((candidate) => ({ type: "response", response: candidate }), (error) => ({ type: "timeout", error: String(error) }));
      let timeoutId;
      const timeout = new Promise((resolve) => {
        timeoutId = setTimeout(() => resolve({ type: "timeout" }), 15_000);
      });

      await button.first().evaluate((element) => {
        if (!(element instanceof HTMLButtonElement) || element.disabled) {
          throw new Error("Load earlier messages was not an enabled button");
        }
        element.click();
      });
      const result = await Promise.race([response, navigation, timeout]);
      clearTimeout(timeoutId);
      removeNavigationListener?.();

      if (result.type === "navigation" || mainFrameNavigations > navigationBeforeClick) {
        handledNavigations = mainFrameNavigations;
        await recoverSameUrlReload();
        handledNavigations = mainFrameNavigations;
        continue;
      }
      if (result.type === "timeout") {
        throw new Error(`History page request timed out for ${sessionId}`);
      }

      const responseUrl = new URL(result.response.url());
      const beforeId = responseUrl.searchParams.get("before_id");
      if (!result.response.ok()) {
        throw new Error(
          `History page request failed ${result.response.status()} for before_id=${beforeId}`,
        );
      }
      if (!beforeId || seenBeforeIds.has(beforeId)) {
        throw new Error(`History paging made no forward progress at before_id=${beforeId}`);
      }
      seenBeforeIds.add(beforeId);
      pagesLoaded += 1;
      await page.waitForFunction(() => {
        const candidate = [...document.querySelectorAll("button")]
          .find((element) => /^(Load earlier messages|Loading…)$/.test(element.textContent?.trim() ?? ""));
        return !candidate || (!candidate.disabled && candidate.textContent?.trim() === "Load earlier messages");
      }, undefined, { timeout: 15_000 });
    }
  } finally {
    page.off("framenavigated", onFrameNavigated);
  }

  return { pagesLoaded, attempts, sameUrlReloads };
}

function createBrowserInitScript() {
  return ({ theme }) => {
    localStorage.setItem("spark-webui-theme", theme);
    localStorage.setItem("spark-web-efficiency-test", "1");
    window.__sparkBaselineInstrumentation = {
      resizeObserver: { constructed: 0, observedTargets: 0, callbacks: 0, callbackEntries: 0 },
    };
    const metrics = window.__sparkBaselineInstrumentation.resizeObserver;
    const NativeResizeObserver = window.ResizeObserver;
    if (!NativeResizeObserver) return;
    window.ResizeObserver = class extends NativeResizeObserver {
      constructor(callback) {
        metrics.constructed += 1;
        super((entries, observer) => {
          metrics.callbacks += 1;
          metrics.callbackEntries += entries.length;
          callback(entries, observer);
        });
      }

      observe(target, options) {
        metrics.observedTargets += 1;
        return super.observe(target, options);
      }
    };
  };
}

async function performanceMetrics(page) {
  const session = await page.context().newCDPSession(page);
  await session.send("Performance.enable");
  const response = await session.send("Performance.getMetrics");
  return Object.fromEntries(response.metrics.map((metric) => [metric.name, metric.value]));
}

async function readAnchor(page) {
  return page.evaluate(() => {
    const panel = document.querySelector('[data-testid="chat-panel"]');
    const scroll = panel?.querySelector('[data-testid="chat-scroll"]');
    if (!(scroll instanceof HTMLElement)) return null;
    const bounds = scroll.getBoundingClientRect();
    const row = [...scroll.querySelectorAll("[data-row-id]")]
      .find((candidate) => {
        const rect = candidate.getBoundingClientRect();
        return rect.bottom > bounds.top + 1 && rect.top < bounds.bottom - 1;
      });
    if (!row) return null;
    return {
      id: row.getAttribute("data-row-id"),
      top: row.getBoundingClientRect().top,
      scrollTop: scroll.scrollTop,
    };
  });
}

async function waitForStableAnchor(page, timeoutMs = 3_000) {
  const deadline = Date.now() + timeoutMs;
  let previous = null;
  let stableSamples = 0;
  while (Date.now() < deadline) {
    await page.waitForTimeout(50);
    const current = await readAnchor(page);
    if (current && previous?.id === current.id && Math.abs(previous.top - current.top) <= 0.5) {
      stableSamples += 1;
      if (stableSamples >= 2) return current;
    } else {
      stableSamples = 0;
    }
    previous = current;
  }
  return null;
}

async function measureScrollDrift(page) {
  const scroll = page.getByTestId("chat-scroll");
  await scroll.evaluate((element) => new Promise((resolve) => {
    let frames = 45;
    const holdAtSample = () => requestAnimationFrame(() => {
      element.scrollTop = Math.min(500, element.scrollHeight);
      frames -= 1;
      if (frames > 0) holdAtSample();
      else resolve(undefined);
    });
    holdAtSample();
  }));
  await page.waitForFunction(() => {
    const scrollElement = document.querySelector('[data-testid="chat-scroll"]');
    if (!(scrollElement instanceof HTMLElement)) return false;
    const bounds = scrollElement.getBoundingClientRect();
    return [...scrollElement.querySelectorAll("[data-row-id]")].some((candidate) => {
      const rect = candidate.getBoundingClientRect();
      return rect.bottom > bounds.top + 1 && rect.top < bounds.bottom - 1;
    });
  }, undefined, { timeout: 3_000 });
  const before = await waitForStableAnchor(page);
  await page.waitForTimeout(250);
  const after = before?.id
    ? await page.evaluate((id) => {
        const row = document.querySelector(`[data-row-id="${CSS.escape(id)}"]`);
        const scrollElement = document.querySelector('[data-testid="chat-scroll"]');
        if (!(row instanceof HTMLElement) || !(scrollElement instanceof HTMLElement)) return null;
        return { id, top: row.getBoundingClientRect().top, scrollTop: scrollElement.scrollTop };
      }, before.id)
    : null;
  await scroll.evaluate((element) => { element.scrollTop = 0; });
  return {
    before,
    after,
    sameRow: Boolean(before && after && before.id === after.id),
    driftPx: before && after && before.id === after.id ? after.top - before.top : null,
  };
}

async function measureStream(page, apiBase, marker) {
  const sessionId = `${baselineSessionPrefix}_stream_${marker.replace(/[^a-z0-9]+/gi, "_")}`;
  const title = `Baseline stream ${marker}`;
  await createEmptyStreamSession(apiBase, sessionId, title);
  await page.reload({ waitUntil: "domcontentloaded" });
  await waitForChatSession(page, sessionId, title);
  const streamNavigations = [];
  const onStreamNavigation = (frame) => {
    if (frame === page.mainFrame()) streamNavigations.push({ url: frame.url(), at: performance.now() });
  };
  page.on("framenavigated", onStreamNavigation);
  await page.evaluate(({ sampleMarker, expectedTokens }) => {
    const panel = document.querySelector('[data-testid="chat-panel"]');
    const samples = [];
    if (!panel) throw new Error("Chat panel missing for stream instrumentation");
    // A diagnostic comparison only: authoritative samples still come from the
    // original fixed-panel observer. Never use this series to rescue a failure.
    const freshSamples = [];
    const identity = [];
    let previousPanel = panel;
    let freshLastVisibleTokens = 0;
    const freshCapture = () => {
      const current = document.querySelector('[data-testid="chat-panel"]');
      const text = current?.textContent ?? "";
      let visibleTokens = 0;
      for (let index = 1; index <= expectedTokens; index += 1) {
        if (text.includes(`${sampleMarker} token ${index}.`)) visibleTokens += 1;
      }
      if (current !== previousPanel || visibleTokens > freshLastVisibleTokens) {
        identity.push({ at: performance.now(), originalConnected: panel.isConnected,
          currentIsOriginal: current === panel, currentConnected: current?.isConnected ?? false,
          currentSession: current?.getAttribute("data-session-id") ?? null,
          panelReplaced: current !== previousPanel, visibleTokens });
      }
      previousPanel = current;
      if (visibleTokens <= freshLastVisibleTokens) return;
      freshLastVisibleTokens = visibleTokens;
      freshSamples.push({ at: performance.now(), visibleTokens,
        visibleChars: Number(current.getAttribute("data-stream-visible-chars") || 0),
        streaming: current.getAttribute("data-streaming") });
    };
    const freshObserver = new MutationObserver(freshCapture);
    freshObserver.observe(document.body, { attributes: true,
      attributeFilter: ["data-stream-visible-chars", "data-streaming", "data-session-id"],
      childList: true, characterData: true, subtree: true });
    let lastVisibleTokens = 0;
    const capture = () => {
      const text = panel.textContent ?? "";
      let visibleTokens = 0;
      for (let index = 1; index <= expectedTokens; index += 1) {
        if (text.includes(`${sampleMarker} token ${index}.`)) visibleTokens += 1;
      }
      if (visibleTokens <= lastVisibleTokens) return;
      lastVisibleTokens = visibleTokens;
      samples.push({
        at: performance.now(),
        visibleTokens,
        visibleChars: Number(panel.getAttribute("data-stream-visible-chars") || 0),
        streaming: panel.getAttribute("data-streaming"),
      });
    };
    const observer = new MutationObserver(capture);
    observer.observe(panel, {
      attributes: true,
      attributeFilter: ["data-stream-visible-chars", "data-streaming"],
      childList: true,
      characterData: true,
      subtree: true,
    });
    window.__sparkWebEfficiency?.snapshot?.(true);
    window.__sparkStreamTrace = {
      startedAt: performance.now(),
      samples,
      observer,
      capture,
      freshCapture,
      freshObserver,
      freshSamples,
      identity,
      nodeState: () => ({
        originalConnected: panel.isConnected,
        currentIsOriginal: document.querySelector('[data-testid="chat-panel"]') === panel,
        originalSession: panel.getAttribute("data-session-id"),
        currentSession: document.querySelector('[data-testid="chat-panel"]')?.getAttribute("data-session-id") ?? null,
      }),
      marker: sampleMarker,
      expectedTokens,
      timeOrigin: performance.timeOrigin,
    };
    sessionStorage.removeItem("spark-stream-observation-archive");
    window.addEventListener("pagehide", () => {
      capture(); freshCapture();
      const trace = window.__sparkStreamTrace;
      sessionStorage.setItem("spark-stream-observation-archive", JSON.stringify({
        timeOrigin: trace.timeOrigin, startedAt: trace.startedAt, expectedTokens,
        samples, freshSamples, identity, originalConnected: panel.isConnected,
        currentIsOriginal: document.querySelector('[data-testid="chat-panel"]') === panel,
      }));
    }, { once: true });
  }, { sampleMarker: marker, expectedTokens: streamTokenCount });
  await createStreamProbe(apiBase, sessionId, title, marker);
  await page.waitForFunction(({ sampleMarker, expectedTokens }) => {
    const text = document.querySelector('[data-testid="chat-panel"]')?.textContent ?? "";
    return text.includes(`${sampleMarker} token ${expectedTokens}.`);
  }, { sampleMarker: marker, expectedTokens: streamTokenCount }, { timeout: 15_000 });
  await waitForTurnIdle(apiBase, sessionId);
  await page.waitForTimeout(150);
  page.off("framenavigated", onStreamNavigation);
  return page.evaluate((streamNavigations) => {
    const trace = window.__sparkStreamTrace;
    trace?.capture();
    trace?.observer.disconnect();
    trace?.freshCapture();
    trace?.freshObserver.disconnect();
    const samples = trace?.samples ?? [];
    const last = samples.at(-1)?.at ?? null;
    const elapsedMs = last == null || trace?.startedAt == null
      ? null
      : Math.max(0, last - trace.startedAt);
    const efficiency = window.__sparkWebEfficiency?.snapshot?.() ?? null;
    return {
      samples,
      observationDiagnostic: { freshSamples: trace?.freshSamples, identity: trace?.identity,
        tracePresent: Boolean(trace),
        nodeState: trace?.nodeState(),
        timeOrigin: performance.timeOrigin, traceTimeOrigin: trace?.timeOrigin,
        streamNavigations, archived: JSON.parse(sessionStorage.getItem("spark-stream-observation-archive") || "null") },
      startedAt: trace?.startedAt,
      firstVisibleTokenMs: samples.length ? samples[0].at - trace.startedAt : null,
      syntheticInitialDelayMs: 60,
      firstVisibleMinusSyntheticDelayMs: samples.length ? samples[0].at - trace.startedAt - 60 : null,
      maxVisibleUpdateGapMs: samples.length > 1 ? Math.max(...samples.slice(1).map((sample, index) => sample.at - samples[index].at)) : null,
      updateCount: samples.length,
      elapsedMs,
      updatesPerSecond: elapsedMs && elapsedMs > 0 ? samples.length / (elapsedMs / 1000) : null,
      expectedTokenCount: trace?.expectedTokens ?? null,
      finalVisibleTokenCount: samples.at(-1)?.visibleTokens ?? 0,
      efficiency,
    };
  }, streamNavigations);
}

async function captureCase({ browser, apiBase, webBase, screenshotRoot, size, viewport, theme }) {
  const sessionId = `${baselineSessionPrefix}_${size}`;
  const title = `Baseline thread ${size} rows`;
  const context = await browser.newContext({
    viewport: { width: viewport, height: viewportHeight },
    deviceScaleFactor: 1,
  });
  await context.addInitScript(createBrowserInitScript(), { theme: theme.id });
  const page = await context.newPage();
  const historyRequests = [];
  const historyResponses = [];
  const pageErrors = [];
  const consoleErrors = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.endsWith(`/api/sessions/${sessionId}/messages`)) {
      historyRequests.push({
        at: performance.now(),
        limit: Number(url.searchParams.get("limit") || 0),
        beforeId: url.searchParams.get("before_id"),
      });
    }
  });
  page.on("response", (response) => {
    if (new URL(response.url()).pathname.endsWith(`/api/sessions/${sessionId}/messages`)) historyResponses.push({ url: response.url(), status: response.status(), at: performance.now() });
  });
  page.on("pageerror", (error) => pageErrors.push(String(error)));
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });

  const startedAt = performance.now();
  try {
    await page.goto(`${webBase}/?spark_efficiency_test=1`, { waitUntil: "domcontentloaded" });
    await waitForChatSession(page, sessionId, title);
    const firstRenderMs = performance.now() - startedAt;
    await page.waitForTimeout(150);
    const paging = await loadEarlierMessages(page, { sessionId, title, expectedRows: size });
    await page.waitForTimeout(250);
    const fullyLoaded = await page.getByRole("button", { name: /^(Load earlier messages|Loading…)$/ }).count() === 0;
    if (!fullyLoaded) throw new Error(`History remained paged for ${size} rows`);

    const scrollDrift = await measureScrollDrift(page);
    const instrumentation = await page.evaluate(() => window.__sparkBaselineInstrumentation);
    const efficiency = await page.evaluate(() => window.__sparkWebEfficiency?.snapshot?.() ?? null);
    const mountedRows = await page.locator('[data-testid="chat-panel"] [data-row-id]').count();
    const browserPerformance = await performanceMetrics(page);
    const navigationTiming = await page.evaluate(() => {
      const entry = performance.getEntriesByType("navigation")[0];
      return entry ? {
        type: entry.type,
        startTime: entry.startTime,
        domContentLoadedEventEnd: entry.domContentLoadedEventEnd,
        loadEventEnd: entry.loadEventEnd,
        duration: entry.duration,
      } : null;
    });
    const screenshotRelativePath = path.join(
      "src", "spark_cli", "web", "screenshots", "baseline", "thread",
      theme.name,
      `${size}-w${viewport}.png`,
    );
    const screenshotPath = path.join(screenshotRoot, theme.name, `${size}-w${viewport}.png`);
    await mkdir(path.dirname(screenshotPath), { recursive: true });
    await page.screenshot({ path: screenshotPath, fullPage: false });
    const stream = await measureStream(page, apiBase, `${size}-${theme.name}-${viewport}`);
    return {
      fixtureRows: size,
      viewport: { width: viewport, height: viewportHeight, deviceScaleFactor: 1 },
      theme: { id: theme.id, name: theme.name },
      firstRenderMs: Math.round(firstRenderMs * 100) / 100,
      navigationTiming,
      history: {
        ...paging,
        fullyLoaded,
        requestCount: historyRequests.length,
        requests: historyRequests,
        mountedRows,
      },
      efficiency,
      resizeObserver: instrumentation?.resizeObserver ?? null,
      performance: browserPerformance,
      scrollDrift,
      stream,
      screenshot: options["output-dir"] ? screenshotPath : screenshotRelativePath,
      errors: { page: pageErrors, console: consoleErrors },
    };
  } catch (error) {
    const diagnostic = {
      error: error.stack, historyRequests, historyResponses, pageErrors, consoleErrors,
      url: page.url(),
      state: await page.evaluate(() => ({
        session: document.querySelector('[data-testid="chat-panel"]')?.getAttribute("data-session-id"),
        buttons: [...document.querySelectorAll("button")].filter((el) => /Load earlier|Loading/.test(el.textContent)).map((el) => ({ text: el.textContent, disabled: el.disabled })),
        mountedRows: [...document.querySelectorAll("[data-row-id]")].map((el) => el.getAttribute("data-row-id")),
        streamObservation: {
          timeOrigin: performance.timeOrigin,
          tracePresent: Boolean(window.__sparkStreamTrace),
          traceTimeOrigin: window.__sparkStreamTrace?.timeOrigin,
          samples: window.__sparkStreamTrace?.samples,
          freshSamples: window.__sparkStreamTrace?.freshSamples,
          identity: window.__sparkStreamTrace?.identity,
          nodeState: window.__sparkStreamTrace?.nodeState(),
          archived: JSON.parse(sessionStorage.getItem("spark-stream-observation-archive") || "null"),
        },
      })).catch(() => null),
    };
    await mkdir(screenshotRoot, { recursive: true });
    const stem = `${theme.name}-${size}-w${viewport}-failure`;
    await writeFile(path.join(screenshotRoot, `${stem}.json`), JSON.stringify(diagnostic, null, 2));
    await page.screenshot({ path: path.join(screenshotRoot, `${stem}.png`) }).catch(() => {});
    throw error;
  } finally {
    await context.close();
  }
}

function buildTemporaryWeb(outDir) {
  const result = spawnSync(
    viteBin,
    ["build", webRoot, "--outDir", outDir, "--emptyOutDir", "--logLevel", "warn"],
    { cwd: webRoot, env: process.env, encoding: "utf8" },
  );
  if (result.status !== 0) {
    throw new Error(`Temporary web build failed (${result.status}): ${result.stderr || result.stdout}`);
  }
}

async function validateCaseResult(result, stagedScreenshotRoot) {
  const expectedPages = Math.ceil(result.fixtureRows / historyPageSize) - 1;
  const label = `${result.theme.name}:${result.fixtureRows}:${result.viewport.width}`;
  if (!result.history.fullyLoaded || result.history.pagesLoaded !== expectedPages) {
    throw new Error(
      `${label} history incomplete: ${result.history.pagesLoaded}/${expectedPages} pages`,
    );
  }
  if (!result.efficiency || result.efficiency.reactCommits <= 0) {
    throw new Error(`${label} did not expose guarded React commit metrics`);
  }
  if (!result.resizeObserver || result.resizeObserver.callbacks <= 0) {
    throw new Error(`${label} did not record ResizeObserver churn`);
  }
  for (const metric of ["JSHeapUsedSize", "JSHeapTotalSize", "Nodes", "LayoutCount", "RecalcStyleCount"]) {
    if (!Number.isFinite(result.performance?.[metric])) {
      throw new Error(`${label} is missing browser performance metric ${metric}`);
    }
  }
  if (!result.scrollDrift.before || !result.scrollDrift.after
    || !Number.isFinite(result.scrollDrift.driftPx)) {
    throw new Error(`${label} did not record a stable scroll-drift sample: ${JSON.stringify(result.scrollDrift)}`);
  }
  const observation = result.stream.observationDiagnostic;
  if (!observation.tracePresent) {
    throw new Error(`${label} stream observation trace missing from current document; capture invalid (navigation/pagehide diagnostics retained, archived samples are not substituted)`);
  }
  if (observation.timeOrigin !== observation.traceTimeOrigin || observation.streamNavigations.length > 0) {
    throw new Error(`${label} stream document changed during capture; continuity measurement invalid`);
  }
  if (result.stream.updateCount <= 0
    || !Number.isFinite(result.stream.elapsedMs)
    || result.stream.elapsedMs <= 0
    || result.stream.finalVisibleTokenCount !== streamTokenCount
    || result.stream.efficiency?.eventPayloads <= 0) {
    throw new Error(`${label} stream probe did not produce nonzero rendered updates and events`);
  }
  if (result.errors.page.length > 0 || result.errors.console.length > 0) {
    throw new Error(`${label} emitted browser errors: ${JSON.stringify(result.errors)}`);
  }
  await access(path.join(
    stagedScreenshotRoot,
    result.theme.name,
    `${result.fixtureRows}-w${result.viewport.width}.png`,
  ));
}

async function publishOutputs(stagedScreenshotRoot, stagedReportPath, reportName) {
  const screenshotsParent = path.dirname(screenshotsRoot);
  const reportsParent = path.dirname(reportsRoot);
  const nextScreenshots = path.join(screenshotsParent, `.thread-next-${process.pid}`);
  const nextReports = path.join(reportsParent, `.reports-next-${process.pid}`);
  await rm(nextScreenshots, { recursive: true, force: true });
  await rm(nextReports, { recursive: true, force: true });
  await cp(stagedScreenshotRoot, nextScreenshots, { recursive: true });
  await mkdir(nextReports, { recursive: true });
  await cp(stagedReportPath, path.join(nextReports, reportName));
  await rm(screenshotsRoot, { recursive: true, force: true });
  await rename(nextScreenshots, screenshotsRoot);
  await rm(reportsRoot, { recursive: true, force: true });
  await rename(nextReports, reportsRoot);
}

async function run(iteration) {
  const caseFilter = parseCaseFilter(options.case);
  const apiPort = await freePort();
  const webPort = await freePort();
  const sparkHome = await mkdtemp(path.join(os.tmpdir(), "spark-thread-baseline-"));
  const stagedOutputRoot = options["output-dir"]
    ? path.resolve(options["output-dir"], `run-${String(iteration).padStart(2, "0")}`)
    : await mkdtemp(path.join(os.tmpdir(), "spark-thread-baseline-output-"));
  await mkdir(stagedOutputRoot, { recursive: true });
  const cases = [];
  let backendReadyMs;
  const stagedScreenshotRoot = path.join(stagedOutputRoot, "screenshots");
  const stagedBuildRoot = path.join(stagedOutputRoot, "web-build");
  await writeFile(
    path.join(sparkHome, "config.yaml"),
    "model:\n  default: test-model\n  provider: ollama\n  base_url: http://127.0.0.1:1/v1\n",
  );
  seedFixtures(sparkHome);

  const apiBase = `http://127.0.0.1:${apiPort}`;
  const webBase = `http://127.0.0.1:${webPort}`;
  const backendStartedAt = performance.now();
  const backend = startProcess(
    pythonBin,
    [
      "-c",
      "from spark_cli.web_server import start_server; import sys; start_server('127.0.0.1', int(sys.argv[1]), False)",
      String(apiPort),
    ],
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
  const vite = startProcess(
    viteBin,
    [webRoot, "--host", "127.0.0.1", "--port", String(webPort)],
    { cwd: webRoot, env: { ...process.env, SPARK_API_TARGET: apiBase } },
  );

  let browser;
  try {
    await waitFor(`${apiBase}/api/status`);
    backendReadyMs = performance.now() - backendStartedAt;
    buildTemporaryWeb(stagedBuildRoot);
    await waitFor(webBase);
    browser = await chromium.launch({ headless: true });
    for (const theme of themes) {
      for (const size of fixtureSizes) {
        for (const viewport of viewports) {
          const caseKey = `${theme.name}:${size}:${viewport}`;
          if (caseFilter && !caseFilter.has(caseKey)) continue;
          process.stdout.write(`Capturing ${theme.name} ${size} rows at ${viewport}px…\n`);
          const result = await captureCase({
            browser,
            apiBase,
            webBase,
            screenshotRoot: stagedScreenshotRoot,
            size,
            viewport,
            theme,
          });
          cases.push(result);
          await validateCaseResult(result, stagedScreenshotRoot);
        }
      }
    }

    if (!caseFilter && cases.length !== fixtureSizes.length * viewports.length * themes.length) {
      throw new Error(`Expected 18 baseline cases, captured ${cases.length}`);
    }

    const commit = spawnSync("git", ["rev-parse", "--short", "HEAD"], {
      cwd: repoRoot,
      encoding: "utf8",
    }).stdout.trim() || "working-tree";
    const reportName = `baseline-${commit}.json`;
    const stagedReportPath = path.join(stagedOutputRoot, reportName);
    const report = {
      schema: "spark.web.baseline.v1",
      capturedAt: new Date().toISOString(),
      backendReadyMs,
      mode: "dev",
      iteration,
      caseFilter: options.case ?? null,
      source: {
        commit,
        branch: spawnSync("git", ["branch", "--show-current"], { cwd: repoRoot, encoding: "utf8" }).stdout.trim(),
        browser: await browser.version(),
        node: process.version,
        nodeExecutable: process.execPath,
      },
      fixtureSizes,
      viewports: viewports.map((width) => ({ width, height: viewportHeight, deviceScaleFactor: 1 })),
      themes,
      cases,
      summary: {
        caseCount: cases.length,
        streamUpdateCount: cases.reduce((total, item) => total + item.stream.updateCount, 0),
        pageErrorCount: cases.reduce((total, item) => total + item.errors.page.length, 0),
        consoleErrorCount: cases.reduce((total, item) => total + item.errors.console.length, 0),
      },
      notes: [
        "This is a raw current-state baseline, not redesign acceptance evidence.",
        "Rows are deterministic user/assistant messages seeded into a temporary SPARK_HOME.",
        "Efficiency counters are exposed only when the explicit spark_efficiency_test flag is present.",
      ],
    };
    await writeFile(stagedReportPath, `${JSON.stringify(report, null, 2)}\n`);
    if (caseFilter || options["output-dir"]) {
      process.stdout.write(`Validated ${cases.length} baseline case(s); report: ${stagedReportPath}; canonical outputs unchanged.\n`);
    } else {
      await publishOutputs(stagedScreenshotRoot, stagedReportPath, reportName);
      process.stdout.write(`Wrote ${path.relative(repoRoot, path.join(reportsRoot, reportName))}\n`);
    }
  } catch (error) {
    await writeFile(path.join(stagedOutputRoot, "failure.json"), JSON.stringify({ iteration, error: error.stack, backendReadyMs, cases }, null, 2));
    await writeFile(path.join(stagedOutputRoot, "backend.log"), backend.logs.join(""));
    await writeFile(path.join(stagedOutputRoot, "vite.log"), vite.logs.join(""));
    console.error("\n--- baseline backend logs ---\n", backend.logs.join("").slice(-12_000));
    console.error("\n--- baseline vite logs ---\n", vite.logs.join("").slice(-12_000));
    throw error;
  } finally {
    if (browser) await browser.close();
    await stopProcess(vite);
    await stopProcess(backend);
    if (!process.env.SPARK_E2E_KEEP_HOME) await rm(sparkHome, { recursive: true, force: true });
    if (!options["output-dir"] && !process.env.SPARK_E2E_KEEP_OUTPUT) await rm(stagedOutputRoot, { recursive: true, force: true });
    else process.stdout.write(`Retained evidence: ${stagedOutputRoot}\n`);
  }
}

let failed = false;
for (let iteration = 1; iteration <= repeat; iteration += 1) {
  try { await run(iteration); }
  catch (error) { console.error(error); failed = true; }
}
process.exitCode = failed ? 1 : 0;
