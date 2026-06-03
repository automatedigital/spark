# Preview Browser Tab Plan

## Goal

Add a `Preview` tab to the chat page right sidebar, beside `Files` and
`Terminal`, so workspace webapps can be opened, refreshed, inspected, and driven
by both the user and the Spark agent.

The target behavior is close to Claude Code Desktop and Codex: a shared embedded
browser for running apps, automatic verification after code changes, console/log
visibility, and agentic browser actions. Claude documents this as an embedded
browser that can start dev servers, inspect DOM/screenshots, click, fill forms,
read server logs, and auto-verify after edits. Its product announcement also
calls out reading console logs and iterating on UI errors. OpenAI documents
Codex's in-app browser as one of the agentic Codex features.

References:

- Claude Code Desktop docs: https://code.claude.com/docs/en/desktop
- Claude Code preview announcement: https://claude.com/blog/preview-review-and-merge-with-claude-code
- OpenAI Codex usage/help page: https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan

## Current Spark Surface

- Chat workspace right panel already exists in
  `src/spark_cli/web/src/pages/ChatPage.tsx`.
- `RightTab` is currently `"files" | "terminal"`.
- `WorkspaceRightPanel` renders the tab bar and switches between:
  - `FileTreePane` from `src/spark_cli/web/src/components/workspace/FileTreePane.tsx`
  - `WorkspaceTerminalPanel` from
    `src/spark_cli/web/src/components/workspace/WorkspaceTerminalPanel.tsx`
- Backend workspace routes already support project-scoped files and terminal
  runs through `src/spark_cli/web_server.py`, `spark_cli.workspace_routes`, and
  `src/spark_cli/web/src/lib/api.ts`.
- Spark already has agent browser tools in `src/tools/browser_tool.py`,
  including navigation, snapshots, click/type/scroll, screenshots/vision, and
  `browser_console`.

## Product Requirements

1. Add a third right-sidebar tab named `Preview`, with an icon button when the
   panel is collapsed and a normal tab when open.
2. Preview should appear only for workspace threads, matching the existing files
   and terminal panel behavior.
3. When Spark completes work on a workspace project that looks like a webapp, the
   preview tab should open automatically and show the running app.
4. The user can manually start/stop/restart preview, refresh the page, enter a
   URL, and open externally.
5. The preview should auto-refresh on file changes when the app lacks native HMR,
   while avoiding refresh loops when Vite/Next/etc. already hot reload.
6. The preview browser should expose console errors, console messages, network
   failures, current URL, page title, and screenshots/snapshots to the agent.
7. The embedded browser and agent browser should share the same underlying page
   session where possible, so the user and agent are looking at the same page.
8. Preview server state should be scoped to a workspace slug, not global chat
   state.
9. Security boundary: preview servers bind to loopback and serve workspace files,
   while browser mode can navigate to normal `http`/`https` pages. Unsafe schemes
   such as `file:`, `data:`, and `javascript:` remain blocked.

## Architecture

### Frontend

Create `WorkspacePreviewPanel` in:

`src/spark_cli/web/src/components/workspace/WorkspacePreviewPanel.tsx`

Responsibilities:

- Render a compact browser toolbar:
  - URL display/input
  - back/forward
  - reload
  - start/stop/restart preview server
  - open externally
  - console/error badge
- Render the preview viewport.
- Render a lower or toggleable diagnostics strip for console/server/network
  events.
- Subscribe to preview state/events over SSE.
- Keep the tab mounted while switching away if feasible, so page state is not
  lost just because the user checks files or terminal.

Update `ChatPage.tsx`:

- Change `type RightTab = "files" | "terminal" | "preview"`.
- Add a `Monitor` or `Globe` icon from `lucide-react`.
- Add Preview to the collapsed right rail and open tab bar.
- Auto-select `preview` when backend emits a preview-ready event for the active
  workspace.
- Persist active tab in local storage if the current tab behavior should survive
  reloads.

Update `src/spark_cli/web/src/lib/api.ts`:

- Add typed API wrappers for preview status, start, stop, restart, navigate,
  refresh, logs, screenshot, snapshot, and event stream.

### Backend

Add a project-scoped preview manager, likely under:

`src/spark_cli/workspace_preview.py`

Responsibilities:

- Detect webapp type and dev command from workspace files.
- Start and stop dev servers in the project directory.
- Capture server stdout/stderr into a bounded ring buffer.
- Detect the listening URL/port.
- Emit preview lifecycle events over SSE.
- Watch workspace files for changes and publish refresh hints.
- Maintain one preview session per workspace slug, with cleanup on process exit.

Add routes, either in `spark_cli.workspace_routes` or `web_server.py`:

- `GET /api/workspace/projects/{slug}/preview/status`
- `POST /api/workspace/projects/{slug}/preview/start`
- `POST /api/workspace/projects/{slug}/preview/stop`
- `POST /api/workspace/projects/{slug}/preview/restart`
- `POST /api/workspace/projects/{slug}/preview/navigate`
- `POST /api/workspace/projects/{slug}/preview/refresh`
- `GET /api/workspace/projects/{slug}/preview/events`
- `GET /api/workspace/projects/{slug}/preview/logs`
- `GET /api/workspace/projects/{slug}/preview/screenshot`
- `GET /api/workspace/projects/{slug}/preview/snapshot`
- `GET /api/workspace/projects/{slug}/preview/console`

Use the existing workspace path resolver so all operations stay inside the
workspace project directory.

### Browser Runtime

Use Playwright as the preview control plane if available. This gives Spark:

- A real page object for navigation and reload.
- Console message capture.
- Page error capture.
- Network request failure capture.
- Screenshots and accessibility snapshots.
- Click/type/evaluate primitives for agentic inspection.

The embedded frontend can render one of two ways:

1. MVP: iframe the detected localhost URL in the Preview tab, while the backend
   Playwright page is used for agent inspection and logs.
2. Better shared-session target: expose the Playwright-controlled page through a
   browser streaming/view bridge or Chrome DevTools Protocol attachment so the
   frontend and agent use the same page.

Recommendation: ship the iframe MVP first, but design the backend API around a
`preview_session_id` so the shared-page implementation can replace the iframe
without changing agent-facing tools.

## Webapp Detection

Detection should be conservative and explainable:

- `package.json`
  - Prefer scripts in this order: `dev`, `start`, `serve`, `preview`.
  - Detect common frameworks and default ports:
    - Vite: 5173
    - Next.js: 3000
    - Remix/React Router: 3000 or script output
    - SvelteKit: 5173
    - Astro: 4321
    - Vue CLI: 8080
- Static apps
  - `index.html` at project root or under `public/`
  - Start a simple static file server on an allocated local port.
- Python webapps
  - Defer beyond MVP unless clear patterns exist, such as `streamlit_app.py`,
    `app.py` with Flask/FastAPI, or explicit config.

Support an explicit project config file after MVP:

`spark.preview.json`

Example:

```json
{
  "command": "npm run dev -- --host 127.0.0.1",
  "url": "http://127.0.0.1:5173",
  "readyPattern": "Local:",
  "autoOpen": true,
  "autoVerify": true
}
```

## Auto-Open Trigger

When a workspace agent turn completes:

1. Inspect changed files and project structure.
2. If the project is likely a webapp and the user asked for build/fix/add UI
   work, call the preview manager to start or reuse the preview server.
3. Emit an event such as `workspace.preview.ready` with `slug`, `url`,
   `server_status`, and `auto_open: true`.
4. The frontend switches the active right tab to `preview` for that workspace.

Implementation hook:

- Extend the workspace conversation completion path in
  `src/spark_cli/web_server.py` near `chat.turn_done` publishing.
- Keep this outside the system prompt and toolset construction so prompt caching
  behavior is not affected.

## Auto-Refresh

Use layered refresh behavior:

- If the dev server is a known HMR server, do not hard-refresh on every file
  change; rely on HMR and only refresh when the page becomes stale or reconnects.
- For static servers or unknown apps, debounce file changes and reload after
  300-800 ms.
- Ignore noisy directories:
  - `node_modules`
  - `.git`
  - `dist`
  - `build`
  - `.next`
  - `.vite`
  - cache directories
- Expose a manual reload button regardless of auto-refresh mode.

## Agentic Browser Integration

Add preview-aware tools or extend existing browser tools with a preview session
target:

- `preview_open`
- `preview_snapshot`
- `preview_click`
- `preview_type`
- `preview_console`
- `preview_screenshot`
- `preview_evaluate`

Preferred implementation:

- Reuse `src/tools/browser_tool.py` concepts and schemas where practical.
- Internally route preview tools to the workspace preview session rather than
  launching an unrelated browser.
- Preserve existing `browser_open` behavior for normal web browsing.

Agent prompt behavior:

- When working in a workspace project with an active preview, tell the agent the
  preview URL and that it can use preview/browser inspection to verify UI work.
- Avoid changing toolsets mid-conversation. The preview tools should either be
  available from the start for web chat sessions or exposed through existing
  browser tool activation rules.

## Logs and Diagnostics

Preview should collect and expose:

- Dev server stdout/stderr.
- Browser console messages.
- Browser page errors.
- Failed network requests.
- Current URL, title, HTTP status where available.
- Last screenshot timestamp/path.

Frontend diagnostics:

- Error badge on the Preview tab when console/page errors occur.
- Scrollable log drawer with filters: `All`, `Console`, `Server`, `Network`,
  `Errors`.
- Clear logs action.

Agent diagnostics:

- Console/log APIs should return bounded JSON, not unbounded raw text.
- Include enough context for the agent to identify the file/route/error.

## Security and Isolation

- Bind preview servers to `127.0.0.1`.
- Allocate ports from a bounded range and track ownership.
- Do not proxy arbitrary remote URLs by default.
- Sanitize URL navigation through existing website policy rules.
- Keep preview processes scoped to workspace slug and working directory.
- Kill preview processes when workspace is deleted or Spark exits.
- Redact likely secrets from server/browser logs before exposing them to the
  frontend or agent.

## Milestones

### Milestone 1: UI Shell

- [x] Add `Preview` tab to `WorkspaceRightPanel`.
- [x] Create a placeholder `WorkspacePreviewPanel`.
- [x] Add API types/stubs in `api.ts`.
- [x] Verify layout at narrow and wide right-panel widths.

### Milestone 2: Preview Server Lifecycle

- [x] Implement initial project-scoped preview manager in `workspace_routes.py`.
- [x] Add start/stop/restart/status/log routes.
- [x] Support Vite/Next/package.json detection and static HTML fallback.
- [x] Stream server status/log events over SSE.

### Milestone 3: Embedded Preview

- [x] Render the detected URL in the Preview tab.
- [x] Add toolbar controls.
- [x] Auto-open the tab on `workspace.preview.ready`.
- [x] Add manual refresh and open-external.

### Milestone 4: Auto-Refresh

- [x] Add workspace file watcher.
- [x] Debounce refresh hints.
- [x] Respect HMR-capable frameworks.
- [x] Show refresh status in the toolbar.

### Milestone 5: Agent Browser Control

- [x] Add preview session browser backend with Playwright.
- [x] Capture console/page/network events.
- [x] Implement preview snapshot, screenshot, console, evaluate, click, type.
- [x] Wire workspace agent instructions to prefer preview verification after webapp
  changes.

### Milestone 6: Polish and Hardening

- [x] Persist preview session settings per workspace.
- [x] Add diagnostics drawer filters.
- [x] Add config file support with `spark.preview.json`.
- [x] Add process cleanup and port conflict handling.
- [x] Add tests for route behavior, detection, lifecycle, and frontend tab state.

## Test Plan

Backend:

- [x] Unit test webapp detection for Vite, Next, static HTML, unknown project.
- [x] Unit test command/URL config parsing.
- [x] Integration test preview start/stop/status with a tiny static app.
- [x] Verify preview server binds to loopback and refuses path traversal.
- [x] Verify logs are bounded and secret-redacted.

Frontend:

- [x] Component test `WorkspaceRightPanel` tab switching.
- [x] Component test `WorkspacePreviewPanel` loading, error, running, stopped states.
- [x] Browser test that a sample Vite app opens in Preview and reloads on change.
- [x] Browser test that console errors show the Preview tab error badge.

Agent:

- [x] Test workspace agent turn emits `workspace.preview.ready` for webapp tasks.
- [x] Test preview console/screenshot tools return bounded JSON.
- [x] Test existing prompt caching invariants are not disturbed by preview startup.

## Decisions

- [x] Preview starts only when a workspace is previewable or explicitly configured.
- [x] The visible pane doubles as an app preview and a general browser surface.
- [x] Agent inspection/control routes through a separate browser automation session
  when `agent-browser` is available, with Playwright/fetch fallbacks for local use.
- [x] Preview state is process/session scoped for now; persistent settings live in
  `spark.preview.json`.
- [x] Navigation accepts normal `http`/`https` browser URLs and blocks unsafe URL
  schemes.
- [x] Preview tools are their own `preview` toolset and are also included in the default
  Spark core tool surface.
