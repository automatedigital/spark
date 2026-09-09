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
const repoRoot = path.resolve(webRoot, "../../..");
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
    "npm",
    ["run", "dev", "--", "--host", "127.0.0.1", "--port", String(webPort)],
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
      { type: "token", text: "after reconnect", delay_ms: 5000 },
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
    await card.getByRole("button", { name: "Reconnect" }).click();
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
    await open("Recovery stalled", "before disconnect");
    const preservedText = page
      .getByText("before disconnect", { exact: false })
      .first();
    await preservedText.waitFor();
    await stop(backend);
    backend = start(python, backendArgs, { cwd: repoRoot, env });
    await wait(`${api}/api/status`);
    const restartPosts = posts;
    await page
      .getByText("before disconnect", { exact: false })
      .first()
      .waitFor({ timeout: 5000 });
    if (posts !== restartPosts)
      throw new Error("gateway restart caused an automatic conversation POST");
    await page.getByRole("button", { name: "Send message", exact: true }).waitFor({ timeout: 5000 });
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
    throw error;
  } finally {
    if (browser) await browser.close();
    await stop(vite);
    await stop(backend);
    if (!process.env.SPARK_E2E_KEEP_HOME)
      await rm(home, { recursive: true, force: true });
  }
}
run().catch((e) => {
  console.error(e);
  process.exit(1);
});
