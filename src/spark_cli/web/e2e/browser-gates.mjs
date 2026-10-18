/** Bounded, provider-free P09 gates. Each attempt retains its own logs/results.
 * node e2e/browser-gates.mjs --suite sidebar --repeat 3 --output-dir /tmp/gates
 * Suites: sidebar, longthread, production-recovery. A failed attempt stays failed.
 */
import { spawn } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";

const { values } = parseArgs({ options: {
  suite: { type: "string" }, repeat: { type: "string", default: "1" },
  "output-dir": { type: "string" },
} });
const repeat = Number(values.repeat);
if (!Number.isInteger(repeat) || repeat < 1 || repeat > 10) throw new Error("--repeat must be 1..10");
if (!["sidebar", "longthread", "production-recovery"].includes(values.suite)) throw new Error("Choose --suite sidebar|longthread|production-recovery");
if (!values["output-dir"]) throw new Error("--output-dir is required");
const output = path.resolve(values["output-dir"]);
const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const root = path.resolve(web, "../../..");
const python = process.env.PYTHON || path.join(root, ".venv/bin/python");
await mkdir(output, { recursive: true });
const attempts = [];
for (let attempt = 1; attempt <= repeat; attempt += 1) {
  const directory = path.join(output, `attempt-${String(attempt).padStart(2, "0")}`);
  // Refuse accidental reuse instead of overwriting prior evidence.
  await mkdir(directory);
  const suite = values.suite;
  const command = suite === "production-recovery" ? python : process.execPath;
  const args = suite === "sidebar" ? ["e2e/sidebar-scale.mjs"]
    : suite === "longthread" ? ["e2e/baseline-capture.mjs", "--repeat", "1", "--case", "dark:2000:1440", "--output-dir", directory]
      : ["e2e/production-recovery.py", "--output-dir", directory];
  const started = Date.now();
  const child = spawn(command, args, { cwd: web, detached: true, env: {
    ...process.env, PYTHON: python, PYTHONPATH: path.join(root, "src"),
    SPARK_E2E_OUTPUT_DIR: directory, SPARK_E2E_SESSION_COUNT: "1000",
  }, stdio: ["ignore", "pipe", "pipe"] });
  let stdout = "", stderr = "", timedOut = false;
  child.stdout.on("data", (data) => { stdout += data; });
  child.stderr.on("data", (data) => { stderr += data; });
  const killGroup = (signal) => { try { process.kill(-child.pid, signal); } catch { /* already exited */ } };
  const timeoutMs = suite === "production-recovery" ? 300_000 : 240_000;
  let escalation;
  const timer = setTimeout(() => {
    timedOut = true;
    killGroup("SIGTERM");
    escalation = setTimeout(() => killGroup("SIGKILL"), 3000);
  }, timeoutMs);
  const result = await new Promise((resolve) => {
    child.once("error", (error) => resolve({ exit: null, error: String(error) }));
    child.once("exit", (exit, signal) => resolve({ exit, signal }));
  });
  clearTimeout(timer); clearTimeout(escalation);
  // Also reap any fixture descendants if the runner failed before cleanup.
  killGroup("SIGKILL");
  await writeFile(path.join(directory, "stdout.log"), stdout);
  await writeFile(path.join(directory, "stderr.log"), stderr);
  attempts.push({ attempt, command, args, directory, timeoutMs, elapsedMs: Date.now() - started, timedOut, ...result });
  await writeFile(path.join(output, "gate.json"), JSON.stringify({ suite, repeat, attempts }, null, 2));
  console.log(`${suite} attempt ${attempt}/${repeat}: exit=${result.exit} timeout=${timedOut}; ${directory}`);
}
process.exitCode = attempts.some((attempt) => attempt.exit !== 0 || attempt.timedOut) ? 1 : 0;
