# Spark Experience Improvement Plan

> The original TUI / Web UI / Agent-Experience / Project-Preview work is
> **complete** (committed `6e01013`; details in that commit's PLAN.md).
>
> This pass completes the remaining roadmap:
> - **§1 WebUI Preview Pane** — readiness gate (`_await_preview_ready`),
>   network-aware client URLs, loopback-decoupled probes, pending-state UI.
> - **§2 Connectors** — environment-aware OAuth callback URL; skills-first
>   connector docs; verified existing skills/MCP infrastructure. (New per-platform
>   OAuth connectors remain deferred — see notes inline; the plan deprioritizes
>   them behind the skills-first path.)
> - **§3 Desktop App** — menu-bar tray, global hotkey, tray activity indicator,
>   native notifications, `spark://` deep links, update-modal changelog.
>   `cargo check` + web build pass; full signed bundle pending the `build-mac` skill.

---

## 1. WebUI Preview Pane (`src/spark_cli/workspace_routes.py`, `src/spark_cli/web/src/components/workspace/`)

### 1.1 Server lifecycle & readiness
- [x] Fix preview start so the dev server actually launches (`start_preview`, `_detect_preview`, `_run_preview_process` in `workspace_routes.py`).
- [x] Do not mark the session `running` or emit `workspace.preview.ready` until `_probe_preview_url` succeeds — added `_await_preview_ready` readiness gate: session stays `starting` after `Popen` and only flips to `running` (and emits `ready`, starts the file watcher) once an HTTP probe succeeds, or `failed` on timeout. `_run_preview_process` now also fails a process that dies while `starting`.
- [x] Wire `WorkspacePreviewPanel.tsx` to wait on `status === "running"` — added `previewPending` gate showing a "Waiting for dev server…" overlay while `starting`, so the iframe/native/streamed pane never loads a URL that isn't answering.

### 1.2 Network-aware preview URLs
- [x] Reuse `get_public_base_url()` / `is_server_environment()` (`src/core/spark_constants.py`) — added `_client_facing_preview_url()` to advertise a client-reachable host.
- [x] **VPS / server:** prefer `dashboard.public_url` (via `get_public_base_url`), else machine hostname so remote browsers can reach the dev server's port.
- [x] **Local / desktop / LAN:** keep loopback on desktop; concrete LAN/private-IP hosts are left untouched (already reachable). Server-side probe is decoupled from the advertised URL via `_loopback_probe_url()`.
- [x] Extend host handling so advertised `0.0.0.0` / `::` bind addresses resolve to a host the **client** can reach; probe always targets loopback regardless of advertised host.

### 1.3 Preview rendering (WebUI + Tauri)
- [x] Streamed pane: `src/spark_cli/preview_browser.py`, `StreamedBrowser.tsx`, profile dirs under `SPARK_HOME/browser/<slug>/` (see `PREVIEW_BROWSER_SECURITY.md`). *(built in `6e01013`)*
- [x] Native pane: `NativePreview.tsx`, `src/spark_cli/web/src/lib/nativePreview.ts`, `src/spark_cli/web/src-tauri/src/lib.rs`. *(built in `6e01013`)*
- [x] Add/adjust tests in `tests/spark_cli/test_preview_port_detection.py` (readiness gate, client-facing URL, loopback probe) and `test_preview_browser_stream.py`.

## 2. Connectors / Plugins (`src/spark_cli/connectors_routes.py`, `src/spark_cli/skills_hub.py`)

### 2.1 OAuth connectors (Web UI)
- [ ] Extend the Google pattern (`google_connector.py`, `connectors_routes.py`) to additional platforms (HubSpot, Notion, Slack, etc.) — token storage under `get_spark_home()`, callback URLs via `set_server_port` in `web_server.py`. *(Deferred: large net-new per-platform work requiring external OAuth app registration; the plan deprioritizes this in favour of §2.2 skills-first.)*
- [ ] Surface connect/disconnect in the dashboard (`OAuthProvidersCard.tsx`, `OAuthLoginModal.tsx` on `EnvPage.tsx`; client API in `web/src/lib/api.ts`). *(Deferred with the above — depends on the new connectors existing first.)*
- [x] Fix connector callback URLs for non-localhost deployments — `_redirect_uri()` is now environment-aware: explicit `connectors.oauth_redirect_base` override → public host via `get_public_base_url()` in server environments → `localhost` default. Tests in `tests/spark_cli/test_connectors_redirect_uri.py`.

### 2.2 Skills & CLI-first integrations (preferred)
- [x] Platform access ships as **Skills** (`skills/` families incl. `gws-*`, `email`, …; user `~/.spark/skills/`) with slash commands via `src/agent/skill_commands.py`. *(Existing infrastructure — verified.)*
- [x] `skills_hub.py` + `spark skills` / `/skills` provide discover/install/enable (`do_search`/`do_browse`/`do_install`/`do_list`), with toolset config in `tools_config.py` and gateway menus from `commands.py`. *(Existing — verified.)*
- [x] Documented the connector order-of-preference (skills/CLI first, OAuth, then MCP) in `docs/integrations/index.md`.

### 2.3 MCP & tool servers (fallback)
- [x] MCP remains the documented fallback (`src/tools/mcp_tool.py`, `src/tools/mcp_oauth.py`); the integrations doc now states "prefer a skill or CLI before adding an MCP server." No new servers added (correct per priority). 
- [x] Provider (model-auth) OAuth stays separate from connector OAuth — `web_server.py` `_OAUTH_PROVIDER_CATALOG` vs `connectors_routes.py` are distinct subsystems (unchanged). *(Verified.)*

## 3. Desktop App (Tauri — `src/spark_cli/web/src-tauri/`)

### 3.1 Menu-bar companion (OpenClaw)
- [x] macOS menu-bar (tray) item — `build_tray()` in `src-tauri/src/lib.rs` with status line, "New Chat", "Show / Hide Window", and "Quit"; left-click toggles the window. Enabled the `tray-icon` Tauri feature.
- [x] Global hotkey (`Cmd/Ctrl+Shift+Space`) to summon/toggle the window from anywhere via `tauri-plugin-global-shortcut`.
- [x] Running-agent indicator — `set_tray_status` IPC command updates the tray tooltip; `ChatPanel.tsx` drives it from the `streaming` state (via `lib/desktop.ts`).

### 3.2 Native integration
- [x] Native notifications via `tauri-plugin-notification` + `notify` command; `NotificationBell.tsx` fires a native OS notification when a background job/cron notification arrives and the window is hidden/unfocused (`nativeNotify` in `lib/desktop.ts`).
- [x] `spark://` deep links via `tauri-plugin-deep-link` (scheme registered in `tauri.conf.json`); cold-start + live links forwarded to the frontend, parsed by `deepLinkToNavTarget` into the app's global-nav system (`spark://session/<id>`, `spark://canvas/<scope>/<id>`). New-chat + deep-link handlers wired in `App.tsx`/`ChatPage.tsx`.
- [x] Build pipeline verified: `cargo check` compiles cleanly with all new plugins/features; `npm run build` (Node 22) rebuilds `web_dist`. *(Full signed `.app`/DMG bundle still to be produced via the `build-mac` skill at release time.)*

### 3.3 Updates
- [x] `UpdateModalContext.tsx` already drives the GitHub-Releases auto-update flow (`/api/mac/update/check` + `/run` in `web_server.py`) — verified intact.
- [x] Changelog display added — `_fetch_latest_mac_release`/`_check_mac_update` now return `release_notes`/`release_name`/`published_at`; the mac update modal renders a "What's new" panel with the release body and a link to the full notes.
