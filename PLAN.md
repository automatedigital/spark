# Spark Web UI and Desktop Improvement Plan

Date: 2026-09-08
Status: Proposed; implementation has not started.
Source baseline: local checkout `3b883aff`.

## Goal

Make Spark easier to leave, return to, and use across several pieces of work.
Prioritize protecting unfinished input, recovering interrupted work, finding
previous results, and making the desktop app feel dependable day to day.

This is a fresh roadmap written into the empty working-copy PLAN.md. The previous
plan remains in Git history. Tasks below are proposals, not verified bugs or
claims that features have shipped. This pass reviewed source and repository
workflows; it did not run the app or test installed desktop packages.

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
- [ ] BASE-04: Record branch/commit, browser/OS, backend mode and test commands. Use isolated Spark profiles and synthetic content; preserve unrelated working-copy edits.

## 1. Recoverable drafts and attachment staging

Outcome: write in chat A, switch to B, refresh or restart, then return to the
same unsent text and context selection in A.

- [ ] DRAFT-01: Define a versioned draft keyed by backend identity, profile, project and thread, including a distinct unsent-new-chat key. Audit existing storage before adding another store.
- [ ] DRAFT-02: Persist text and context references with a debounce; show a quiet saved/recovered indicator and an explicit discard action. Handle unavailable storage without losing the in-memory draft.
- [ ] DRAFT-03: Show attachment states before send: uploading, ready, missing and failed. Persist valid references, not an assumption that browser File objects survive restart; offer reattachment where necessary.
- [ ] DRAFT-04: Clear a draft only after confirmed submission. Preserve it on failures and prevent an acknowledgement for chat A from clearing chat B. Detect competing tab edits rather than silently overwriting them.
- [ ] DRAFT-05: Verify refresh, rapid switching, failed send, duplicate acknowledgement, app restart and profile/backend isolation.

Acceptance: no lost text or cross-thread draft leakage in those flows; recovered
attachments are usable or explicitly identified as needing reattachment.

## 2. Clear interrupted-run recovery

Outcome: an interrupted chat says what is known and presents the appropriate
next action instead of leaving the user to interpret a permanent spinner.

- [ ] REC-01: Audit backend lifecycle states and expose the distinction between running, waiting for approval/input, reconnecting, interrupted, failed and complete. Include last confirmed activity and reconcile on reconnect.
- [ ] REC-02: Add an inline recovery card with state-appropriate actions: reconnect, inspect failure, or explicitly retry. Do not automatically replay tool actions or resubmit a possibly accepted prompt.
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
  unrelated edits. No source implementation or release is part of this planning task.
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
  Do not edit ignored bundles as source or publish a release as part of planning.

## Completion evidence

Keep every checkbox open until its acceptance behavior has been demonstrated.
For each delivered slice, record:

| Slice | Commit / PR | Automated checks | Browser evidence | Installed macOS | Installed Windows | Limitations |
| --- | --- | --- | --- | --- | --- | --- |
| Pending | — | — | — | — | — | Planning only |

A release slice is complete when its selected tasks pass, shared chat recovery
still works, the served assets match the intended build, and each claimed desktop
platform has been checked in an installed package. Other roadmap items remain
explicitly unchecked.
