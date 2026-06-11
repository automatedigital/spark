# PLAN - 100626

## UI Updates
This applies to both webui and desktop app (same React codebase in `src/spark_cli/web/`; desktop is the Tauri wrapper, so one fix covers both — verify in both at the end).

---

### Phase 1 — Logo Swap

- Reference: screenshots/100626/feature-requests_pm/spark_landing-page.png — the logo is nearly invisible against the dark background.

**Root cause (researched):** Theming is driven by `data-webui-theme` on `<html>` (`src/lib/theme.tsx`), but the landing hero (`pages/ChatPage.tsx:137-144`) picks the logo via a `prefers-color-scheme` media query — which tracks the **OS** setting, not the app theme. The other three usages (`App.tsx:159`, `components/ChatPanel.tsx:207`, `components/OnboardingWizard.tsx:615`) hardcode `icon_small-dark.png` (the dark glyph). Note the asset names are inverted vs. intuition: `icon_small-light.png` is the **white** glyph for dark backgrounds.

**Tasks:**
- [x] Create a shared `BrandLogo` component (`src/components/BrandLogo.tsx`) that reads the active theme via `useWebUITheme()` and renders the white glyph (`icon_small-light.png`) on dark themes and the dark glyph on light themes (currently only `daylight` is light). Accept `className` for sizing.
- [x] Replace all four hardcoded usages: `App.tsx:159` (sidebar), `pages/ChatPage.tsx:137` (landing hero), `components/ChatPanel.tsx:207`, `components/OnboardingWizard.tsx:615`.
- [x] Landing hero specifically: bump logo contrast/size so it reads clearly (per screenshot, white glyph + slightly larger).
- [x] Optional polish: swap favicon (`index.html:5`) dynamically via JS to match OS scheme (favicons CAN legitimately use `prefers-color-scheme` since they render on browser chrome, not app background).

---

### Phase 2 — Right-hand sidebar: structural cleanup

The panel lives in `pages/ChatPage.tsx` (`RIGHT_TABS = ["files", "terminal", "preview"]`, ~line 319) with panes in `src/components/workspace/`. References:
- screenshots/100626/feature-requests_pm/claude-desktop_right-hand-sidebar-FILES_02.png
- screenshots/100626/feature-requests_pm/claude-desktop_right-hand-sidebar-OPTIONS_01.png
- screenshots/100626/feature-requests_pm/claude-desktop_right-hand-sidebar-PREVIEW_03.png
- screenshots/100626/feature-requests_pm/codex-desktop_right-hand-sidebar_BROWSER-TAB_01.png
- screenshots/100626/feature-requests_pm/codex-desktop_right-hand-sidebar_OPTIONS_01.png
- screenshots/100626/feature-requests_pm/codex-desktop_right-hand-sidebar_REVIEW-CHANGES_01.png

**Tasks:**
- [x] **Tab persistence**: persist active tab per workspace slug in localStorage (currently resets); already persists width + open state — extend the same pattern.
- [x] **Panel switcher dropdown** (Claude desktop OPTIONS_01 style): replace the cramped 3-button tab strip with a compact header — current tab name + chevron dropdown listing Preview / Terminal / Files / Changes, each with its keyboard shortcut shown (⇧⌘P, ⌃` , ⇧⌘F, ⇧⌘D). Keep the collapse button. _(Changes entry added in Phase 6 once the panel exists.)_
- [x] **Keyboard shortcuts**: global bindings to open/switch panel tabs (mirror Claude desktop: ⇧⌘P preview, ⇧⌘F files, ⇧⌘D changes, ⌃` terminal). Register in ChatPage, surface in `KeyboardShortcutsModal.tsx`. _(⇧⌘D added in Phase 6.)_
- [x] **Keep panes alive across tab switches**: render all panes and toggle with CSS `hidden` instead of conditional mount. Today switching tabs unmounts `WorkspaceTerminalPanel`, which **kills the shell** (cleanup calls `stopWorkspaceTerminalRun`) and drops preview iframe state. This is the single biggest "feels rough" bug.
  - **Tauri caveat**: `NativePreview` is a real native child webview overlaying the panel region — CSS `hidden` does NOT hide it on desktop. When the active tab isn't Preview (or the panel is collapsed), explicitly hide/show the native webview via the `nativePreview` bridge. _(Done: `visible` prop threads ChatPage → WorkspacePreviewPanel → NativePreview → `nativePreview.setVisible`.)_
  - Define behavior on panel **collapse** and **workspace switch** too: collapse keeps the shell alive (just hidden); switching to a different workspace slug still tears it down (intentional). _(Collapse: panel content stays mounted behind the rail, shell alive, preview `visible=false`. Workspace switch: `slug` prop change remounts panes — intentional teardown.)_

---

### Phase 3 — Files pane polish (`FileTreePane.tsx`)

Reference: claude-desktop FILES_02 screenshot (clean indented tree, filter box at top).

- [x] **Filter/search box** at the top of the tree ("Filter files…" like Claude desktop) — client-side fuzzy filter on path, auto-expand matching dirs.
- [x] **Persist expanded-dir state** per workspace (currently every refresh collapses everything). _(localStorage `spark-files-expanded:<slug>`; expansion lifted from per-row state into FileTreePane.)_
- [x] **Auto-refresh on agent activity**: subscribe to the event bus (workspace file-change topic; add one server-side if missing in `workspace_routes.py`) so the tree updates as the agent writes files, instead of requiring manual refresh. Debounce. _(Listens for `chat.turn_done` — the agent-activity signal — plus a new `workspace.files.changed` event emitted by write/mkdir/rename/delete/upload endpoints. 400ms debounce.)_
- [x] **Better file viewer**: the current `SimpleFileViewer` is bare. Add syntax highlighting (highlight.js already ships for Markdown), line numbers, image/video preview using existing `getFileCategory`, and a copy-path button. _(Highlighting + image/video already existed; added a line-number gutter and a copy-path button.)_
- [x] **Inline file ops**: new file / new folder / rename (server endpoints exist for write+delete in `workspace_routes.py`; add rename). Replace `window.confirm` delete with a small inline confirm. _(Added project-scoped `PUT /file`, `POST /mkdir`, `POST /rename` endpoints + 9 pytest cases; inline create inputs, per-row rename, inline delete confirm.)_
- [x] **Distinct refresh icon** — currently a `Loader2` spinner doubles as the refresh button, which reads as "stuck loading". Use `RefreshCw`.

---

### Phase 4 — Terminal pane polish (`WorkspaceTerminalPanel.tsx`)

- [x] **Session survives tab switches** (covered by Phase 2 keep-alive) and **reconnects** after SSE drop: on `onerror`, attempt re-attach to the existing run before declaring failed, with a "Reconnect" button on the status pill. _(Connect logic extracted into a re-callable `connect()`; on drop the status goes `failed` and a Reconnect button starts a fresh shell.)_
- [x] **xterm addons**: `@xterm/addon-web-links` (clickable URLs — agent often prints localhost links) and `@xterm/addon-search` with a small find bar (⌘F when focused). _(Installed both; links open via `openExternalUrl`; ⌘F toggles a find bar with next/prev.)_
- [x] **Theme-aware terminal colors**: palette is hardcoded amber (`#FDA632`) — derive background/cursor/selection from the active webui theme CSS variables so Slate/Daylight/etc. don't clash. _(`buildTerminalTheme()` reads `--color-card`/`--color-foreground`/`--color-primary`; re-applied on theme change via `useWebUITheme`.)_
- [x] **Toolbar row**: clear scrollback, copy selection, kill & restart shell. Keep it to one slim row matching the Files/Preview headers.

---

### Phase 5 — Preview pane polish (`WorkspacePreviewPanel.tsx`)

Reference: codex BROWSER-TAB_01 (clean URL bar, minimal chrome) and claude-desktop PREVIEW_03.

- [x] **Declutter the toolbar**: currently ~12 icon buttons in one row. Keep nav (back/forward/reload) + URL bar + start/stop visible; move port-pin, private mode, cookies, clear-data, open-external, logs-toggle into a "⋯" overflow dropdown (codex OPTIONS_01 style). _(Plus auto-open toggle in the same menu.)_
- [x] **Auto-open on preview ready**: ChatPage already listens for `workspace.preview.ready` — make it switch the panel to the Preview tab and expand the panel if collapsed, so when the agent spins up a dev server the user sees it immediately. Add a setting/toggle to disable. _(Done in Phase 2; now gated on `previewAutoOpenEnabled()` from `lib/previewPrefs`, toggled in the overflow menu.)_
- [x] **Status pill instead of status strip**: fold the status/kind/port/refresh-reason line into a compact pill in the toolbar (running = green dot, starting = amber spinner, failed = red with error tooltip) to reclaim vertical space. _(Status dot in the toolbar with a full tooltip; page title/favicon moved to a floating overlay on the viewport.)_
- [x] **Device viewport presets**: dropdown for Responsive / iPhone / iPad / Desktop widths — constrain the iframe/native view to the preset, centered, with dimensions label. Cheap to do in the web iframe path; for Tauri native webview, resize the child webview bounds via `nativePreview`. _(Wrapper `max-width` centers the region; NativePreview already tracks its placeholder rect, so the native webview follows automatically.)_
- [x] **Replace `window.confirm`/`window.alert`** (external-nav confirm, cookies list, clear-data) with the app's own dialog components — alerts feel broken inside the desktop app. _(New reusable `ConfirmDialog`; external-nav, clear-data, and cookies all route through it.)_
- [x] **Empty state upgrade**: instead of just "Start App", show detected app kind/command (backend already detects `kind`) — "Detected Vite app — Start `npm run dev`".

---

### Phase 6 — NEW: Changes (diff review) tab

Reference: codex REVIEW-CHANGES_01 — this is the standout feature in both reference apps, and Spark has nothing like it. Workspaces are often git repos; the agent edits files and the user has no way to see what changed without leaving the app.

- [x] **Backend** (`workspace_routes.py`): add endpoints
  - `GET /projects/{slug}/git/status` → branch, dirty file list with per-file `+adds/-dels`, total `+N -M` (shell out to `git status --porcelain` + `git diff --numstat`; handle non-git workspaces gracefully → tab hidden/disabled). _(Untracked files counted as additions; `is_repo:false` for non-git.)_
  - `GET /projects/{slug}/git/diff?path=` → unified diff for one file (staged+unstaged vs HEAD), and full-workspace diff when no path. _(Untracked files synthesize an add-diff via `--no-index`.)_ Plus `POST /git/revert`. 10 pytest cases, all green.
- [x] **Frontend**: new `WorkspaceChangesPanel.tsx` — file list grouped Edited/Added/Deleted with `+N -M` badges (green/red, codex-style), click to expand inline unified diff with syntax-coloured add/remove lines. "Changes +16 -89" summary in the panel switcher dropdown (codex OPTIONS_01). _(Summary fetched lazily when the switcher opens.)_
- [x] **Actions**: per-file "Revert" (git checkout — with confirm), and a "Commit or push" affordance that pre-fills a prompt to the agent ("commit these changes") rather than reimplementing git UI — keeps the agent in the loop. _(Commit button dispatches a `spark:compose` event that ChatPanel fills into the composer.)_
- [x] **Live updates**: refresh status on the same file-change event-bus topic as the Files pane. _(`chat.turn_done` + `workspace.files.changed`, debounced.)_

---

### Phase 7 — Verification & release

- [ ] `npm run build` in `src/spark_cli/web/` clean; `tsc` + eslint pass.
- [ ] Verify in browser (webui): logo on landing + sidebar across all 8 themes; tab switching keeps terminal alive; preview auto-opens on `workspace.preview.ready`; Changes tab against a dirty git workspace and a non-git workspace.
- [ ] Python tests for new git endpoints (`tests/`, follow existing workspace route test patterns; respect `_isolate_spark_home`).
- [ ] Rebuild desktop app (`/build-mac`) and smoke-test: native preview webview, terminal, logo.
- [ ] Screenshots into `screenshots/100626/after/` for before/after comparison.
- [ ] Feature branch + PR (never direct to main).

---

## Notes / explicitly out of scope (this round)
- Background-tasks and Plan tabs from Claude desktop's switcher — worth considering later once Changes ships.
- Multi-tab terminal sessions — single persistent shell first; tabs are a follow-up.
- Right panel for non-project (no-slug) chat sessions — panel remains workspace-only.
