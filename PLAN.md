# PLAN — Pete's VPS WebUI Bug Fixes (2026-06-10)

Feedback from Pete (Spark WebUI on a VPS) + his logs (`references/logs/petes-logs.md`) and
screenshot (`screenshots/bugs-issues/Screenshot 2026-06-10 at 09.47.16.png`).

## Root-cause research summary

1. **Chat freeze while waiting for an answer** — Web chat tokens and `chat.turn_done` arrive
   over the global `/api/events` SSE bus (`src/spark_cli/web/src/hooks/useEventBus.ts`).
   If the SSE connection drops mid-turn (common behind VPS reverse proxies / flaky networks —
   Pete's logs show repeated `httpx.ReadTimeout`/`ReadError`), the bus reconnects with backoff
   but **events emitted during the gap are lost**. A missed `chat.turn_done` leaves
   `ChatPanel.tsx` stuck with `streaming=true` → perpetual typing indicator = "freeze".
   There is no re-sync on reconnect and no stall watchdog.

2. **Sidebar can't scroll / no scrollbar** — `SidebarSessions.tsx:345` has
   `overflow-y-auto`, but with many expanded project groups the screenshot shows content
   clipped with no scrollbar. Likely a flex `min-h-0` chain break in the `<aside>` in
   `App.tsx` (~line 605) — the aside has no explicit `overflow-hidden`/height constraint in
   the hover-expanded absolute mode — plus the scrollbar is styled invisible. Needs repro +
   always-visible thin scrollbar.

3. **New project → new chat → can't upload** — Confirmed in code. The new-session hero
   composer in `ChatPage.tsx` (~line 118) renders `<PromptBar>` **without `onUploadFiles`**,
   and `PromptBar.tsx:747` only renders the upload (+) button when `onUploadFiles` is set.
   So any "new chat" started from the hero has no upload affordance at all. (Project
   `NewThreadCompose` at line 188 does pass it — but the global "New session" path doesn't.)
   Pete's workaround (upload via sidebar file pane, reference filename) matches this.

4. **Memory provider errors in logs** — Two distinct bugs:
   - `web_server.py:117` calls `HolographicMemoryProvider().initialize()` but the provider
     signature is `initialize(self, session_id, **kwargs)` → "missing 1 required positional
     argument" warning on every boot.
   - `agent.memory_manager: Memory provider 'holographic' initialize failed: file is not a
     database` → Pete's `memory_store.db` is corrupted; there is no recovery path, so memory
     fails on every turn.

   (Telegram `TimedOut` entries in the logs are the gateway's existing retry loop working as
   designed — network blips on the VPS, not a bug. No action beyond log-noise review.)

---

## Phase 1 — Chat freeze: SSE resilience + turn re-sync

- [x] In `src/spark_cli/web/src/hooks/useEventBus.ts`, emit a synthetic local event (e.g. `bus.reconnected`) to listeners whenever the EventSource reopens after an error.
- [x] In `src/spark_cli/web/src/components/ChatPanel.tsx`, handle `bus.reconnected` while `streaming=true`: re-fetch session messages (`api.getSessionMessages`) and clear `streaming`/`statusLabel` if the turn already finished (reuse the existing mount-time logic at ~line 555).
- [x] Add a stall watchdog in `ChatPanel.tsx`: if `streaming=true` and no token/event has arrived for N seconds (e.g. 45s), poll session state once; if turn finished, finalize; if not, keep waiting but show a "still working…" status instead of freezing silently.
- [x] Backend: add a lightweight turn-status source of truth the UI can poll — either include `turn_active` in the existing session-messages response or add `GET /api/conversations/{session_id}/turn-status` in `src/spark_cli/web_server.py` (web chat section, ~line 5395).
- [x] Verify `/api/events` SSE generator in `web_server.py` (~line 323) sends periodic heartbeats so proxies don't kill idle connections; add one if missing (the per-conversation stream at line 6184 already pings every 30s).
- [x] Frontend tests/build: `cd src/spark_cli/web && npm run build` passes with no type errors.

## Phase 2 — Sidebar scrolling + visible scrollbar

- [x] Reproduce: load the WebUI with enough projects/sessions to overflow the sidebar (can seed via SessionDB or mock) and confirm the scroll failure mode in both pinned-expanded and hover-expanded sidebar states.
- [x] Fix the flex/overflow chain: ensure `<aside>` in `src/spark_cli/web/src/App.tsx` (~line 605) and every wrapper down to `SidebarSessions`' scroll container (`SidebarSessions.tsx:345`) has `min-h-0` + proper `overflow` so the sessions list scrolls within the viewport.
- [x] Add an always-visible thin scrollbar style for the sidebar sessions list (custom `scrollbar-width: thin` / `::-webkit-scrollbar` styling in `src/spark_cli/web/src/index.css`, applied via a class on the scroll container).
- [x] Check the collapsed→hover-expanded absolute-positioned sidebar variant (`navHovered && !navExpanded` branch) gets the same scroll behavior.
- [ ] Verify with browser preview at a short viewport height (e.g. 700px) that all sessions are reachable by scroll and the scrollbar is visible.

## Phase 3 — Upload missing in new-chat composer

- [x] Add an `onUploadFiles` handler to the new-session hero `<PromptBar>` in `src/spark_cli/web/src/pages/ChatPage.tsx` (~line 118), using `api.uploadChatFiles` and appending `@files/<filename>` refs to the draft message (mirror `NewThreadCompose.handleUpload` at line 161).
- [x] Confirm `NewThreadCompose` upload works immediately after project creation: `POST /api/workspace/projects` (`workspace_routes.py:204`) must create the project directory on disk before `_project_dir()` (line 78) is hit by the upload route — fix ordering if the dir is created lazily.
- [x] Add drag-and-drop + paste-to-upload support on the hero composer if PromptBar already wires it (it does via `onUploadFiles` — verify it activates once the prop is passed).
- [ ] Manual verify in preview: create project → "new chat" → upload via + button, drag-drop, and paste; file lands in workspace and `@files/...` ref is inserted.

## Phase 4 — Memory provider fixes

- [ ] Fix `_init_memory_store()` in `src/spark_cli/web_server.py` (~line 115): pass a session id (e.g. a boot/warmup session id) to `provider.initialize(...)`, or change the call to match the provider API; eliminate the "missing 1 required positional argument" warning.
- [ ] Add corrupted-DB recovery in `src/plugins/memory/holographic/__init__.py` `initialize()`: catch `sqlite3.DatabaseError` ("file is not a database"), rename the bad file to `memory_store.db.corrupt-<timestamp>`, recreate a fresh store, and log a clear one-time warning.
- [ ] Audit `src/agent/memory_manager.py` (~line 385) so a failing memory provider degrades gracefully (no repeated per-turn warnings — warn once per process).
- [ ] Add unit tests: corrupted-db recovery path and web_server memory-init call signature (tests must use the `_isolate_spark_home` fixture; never touch `~/.spark`).
- [ ] Run `python -m pytest tests/ -k "memory or holographic" -q` and `ruff check src/`.

## Phase 5 — Test, lint, and PR

- [ ] Run full relevant test suites: `python -m pytest tests/ -m "not slow" -q` (use `.venv`, not anaconda).
- [ ] `ruff check src/` and `mypy src/agent/ src/spark_cli/` clean for touched files.
- [ ] `cd src/spark_cli/web && npm run build` — production bundle builds clean.
- [ ] Browser-preview smoke test: new session upload, project thread upload, sidebar scroll, simulated SSE drop mid-turn recovers without freeze.
- [ ] Open a PR from a feature branch (e.g. `fix/webui-pete-feedback`) — never push to main directly.

## Phase 6 — Rebuild + release macOS desktop app

- [ ] After PR is merged to main: bump desktop version (next after 1.0.8) per the build skill's convention.
- [ ] Run `/build-mac` skill to rebuild the .app + .dmg with the updated web UI + backend.
- [ ] Smoke-test the built app: launch, new session upload, sidebar scroll.
- [ ] Run `/release-mac` skill to publish the DMG to GitHub Releases.
- [ ] Notify Pete with the changelog (freeze fix, sidebar scroll, upload in new chat, memory store recovery) and ask him to `git pull` + restart on the VPS.
