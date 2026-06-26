# PLAN

## Researched Tasklist For Agents

### Agent 1: Clickable Links In User Chat Bubbles

- [x] Start in `src/spark_cli/web/src/components/ChatPanel.tsx`.
- [x] Update the user-bubble plain text renderer around `BUBBLE_TOKEN_RE` and `renderTokens()` so user-sent URLs become clickable without moving user messages through the full assistant `Markdown` renderer.
- [x] Preserve the existing token behavior: `@file` references and leading slash commands must still render with `text-primary font-medium`.
- [x] Add a small URL tokenizer that recognizes `http://`, `https://`, and likely `www.` URLs inside normal user text.
- [x] Strip trailing punctuation from the clickable href/text boundary when punctuation is sentence grammar, for example `https://example.com).` should link only the URL.
- [x] Keep URL parsing intentionally modest: do not parse markdown, code spans, or local file paths in user bubbles unless they already worked there.
- [x] Render links with subtle styling that matches user bubbles: quiet underline or primary tint on hover, no bulky chips, and `break-words`/`overflow-wrap` behavior for long URLs.
- [x] Use `target="_blank"` and `rel="noreferrer"` for browser links.
- [x] For desktop/Tauri, check existing helpers in `src/spark_cli/web/src/lib/api.ts` and `src/spark_cli/web/src/lib/desktop.ts`; use the same external-opening convention already used by `Markdown.tsx` if the app needs intercepted desktop opening.
- [x] Ensure link clicks do not trigger edit/retry/fork/copy hover controls or otherwise interfere with the user row action buttons.
- [x] Keep assistant rendering unchanged: `src/spark_cli/web/src/components/Markdown.tsx` already handles assistant markdown links, bare URLs, and file path chips.
- [x] Add focused tests near the existing markdown/render tests, or add a small `ChatPanel` renderer test if needed.
- [x] Cover these cases in tests: plain URL, `www.` URL, URL followed by `.`, URL inside parentheses, existing `@files/foo.ts`, leading `/model`, mixed text with two links, and unsafe-looking text that should remain plain.
- [x] Run the relevant frontend tests from `src/spark_cli/web`, especially `Markdown.test.ts` and any new `ChatPanel` test.
- [x] Acceptance covered by `userBubbleTokens.test.ts`: `https://` links are clickable tokens while `@files/app.ts` and `/model` remain highlighted tokens.

### Agent 2: Open In Files Should Select And Preview The File

- [x] Start in `src/spark_cli/web/src/components/Markdown.tsx`, `src/spark_cli/web/src/lib/globalNavigation.ts`, and `src/spark_cli/web/src/pages/FilesPage.tsx`.
- [x] Confirm the current chat action dispatches `setGlobalNavTarget({ type: "file", path, name })` from `FilePathAction.handleOpenInFiles()`.
- [x] Fix the navigation lifecycle so clicking `Open in Files` switches to the Files area and then selects the file preview, rather than only changing tabs.
- [x] Prefer reusing `GLOBAL_NAV_EVENT`, `GLOBAL_NAV_TARGET_KEY`, and `takeGlobalNavTarget("file")`; only add new routing state if the existing event/localStorage handoff cannot cover the tab switch plus delayed mount.
- [x] Audit the app-level global navigation handling in `src/spark_cli/web/src/App.tsx` so a `file` target routes to the Files view before `FilesPage` consumes the target.
- [x] Harden `workspaceRelativePath()`, `parentDirForFile()`, and `fileEntryFromPath()` in `FilesPage.tsx` for paths produced by chat output.
- [x] Support workspace-relative paths such as `files/report.md`, `./files/report.md`, and nested paths like `reports/2026/summary.md`.
- [x] Support absolute Spark workspace paths containing `/.spark/workspace/`.
- [x] Support profile-aware Spark workspace paths if they appear in output, for example paths containing `/.spark/profiles/<profile>/workspace/`.
- [x] Be careful with non-workspace absolute paths: either leave them as safe non-previewable entries with a clear error, or normalize only when the backend file APIs can actually read them.
- [x] Make selected-file feedback immediate: set `selectedFile` before the read starts, show loading for text files, and keep image/video/binary previews instant.
- [x] Ensure the file browser highlights the selected file after `setCurrentPath(parentDirForFile(...))`; if the list loads after selection, selection should not be lost.
- [x] Preserve the special `.canvas.json` behavior in `handleSelectFile()`, which routes canvas files to the Canvas tab.
- [x] Add tests for pure path helpers by exporting or moving them to a small testable utility if that is the least invasive option.
- [x] UI-level delayed-mount behavior resolved through the existing global navigation handoff; path normalization and selected-file construction are covered by extracted helper tests.
- [x] Cover these path cases in tests: `files/a.md`, `./files/a.md`, `/Users/joe/.spark/workspace/files/a.md`, `/Users/joe/.spark/profiles/dev/workspace/files/a.md`, nested folders, quoted paths, and backslash-normalized paths.
- [x] Run `Markdown.test.ts` because it already asserts local file paths render `Open in Files`.
- [x] Acceptance covered by `Markdown.test.ts` for `Open in Files` rendering and `filesPathUtils.test.ts` for selected file/path preview setup.

### Agent 3: Parallel Thread Progress, Stop Controls, And Notifications

- [x] Start in `src/spark_cli/web/src/components/ChatPanel.tsx`, `src/spark_cli/web/src/lib/chatTurnState.ts`, `src/spark_cli/web/src/lib/sessionStore.tsx`, `src/spark_cli/web/src/lib/unreadSessionStore.ts`, and `src/spark_cli/web/src/components/NotificationBell.tsx`.
- [x] Treat the backend as the source of truth before adding new frontend state: `src/spark_cli/web_server.py` already exposes `GET /api/conversations/{session_id}/turn-status` and `GET /api/conversations/{session_id}/stream-snapshot`.
- [x] Understand the current frontend recovery path: `ChatPanel` polls `turn-status` when idle, polls `stream-snapshot` while streaming, handles `BUS_RECONNECTED_TOPIC`, and uses `normalizeBackendPhase()` to restore `starting`, `streaming`, `stopping`, or `redirecting`.
- [x] Identify why returning to an in-progress thread can lose the stop button: likely causes include `turnState` being local to the mounted `ChatPanel`, session switches clearing local buffers, or events for inactive sessions being ignored by `if (!sid || sid !== activeSessionRef.current) return`.
- [x] Do not make one global `streaming` boolean for all sessions. Progress must be keyed by session id or recovered per selected session.
- [x] When a selected session changes, immediately call `getTurnStatus(selectedId)` and set the local `turnState` from `phase`/`interrupt_requested` before waiting for SSE.
- [x] If `turn_active` is true, call `getStreamSnapshot(active_turn_session_id ?? selectedId)` and hydrate the current assistant bubble with `stream_text` when available.
- [x] If `turn_active` is false, ensure the UI clears streaming state, finalizes any local assistant bubble, and refreshes recent history from `getSessionMessages()`.
- [x] Make stop use the authoritative active session id returned by turn status when present, while still preserving the visible selected thread id.
- [x] Preserve migration behavior: `chat.session_migrated` can move the active turn from the old session id to a new compressed session id; do not break `onSessionUpdated`.
- [x] Scope `pendingInitialMessage` by session id so the optimistic first user bubble for a newly created thread cannot appear in another active thread while that other thread is still streaming.
- [x] Store pending initial messages in a per-session map so starting thread B does not overwrite thread A's first prompt before thread A has saved backend history.
- [x] Add a focused regression test for session-scoped pending initial messages, covering both directions: thread B's first prompt must not render at the top of thread A, and thread A's first prompt must remain available while thread B is also pending.
- [x] Keep per-session progress around when navigating away so live reasoning/tool rows do not disappear when switching between active threads; do not mutate conversation history or system prompts to do this.
- [x] Use `SessionInfo.is_active` and `message_count` from `src/spark_cli/web/src/lib/api.ts` only as sidebar hints; use `turn-status` for stop-button truth.
- [x] Update `sessionStore.tsx` notification logic so off-screen thread completion or new assistant output creates exactly one notification entry through `addSessionNotification()`.
- [x] Refresh existing unread chat notifications when later session metadata arrives, so an early `Untitled thread` notification updates to the final generated thread title.
- [x] Make chat notification rows open their thread via the global thread navigation target, while keeping the `x` button as dismiss-only.
- [x] Avoid notifying for the thread the user is currently viewing.
- [x] Avoid duplicate notifications when `sessions.changed` fires multiple times for title updates, auto-title, tool-only changes, or final `turn_done` refreshes.
- [x] Sync read state through `markSessionRead()` when the user opens a thread, `dismissSessionNotification()` when they dismiss one item, and `clearAllSessionNotifications()` when they clear the bell.
- [x] Consider making `SessionNotification` include a reason/status such as `completed` vs `updated` only if the existing bell needs clearer copy; keep payload additive and small.
- [x] Add tests for `unreadSessionStore.ts` because it is currently untested and owns deduping, dismissal, and unread counts.
- [x] Extend `chatTurnState.test.ts` for returning to an active backend turn from idle, including `starting`, `stopping`, `redirecting`, and unknown active phases.
- [x] Add focused React or store tests for `sessionStore.tsx` if the existing setup allows it; otherwise cover notification dedupe with extracted pure helpers.
- [x] Confirmed no backend endpoint contract changes were needed, so `tests/spark_cli/test_web_server_events.py` did not require extension.
- [x] Manual acceptance completed in the web UI: start thread A, switch to thread B, return to thread A while it is running, and confirm status plus stop button remain correct.
- [x] Manual acceptance completed in the web UI: off-screen thread completion produces one chat notification, and the notification row opens/clears the thread.
- [x] Stopping/redirect state covered by `chatTurnState.test.ts` for interrupted, stopping, redirecting, unknown active phases, and late backend recovery.

## Cross-Agent Guardrails

- [x] Keep changes scoped to the web chat/files/notification surfaces unless a backend contract is proven incomplete.
- [x] Do not introduce broad visual redesign; use existing compact Spark dashboard styling.
- [x] Do not alter past conversation context, toolsets, system prompts, or prompt-cache-sensitive behavior for UI state.
- [x] Do not hardcode `~/.spark` in backend code; use profile-safe helpers there. Frontend path parsing may recognize displayed paths, but backend storage paths must stay profile-safe.
- [x] Keep APIs additive where possible so older clients ignore new fields.
- [x] Prefer small pure helpers for parsing/deduping so tests do not require a full browser harness.

## Final Verification

- [x] From `src/spark_cli/web`, run the relevant frontend tests: markdown rendering, chat turn state, unread session store, and any new file-navigation tests.
- [x] Backend tests not required because this work did not change backend endpoint contracts.
- [x] Manually tested the desktop web UI with two parallel running threads, notification open/clear behavior, and live progress restoration while switching threads.
- [x] Confirm there are no unrelated refactors, no noisy style drift, and no regression to assistant markdown/file path rendering.
- [x] After code changes are complete, run `graphify update .` so the project graph stays current.
