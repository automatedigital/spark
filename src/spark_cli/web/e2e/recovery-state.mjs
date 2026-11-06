import { spawn } from "node:child_process";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const webRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const repoRoot = process.env.SP02_SOURCE_ROOT || path.resolve(webRoot, "../../..");
const python = process.env.PYTHON || path.join(repoRoot, ".venv/bin/python");
const port = () =>
  new Promise((resolve) => {
    const s = net.createServer();
    s.listen(0, "127.0.0.1", () => {
      const p = s.address().port;
      s.close(() => resolve(p));
    });
  });
const wait = async (url) => {
  for (let i = 0; i < 180; i++) {
    try {
      const r = await fetch(url);
      if (r.ok) return;
    } catch {}
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(`Timed out: ${url}`);
};
const start = (cmd, args, opts) => {
  const child = spawn(cmd, args, {
    ...opts,
    stdio: ["ignore", "pipe", "pipe"],
  });
  child.stdout.on("data", (b) => {
    if (process.env.E2E_VERBOSE) process.stderr.write(b);
  });
  child.stderr.on("data", (b) => {
    if (process.env.E2E_VERBOSE) process.stderr.write(b);
  });
  return child;
};
const stop = async (p) => {
  if (!p || p.exitCode !== null) return;
  p.kill("SIGTERM");
  await new Promise((r) => setTimeout(r, 700));
  if (p.exitCode === null) p.kill("SIGKILL");
};
async function fake(api, id, title, events) {
  const r = await fetch(`${api}/api/dev/fake-streams`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      session_id: id,
      title,
      message: `${title} prompt`,
      events,
    }),
  });
  if (!r.ok) throw new Error(await r.text());
}
async function run() {
  const apiPort = await port();
  const webPort = await port();
  const home = await mkdtemp(path.join(os.tmpdir(), "spark-recovery-e2e-"));
  await mkdir(path.join(home, "workspace"), { recursive: true });
  await writeFile(
    path.join(home, "config.yaml"),
    "model:\n  default: test-model\n  provider: ollama\n  base_url: http://localhost:11434/v1\n",
  );
  const env = {
    ...process.env,
    SPARK_HOME: home,
    SPARK_WEB_FAKE_STREAMS: "1",
    PYTHONPATH: path.join(repoRoot, "src"),
  };
  const backendArgs = [
    "-c",
    `import spark_cli.web_server as w; w._WEB_TURN_STALE_AFTER_S=1.0; w.start_server(host='127.0.0.1', port=${apiPort}, open_browser=False)`,
  ];
  let backend = start(python, backendArgs, { cwd: repoRoot, env });
  const vite = start(
    path.join(webRoot, "node_modules/.bin/vite"),
    [path.join(repoRoot, "src/spark_cli/web"), "--host", "127.0.0.1", "--port", String(webPort)],
    {
      cwd: webRoot,
      env: { ...process.env, SPARK_API_TARGET: `http://127.0.0.1:${apiPort}` },
    },
  );
  let browser;
  try {
    const api = `http://127.0.0.1:${apiPort}`;
    const web = `http://127.0.0.1:${webPort}`;
    await wait(`${api}/api/status`);
    await wait(web);
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({
      viewport: { width: 1440, height: 980 },
    });
    await page.goto(web);
    await page.getByText("Spark").first().waitFor();
    // The fixture sessions are created before the browser starts. Refresh once
    // after the app shell is ready so the initial session fetch cannot race
    // those writes on slower hosted runners.
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.getByText("Spark").first().waitFor();
    await fake(api, "recovery_stalled", "Recovery stalled", [
      { type: "token", text: "before disconnect" },
      { type: "stall", phase: "api", text: "network stalled" },
      // Hold the provider until the test restarts its owning backend. A five-
      // second stream could finish during page startup, before card assertions.
      { type: "token", text: "after reconnect", delay_ms: 60000 },
    ]);
    await fake(api, "recovery_failed", "Recovery failed", [
      { type: "token", text: "partial failure" },
      { type: "compact_fail", text: "Backend failure", delay_ms: 1200 },
    ]);
    await fake(api, "recovery_approval", "Recovery approval", [
      { type: "approval", args: { command: "Approval required", description: "Approval required" } },
      { type: "token", text: "approval held", delay_ms: 60000 },
    ]);
    await new Promise((r) => setTimeout(r, 500));
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.getByText("Spark").first().waitFor();
    const open = async (title, text) => {
      const button = page
        .getByRole("button", { name: new RegExp(title) })
        .first();
      await button.waitFor({ timeout: 15000 });
      await button.click({ force: true });
      await page
        .getByText(text, { exact: false })
        .first()
        .waitFor({ timeout: 15000 });
    };
    // Establish the backend precondition rather than race the stale threshold.
    let stalled = false;
    for (let i = 0; i < 40; i++) {
      const status = await (await fetch(`${api}/api/conversations/recovery_stalled/turn-status`)).json();
      if (status.turn_active && status.state === "stalled") { stalled = true; break; }
      await page.waitForTimeout(100);
    }
    if (!stalled) throw new Error("Fixture did not retain a stalled backend turn");
    await page.getByText("Running", { exact: false }).first().click();
    await open("Recovery stalled", "before disconnect");
    await page.getByTestId("recovery-card").waitFor({ timeout: 15000 });
    const card = page.getByTestId("recovery-card");
    if ((await card.getAttribute("data-recovery-state")) !== "reconnecting")
      throw new Error("stalled turn did not produce reconnecting card");
    let posts = 0;
    page.on("request", (r) => {
      if (r.method() === "POST" && r.url().includes("/api/conversations/"))
        posts++;
    });
    const reconnect = card.getByRole("button", { name: "Reconnect" });
    await reconnect.focus();
    if (!(await reconnect.evaluate(el => el === document.activeElement))) throw new Error("Reconnect did not receive keyboard focus");
    await page.keyboard.press("Enter");
    if (posts !== 0)
      throw new Error("Reconnect unexpectedly submitted a prompt");
    await page.screenshot({
      path: path.join(webRoot, "screenshots", "e2e-recovery-state.png"),
      fullPage: true,
    });
    await new Promise((r) => setTimeout(r, 2000));
    await page.getByText("Needs you", { exact: false }).first().click();
    await open("Recovery failed", "partial failure");
    await page
      .getByText("Backend failure", { exact: false })
      .first()
      .waitFor({ timeout: 15000 });
    await page.getByTestId("recovery-card").waitFor();
    const approvalStatus = await (
      await fetch(`${api}/api/conversations/recovery_approval/turn-status`)
    ).json();
    if (approvalStatus.phase !== "approval")
      throw new Error(
        `approval phase was not retained by backend: ${JSON.stringify(approvalStatus)}`,
      );
    await page.getByText("Running", { exact: false }).first().click();
    await open("Recovery stalled", "before disconnect");
    const preservedText = page
      .getByText("before disconnect", { exact: false })
      .first();
    await preservedText.waitFor();
    await stop(backend);
    backend = start(python, backendArgs, { cwd: repoRoot, env });
    await wait(`${api}/api/status`);
    // A persisted decision survives process loss, but no dead waiter can
    // accept an answer or make its durable state appear resolved.
    const pending = await (await fetch(`${api}/api/conversations/recovery_approval/recovery`)).json();
    const approval = pending.pending_actions.find(action => action.kind === "approval" && action.status === "pending");
    if (!approval) throw new Error("Restart lost the pending approval");
    const rejected = await fetch(`${api}/api/conversations/recovery_approval/approval`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ action_id: approval.action_id, choice: "once" }),
    });
    if (rejected.status !== 404) throw new Error("Dead approval waiter accepted a response");
    const afterRejection = await (await fetch(`${api}/api/conversations/recovery_approval/recovery`)).json();
    if (!afterRejection.pending_actions.some(action => action.action_id === approval.action_id && action.status === "pending")) throw new Error("Rejected approval changed durable state");
    const restartPosts = posts;
    await page
      .getByText("before disconnect", { exact: false })
      .first()
      .waitFor({ timeout: 5000 });
    if (posts !== restartPosts)
      throw new Error("gateway restart caused an automatic conversation POST");
    await page.getByRole("button", { name: "Send message", exact: true }).waitFor({ timeout: 5000 });
    await page.getByText("The live response is unavailable after a restart. Saved history is shown; work has not been replayed.", { exact: true }).waitFor({ timeout: 5000 });
    if (await page.getByRole("button", { name: "Stop response", exact: true }).count()) {
      throw new Error("gateway restart left stale running controls visible");
    }
    await page.getByText("Finalizing from saved history…", { exact: true }).waitFor({ state: "hidden", timeout: 5000 });
    await page.screenshot({
      path: path.join(
        webRoot,
        "screenshots",
        "e2e-recovery-gateway-restart.png",
      ),
      fullPage: true,
    });
    await page.getByText("Needs you", { exact: false }).first().click();
    await open("Recovery approval", "Approval required");
    await page.getByTestId("recovery-card").waitFor();
    if ((await page.getByTestId("recovery-card").getAttribute("data-recovery-state")) !== "waiting-approval") throw new Error("Restart concealed an unresolved decision");
    console.log(
      "recovery-state: stalled reconnect, no POST, failure outcome, approval, three-chat switching, and gateway restart passed",
    );
  } catch (error) {
    if (browser) {
      const pages = browser.contexts().flatMap((c) => c.pages());
      if (pages[0])
        await pages[0].screenshot({
          path: path.join(
            webRoot,
            "screenshots",
            "e2e-recovery-state-failure.png",
          ),
          fullPage: true,
        });
    }
    if (browser) console.error("UI", await browser.contexts()[0].pages()[0].locator("body").innerText());
    console.error("FINAL", await (await fetch(`http://127.0.0.1:${apiPort}/api/conversations/recovery_stalled/recovery`)).text());
    throw error;
  } finally {
    if (browser) await browser.close();
    await stop(vite);
    await stop(backend);
    if (!process.env.SPARK_E2E_KEEP_HOME)
      await rm(home, { recursive: true, force: true });
  }
}
run()
  .then(() => process.exit(0))
  .catch((e) => {
    console.error(e);
    process.exit(1);
  });
