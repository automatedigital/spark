# Plan: Stabilize Spark Web UI/Desktop Without Hiding Assistant Responses

## Goal

Fix the freeze/crash class seen in long Spark conversations while preserving one important product rule:

- [x] Assistant responses must remain fully readable by default. Do not add a hard assistant-message render budget that replaces the answer with a preview or forces the user to click to read the full response.
- [x] Tool calls, reasoning blocks, logs, and other secondary diagnostic output may be collapsed by default and expanded manually.
- [x] If the UI detects browser main-thread distress, it may enter a safe render mode that reduces expensive decorations, measurement, highlighting, and open diagnostic panels, while still showing the full assistant text.

## Current Understanding

- [x] The freeze is probably in the shared Web UI renderer, not exclusively in the macOS native shell.
- [x] The desktop app is a Tauri shell pointed at the local Spark dashboard sidecar on `http://127.0.0.1:9119`, so Activity Monitor showing `http://127.0.0.1:9119` is expected for the webview page.
- [x] The browser Web UI and desktop app share the same React chat renderer, markdown renderer, SSE event flow, and session APIs.
- [x] Prior fixes already reduced streaming markdown cost:
  - [x] `9f63cc10` added SSE reconnection and turn-status recovery.
  - [x] `2b4ec6d8` split markdown parsing into stable prefix plus live tail, batched token updates with `requestAnimationFrame`, deferred live syntax highlighting, and added a streaming soft cap.
- [x] The remaining risk is likely defense-in-depth work around huge secondary rows, layout/measurement churn, long-task detection, safe-mode recovery, and context replay after interrupted turns.

## Evidence To Keep In Mind

- [x] Screenshot 1 shows the app frozen while a response appears partially rendered and the turn status still says `THINKING...`.
- [x] Screenshot 2 shows a follow-up question receiving a clarification response despite visible prior context about Porsche fuel costs.
- [x] Screenshot 3 shows the webview/page process at about 100% CPU.
- [x] Attached logs show large web turns, large delegated/tool outputs, and at least one `interrupted_during_api_call`.
- [x] Logs showing `history=0` do not prove total context loss; they mean no explicit `conversation_history` argument was passed, which is normal when a cached web agent is reused. Still, cached-agent state must be validated after interrupts, reloads, compression, and sidecar restarts.

## Non-Goals

- [x] Do not hide or truncate the assistant's main answer behind a mandatory "show more" affordance.
- [x] Do not remove markdown rendering entirely for normal assistant answers.
- [x] Do not make desktop-only changes until browser Web UI behavior has also been tested.
- [x] Do not rely on a single fix. This should be resilient even if the exact freeze trigger changes.

## Phase 0: Reproduce And Instrument

- [x] Add a dev-only fixture or test helper that creates a synthetic heavy session with:
  - [x] a long assistant response with many markdown blocks,
  - [x] a long single-paragraph assistant response,
  - [x] long code blocks,
  - [x] a large table,
  - [x] large reasoning text,
  - [x] large tool outputs from multiple tools.
- [ ] Reproduce in browser Web UI at `http://127.0.0.1:9119`.
- [ ] Reproduce in the Tauri desktop app.
- [ ] Capture Chrome/WebKit performance profiles for:
  - [ ] live streaming,
  - [ ] turn completion,
  - [ ] loading the session from SQLite history,
  - [ ] expanding a large tool call,
  - [ ] expanding a large reasoning block.
- [x] Add safe debug logging for web turns:
  - [x] session id,
  - [x] whether context source is cached agent, DB replay, or rebuilt agent,
  - [x] message count,
  - [x] last few roles,
  - [x] approximate token count,
  - [x] whether the prior turn was interrupted or migrated.
- [x] Ensure logs never include full user/assistant/tool content for this debug line.

## Phase 1: Collapse Heavy Secondary Output By Default

- [x] Keep assistant messages fully visible.
- [x] Ensure all tool calls are collapsed by default when restored from history and while streaming.
- [x] Keep the existing manual toggle for opening tool calls.
- [x] In closed tool-call rows, show only lightweight metadata:
  - [x] tool name,
  - [x] status,
  - [x] elapsed time,
  - [x] small argument preview,
  - [x] output size or "large output" indicator.
- [x] When a tool call is opened, render result content inside a bounded scroll container.
- [x] Provide copy-full-result behavior so users can access the full tool output without forcing the full output into page layout.
- [x] Avoid media previews for large/unknown tool results until the tool row is opened.
- [x] Apply the same closed-by-default behavior to historical tool rows loaded from SQLite.
- [ ] Add tests that a historical session with many large tool results loads with tool rows closed.

## Phase 2: Collapse And De-Emphasize Reasoning Blocks

- [x] Keep reasoning blocks collapsed by default.
- [x] In closed reasoning rows, show:
  - [x] "Reasoning",
  - [x] active/done state,
  - [x] approximate word count,
  - [x] a very small plain-text preview only if it is cheap.
- [x] When opened, render reasoning in a bounded scroll container.
- [x] Do not markdown-parse reasoning text.
- [x] Avoid live animation or large preview updates for rapidly growing reasoning text.
- [ ] Add tests for large reasoning text loaded from history and streamed live.

## Phase 3: Add Frontend Long-Task Monitoring

- [x] Add a small browser-side performance monitor using `PerformanceObserver` for `longtask` entries where supported.
- [x] Track recent long tasks in memory:
  - [x] count,
  - [x] max duration,
  - [x] rolling time window,
  - [x] active session id,
  - [x] whether a turn is streaming.
- [x] When repeated long tasks are detected, automatically enable safe render mode for the active session.
- [x] Persist a per-session safe-mode flag in local storage so reopening the same heavy thread starts safely.
- [x] Publish a lightweight in-app status notice when safe mode turns on.
- [x] Add a manual "Disable safe mode for this thread" action.
- [x] Add tests or a controllable hook to simulate long-task events and verify safe mode activates.

## Phase 4: Define Safe Render Mode

Safe render mode must protect the page without hiding the assistant answer.

- [x] Full assistant message text remains visible.
- [x] Tool calls remain closed unless manually opened.
- [x] Reasoning remains closed unless manually opened.
- [x] Syntax highlighting is disabled or deferred for very large code blocks.
- [x] Inline media previews are disabled unless explicitly opened.
- [x] Row measurement is debounced or minimized.
- [x] Smooth auto-scroll is disabled for the active heavy thread.
- [x] Nonessential animations are disabled.
- [x] Search highlighting is deferred until the user explicitly searches.
- [x] The user can still copy assistant text and interact with the composer.
- [x] Add a visible but unobtrusive safe-mode indicator in the chat header.

## Phase 5: Reduce Virtualizer And Layout Churn

- [x] Audit `ChatPanel.tsx` virtualizer usage around `measureElement`.
- [x] Avoid measuring closed tool/reasoning rows as if their hidden full content affects layout.
- [x] Debounce measurement of the active streaming assistant row.
- [x] Avoid `smooth` scrolling while a large response is streaming.
- [x] Only auto-scroll when the user is already close to the bottom.
- [x] Use role-aware estimated row sizes:
  - [x] user row,
  - [x] assistant row,
  - [x] closed tool row,
  - [x] open tool row,
  - [x] closed reasoning row,
  - [x] open reasoning row.
- [x] Add browser-level verification that scrolling and typing remain responsive in a heavy session.

## Phase 6: Harden Context Replay And Interrupt Recovery

- [x] On follow-up web turns, resolve the current leaf session id before running the agent.
- [x] Load DB conversation history or validate cached-agent history before reuse.
- [x] Compare cached-agent state with DB state:
  - [x] message count,
  - [x] last role,
  - [x] last user content hash,
  - [x] last assistant presence,
  - [x] compression/migration state.
- [x] If cached state and DB state disagree, rebuild the web agent or pass explicit `conversation_history`.
- [x] Treat `interrupted_during_api_call` as a boundary:
  - [ ] persist partial visible assistant text if it was shown,
  - [x] otherwise persist a clear assistant note that the turn was interrupted,
  - [x] prevent the next turn from silently continuing from a dangling user-only state.
- [ ] Add backend tests covering follow-up after:
  - [ ] interrupt,
  - [ ] reload,
  - [ ] sidecar restart,
  - [ ] compression migration,
  - [ ] stale cached agent.

## Phase 7: Improve SSE And Turn Completion Recovery

- [x] Publish `chat.turn_done` only after final assistant state is persisted enough for the UI to reconcile.
- [x] Include authoritative metadata in `chat.turn_done`:
  - [x] resolved session id,
  - [x] message count,
  - [x] final assistant message id if available,
  - [x] interrupted flag if applicable,
  - [x] migrated session id if applicable.
- [ ] On `chat.turn_done`, reconcile local streamed state with the DB tail once, without replacing visible assistant content with stale/incomplete data.
- [x] Update turn-status to consider `_web_streaming`, not only `_web_queues`.
- [ ] Add tests for dropped SSE connection mid-turn.
- [ ] Add tests for turn completion after the EventSource has disconnected.

## Phase 8: Crash And Safe-Mode Recovery

- [x] Store the last active session id and render health metadata locally.
- [x] If desktop or browser reloads after a suspected heavy-thread stall, reopen that session in safe mode.
- [x] Add a small "Recovered this thread in safe mode" notice.
- [x] Allow the user to turn safe mode off once the thread is responsive.
- [x] Add a desktop diagnostic endpoint/action that reports:
  - [x] sidecar PID,
  - [x] active session id,
  - [x] active turn status,
  - [x] safe-mode state,
  - [x] recent long-task counts,
  - [x] current connection mode.
- [x] Document why Activity Monitor can show `http://127.0.0.1:9119` for Spark desktop.

## Phase 9: Verification Matrix

- [x] Browser Web UI using the same local server path on isolated port `http://127.0.0.1:9129`.
- [ ] Tauri desktop app using the bundled sidecar.
- [ ] Fresh session with a long assistant response.
- [x] Existing heavy session loaded from SQLite history.
- [x] Session with many delegated subagent/tool results.
- [ ] Session with a long reasoning stream.
- [ ] Session interrupted during an API call, then followed up.
- [ ] Session after compression migration.
- [ ] Remote/LAN dashboard with SSE reconnect.
- [x] Safe mode automatically enabled by simulated long tasks.
- [x] Safe mode manually disabled by the user.

## Tests To Add

- [ ] Frontend unit tests:
  - [ ] tool rows default closed for large historical outputs,
  - [ ] reasoning rows default closed for large historical reasoning,
  - [x] safe-mode state persists per session,
  - [x] safe-mode activation responds to long-task monitor events,
  - [x] assistant message content remains fully present in the DOM/state.
- [ ] Frontend browser tests:
  - [x] load heavy fixture session and confirm composer remains usable,
  - [ ] stream a long response and confirm stop button/sidebar remain interactive,
  - [x] expand a large tool row manually and confirm bounded scroll container,
  - [x] reload after safe-mode flag and confirm safe mode is active.
- [x] Backend tests:
  - [x] cached-agent mismatch triggers DB replay or rebuild,
  - [x] interrupted turn persists a coherent boundary,
  - [x] turn-status reports active while `_web_streaming` is active,
  - [x] turn_done includes reconciliation metadata.

## Implementation Order

- [x] Phase 0: build repro/instrumentation first.
- [x] Phase 1: collapse heavy tool output by default.
- [x] Phase 2: collapse reasoning output by default.
- [x] Phase 3: add long-task monitoring.
- [x] Phase 4: add safe render mode.
- [x] Phase 5: reduce virtualizer/layout churn.
- [x] Phase 6: harden context replay and interrupt recovery.
- [x] Phase 7: improve SSE/turn completion reconciliation.
- [x] Phase 8: add crash/safe-mode recovery and diagnostics.
- [ ] Phase 9: verify in browser and desktop.
- [x] Rebuild web assets.
- [x] Rebuild macOS app.
- [x] Run focused frontend tests.
- [x] Run focused backend tests.
- [x] Run full test suite before pushing.

## Open Questions

- [ ] Did screenshot 1 freeze while streaming, after completion, or during history reload?
- [ ] Did the user submit a redirect while the previous turn was still active?
- [ ] Are freezes correlated more with delegated tool output, reasoning output, markdown-heavy assistant output, or virtualizer measurement?
- [ ] Should safe mode be per session, global until restart, or both?
- [ ] Should there be a user-visible setting for "always collapse tool calls"?
- [ ] Can Tauri/WebKit expose a better Activity Monitor process name, or is that cosmetic only?
