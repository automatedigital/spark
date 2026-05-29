/**
 * sidecar.ts — Tauri desktop bootstrap helper for the Spark Python backend.
 *
 * The backend is spawned and killed from Rust (see src-tauri/src/lib.rs): the
 * PyInstaller --onedir build is shipped as a Tauri bundle resource and launched
 * on app start, then terminated on exit. This module therefore only needs to:
 *   1. Poll http://127.0.0.1:9119/ until the HTTP server responds (ready).
 *   2. Navigate the window to the running server once it is up.
 *
 * The bundled loading page uses the standalone src-tauri/loading/boot.js (no
 * bundler) for the same logic. This module is the importable equivalent for
 * use inside the React app if ever needed. In a plain browser (`vite dev`) it
 * no-ops, so importing it is always safe.
 */

const SERVER_ORIGIN = "http://127.0.0.1:9119";
const READY_PATH = "/";
const POLL_INTERVAL_MS = 250;
const STARTUP_TIMEOUT_MS = 120_000;

/** True when running inside the Tauri webview (vs. a plain browser tab). */
export function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Poll the server origin until it answers or we time out. */
export async function waitForServer(
  timeoutMs = STARTUP_TIMEOUT_MS
): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(SERVER_ORIGIN + READY_PATH, {
        method: "GET",
        cache: "no-store",
      });
      if (res.ok || res.status === 200 || res.status === 404) {
        // Any HTTP response means the listener is up.
        return true;
      }
    } catch {
      // Connection refused — server not up yet.
    }
    await sleep(POLL_INTERVAL_MS);
  }
  return false;
}

/**
 * Wait for the Rust-spawned backend, then hand the window over to it.
 * Call once on app start.
 */
export async function bootSidecar(): Promise<void> {
  if (!isTauri()) {
    console.warn("sidecar: not running under Tauri — skipping sidecar boot.");
    return;
  }

  const ready = await waitForServer();
  if (!ready) {
    console.error(
      `sidecar: spark-server did not become ready within ${STARTUP_TIMEOUT_MS}ms`
    );
    document.body.innerHTML =
      '<div style="font-family: sans-serif; padding: 2rem; color: #c00;">' +
      "Spark backend failed to start. Please restart the app.</div>";
    return;
  }

  // Hand the window over to the live Python server.
  window.location.replace(SERVER_ORIGIN);
}
