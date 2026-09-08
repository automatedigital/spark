# Spark Web UI and Desktop Improvement Plan

Date: 2026-09-08
Status: In progress — first shared web/desktop slice implemented on `feat/webui-work-recovery`.
Source baseline: local checkout `3b883aff`.

## Goal

Make Spark easier to leave, return to, and use across several pieces of work.
Prioritize protecting unfinished input, recovering interrupted work, finding
previous results, and making the desktop app feel dependable day to day.

This is a fresh roadmap written into the empty working-copy PLAN.md. The previous
plan remains in Git history. Tasks below are proposals, not verified bugs or
claims that features have shipped. Execution evidence below distinguishes verified
web behavior from the remaining installed-desktop and wider-roadmap work.

## Existing foundations

Build on these surfaces instead of introducing competing navigation or state:

| Existing surface | Source | Opportunity |
| --- | --- | --- |
| Chat, composer, session/stream controllers | `src/spark_cli/web/src/components/ChatPanel.tsx`, `components/chat/PromptBar.tsx`, `hooks/useChatSessionController.ts`, `hooks/useChatStreamController.ts` | Protect drafts and explain recovery at the point of work |
| Command palette | `src/spark_cli/web/src/components/CommandPalette.tsx` | Extend its current project/session/skill navigation with message search; it currently requests up to 500 sessions |
| Inbox and unread state | `src/spark_cli/web/src/components/sidebar/InboxSidebarSessions.tsx`, `lib/unreadSessionStore.ts` | Make attention and background work easier to triage |
| Files, changes, previews, plans and canvases | `src/spark_cli/web/src/components/workspace/`, `components/chat/ChangedFilesCard.tsx`, `components/chat/PlanCard.tsx`, `pages/CanvasPage.tsx` | Collect useful outputs without duplicating their authoritative content |
| Notifications, tray, deep links and Quick Ask | `src/spark_cli/web/src/components/NotificationBell.tsx`, `lib/desktop.ts`, `src-tauri/src/lib.rs` | Improve handoff, interruption control and return-to-work behavior |
| Web quality gates | `.github/workflows/web-quality.yml`, `src/spark_cli/web/package.json` | Extend existing browser coverage and bundle checks |

Paths abbreviated in the table are relative to `src/spark_cli/web/src/`.
Use the domain vocabulary in CONTEXT.md: Chat, Project, Quick Ask, Artifact,
Canvas, Task and Subagent.

## Priorities and delivery order

Effort is relative: S = contained UI/state work; M = shared UI/API work;
L = indexing or native lifecycle work. These are sizing estimates, not dates.

| Order | Improvement | Platforms | Effort | Dependency |
| --- | --- | --- | --- | --- |
| 1 | Recoverable drafts and attachment staging | Both | M | Baseline audit |
| 2 | Clear interrupted-run recovery | Both | M | Baseline audit |
| 3 | Search inside previous conversations | Both | L | Stable message navigation |
| 4 | Background-work attention inbox | Both | M | Run recovery contracts |
| 5 | Saved outputs and project handoff | Both | M | Stable message navigation |
| 6 | Desktop return-to-work restoration | Desktop | M | Drafts and run recovery |
| 7 | Quick Ask project handoff | Desktop; macOS first | M | Drafts and restoration |
| 8 | Quiet, actionable notifications | Both, native desktop integration | M | Attention inbox |
| 9 | Recoverable desktop updates and diagnostics | Desktop | L | Restoration |
| 10 | Focus layout and accessible navigation | Both | S–M | Shared navigation patterns |

Recommended first release: items 1–2 only, followed by desktop restoration once
those shared contracts pass. Deliver each later improvement as a separate slice;
do not wait for the entire roadmap before making useful improvements available.

## Phase 0 — Establish what needs changing

- [ ] BASE-01: Run the current web UI and installed desktop app; inventory existing draft persistence, recovery, search, notification and restoration behavior. Narrow each proposal to the missing behavior before implementation.
- [ ] BASE-02: Capture light/dark screenshots at 1440, 1024 and 768px, plus a narrow 390px browser view. Include a long thread, empty project, pending approval, disconnected chat and concurrent runs.
- [ ] BASE-03: Record first-token latency, gateway startup, reconnect recovery, sidebar refresh time and scroll continuity with reproducible fixtures. Include 2,000 message rows and 1,000 sessions.
- [x] BASE-04: Record branch/commit, browser/OS, backend mode and test commands. Use isolated Spark profiles and synthetic content; preserve unrelated working-copy edits.

## 1. Recoverable drafts and attachment staging

Outcome: write in chat A, switch to B, refresh or restart, then return to the
same unsent text and context selection in A.

- [x] DRAFT-01: Define a versioned draft keyed by backend identity, profile, project and thread, including a distinct unsent-new-chat key. Audit existing storage before adding another store.
- [x] DRAFT-02: Persist text and context references with a debounce; show a quiet saved/recovered indicator and an explicit discard action. Handle unavailable storage without losing the in-memory draft.
- [x] DRAFT-03: Show attachment states before send: uploading, ready, missing and failed. Persist valid references, not an assumption that browser File objects survive restart; offer reattachment where necessary.
- [x] DRAFT-04: Clear a draft only after confirmed submission. Preserve it on failures and prevent an acknowledgement for chat A from clearing chat B. Detect competing tab edits rather than silently overwriting them.
- [ ] DRAFT-05: Verify refresh, rapid switching, failed send, duplicate acknowledgement, app restart and profile/backend isolation.

Acceptance: no lost text or cross-thread draft leakage in those flows; recovered
attachments are usable or explicitly identified as needing reattachment.

## 2. Clear interrupted-run recovery

Outcome: an interrupted chat says what is known and presents the appropriate
next action instead of leaving the user to interpret a permanent spinner.

- [x] REC-01: Audit backend lifecycle states and expose the distinction between running, waiting for approval/input, reconnecting, interrupted, failed and complete. Include last confirmed activity and reconcile on reconnect.
- [x] REC-02: Add an inline recovery card with state-appropriate actions: reconnect, inspect failure, or explicitly retry. Do not automatically replay tool actions or resubmit a possibly accepted prompt.
- [ ] REC-03: Preserve pending approvals, exact transcript content and the user's scroll anchor through recovery; reuse the existing stream/session controllers.
- [ ] REC-04: Test network loss before/after submit acknowledgement, gateway restart, refresh during tools, stop during disconnect and switching between three active chats.

Acceptance: within five seconds of a successful status response, the UI agrees
with backend state; reconnection creates no duplicate messages or executions.

## 3. Search inside previous conversations

Outcome: find an answer by its contents even when its thread title is forgotten.

- [ ] SEARCH-01: Add paginated, profile-scoped server search over persisted message text. Evaluate existing database search support and query plans before introducing an index or dependency.
- [ ] SEARCH-02: Extend the existing command palette with conversation results, matching snippets and project/date filters; retain quick navigation and keyboard selection.
- [ ] SEARCH-03: Deep-link to a stable message identifier and load the needed history page before scrolling. Cancel stale requests and handle deleted/inaccessible results.
- [ ] SEARCH-04: Cover sessions beyond the first 500, repeated phrases, Unicode, empty results, profile boundaries and keyboard/screen-reader use.

Acceptance: a result opens the correct message, including unloaded history.
Provisional target: warm local search p95 under 500 ms on 10,000 fixture messages;
record hardware and revise the target from BASE-03 if necessary.

## 4. Background-work attention inbox

Outcome: quickly see which threads need a decision and which finished while the
user was elsewhere.

- [ ] INBOX-01: Extend the existing inbox with Needs you, Running and Finished filters and counts derived from structured backend events.
- [ ] INBOX-02: Give each attention item a specific reason and direct navigation to the relevant approval, question or failure. Never infer failure from ordinary transcript words.
- [ ] INBOX-03: Audit local settled/unread behavior; persist acknowledgement where needed and reopen attention only for a newer relevant event. Keep unresolved approvals visible.
- [ ] INBOX-04: Test duplicate/out-of-order events, reload, two clients, child-agent completion and a burst of background completions.

Acceptance: resolving an item clears its attention state consistently; ordinary
completion never conceals unresolved input or marks unrelated threads read.

## 5. Saved outputs and project handoff

Outcome: return to a project's useful files, answers and decisions without
rereading the full conversation.

- [ ] OUTPUT-01: Add an explicit Save output action to eligible messages and artifacts; store a reference, title and project association rather than copying the transcript.
- [ ] OUTPUT-02: Add a compact Saved outputs section to the existing project panel, with source-thread navigation and missing/deleted-source handling.
- [ ] OUTPUT-03: Allow the user to maintain a short project handoff note containing decisions, open questions and next actions. Link Tasks and Plans rather than creating a second task system.
- [ ] OUTPUT-04: Offer explicit attachment of a saved output or handoff to a new prompt. Do not silently rewrite active context or cached system prompts.
- [ ] OUTPUT-05: Verify rename, project move, source deletion, refresh and profile isolation.

Acceptance: every saved item opens its source or explains why it is unavailable;
project organization alone never changes an active conversation's context.

## 6. Desktop return-to-work restoration

Outcome: relaunch Spark into the project, thread and layout the user left.

- [ ] DESK-01: Persist selected project/thread, open panel, panel widths and a stable scroll anchor per backend/profile. Restore only targets that still exist.
- [ ] DESK-02: Restore navigation after backend readiness and reconcile active runs; never revive a stale local running indicator as authoritative state.
- [ ] DESK-03: Define close-to-tray versus quit behavior clearly and handle sleep/wake, changed displays and out-of-bounds window positions.
- [ ] DESK-04: Verify installed macOS and Windows packages through quit/relaunch, sleep/wake, crash recovery and backend-unavailable startup.

Acceptance: the previous work surface and draft return without duplicate runs;
a removed project or unavailable backend produces a usable fallback screen.

## 7. Quick Ask project handoff

Outcome: capture a short request from the global shortcut, then continue in the
full Chat workbench with the same content and thread.

- [ ] QUICK-01: Extend existing Quick Ask with a visible destination: new standalone chat or a selected recent project. Start with macOS, matching the domain definition.
- [ ] QUICK-02: Reuse draft/attachment rules and make Expand into Chat preserve prompt, context, selected destination and any already-created session.
- [ ] QUICK-03: Handle shortcut conflicts and focus restoration; do not capture clipboard or selected text without an explicit user action.
- [ ] QUICK-04: Test repeated shortcut presses, dismissal/reopening, sending then expanding, offline capture and destination removal.

Acceptance: capture-to-Chat creates at most one thread and loses no input. Record
Windows support separately instead of assuming native behavior is identical.

## 8. Quiet, actionable notifications

Outcome: be interrupted for decisions that matter, then land directly on them.

- [ ] NOTIFY-01: Add preferences for approvals/questions, failures and completions, plus quiet hours and per-project mute. Keep unresolved items accessible in-app.
- [ ] NOTIFY-02: Deduplicate browser/native delivery by event identity; suppress redundant completion alerts for the actively viewed thread and group bursts.
- [ ] NOTIFY-03: Route notification clicks to the exact thread/event after cold start. Default lock-screen content to a generic summary with an opt-in preview.
- [ ] NOTIFY-04: Verify denied OS permission, quiet hours across midnight, cold-start clicks, duplicate events and unavailable/deleted destinations.

Acceptance: one event produces at most one OS notification per client; a click
opens the correct work, and notification settings never hide in-app approvals.

## 9. Recoverable desktop updates and diagnostics

Outcome: understand update progress and recover from startup trouble without
having to find backend logs manually.

- [ ] UPDATE-01: Audit the current updater and expose its actual stages: checking, downloading, verifying, ready, installing and failed, with actionable errors.
- [ ] UPDATE-02: Before restarting, persist drafts/layout and inspect active work. Offer update after work finishes; require an explicit choice to interrupt running work.
- [ ] UPDATE-03: Add a startup recovery surface for backend health, retry and log access. Provide a previewable diagnostic export that redacts credentials and excludes conversation content by default.
- [ ] UPDATE-04: Exercise interrupted download, verification failure, insufficient disk space and failed relaunch. Specify a supported recovery route before claiming automatic rollback.
- [ ] UPDATE-05: Verify signing, macOS notarization/stapling/Gatekeeper and the Windows installer independently using the project's release procedures.

Acceptance: failure leaves a working installed version or a tested recovery path;
update success is confirmed by the installed runtime version and usable UI.

## 10. Focus layout and accessible navigation

Outcome: keep the answer and composer easy to use on small windows and by keyboard.

- [ ] UX-01: Add a reversible Focus view that hides secondary panels while retaining visible run state and pending decisions; preserve the previous layout.
- [ ] UX-02: Make narrow screens use one work panel at a time, with predictable back navigation and a composer that remains reachable above the virtual keyboard.
- [ ] UX-03: Audit command palette, dialogs, project tree and thread actions for focus order, Escape handling, accessible names and visible focus.
- [ ] UX-04: Verify 200% zoom, reduced motion, light/dark contrast, long code lines, keyboard-only use and screen-reader announcements that do not repeat every streamed token.

Acceptance: core chat, project, recovery and search flows work without a mouse;
no inaccessible controls or page-level horizontal overflow at tested widths.

## Implementation and validation rules

- Make source changes on descriptive feature branches from verified current main;
  never use a `codex/` prefix. Keep independently reviewable slices and preserve
  unrelated edits. Implementation was authorized on 2026-09-08; release publication
  is not part of this execution slice.
- Extend existing components, APIs and state stores before introducing new ones.
  Backend session/task state remains authoritative; local presentation state must
  reconcile. Resolve backend state paths through `get_spark_home()`.
- Preserve prompt caching: do not rewrite past messages, reload memory, swap
  toolsets or rebuild system prompts mid-conversation outside compression.
- Activate `.venv` before Python commands or local servers. Run relevant focused
  tests during development, then `ruff check src/`, relevant pytest subsets and
  the full suite when practical. Report baseline failures separately.
- From `src/spark_cli/web`, run `npm run lint`, `npm test`, the applicable existing
  E2E suites and `npm run build` with its bundle budget check. Add behavior tests
  for the new failure/recovery contracts rather than implementation mirrors.
- For every chat/session change, manually exercise long conversations, three
  concurrent chats, switching while generating, refresh, reconnect and gateway
  restart. Confirm new project chats appear under an expanded project folder.
- Record exact browser flows, screenshots, test results and performance deltas.
  Proposed performance gate: no unexplained regression above 10% against repeated
  baseline measurements; investigate measurement noise before changing scope.
- Web acceptance precedes desktop packaging. Installed macOS and Windows smoke
  tests are separate gates; a successful web build is not desktop acceptance.
  Do not edit ignored bundles as source. Commit the verified generated web bundle
  at the final web gate; desktop packaging and publication remain separate.

## Completion evidence

Keep every checkbox open until its acceptance behavior has been demonstrated.
For each delivered slice, record:

| Slice | Commit / PR | Automated checks | Browser evidence | Installed macOS | Installed Windows | Limitations |
| --- | --- | --- | --- | --- | --- | --- |
| Drafts and recovery | `7c84d260` on `feat/webui-work-recovery` | See execution record | Draft/recovery E2E and screenshots below | Not rebuilt/tested | Not rebuilt/tested | Remaining acceptance matrix stays open |

A release slice is complete when its selected tasks pass, shared chat recovery
still works, the served assets match the intended build, and each claimed desktop
platform has been checked in an installed package. Other roadmap items remain
explicitly unchecked.


## Execution record — 2026-09-08

### Delivered first slice

- Used Luna subagents at low reasoning effort for draft/recovery implementation,
  tests and baseline auditing; parent review corrected gaps and verified results.
- `draftStore.ts` and `useChatDraft.ts` now own versioned drafts for all three
  composers. Keys use the effective backend URL and confirmed `spark_home`, plus
  project/thread identity. In-memory updates are immediate; persisted writes are
  debounced and flushed on navigation/page hide. Storage failure preserves input.
- Submission captures a revision. Only confirmed acceptance clears that exact
  draft; late acknowledgements and failures cannot change the selected chat.
  Competing tabs get an explicit choice rather than overwriting one another.
- Uploaded attachments show uploading/ready/failed states. An upload interrupted
  by browser restart recovers as missing and blocks sending until removed or
  reattached. Server file references survive refresh. Uploads follow the selected
  backend, and late upload results remain attached to their originating draft.
- The recovery card uses backend status, durable turn outcomes and pending
  decisions. It distinguishes failed/interrupted work from active work, preserves
  pending decisions, and offers reconnect/diagnostics/explicit retry. Backend
  status now reconciles the stream reducer and composer controls together.
- The composer uses the theme background so recovered draft text remains readable
  in the light theme. No installed desktop package or release was produced.

### Environment and reproducible checks

- Base: `origin/main` verified equal to local `3b883aff` before branching.
  Roadmap commit: `5e674831`; implementation and generated bundle: `7c84d260`.
  Branch: `feat/webui-work-recovery`.
- Host: macOS 26.6.2; Node v22.22.1; Python 3.11.7 in `.venv`.
  Browser: headless Chromium, through Node Playwright 1.59.1 and Python Playwright
  1.62.0. Every backend fixture used a temporary `SPARK_HOME`, ephemeral localhost
  ports and synthetic messages; no model-provider calls were required.
- `npm run lint`, TypeScript and all **382 frontend tests** passed.
- `npm run build` passed; the final initial JavaScript graph is **226.42 KiB gzip**
  against the 600 KiB budget (`assets/index-DFiJUvqX.js`). The generated bundle
  is committed with the source.
- `python -m pytest tests/spark_cli/test_web_server.py tests/spark_cli/test_web_server_events.py tests/test_web_turn_persistence.py -q`:
  **256 passed**. The full Python suite was not run for this frontend slice.
- `ruff check src/`: **305 existing findings in unchanged Python files**.
  Ruff passes on the added Python acceptance script. These repository-wide
  findings remain open; this is not a claim of a clean global lint gate.
- `npm run test:e2e` and `node e2e/chat-contracts.mjs`: passed the existing
  multi-chat/reconnect/gateway-restart and chat-contract flows.
- `python src/spark_cli/web/e2e/work-recovery.py` from the root with `.venv`
  active: **10 browser scenarios passed** — rapid switches/refresh, failed send,
  late acknowledgement, conflicting tabs, project destination isolation, new
  chat recovery, attachment reference recovery, interrupted upload, failed upload
  and profile isolation. Light/dark screenshots cover 1440/1024/768/390px; no
  page-level horizontal overflow was observed.
- `npm run test:e2e:recovery`: passed stalled reconnect without prompt replay,
  durable failure, approval visibility, three-chat switching and gateway restart
  without reloading the page. The interrupted card and idle composer are required
  within five seconds of backend readiness. The test shortens the stale threshold
  to one second only in its isolated backend process.
- `SPARK_E2E_BASELINE_CASE=dark:2000:1440 npm run test:e2e:baseline`: passed
  the 2,000-row long-thread fixture. Filtered runs deliberately leave historical
  canonical baseline outputs unchanged; they are not a complete performance
  comparison.
- The draft acceptance scenarios also passed with `SPARK_E2E_BUILT_WEB=1`,
  serving the generated web bundle directly from the isolated backend instead
  of Vite. Screenshots were visually inspected after the light-theme fix.
- New draft and recovery acceptance scripts are wired into `web-quality.yml`.
  Hosted CI has not run because this branch has not been pushed.

### Evidence files and unfinished checks

Current local screenshots/reports (generated, not committed):

- `src/spark_cli/web/screenshots/work-recovery/report.json`
- `src/spark_cli/web/screenshots/work-recovery/draft-conflict.png`
- `src/spark_cli/web/screenshots/work-recovery/draft-codex-1440.png`
- `src/spark_cli/web/screenshots/work-recovery/draft-daylight-390.png`
- `src/spark_cli/web/screenshots/e2e-recovery-state.png`
- `src/spark_cli/web/screenshots/e2e-recovery-gateway-restart.png`

Items deliberately left unchecked:

- **BASE-01/02:** the source/web audit and draft viewport captures are done, but
  the full baseline state/theme matrix and installed-app behavior are not.
  `/Applications/Spark.app` reported version 1.3.38 from metadata only; it was
  not launched or treated as current implementation evidence.
- **BASE-03:** full baseline capture failed at `dark:500:1024` because a stable
  scroll sample was absent. The 1,000-session sidebar attempt timed out waiting
  for the second page (`offset=50`). The fixture now accepts
  `SPARK_E2E_SESSION_COUNT=1000` and starts the backend without an auto-build race,
  but pagination and a complete performance comparison remain unresolved.
- **DRAFT-05:** browser recovery, failures and scope tests pass; installed-app
  restart and the complete cross-backend/native matrix still need verification.
- **REC-03/04:** transcript/approval recovery and concurrent switching pass, but
  the complete scrolled-up recovery matrix and stop-during-disconnect case have
  not yet been demonstrated. These broader acceptance tasks remain open.
- **SEARCH through UX, desktop restoration and installed-platform gates:** remain
  future slices. No checkbox represents an untested macOS/Windows package.
