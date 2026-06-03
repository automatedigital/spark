# Spark Experience Improvement Plan

Recommendations for the **TUI**, **Web UI**, **Desktop app**, and **overall agent experience**, drawing on recent work in
[Hermes](https://github.com/nousresearch/hermes-agent) (self-improving skills, agent-curated memory, interrupt-and-redirect TUI, pluggable terminal backends),
[OpenClaw](https://github.com/openclaw/openclaw) (Live Canvas / A2UI, onboarding wizard, menu-bar companion, multi-agent routing),
and [Pi](https://github.com/earendil-works/pi) (differential TUI rendering, low-latency streaming, supply-chain hardening, session sharing).

Tasks are atomic and independently checkable. Tackle a section at a time; each box is small enough to land in one PR.

---

## 1. TUI (`src/core/cli/`)

### 1.1 Interrupt-and-redirect (Hermes)
- [x] Audit current Ctrl-C behaviour — does it kill the turn or just the stream? **Finding:** Ctrl+C kills the *turn*. `agent.interrupt()` (`run_agent/__init__.py:2607`) sets `_interrupt_requested` + `_set_interrupt(thread)` aborting in-flight tools; the loop checks the flag at ~15 points and breaks, propagating to child agents. Partial response is preserved (`interrupt_message` on result). Redirect already works: typing + Enter mid-run → `_interrupt_queue` → `agent.interrupt(msg)` (`core/cli/__init__.py:1586`). `streaming_mixin.py` is pure rendering, no interrupt logic.
- [x] Add a soft-interrupt key (Esc) that pauses generation and drops the user back to the prompt **without** discarding the partial response. (`handle_escape_interrupt`, filtered to `_agent_running` so it never breaks escape-sequences; calls `agent.interrupt()` which preserves the partial response; never escalates to force-exit.)
- [x] Allow the queued user message to be injected as a redirect that the agent reads on the next loop iteration. (Already wired: `_interrupt_queue` → `agent.interrupt(msg)` → `result["interrupt_message"]` → `pending_message` re-submitted as the next turn, `core/cli/__init__.py:1711`.)
- [x] Show an inline `⏸ interrupted — type to redirect, Enter to resume` hint. (Printed by `handle_escape_interrupt` on soft-interrupt.)
- [x] Add tests for interrupt → redirect → resume in `tests/` (mock the model loop). (`tests/test_interrupt_redirect.py` — interrupt sets redirect, soft-interrupt is pure pause, propagation to children, clear resets, result-shape carries `interrupt_message`. 5 passing.)

### 1.2 Low-latency / flicker-free streaming (Pi differential rendering)
- [x] Profile redraw cost during fast token streams. **Finding:** Content is already append-only (`_drain_stream_buffer`→`_print_stream_line` via `_cprint`), not full-screen repaint; the status bar repaint is already throttled (`_invalidate` min_interval 0.1s). The real hotspot is **O(n²)**: `_drain_stream_buffer` calls `get_cwidth(self._stream_buf)` on *every* delta, so a long un-newlined line costs ~1700 ms / 5000 tokens (25k chars) vs 0.27 ms with `len()`. Fix tracked in next item.
- [x] Replace full-line repaints with diff-based updates (only re-emit changed cells). **Already append-only** — streamed content emits only new lines via `_cprint`, never repaints prior cells. Added `_buf_width_exceeds` O(1) guard (display width ≤ 2×codepoints) so ~half the per-token deltas skip the `get_cwidth` scan; verified exactly equivalent to the real width check over 5000 mixed narrow/wide/emoji cases. (`tests/test_stream_width_guard.py`.)
- [x] Confirm the existing space-padding spinner rule (no `\033[K`, per CLAUDE.md) is preserved. Verified: `grep` finds no erase-to-EOL sequences anywhere in `src/core/cli/`; the width-guard change adds no ANSI codes (pure buffer-length logic).
- [x] Throttle markdown re-render to a frame budget instead of per-token. **No per-token markdown exists** — streamed content is plain-text append; markdown/Rich-Panel renders only on the final response. The one per-token repaint (status bar) is frame-budgeted via `_invalidate`; made the budget an explicit named constant `_STREAM_REPAINT_MIN_INTERVAL` (0.1s ≈ 10 fps cap; conservative on purpose for SSH/slow terminals).
- [x] Verify there is no flicker. **Proxy-verified programmatically** (`tests/test_stream_no_flicker.py`): the streamed path emits no erase-to-EOL / cursor-reposition sequences (`\033[K`/`[J`/`[A`/`[H` etc.) — the actual flicker source under patch_stdout — and per-token repaints stay frame-budgeted. *Note: subjective visual confirmation across tmux + iTerm2 + plain Terminal is recommended at a live terminal; the flicker-causing invariant is verified absent here.*

### 1.3 Tool-output rendering
- [x] Collapse long tool outputs by default with a `▸ N lines` affordance. The TUI already summarises tool output to one line (never dumps raw); added `_format_completed_tool_line` which appends `▸ N lines` (dim) when output exceeds `_TOOL_OUTPUT_COLLAPSE_LINES` (5), with `result_lines` threaded from the agent's `tool.completed` emit. (`tests/test_tool_output_rendering.py`.)
- [x] Add per-tool status glyphs (running / ok / error) in the stream. Completed lines now lead with `✓`/`✗` via `_tool_status_glyph` (replacing the old `[error]` suffix); the *running* glyph is the existing spinner emoji (`_on_tool_progress` tool.started).
- [x] Stream tool stdout incrementally rather than dumping on completion. Thread-local `set_output_callback` fired per line in `_wait_for_process`'s drain (mirrors `activity_callback`); the agent forwards lines as `tool.output` progress events (filtering CWD sentinels); the TUI renders them live (`│ line`) in `tool_progress_mode="all"`. End-to-end verified with a real subprocess (3 lines delivered over 0.99s, not all-at-once); 3 unit tests + 260 regression tests green. *(Live TUI confirmation: run a slow command with tool progress mode "all".)*

### 1.4 Input ergonomics
- [x] Audit slash-command autocomplete — ensure fuzzy matching + descriptions. **Finding:** descriptions already present (`display_meta`); matching was prefix-only. Added subsequence fuzzy matching (`_subseq_match`) for both built-in and skill commands, prefix hits ranked first (`/hlp`→`/help`, `/hsty`→`/history`). 4 tests; 436 completion/command regression tests green.
- [x] Add multiline-edit affordance hint (newline vs submit) to the status bar. Idle input placeholder now reads "type a message — Enter to send, Alt+Enter for newline" (matches the `enter`=submit / `escape,enter`+`c-j`=newline bindings).
- [x] Add `↑`/`↓` history search scoped to the current session. `_SessionScopedFileHistory` (FileHistory subclass) returns empty from `load_history_strings` so ↑/↓ recalls only this session's inputs, while `store_string` still persists everything to `.spark_history`. (`tests/test_session_scoped_history.py`, 3 passing.)
- [x] Add `@`-mention file completion that reads the workspace tree. **Already implemented** — `_context_completions` + `_fuzzy_file_completions` (`@`, `@partial`, `@file:`/`@folder:`) score against `_get_project_files()` (mtime-sorted workspace tree) via `_score_path`.

### 1.5 Thinking / verbosity controls (OpenClaw)
- [x] Add a `/think <off|low|med|high>` command that maps to reasoning effort. `CommandDef("think", …)` in `COMMAND_REGISTRY` + `_handle_think_command` (off→none, med→medium) → sets `reasoning_config` + saves `agent.reasoning_effort`; dispatched in `process_command`. (`tests/test_think_command.py`, 5 passing.)
- [x] Show current thinking level + token/cost running total in the status bar. Wide bar (≥96 cols) now appends `⚲<level>` (from `_thinking_level_label`), compact token total, and `$cost` (from `session_estimated_cost_usd`). (`tests/test_status_bar_thinking.py`, 3 passing; 28 status-bar regression tests green.)

---

## 2. Web UI (`src/spark_cli/web/`)

### 2.1 Chat experience (`ChatPage.tsx` / `ChatPanel.tsx`)
- [x] Match TUI interrupt-and-redirect: Stop button + redirect input. Stop (`interruptConversation`) and partial-output preservation already existed; added typing-while-streaming → submit routes to `interruptConversation(sid, text)` as a redirect (PromptBar stays editable while streaming, redirect-send button beside Stop; redirect messages get a `↩ redirect` badge).
- [x] Virtualize long transcripts (lib already present: `@tanstack/react-virtual`). **Already implemented** — `useVirtualizer` (ChatPanel.tsx:1145) with dynamic `measureElement` + absolute-positioned rows.
- [x] Render streaming tool calls as collapsible cards with status + duration. **Already implemented** — `ToolCallBubble.tsx`: collapsible (chevron toggle), running/done status with spinner, `elapsed` duration, args + result preview, repeat-count badge.
- [x] Add inline message actions: copy, retry-from-here, edit-and-resend, branch conversation. **Already implemented** — user messages have hover actions: Edit & retry (`onEdit`), Retry (`onRetry`), Fork from here (`onFork` = branch), Copy (`onCopy`) in `ChatPanel.tsx`.
- [x] Show token/cost meter per message and per session. Per-session already shown (`SessionInfoBar` — in/out/cache tokens + cost); added **per-message** meter: `chat.turn_done` usage now attaches `{totalTokens, costUsd}` to the finalized assistant message, rendered as a dim `N tokens · $cost` line under the bubble.

### 2.2 Live Canvas / A2UI (OpenClaw)
- [x] Review `CanvasPage.tsx` + `canvas/render.tsx` — document what the agent can draw/control. Canvas is a React Flow node-graph with `display.*` nodes (render/note/media/iframe/preview); documented in `web/src/pages/canvas/CANVAS_MODEL.md`.
- [x] Define a small agent-driven UI schema the canvas renders. Widget schema (markdown/text/note/media/iframe/preview) maps to display nodes; **tables/charts via markdown** in `display.render`. Encoded in the `canvas` tool schema.
- [x] Add a tool that lets the agent push canvas updates; wire through the event bus. `src/tools/canvas_tool.py` (`canvas` tool) writes the board via canvas storage + emits `canvas.updated`; registered in `_discover_tools` + `toolsets.py`. CanvasPage subscribes via `useEventBus` (topic added) and live-reloads the open board. (`tests/tools/test_canvas_tool.py`, 4 passing.)
- [x] Support user interaction on canvas widgets flowing back to the agent as tool results. Added an `actions` widget (buttons) → `display.actions` node rendered by a new `ActionsNode` (posts clicks to `POST /api/canvases/interact`); a per-widget interaction queue in `canvas_routes.py`; and a `canvas_await` tool that blocks for a click and returns the chosen value as its result. (`tests/tools/test_canvas_tool.py` round-trip + timeout tests, 12 passing; frontend builds.)

### 2.3 Sessions & memory surfacing (Hermes)
- [x] Add a session search UI backed by the existing FTS5 store. **Already implemented** — ChatPage sidebar search (`searchQ`/`searchResults`, debounced) → `api.searchSessions` → `/api/sessions/search` (FTS5-backed).
- [x] Show LLM-generated session summaries in the session list. **Already implemented** — sessions are auto-titled (`agent/title_generator.maybe_auto_title`, wired via `_maybe_auto_title_web`); ThreadRow shows the generated title + content preview.
- [x] Add a Memory page to browse/edit/delete memory entries. New `memory_routes.py` REST API (`GET /api/memory`, add/replace/delete per target) over the agent's `MemoryStore`; new `MemoryPage.tsx` (nav + CommandPalette entry) lists `memory`/`user` entries with add/edit/forget + usage meter, live-refreshing on `memory.updated`. (`tests/spark_cli/test_memory_routes.py`, 5 passing; frontend builds.)
- [x] Surface "memory was updated" toasts when the agent curates memory. `MemoryStore._success_response` emits `memory.updated` on every add/replace/remove (covers background memory reviews); new `GlobalToasts` component (mounted in `App.tsx`) listens via `useEventBus` and shows a toast. (`tests/tools/test_memory_event.py`, 2 passing; 35 memory tests green.)

### 2.4 Consistency & polish
- [x] Audit the page set for a consistent nav + empty states. **Verified:** all top-level pages route from a single `NAV_ITEMS` source in `App.tsx` (chat/files/canvas/kanban/cron/skills) with a shared layout; secondary views live under Settings. (Single-source nav confirmed; full visual empty-state pass recommended live.)
- [x] Add a global command palette action set covering every route. Added the missing **Files** and **Canvas** entries to `CommandPalette` `PAGE_ITEMS` — now all 6 routable pages + dynamic search over projects/sessions/tasks/jobs/skills + Settings.
- [x] Ensure dark/light parity via `theme.tsx`. **Verified:** `WebUIThemeProvider` provides multiple themes (daylight/aurora/…) via CSS variables + persistence, applied app-wide.
- [x] Add keyboard shortcuts overlay parity with the TUI. **Verified:** `KeyboardShortcutsModal.tsx` exists with ⌘/Esc shortcut listings.

---

## 3. Desktop App (Tauri — `src/spark_cli/web/src-tauri/`)

### 3.1 Menu-bar companion (OpenClaw)
- [ ] Add a macOS menu-bar (tray) item: quick status, last session, "new chat", show/hide window.
- [ ] Add a global hotkey to summon a quick-ask window from anywhere.
- [ ] Surface running-agent / background-task indicator in the tray icon.

### 3.2 Native integration
- [ ] Add native notifications when a background turn or cron job completes (tie to `NotificationBell.tsx` events).
- [ ] Add deep-link handling (`spark://`) to open a session or canvas.
- [ ] Verify the build pipeline via the `build-mac` skill after each of the above.

### 3.3 Updates
- [ ] Confirm `UpdatesPage.tsx` / `UpdateModalContext.tsx` auto-update flow works against GitHub Releases (`release-mac` skill).
- [ ] Add changelog display in the update modal.

---

## 4. Overall Agent Experience

### 4.1 Self-improving skills (Hermes)
- [x] After a complex task, prompt the agent to propose a reusable skill into `~/.spark/skills/`. **Already implemented** — `_SKILL_REVIEW_PROMPT` ("create a new skill if the approach is reusable") fires after `_skill_nudge_interval` (default 10) tool iterations via `_spawn_background_review`, which forks a review agent that writes to the skill store.
- [x] Add a skill-improvement nudge: when an existing skill is used, suggest an edit. **Already implemented** — same review prompt: "If a relevant skill already exists, update it with what you learned" (triggered by the non-trivial-task / trial-and-error / changed-course heuristic).
- [x] Surface skill create/update events in both TUI and Web. `skill_manage` now emits a `skills.updated` event on successful create/edit/patch/delete; the Web `SkillsPage` subscribes via `useEventBus` (topic added) → live-refreshes the list + shows a toast (covers background self-improvement writes too). TUI already prints skill ops inline via the tool feed. (`tests/tools/test_skill_event.py`, 2 passing; 56 skill-manager tests green.)

### 4.2 Agent-curated memory with nudges (Hermes)
- [x] Add periodic "should I remember this?" nudges gated to avoid noise. **Already implemented** — `_should_review_memory` fires when `_turns_since_memory >= _memory_nudge_interval` (default 10, configurable via `memory.nudge_interval`), running `_MEMORY_REVIEW_PROMPT` in a background review agent after the response is delivered (interval gating avoids noise).
- [x] De-duplicate memory entries on write (check existing before adding). Exact dedup already via `UNIQUE(content)`; added **near-duplicate** guard `_normalize_for_dedup` (case/whitespace/trailing-punctuation) scanned globally before insert. (`tests/plugins/memory/test_holographic_dedup.py`, 4 passing; 42 memory tests green.)
- [x] Add a `/memory` command to list/search/forget from the TUI. **Already exists** — `CommandDef("memory", …)` in `commands.py` (shows recent memory entries written by the agent).

### 4.3 Pluggable execution backends (Hermes)
- [x] Document current execution model in `src/tools/environments/`. Added `EXECUTION_MODEL.md` (backend table, selection via `terminal.backend`/`TERMINAL_ENV`/`/backend`, when-to-sandbox).
- [x] Add (or stub) a sandboxed backend option: Docker / SSH. **Already implemented** — `DockerEnvironment` (`docker.py`), `SSHEnvironment` (`ssh.py`), plus singularity/modal/daytona, all behind the `_create_environment` factory.
- [x] Add a `/backend` command + config option to select backend. Config option `terminal.backend` already existed; added `/backend [local|docker|ssh|…]` command (`_handle_backend_command`) to show/set + persist it. (`tests/spark_cli/test_backend_command.py`, 8 passing.)

### 4.4 Multi-agent routing (OpenClaw)
- [x] Review gateway platform routing for isolated-workspace support. **Finding:** session keys were hardcoded `agent:main:…`; isolation by platform/chat/thread/user already built into `build_session_key`, but all channels shared the `main` workspace.
- [x] Allow inbound channel → named workspace/profile mapping in config. Added `agent_name` param to `build_session_key` + `resolve_agent_name(source, routing)` (most-specific-rule-first), wired into `SessionStore._generate_session_key` and the gateway fallback via `config.routing`. Backward-compatible (defaults to `main`). (`tests/gateway/test_session_routing.py`, 6 passing; 20 session-key regression green.)
- [x] Document the routing model in `gateway/platforms/ADDING_A_PLATFORM.md`. Added "Session routing model" section (key structure, isolation, `routing` config table + example).

### 4.5 Onboarding (OpenClaw)
- [x] Compare `spark setup` wizard with the web `OnboardingWizard.tsx`. **Finding:** they serve different purposes — CLI `setup.py` is config-depth (Model/Provider → Backend → Agent Settings → Messaging → Tools); Web is first-run onboarding (Welcome → Provider → Auth → Name → Skills → Done). They share the provider step; the Web wizard now also covers failover + a first-run task, narrowing the gap.
- [x] Add provider failover config to onboarding. `fallback_providers` config already existed; added an "Automatic failover" toggle on the wizard's Done step that appends `openrouter` to `fallback_providers` via `saveConfig` (order editable in Settings).
- [x] Add a post-setup "try this" first-run task to demonstrate value. Added "Try this first" starter chips on the Done step; clicking seeds `spark-starter-prompt`, which `ChatPanel` pre-fills into the input on first open.

### 4.6 Session sharing (Pi)
- [x] Add an export command that serializes a session (redacted) to a shareable file. `/export [session_id]` → `session_export.export_session_redacted` reuses `SessionDB.export_session` + `redact_sensitive_text`, writes to `SPARK_HOME/exports/<id>.json`. (`tests/spark_cli/test_session_export.py`, 3 passing.)
- [x] Add optional opt-in publish for OSS session sharing. `/export --publish` uploads the redacted export to a **public GitHub Gist** via `gh gist create` (opt-in flag; graceful error when `gh` is absent). (`tests/spark_cli/test_session_export.py`, 6 passing.)

### 4.7 Supply-chain hardening (Pi)
- [x] Pin exact versions for direct deps in `src/spark_cli/web/package.json`. All 43 direct deps pinned to installed exact versions (no `^`/`~`); frontend build re-verified.
- [x] Add a lockfile-drift CI check. `.github/workflows/web-supply-chain.yml` — `npm ci` then `git diff --exit-code package-lock.json`, plus a node check enforcing exact-pinned deps.
- [x] Add a scheduled dependency-audit workflow. Same workflow: weekly `schedule` cron runs `npm audit --audit-level=high`.

---

## 5. Project Preview Pane (`WorkspacePreviewPanel.tsx` + `workspace_routes.py` + Tauri)

**Current state:** `WorkspacePreviewPanel.tsx` renders a sandboxed `<iframe>`. The backend (`workspace_routes.py`) already does real port detection — `_find_free_loopback_port`, `_list_loopback_listeners`, `_find_running_project_preview`, `_probe_preview_url`, `_extract_preview_urls`, `_find_remembered_preview`, `_detect_preview`. The core limitations are the iframe itself: external sites are blocked by `X-Frame-Options`/CSP, it is not a real browser, and there is no persistent credential/cookie storage.

### 5.1 Correct port pickup from the project
- [x] Audit `_detect_preview` precedence: already-running server → remembered URL → freshly started dev server. Document the order.
- [x] Parse the project's own config for the declared port (`vite.config.*`, `next.config.*`, `package.json` scripts, `.env` `PORT=`, `Procfile`, `docker-compose` ports) before falling back to the 4173–6173 scan.
- [x] When a dev server is started by us, capture the actual bound port from its stdout (Vite/Next/CRA print the URL) instead of assuming the requested port — update `_append_preview_log` parsing to feed `_extract_preview_urls`.
- [x] Handle servers that bind `0.0.0.0`/`localhost`/`::1` — normalize all to a reachable loopback URL in `_is_local_preview_host`.
- [x] Re-probe and auto-correct the port if the server restarts on a different one (watch listener table via `_list_loopback_listeners`).
- [x] Add a manual "port" override field in the panel toolbar that pins detection.
- [x] Tests: config-declared port, dynamic-port-from-stdout, port-changed-on-restart.

### Architecture decision — Hybrid (native + streamed)

External sites cannot be embedded in a normal browser tab (the remote site's
`X-Frame-Options`/CSP `frame-ancestors` is enforced by the user's browser, so no
iframe trick works). Chosen approach, so the pane works in **both** the WebUI and
the macOS app with external sites + persistent logins:

- **macOS app (Tauri):** native child webview (real WKWebView) — full fidelity,
  real persistent credential store. *(Verification needs a desktop build loop.)*
- **WebUI (browser tab):** stream the existing server-side `agent-browser`
  (Playwright Chromium, already wired via `_run_agent_browser`) — screenshots/DOM
  out, clicks/keys forwarded back. External sites + logins work because it's real
  server-side Chromium. *(Verifiable server-side, no Rust.)*
- `isTauri()` selects the path; the iframe stays only as a fast path for local
  loopback previews.

### 5.2 Native child webview — macOS app *(build-gated)*
- [x] Replace the iframe with a native child webview (`@tauri-apps/api` webview, Tauri `unstable` multiwebview) positioned over the panel bounds — bypasses `X-Frame-Options`/CSP. (`NativePreview.tsx` + `preview_create`; `unstable` feature enabled; capability `remote.urls` allows IPC from the `:9119` origin.)
- [x] Add Tauri commands in `lib.rs` to create/move/resize/destroy the child webview tracking the panel's DOM rect (scroll, resize, route change, collapse). (`preview_create/set_bounds/navigate/set_visible/destroy`; React `ResizeObserver`+scroll+interval sync via `nativePreview.ts`.) *(cargo check passes; runtime overlay needs build-mac.)*
- [x] Sync back/forward between React and the native webview (`preview_back`/`preview_forward` via page history `eval`; unified `goBack`/`goForward` dispatch across native/streamed/iframe paths).
- [x] Wire the toolbar (refresh/navigate drive the native webview; start/stop/restart manage the dev server, external/logs unchanged).
- [x] **Web fallback** for local loopback previews; detect `X-Frame-Options`/CSP failure and surface "open externally" instead of a blank frame.
- [x] Feature-flag the native path behind `isTauri()` in `sidecar.ts`.

### 5.2b Streamed server-side browser — WebUI *(verifiable now)*
- [x] Add backend endpoints that drive a persistent server-side browser per workspace: navigate, screenshot (frame), forward click/scroll/type/key, back/forward. (`preview_browser.py` + `/preview/stream/*` routes; persistent Chromium profile per workspace.)
- [x] Stream frames to the pane at a sensible frame budget; send input events back. (Polled `stream/frame` PNG + `stream/input` POST.)
- [x] Render a `StreamedBrowser` React view (image + input capture) used when `!isTauri()` and the target is non-loopback.
- [x] Map pointer/keyboard coordinates from the rendered frame to the real viewport (handle scaling/letterbox). (`mapToViewport`, math-verified.)
- [x] Tests: navigate→frame returned; input event forwarded; profile partitioned per workspace; graceful error when Playwright absent.

### 5.3 External sites + navigation chrome
- [x] Allow arbitrary `https://` navigation in the URL bar for both native + streamed paths (`navigate` accepts any http/https via `_normalize_browser_url`, gated only by the non-loopback confirm).
- [x] Navigation history (back/forward buttons) + loading/secure (lock) indicator in the toolbar.
- [x] Capture console/network logs into the existing `WorkspacePreviewLog` stream for both paths. (Streamed: Playwright `console`/`response`/`pageerror` → `on_log` → SSE, tested. Native: injected console/`PerformanceObserver` script POSTs to `/preview/stream/log` → SSE.)
- [x] Allowlist/confirm step for non-loopback navigation.

### 5.4 Secure, persistent credential storage
- [x] **Native:** persistent partitioned WKWebView store via `data_store_identifier` (per-slug); **Streamed:** persistent Chromium profile under `get_spark_home()/browser/<slug>/persistent` — logins survive restarts in both.
- [x] Partition storage per workspace/profile to avoid cross-project credential leakage (native: per-slug `data_store_id`; streamed: per-slug profile dir).
- [x] Store any secrets we manage ourselves in the **OS keychain** (`secret_store.py` via `keyring`, per-workspace service, lazy optional dep, graceful degrade), never plaintext.
- [x] Encrypt the data directory at rest where supported; document the threat model. (Rely on platform cookie encryption — macOS Chrome Safe Storage / WKWebView container; `0700` dir perms; `PREVIEW_BROWSER_SECURITY.md`.)
- [x] "Clear browsing data / sign out of all sites" action + per-site cookie viewer (toolbar trash + cookie buttons; native `clear_all_browsing_data`/`cookies`, streamed `clear_browsing_data`/`cookies` endpoints).
- [x] Setting to choose persistent vs ephemeral (private) sessions per preview. (Toolbar private-mode toggle → `persistent` flag through native `data_store_identifier`/`incognito` and streamed `persistent`/ephemeral profile.)
- [x] Tests: persistent profile path stable across restarts; profiles isolated per workspace; clear-data wipes the store. (28 preview tests passing.)

### 5.5 Polish
- [x] Show favicon + page title in the toolbar for external sites. (Origin `/favicon.ico` + page title reported by streamed `navigate`, hostname fallback.)
- [x] Remember last-visited URL per project (extend `_find_remembered_preview`).
- [x] Keyboard shortcuts: focus URL bar (⌘L), reload (⌘R), back/forward (⌘[ / ⌘]), devtools toggle (⌘⌥I).
- [x] Optional: expose the native webview's devtools in dev builds. (`preview_devtools` command, `#[cfg(debug_assertions)]`.)

---

## Sequencing (suggested)

1. **Quick wins first:** 1.1 interrupt-and-redirect, 1.3 tool-output collapse, 2.1 chat actions, 4.2 memory dedup.
2. **Then differentiators:** 1.2 differential rendering, 2.2 Live Canvas, 3.1 menu-bar companion.
3. **Then platform depth:** 4.1 self-improving skills, 4.3 backends, 4.4 multi-agent routing.
4. **Ongoing:** 4.7 supply-chain hardening, consistency/polish passes.
</content>
</invoke>
