# Spark Desktop Webview Diagnostics

Spark Desktop is a Tauri shell. On startup it launches the bundled Python
sidecar server and navigates the main webview to the local dashboard URL,
usually `http://127.0.0.1:9119`.

Because the busy renderer is the webview page, macOS Activity Monitor can show
the process as `http://127.0.0.1:9119` instead of `Spark`. That does not mean the
user is running the browser Web UI instead of the desktop app; it means the
desktop app is rendering the same shared React Web UI through its local sidecar.

Useful checks when investigating a freeze:

- Browser Web UI and desktop share the same chat renderer, markdown renderer,
  session APIs, and SSE event flow.
- If `http://127.0.0.1:9119` is consuming CPU while Spark Desktop is open, treat
  it as the Spark webview renderer.
- Use `/api/diagnostics/webview` for sidecar PID, active session, active turn,
  and optional browser-provided safe-mode or long-task state.
