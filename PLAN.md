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

- [ ] Inspect every 2026-06-24 screenshot and write a short note for each: visible UI state, whether stop button is present, whether text input is editable, whether the assistant bubble is streaming, and whether formatting is broken.
- [ ] Summarize the referenced logs into `references/logs/Issue 240626 analysis.md`, including timestamps for long API calls, overload retries, `interrupted_during_api_call`, and turn completion.
- [ ] Reproduce in desktop dev mode with a long markdown-heavy response, a long tool-heavy response, and a response interrupted by typing a new message mid-stream.
- [ ] Capture baseline browser performance evidence: count long tasks, measure token-to-paint delay, and note when safe mode turns on.
- [ ] Confirm whether these issues reproduce in browser dashboard, Tauri desktop, or only remote dashboard mode.
- [ ] Record exact commands used for reproduction in this plan before changing behavior.

## Phase 1 - Make Turn State Authoritative

- [ ] Replace the bare `_web_streaming: set[str]` usage in `src/spark_cli/web_server.py` with a small active-turn state record keyed by resolved session id: `started_at`, `last_event_at`, `status`, `interrupt_requested`, `active_agent_session_id`, and `phase`.
- [ ] Register active-turn state before `/api/conversations`, `/api/conversations/{session_id}/messages`, retry, and workspace conversation endpoints return, not only after the background task starts.
- [ ] Clear active-turn state only in the task `finally` block after persistence, session update emission, queue close, and `chat.turn_done` publication have all happened.
- [ ] Extend `/api/conversations/{session_id}/turn-status` to return resolved session id, latest descendant id, `turn_active`, current status text, `started_at`, `last_event_at`, and `interrupt_requested`.
- [ ] Update `api.getTurnStatus()` types in `src/spark_cli/web/src/lib/api.ts`.
- [ ] Make `/api/conversations/{session_id}/interrupt` resolve aliases/latest descendants before looking up the agent, so stop works after context compression/session migration.
- [ ] Change interrupt UX semantics so `chat.interrupted` or `interrupt_requested` means "stopping/redirecting", not "the turn is fully done"; only `chat.turn_done` or `turn-status.turn_active === false` should clear streaming UI.
- [ ] Add a regression test that an interrupt request leaves the turn active until the background agent task exits.
- [ ] Add a regression test that `turn-status` returns active immediately after a web message endpoint accepts a turn.
- [ ] Add a regression test that interrupt works when the requested session id resolves to a compressed/latest descendant session id.

## Phase 2 - Fix Stop, Redirect, and "Still Working" UX

- [ ] In `ChatPanel.tsx`, introduce explicit frontend turn substates: `idle`, `starting`, `streaming`, `stalled`, `stopping`, and `redirecting`.
- [ ] Keep `PromptBar` editable while streaming, but make Enter behavior explicit: no text means stop remains available; text means redirect is available; stop remains visible either way.
- [ ] Ensure the stop button is visible whenever frontend streaming is true or backend `turn-status.turn_active` is true, even if the last visible message is a tool row, note row, or empty typing row.
- [ ] On stop click, optimistically switch to `stopping`, keep the stop control disabled or guarded against duplicate clicks, and poll `turn-status` until the backend confirms inactive.
- [ ] On redirect submit, append a visible redirected user row and keep the turn state as `redirecting` until the backend confirms whether the redirect became the next turn.
- [ ] Audit `sendMessage()` so typing mid-answer never clears the input before the redirect request has been accepted or safely queued.
- [ ] Make the stall watchdog escalate status text over time: `Still working...`, then `Still waiting for backend...`, then `Reconnecting...` if EventSource has dropped.
- [ ] Use `chat.status` events to surface backend retry/overload/waiting states when available.
- [ ] Add a pure state-transition helper for chat turn state and test it with Vitest instead of burying every transition directly in React component state.
- [ ] Add tests for these transitions: token received, tool start/end, interrupt requested, turn done after interrupt, SSE reconnect while active, SSE reconnect after missed `turn_done`, and session migration.

## Phase 3 - Harden Markdown Rendering

- [ ] Add markdown parser tests for partial fenced code blocks, unclosed fences, huge paragraphs, huge tables, nested emphasis, bare URLs, media links, task lists, and malformed markdown.
- [ ] Add a streaming performance fixture that appends tokens to a 10k, 50k, and 100k character assistant message and asserts parsing work stays bounded.
- [ ] In `Markdown.tsx`, apply the soft render cap during streaming too. Long streaming messages should render a bounded parsed tail plus plain text for the rest, or switch to safe plain text until final.
- [ ] Avoid reparsing the entire stable prefix on every token. Cache committed parsed blocks by stable boundary and only parse newly committed text plus the current live tail.
- [ ] Audit `parseInline()` and table parsing in `markdownParse.ts` for regex backtracking and unbounded per-token work; replace any risky regex path with linear scanning or hard caps.
- [ ] Cap table rendering during streaming: limit rows/cells parsed live, then render the full table only after the block is stable and below a size threshold.
- [ ] Keep syntax highlighting disabled while code blocks are live and enforce the existing size cap after completion.
- [ ] Make safe mode reversible and visible: when long tasks trigger safe mode, show a compact inline notice with a "render markdown" retry option after the turn finishes.
- [ ] Persist render-health details per session so a reopened problematic thread starts safe and explains why.
- [ ] Add tests to `src/spark_cli/web/src/components/Markdown.test.ts` covering safe-mode fallback, streaming cap behavior, and final rich rendering after streaming completes.

## Phase 4 - Stabilize Virtualized Chat Rows

- [ ] Review TanStack Virtual usage in `ChatPanel.tsx` for streaming rows with dynamic heights.
- [ ] Use stable message ids for virtual row keys so row identity does not drift when tool rows collapse or earlier history prepends.
- [ ] Throttle measuring the live assistant row and skip measurement for unchanged committed rows.
- [ ] Preserve bottom anchoring while streaming without forcing a smooth scroll on every token.
- [ ] Verify prepending earlier history does not jump the current viewport.
- [ ] Add a stress test or manual QA script for rapid token updates, tall code blocks, large tool results, and repeated collapsed tool rows.

## Phase 5 - Backend Progress and Error Transparency

- [ ] Emit `chat.status` for long backend gaps: API call started, retry scheduled, tool running longer than threshold, waiting for approval, context compression, and interrupt requested.
- [ ] Include retry/error summaries in status events without exposing secrets or huge payloads.
- [ ] Ensure `chat.turn_done` payload includes `final_assistant_present`, `interrupted`, token stats, and any backend error class.
- [ ] In the frontend, display backend overload/API retry notes as status, not as final assistant content.
- [ ] If a turn ends with no assistant content and no intentional interrupt, show a recoverable error note with retry guidance.
- [ ] Add tests that backend exceptions still publish `chat.turn_done` and clear active-turn state.

## Phase 6 - Manual QA Matrix

- [ ] Long markdown response: headings, bullets, tables, code fences, and links stream without UI freeze.
- [ ] Huge tool output response: tool rows collapse, full-result fetch still works, and scrolling stays responsive.
- [ ] Type while assistant is mid-answer: redirect is visible, old turn stops, new instruction is handled once.
- [ ] Press stop while a tool is running: UI says stopping, backend interrupt is requested, final state clears only when backend is inactive.
- [ ] Simulate dropped SSE: close/reopen EventSource or throttle network; UI recovers from `turn-status`.
- [ ] Simulate backend overload/retry: status shows retry/waiting and does not look finished.
- [ ] Context compression/session migration during a turn: events follow the new session id and stop still works.
- [ ] Restart desktop while a prior session has a recent active-looking turn: history and turn-status reconcile cleanly.

## Phase 7 - Add `/issue` Skill

- [ ] Create a built-in skill named `issue` so `/issue` appears through `scan_skill_commands()` and the web `/api/commands` skill list.
- [ ] Place the skill under an appropriate skill category, likely `skills/github/issue/SKILL.md`, and make its frontmatter name exactly `issue`.
- [ ] Have the skill collect: user description, current session id, recent redacted logs, relevant screenshots/files, Spark version/git SHA, OS/platform, active profile, web/desktop mode, and reproduction steps.
- [ ] Reuse `skills/github/github-issues/templates/bug-report.md` or add a focused template for Spark product bugs.
- [ ] Require the agent to show the exact GitHub issue title, body, labels, and attachments/references before creating the issue.
- [ ] Use the existing GitHub issue workflow (`gh issue create` first, REST fallback if needed) rather than adding a new tool unless the existing skill cannot attach the required evidence.
- [ ] Add guidance for screenshots referenced by `@path` and for logs under `references/logs/`.
- [ ] Add redaction rules: never include API keys, bearer tokens, dashboard tokens, full home-directory secrets, or unrelated session content.
- [ ] Add a happy-path test that the skill is discoverable as `/issue` in CLI skill commands.
- [ ] Add a web command-list test that installed skills include `/issue` in `/api/commands`.
- [ ] Add a dry-run/manual QA step: invoke `/issue` with the 2026-06-24 screenshots and logs, verify the drafted issue is detailed, redacted, and asks for approval before submission.

## Verification Commands

- [ ] `source venv/bin/activate`
- [ ] `python -m pytest tests/ -m "not slow and not integration" -q`
- [ ] `python -m pytest tests/run_agent/ tests/tools/test_interrupt.py -q`
- [ ] `python -m pytest tests/spark_cli/ tests/cli/ -q`
- [ ] `cd src/spark_cli/web && npm run test`
- [ ] `cd src/spark_cli/web && npm run lint`
- [ ] `cd src/spark_cli/web && npm run build`
- [ ] `ruff check src/`
- [ ] `mypy src/agent/ src/spark_cli/`

## Definition of Done

- [ ] All five reported issues have a clear root-cause note or an evidence-backed explanation in the implementation PR.
- [ ] The stop button is always visible and functional while any backend turn is active.
- [ ] Typing during a response either redirects cleanly or remains queued visibly; it never makes the UI look finished while work continues.
- [ ] Long markdown responses stay responsive in desktop and browser dashboard.
- [ ] Backend overloads, retries, and long-running tools produce visible status updates.
- [ ] The app recovers from missed SSE events by polling authoritative turn state.
- [ ] `/issue` can draft a detailed, redacted GitHub issue with logs and screenshots, and it asks for approval before submitting.
