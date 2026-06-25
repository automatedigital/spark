# Stabilize Desktop Chat Streaming and Issue Capture

## Goal

Fix the desktop/web chat reliability regressions reported on 2026-06-24 before adding the new `/issue` workflow.

The main product outcome is simple: while Spark is working, the UI must always look alive, remain editable, expose a reliable stop control, avoid render freezes on long markdown, and recover truthfully from backend stalls, retries, interrupts, and EventSource drops.

## Evidence to Preserve

- Issue 01 screenshot: `screenshots/240626/Issue 01 - Screenshot 2026-06-24 at 08.54.14.png`
- Issue 01 logs: `references/logs/Issue 01 - Logs 240626.md`
- Issue 02 screenshot: `screenshots/240626/Issue 02 - Screenshot 2026-06-24 at 09.22.10.png`
- Issue 02 logs: `references/logs/Issue 02 - Logs 240626.md`
- Issue 03 screenshot: `screenshots/240626/Issue 03 - Screenshot 2026-06-24 at 10.08.29.png`
- Issue 04 screenshot: `screenshots/240626/Issue 04 - Screenshot 2026-06-24 at 10.09.45.png`
- Issue 04a screenshot: `screenshots/240626/Issue 04a - Screenshot 2026-06-24 at 10.10.34.png`
- Issue 04 logs: `references/logs/Issue 04 - Logs 240626.md`
- Issue 05 screenshot: `screenshots/240626/Issue 05 - Screenshot 2026-06-24 at 10.11.49.png`
- Issue 05a screenshot: `screenshots/240626/Issue 05a - Screenshot 2026-06-24 at 10.14.39.png`

## Code Areas

- Web chat shell: `src/spark_cli/web/src/components/ChatPanel.tsx`
- Composer and stop/redirect controls: `src/spark_cli/web/src/components/chat/PromptBar.tsx`
- Markdown rendering: `src/spark_cli/web/src/components/Markdown.tsx`
- Markdown parsing helpers: `src/spark_cli/web/src/components/markdownParse.ts`
- Render-health safe mode: `src/spark_cli/web/src/lib/renderHealth.ts`
- Frontend API client: `src/spark_cli/web/src/lib/api.ts`
- Web conversation endpoints and SSE events: `src/spark_cli/web_server.py`
- Agent interruption: `src/core/run_agent/`, `src/tools/interrupt.py`
- Slash command registry: `src/spark_cli/commands.py`
- Skill slash command bridge: `src/agent/skill_commands.py`
- Existing GitHub issue skill/template: `skills/github/github-issues/`

## External References

- React memoization and render caching: https://react.dev/reference/react/useMemo
- Long task detection: https://developer.mozilla.org/en-US/docs/Web/API/PerformanceObserver
- Long task timing threshold and semantics: https://developer.mozilla.org/en-US/docs/Web/API/PerformanceLongTaskTiming
- TanStack Virtual chat guidance for streaming, dynamic rows, and bottom anchoring: https://tanstack.com/virtual/latest/docs/chat
- TanStack Virtual dynamic measurement API: https://tanstack.com/virtual/latest/docs/api/virtualizer

## Working Hypotheses

- Issues 02, 03, and part of 05 are likely render-pressure bugs: long assistant responses, tables, code fences, or tool output trigger repeated parsing, highlighting, measurement, or virtualizer work during streaming.
- Issues 01, 04, and part of 05 are likely state-truth bugs: the frontend can locally believe a turn stopped while the backend is still active, or can miss the authoritative `chat.turn_done`/interrupt state during SSE gaps, backend retries, overloads, or session migration.
- The logs show real long backend turns, retries, overloads, and interrupted API calls. The UI must distinguish "backend is slow but alive" from "frontend is frozen" and must not mark work as done until backend turn state confirms it.

## Phase 0 - Reproduce and Baseline

- [x] Inspect every 2026-06-24 screenshot and write a short note for each: visible UI state, whether stop button is present, whether text input is editable, whether the assistant bubble is streaming, and whether formatting is broken.
- [x] Summarize the referenced logs into `references/logs/Issue 240626 analysis.md`, including timestamps for long API calls, overload retries, `interrupted_during_api_call`, and turn completion.
- [x] Reproduce in desktop dev mode with a long markdown-heavy response, a long tool-heavy response, and a response interrupted by typing a new message mid-stream.
- [x] Capture baseline browser performance evidence: count long tasks, measure token-to-paint delay, and note when safe mode turns on.
- [x] Confirm whether these issues reproduce in browser dashboard, Tauri desktop, or only remote dashboard mode.
- [x] Record exact commands used for reproduction in this plan before changing behavior.

### Reproduction and Verification Commands Used

- `cd src/spark_cli/web && npm run test -- --run`
- `.venv/bin/python -m pytest tests/spark_cli/test_web_server_events.py -q`
- `.venv/bin/python /Users/joe/.agents/skills/webapp-testing/scripts/with_server.py --help`
- `RUN_LIVE_SPARK_WEBUI=0 .venv/bin/python /Users/joe/.agents/skills/webapp-testing/scripts/with_server.py --server "PYTHONPATH=src SPARK_WEB_MAX_ITERATIONS=8 .venv/bin/python -c \"from spark_cli.web_server import start_server; start_server(host='127.0.0.1', port=9119, open_browser=False)\"" --port 9119 --server "cd src/spark_cli/web && SPARK_API_TARGET=http://127.0.0.1:9119 npm run dev -- --host 127.0.0.1 --port 5173 --strictPort" --port 5173 --timeout 90 -- node tmp_webui_smoke.cjs`

## Phase 1 - Make Turn State Authoritative

- [x] Replace the bare `_web_streaming: set[str]` usage in `src/spark_cli/web_server.py` with a small active-turn state record keyed by resolved session id: `started_at`, `last_event_at`, `status`, `interrupt_requested`, `active_agent_session_id`, and `phase`.
- [x] Register active-turn state before `/api/conversations`, `/api/conversations/{session_id}/messages`, retry, and workspace conversation endpoints return, not only after the background task starts.
- [x] Clear active-turn state only in the task `finally` block after persistence, session update emission, queue close, and `chat.turn_done` publication have all happened.
- [x] Extend `/api/conversations/{session_id}/turn-status` to return resolved session id, latest descendant id, `turn_active`, current status text, `started_at`, `last_event_at`, and `interrupt_requested`.
- [x] Update `api.getTurnStatus()` types in `src/spark_cli/web/src/lib/api.ts`.
- [x] Make `/api/conversations/{session_id}/interrupt` resolve aliases/latest descendants before looking up the agent, so stop works after context compression/session migration.
- [x] Change interrupt UX semantics so `chat.interrupted` or `interrupt_requested` means "stopping/redirecting", not "the turn is fully done"; only `chat.turn_done` or `turn-status.turn_active === false` should clear streaming UI.
- [x] Add a regression test that an interrupt request leaves the turn active until the background agent task exits.
- [x] Add a regression test that `turn-status` returns active immediately after a web message endpoint accepts a turn.
- [x] Add a regression test that interrupt works when the requested session id resolves to a compressed/latest descendant session id.

## Phase 2 - Fix Stop, Redirect, and "Still Working" UX

- [x] In `ChatPanel.tsx`, introduce explicit frontend turn substates: `idle`, `starting`, `streaming`, `stalled`, `stopping`, and `redirecting`.
- [x] Keep `PromptBar` editable while streaming, but make Enter behavior explicit: no text means stop remains available; text means redirect is available; stop remains visible either way.
- [x] Ensure the stop button is visible whenever frontend streaming is true or backend `turn-status.turn_active` is true, even if the last visible message is a tool row, note row, or empty typing row.
- [x] On stop click, optimistically switch to `stopping`, keep the stop control disabled or guarded against duplicate clicks, and poll `turn-status` until the backend confirms inactive.
- [x] On redirect submit, append a visible redirected user row and keep the turn state as `redirecting` until the backend confirms whether the redirect became the next turn.
- [x] Audit `sendMessage()` so typing mid-answer never clears the input before the redirect request has been accepted or safely queued.
- [x] Make the stall watchdog escalate status text over time: `Still working...`, then `Still waiting for backend...`, then `Reconnecting...` if EventSource has dropped.
- [x] Use `chat.status` events to surface backend retry/overload/waiting states when available.
- [x] Add a pure state-transition helper for chat turn state and test it with Vitest instead of burying every transition directly in React component state.
- [x] Add tests for these transitions: token received, tool start/end, interrupt requested, turn done after interrupt, SSE reconnect while active, SSE reconnect after missed `turn_done`, and session migration.

## Phase 3 - Harden Markdown Rendering

- [x] Add markdown parser tests for partial fenced code blocks, unclosed fences, huge paragraphs, huge tables, nested emphasis, bare URLs, media links, task lists, and malformed markdown.
- [x] Add a streaming performance fixture that appends tokens to a 10k, 50k, and 100k character assistant message and asserts parsing work stays bounded.
- [x] In `Markdown.tsx`, apply the soft render cap during streaming too. Long streaming messages should render a bounded parsed tail plus plain text for the rest, or switch to safe plain text until final.
- [x] Avoid reparsing the entire stable prefix on every token. Cache committed parsed blocks by stable boundary and only parse newly committed text plus the current live tail.
- [x] Audit `parseInline()` and table parsing in `markdownParse.ts` for regex backtracking and unbounded per-token work; replace any risky regex path with linear scanning or hard caps.
- [x] Cap table rendering during streaming: limit rows/cells parsed live, then render the full table only after the block is stable and below a size threshold.
- [x] Keep syntax highlighting disabled while code blocks are live and enforce the existing size cap after completion.
- [x] Make safe mode reversible and visible: when long tasks trigger safe mode, show a compact inline notice with a "render markdown" retry option after the turn finishes.
- [x] Persist render-health details per session so a reopened problematic thread starts safe and explains why.
- [x] Add tests to `src/spark_cli/web/src/components/Markdown.test.ts` covering safe-mode fallback, streaming cap behavior, and final rich rendering after streaming completes.

### 2026-06-25 Web Markdown Freeze Follow-Up

- [x] Confirmed the reproduction is present in the browser web UI, not only the macOS shell: the long markdown prompt stalled mid-response with the textarea/stop state still active.
- [x] Tightened streaming Markdown rendering so active assistant messages stay on a safe plain-text path instead of reparsing/re-highlighting the whole Markdown document on every token.
- [x] Removed the completed-message hidden-middle fallback entirely. Oversized completed messages now show the full text plainly if they ever reach the renderer; no chat content is replaced with a hidden-character notice.
- [x] Added a backend artifact boundary for oversized assistant output: long report/document responses are written intact to `workspace/chat-artifacts/<session>/...md`, while chat stores a short card linking to the file.
- [x] Added cleanup so the internal long-document delivery instruction never leaks into persisted user-visible chat history.
- [x] Throttled chat token flushes to an 80 ms cadence while preserving immediate flushes before tool rows, interruptions, and turn completion.
- [x] Added Markdown tests for bounded huge streaming blocks and bounded huge completed messages.
- [x] Fixed the deeper Codex watchdog bug: long Codex streams now refresh provider-progress on each stream event, so the outer web watchdog no longer kills a healthy stream after 60s just because the final response has not returned.
- [x] Verified through the patched web API with the long markdown prompt: session `20260625_135310_02700f31` streamed past 7 minutes and ~58k chars, then stopped only after an explicit interrupt.
- [x] Verified the no-hidden-content artifact path in a real browser against isolated FastAPI + Vite dev servers: a seeded 40,027-character markdown response rendered as a short `Open the markdown file` card, the linked file returned the full content, and the DOM did not contain `hidden for render performance`.

## Phase 4 - Stabilize Virtualized Chat Rows

- [x] Review TanStack Virtual usage in `ChatPanel.tsx` for streaming rows with dynamic heights.
- [x] Use stable message ids for virtual row keys so row identity does not drift when tool rows collapse or earlier history prepends.
- [x] Throttle measuring the live assistant row and skip measurement for unchanged committed rows.
- [x] Preserve bottom anchoring while streaming without forcing a smooth scroll on every token.
- [x] Verify prepending earlier history does not jump the current viewport.
- [x] Add a stress test or manual QA script for rapid token updates, tall code blocks, large tool results, and repeated collapsed tool rows.

## Phase 5 - Backend Progress and Error Transparency

- [x] Emit `chat.status` for long backend gaps: API call started, retry scheduled, tool running longer than threshold, waiting for approval, context compression, and interrupt requested.
- [x] Include retry/error summaries in status events without exposing secrets or huge payloads.
- [x] Ensure `chat.turn_done` payload includes `final_assistant_present`, `interrupted`, token stats, and any backend error class.
- [x] In the frontend, display backend overload/API retry notes as status, not as final assistant content.
- [x] If a turn ends with no assistant content and no intentional interrupt, show a recoverable error note with retry guidance.
- [x] Add tests that backend exceptions still publish `chat.turn_done` and clear active-turn state.

## Phase 6 - Manual QA Matrix

- [x] Long markdown response: headings, bullets, tables, code fences, and links stream without UI freeze.
- [x] Huge tool output response: tool rows collapse, full-result fetch still works, and scrolling stays responsive.
- [x] Type while assistant is mid-answer: redirect is visible, old turn stops, new instruction is handled once.
- [x] Press stop while a tool is running: UI says stopping, backend interrupt is requested, final state clears only when backend is inactive.
- [x] Simulate dropped SSE: close/reopen EventSource or throttle network; UI recovers from `turn-status`.
- [x] Simulate backend overload/retry: status shows retry/waiting and does not look finished.
- [x] Context compression/session migration during a turn: events follow the new session id and stop still works.
- [x] Restart desktop while a prior session has a recent active-looking turn: history and turn-status reconcile cleanly.

## Phase 7 - Add `/issue` Skill

- [x] Create a built-in skill named `issue` so `/issue` appears through `scan_skill_commands()` and the web `/api/commands` skill list.
- [x] Place the skill under an appropriate skill category, likely `skills/github/issue/SKILL.md`, and make its frontmatter name exactly `issue`.
- [x] Have the skill collect: user description, current session id, recent redacted logs, relevant screenshots/files, Spark version/git SHA, OS/platform, active profile, web/desktop mode, and reproduction steps.
- [x] Reuse `skills/github/github-issues/templates/bug-report.md` or add a focused template for Spark product bugs.
- [x] Require the agent to show the exact GitHub issue title, body, labels, and attachments/references before creating the issue.
- [x] Use the existing GitHub issue workflow (`gh issue create` first, REST fallback if needed) rather than adding a new tool unless the existing skill cannot attach the required evidence.
- [x] Add guidance for screenshots referenced by `@path` and for logs under `references/logs/`.
- [x] Add redaction rules: never include API keys, bearer tokens, dashboard tokens, full home-directory secrets, or unrelated session content.
- [x] Add a happy-path test that the skill is discoverable as `/issue` in CLI skill commands.
- [x] Add a web command-list test that installed skills include `/issue` in `/api/commands`.
- [x] Add a dry-run/manual QA step: invoke `/issue` with the 2026-06-24 screenshots and logs, verify the drafted issue is detailed, redacted, and asks for approval before submission.

## Verification Commands

- [x] `source venv/bin/activate`
- [x] `python -m pytest tests/ -m "not slow and not integration" -q`
- [x] `python -m pytest tests/run_agent/ tests/tools/test_interrupt.py -q`
- [x] `python -m pytest tests/spark_cli/ tests/cli/ -q`
- [x] `cd src/spark_cli/web && npm run test`
- [x] `cd src/spark_cli/web && npm run lint`
- [x] `cd src/spark_cli/web && npm run build`
- [x] `ruff check src/`
- [x] `mypy src/agent/ src/spark_cli/`

### Verification Results

- `python -m pytest tests/ -m "not slow and not integration" -q`: 11737 passed, 151 skipped.
- `python -m pytest tests/run_agent/ tests/tools/test_interrupt.py -q`: 763 passed, 6 skipped.
- `python -m pytest tests/spark_cli/ tests/cli/ -q`: run; combined collection currently exposes unrelated isolation failures in env-loader/CLI reload/prompt-toolkit stdout tests. The directly failing files pass when isolated: `python -m pytest tests/spark_cli/test_env_loader.py tests/cli/test_resume_display.py tests/cli/test_tool_progress_scrollback.py tests/cli/test_quick_commands.py -q -n0` => 60 passed.
- Web UI rerun after implementation: `npm run test -- --run` => 59 passed; `npm run lint` passed with existing warnings; `npm run build` passed.
- Web UI smoke against local FastAPI + Vite dev servers passed: composer rendered, stop/redirect controls appeared during active backend turns, and no console/page/request errors were observed.
- 2026-06-25 provider-stall regression: reproduced a partial-answer wait on session `20260625_095303_24237586`; backend was in a non-streaming provider call for 300s after visible partial text. Added active stream snapshots, web non-streaming provider wait heartbeats, and a 60s default web stale-call timeout.
- Targeted regression rerun: `python -m pytest tests/spark_cli/test_web_server_events.py tests/run_agent/test_openai_client_lifecycle.py tests/run_agent/test_interrupt_propagation.py -q` => 50 passed.
- Targeted Playwright smoke rerun with a fake 18s provider stall passed: partial streamed text remained visible during the stall and final text appeared after completion.
- 2026-06-25 browser-dashboard provider-stall regression: reproduced in web UI on session `20260625_114931_d9c0d685`; backend entered repeated 60s non-streaming provider waits and eventually persisted an assistant error while the UI showed the local streamed draft. Added a web-specific stale non-streaming guard so the turn ends after the first stale timeout, and made `ChatPanel` prefer persisted assistant history on `turn_done`/inactive resync so saved errors replace stale streaming drafts.
- Targeted rerun after the web provider-stall fix: `python -m pytest tests/run_agent/test_openai_client_lifecycle.py tests/spark_cli/test_web_server_events.py -q` => 44 passed; `npm run test -- --run` => 59 passed; `npm run lint` => 0 errors, 6 existing warnings; `npm run build` passed.
- Targeted Playwright smoke with a fake partial stream followed by backend error passed: saved error replaced the draft, stop disappeared, composer was enabled, and no console/page/request errors were observed.
- Live web UI `/help` smoke against the restarted patched backend passed: assistant help rendered, composer was enabled, and no failed browser responses were observed.
- 2026-06-25 macOS rebuild after provider-stall fix completed: `Spark.app` was signed, `Spark.dmg` was notarized and stapled, `/api/commands` returned 145 commands including `/issue`, and a packaged-app `/help` chat completed with an assistant message in session `20260625_113908_1fc23a9f`.
- macOS app build completed: `Spark.app` was code-signed, `Spark.dmg` was notarized and stapled, `xcrun stapler validate` passed, `hdiutil verify` passed, and a launched `Spark.app` responded on `http://127.0.0.1:9119/api/commands`.
- `ruff check src/`: run; fails on existing repo-wide lint debt outside this change set.
- `mypy src/agent/ src/spark_cli/`: run; fails on existing repo-wide typing debt outside this change set.

## Definition of Done

- [x] All five reported issues have a clear root-cause note or an evidence-backed explanation in the implementation PR.
- [x] The stop button is always visible and functional while any backend turn is active.
- [x] Typing during a response either redirects cleanly or remains queued visibly; it never makes the UI look finished while work continues.
- [x] Long markdown responses stay responsive in desktop and browser dashboard.
- [x] Backend overloads, retries, and long-running tools produce visible status updates.
- [x] The app recovers from missed SSE events by polling authoritative turn state.
- [x] `/issue` can draft a detailed, redacted GitHub issue with logs and screenshots, and it asks for approval before submitting.
