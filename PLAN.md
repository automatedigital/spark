# Plan: Fix Live Chat Freeze After Many Tool Calls

## Incident Summary

- [x] Confirmed this still reproduces in the installed macOS desktop app version `1.3.6`.
- [x] Confirmed the failing session is `20260618_195415_a0b09977`.
- [x] Confirmed the backend completed the turn successfully:
  - [x] `Turn ended` logged at `2026-06-18 19:58:01`.
  - [x] `turn_active` is now `false`.
  - [x] SQLite/session history contains the full response after restart.
- [x] Confirmed the broken path is the live in-turn UI path, not durable persistence.
- [x] Confirmed restart/reload recovers because history replay from storage works.

## Current Root Cause Hypothesis

- [x] The app is not crashing because the thread is simply too long.
- [x] The failing thread has only 39 persisted messages, 18 tool turns, and one final assistant message around 9k characters.
- [x] The live webview likely falls behind while receiving many tool/reasoning/token events.
- [x] The shared SSE bus currently uses a bounded per-client queue and can silently drop a subscriber if it falls behind.
- [x] If that happens before `chat.turn_done`, the frontend can remain in `streaming=true` even though the backend finished.
- [x] The frontend recovery watchdog is too slow and too dependent on the main thread being healthy.
- [x] Existing fixes reduced markdown cost, but did not guarantee delivery or recovery of authoritative turn completion.

## Non-Negotiables

- [ ] Do not ship another desktop build until the live failure is reproduced in a test harness and fixed.
- [ ] Do not rely on manual restart as recovery.
- [ ] Assistant answers remain fully readable.
- [ ] Tool calls and reasoning can stay collapsed by default.
- [ ] `chat.turn_done` or an equivalent authoritative completion signal must not be lossy.
- [ ] A finished backend turn must clear the composer/stop-button state quickly, even if token streaming was dropped.

## Phase 1: Reproduce The Exact Failure

- [ ] Add a deterministic backend/frontend stress route or test-only fixture that emits:
  - [ ] 15-30 `chat.tool_start` / `chat.tool_end` pairs.
  - [ ] large tool results comparable to this incident: 500 chars to 9k chars.
  - [ ] reasoning events.
  - [ ] a streamed final assistant response of 8k-15k chars.
  - [ ] a final `chat.turn_done`.
- [ ] Run the fixture in the browser Web UI.
- [ ] Run the same fixture in the packaged Tauri desktop app.
- [ ] Capture whether the frontend receives `chat.turn_done`.
- [ ] Capture whether the composer exits responding mode within 2 seconds of backend completion.
- [ ] Capture main-thread long tasks during the live stream.
- [ ] Save screenshots or traces for before/after comparison.

## Phase 2: Make Turn Completion Non-Lossy

- [x] Change SSE fan-out so low-priority events cannot crowd out completion events.
- [x] Give `chat.turn_done`, `chat.interrupted`, `chat.session_migrated`, and approval events priority handling.
- [x] Do not silently discard a chat subscriber on queue overflow without a recoverable signal.
- [x] Coalesce or drop only low-value live events when the client falls behind:
  - [x] token deltas,
  - [x] repeated status updates,
  - [x] large tool-result payloads.
- [x] Add queue overflow diagnostics with session id, topic, queue depth, and dropped-event counts.
- [x] Add backend tests proving `chat.turn_done` is delivered or recoverable after queue pressure.

## Phase 3: Reduce Live Event Payload Pressure

- [x] Stop sending full tool result content through the live shared event bus by default.
- [x] For `chat.tool_end`, send lightweight metadata first:
  - [x] tool id,
  - [x] name,
  - [x] elapsed time,
  - [x] result character count,
  - [x] small preview,
  - [x] `has_full_result`.
- [x] Add an on-demand endpoint to fetch full tool results when a user expands a tool row.
- [x] Keep full tool results persisted in session history.
- [x] Ensure historical reload still shows full data when the row is manually opened.
- [ ] Add tests that large tool results do not enter the live React state unless expanded.

## Phase 4: Harden Frontend Finalization

- [x] On `chat.turn_done`, immediately set `streaming=false` before any expensive reconciliation work.
- [x] Fetch the authoritative DB tail after completion and reconcile once.
- [ ] If `chat.turn_done` is missed, poll `turn-status` sooner:
  - [ ] shortly after the first assistant token starts,
  - [x] whenever no events arrive for 5-10 seconds during an active turn,
  - [ ] immediately after SSE reconnect.
- [x] If `turn-status` says inactive, clear responding UI and load the DB tail.
- [ ] Add a visible non-blocking recovery notice only if reconciliation had to recover a missed completion.
- [ ] Add frontend tests for missed `chat.turn_done` while final history is available.

## Phase 5: Fix Remaining Render Hot Spots

- [x] Verify `safeMode` is passed through `Markdown` block rendering; currently the memoized block path appears to drop it.
- [ ] Keep markdown parsing disabled or minimal for active streaming assistant text, then parse after turn completion.
- [ ] Ensure closed tool rows do not keep large `result` strings in rendered props.
- [ ] Ensure closed reasoning rows do not re-render on every reasoning delta.
- [ ] Audit virtualizer measurement during streaming:
  - [ ] no repeated full-row measurement loops,
  - [ ] no smooth scroll during active streaming,
  - [ ] no measuring hidden tool/reasoning content.
- [ ] Add component tests for safe mode and live streaming render stability.

## Phase 6: End-To-End Verification Gate

- [ ] Browser Web UI stress test passes.
- [ ] Packaged Tauri app stress test passes.
- [ ] Real model/browser-tool scenario similar to the landing-page prompt passes.
- [ ] Composer exits responding mode after backend completion without restart.
- [ ] The final answer is fully readable.
- [ ] Tool rows remain collapsed and expandable.
- [ ] Expanding a large tool row fetches and displays the full result.
- [ ] Activity Monitor no longer shows sustained 100% CPU after turn completion.
- [ ] Full frontend tests pass.
- [ ] Focused backend SSE/turn-status tests pass.
- [ ] Full Python test suite passes before release.

## Release Rule

- [ ] Do not build or release a new macOS DMG until every Phase 6 checkbox is complete.
- [ ] Release notes must mention the exact tested scenario, not just generic "rendering fixes".
