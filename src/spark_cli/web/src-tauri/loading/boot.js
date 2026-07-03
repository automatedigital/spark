// boot.js — loading-page bootstrap for the Tauri shell.
//
// The backend is spawned from Rust (see src-tauri/src/lib.rs) as a --onedir
// PyInstaller resource. This page just waits for the server to come online,
// then redirects the window to it. In dev mode the user runs the server
// manually; the same poll-and-redirect applies.

const SERVER_ORIGIN = "http://127.0.0.1:9119";
const POLL_INTERVAL_MS = 250;
const STARTUP_TIMEOUT_MS = 120000;
const STARTED_AT = Date.now();
const STATUS_STEPS = [
  "Starting Spark...",
  "Starting local backend...",
  "Loading workspace...",
  "Opening Spark...",
];

const statusEl = document.getElementById("status");
const elapsedEl = document.getElementById("elapsed");
const progressEl = document.getElementById("progress");
const errorNoteEl = document.getElementById("error-note");

const setStatus = (msg) => {
  if (statusEl) statusEl.textContent = msg;
};

const setProgress = (value) => {
  const progress = Math.max(6, Math.min(100, Math.round(value)));
  document.documentElement.style.setProperty("--progress", String(progress));
  if (progressEl) progressEl.setAttribute("aria-valuenow", String(progress));
};

const updateProgress = () => {
  const elapsed = Date.now() - STARTED_AT;
  const ratio = Math.min(elapsed / STARTUP_TIMEOUT_MS, 0.94);
  const step = Math.min(
    STATUS_STEPS.length - 1,
    Math.floor(ratio * STATUS_STEPS.length)
  );
  setStatus(STATUS_STEPS[step]);
  if (elapsedEl) elapsedEl.textContent = `${Math.floor(elapsed / 1000)}s`;
  setProgress(8 + ratio * 86);
};

const showError = () => {
  document.body.dataset.state = "error";
  if (statusEl) statusEl.className = "status error";
  if (errorNoteEl) errorNoteEl.hidden = false;
  setStatus("Spark backend did not start in time.");
  setProgress(100);
};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitForServer(timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    updateProgress();
    try {
      const res = await fetch(SERVER_ORIGIN + "/", {
        method: "GET",
        cache: "no-store",
      });
      if (res.ok || res.status === 200 || res.status === 404) return true;
    } catch {
      /* connection refused — not up yet */
    }
    await sleep(POLL_INTERVAL_MS);
  }
  return false;
}

async function main() {
  document.body.dataset.state = "starting";
  setProgress(8);
  setStatus(STATUS_STEPS[0]);
  const ready = await waitForServer(STARTUP_TIMEOUT_MS);
  if (!ready) {
    showError();
    return;
  }
  document.body.dataset.state = "ready";
  setStatus("Ready.");
  setProgress(100);
  window.location.replace(SERVER_ORIGIN);
}

main();
