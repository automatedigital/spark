// boot.js — loading-page bootstrap for the Tauri shell.
//
// The backend is spawned from Rust (see src-tauri/src/lib.rs) as a --onedir
// PyInstaller resource. This page just waits for the server to come online,
// then redirects the window to it. In dev mode the user runs the server
// manually; the same poll-and-redirect applies.

const SERVER_ORIGIN = "http://127.0.0.1:9119";
const POLL_INTERVAL_MS = 250;
const STARTUP_TIMEOUT_MS = 120000;

const statusEl = document.getElementById("status");
const setStatus = (msg) => {
  if (statusEl) statusEl.textContent = msg;
};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitForServer(timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
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
  setStatus("Starting the Spark backend…");
  const ready = await waitForServer(STARTUP_TIMEOUT_MS);
  if (!ready) {
    if (statusEl) statusEl.className = "status error";
    setStatus("Spark backend did not start in time. Please restart the app.");
    return;
  }
  setStatus("Ready.");
  window.location.replace(SERVER_ORIGIN);
}

main();
