# Spark app upgrade and delivery plan

Date: 2026-10-15

Status: Approved; implementation in progress on `feat/app-orchestration-upgrade`.

Spark baseline: `0ed3654b` (`main` must be rechecked before execution).
Delivery shape: five working days for the core slice, then independently scheduled extensions.

## 1. Outcome and scope

Make Spark a dependable workbench for several simultaneous pieces of work: a clear
project/thread sidebar, visible and controllable delegated work, and consistent
state after refresh, disconnection, or gateway restart. Improve the existing
Python agent and React/Tauri app rather than replacing them with either reference
repository.

A user should be able to start a project chat, delegate two bounded jobs, keep
working in another chat, inspect child progress beside the parent, stop a child,
and return after reconnect to the correct durable outcome. Coding children can
request separate Git worktrees. Completed work and decisions remain discoverable.

The five-day core is **P00–P10** below. Memory/skill improvements, cron durability,
context transfer, and broader provider integrations are **E01–E05**, separately
estimated. The core does not promise full Hermes or T3 feature parity. If the
baseline reveals major recovery defects, protect correctness and reduce the UI
scope before adding more execution modes.

## 2. Review evidence and limits

This is a source and documentation review, not a runtime acceptance report.
Reviewed Spark's entry points, agent loop boundaries, tool registration,
persistence/migrations, web lifecycle and projections, frontend stores/hooks,
sidebar and subagent UI, Kanban dispatch/worker code, memory/Dream/skills, cron,
desktop configuration, browser fixtures, CI, and both accepted ADRs. Inspected
selected source and tests rather than reading every repository file. No live
provider, installed desktop, or browser flow was exercised for this planning pass.

The working-copy `PLAN.md` was empty on entry. The previous September roadmap and
its execution record remain in Git history (`git show HEAD:PLAN.md`). Historical
checked boxes are not acceptance evidence for this upgrade. An unrelated handoff
file move was already present and is outside this change.

Reference repositories were freshly cloned and pinned, not inferred from their
marketing pages. All reference paths below are relative to the respective pinned
repository. Recheck the pins only when deliberately refreshing this plan.

| Reference | Reviewed commit | Why it matters |
| --- | --- | --- |
| [Hermes Agent](https://github.com/nousresearch/hermes-agent/tree/7520c4e8b3791f081b2c26d5ea9a0c07b0363401) | `7520c4e8b3791f081b2c26d5ea9a0c07b0363401` | Background delegation, isolation, recall, skill audit, scheduled execution reliability |
| [T3 Code](https://github.com/pingdotgg/t3code/tree/42da166d131017335a1158d0b379dd68b8985796) | `42da166d131017335a1158d0b379dd68b8985796` | Sidebar interaction, execution graph, capabilities, command receipts and replay tests |

### Reference reading map

| ID | Pinned source | Adaptation to Spark |
| --- | --- | --- |
| H1 | [tools/delegate_tool.py](https://github.com/nousresearch/hermes-agent/blob/7520c4e8b3791f081b2c26d5ea9a0c07b0363401/tools/delegate_tool.py), [tools/async_delegation.py](https://github.com/nousresearch/hermes-agent/blob/7520c4e8b3791f081b2c26d5ea9a0c07b0363401/tools/async_delegation.py) | Stable background handles, completion delivery, bounded concurrency and stale-work recovery. Preserve Spark's existing synchronous callers behind compatibility handling. |
| H2 | [tools/subagent_worktree.py](https://github.com/nousresearch/hermes-agent/blob/7520c4e8b3791f081b2c26d5ea9a0c07b0363401/tools/subagent_worktree.py) | Git isolation and conservative cleanup. Spark should explicitly reject unsupported requested isolation rather than silently sharing a directory. |
| H3 | [tools/session_search_tool.py](https://github.com/nousresearch/hermes-agent/blob/7520c4e8b3791f081b2c26d5ea9a0c07b0363401/tools/session_search_tool.py) | Discover/read/scroll recall with message anchors and lineage-aware exclusions; extend Spark's existing search. |
| H4 | [tools/skill_ledger.py](https://github.com/nousresearch/hermes-agent/blob/7520c4e8b3791f081b2c26d5ea9a0c07b0363401/tools/skill_ledger.py), [tools/skill_provenance.py](https://github.com/nousresearch/hermes-agent/blob/7520c4e8b3791f081b2c26d5ea9a0c07b0363401/tools/skill_provenance.py) | Before/after audit, actor provenance, bounded backups and safe rollback for skill edits. |
| H5 | [cron/occurrences.py](https://github.com/nousresearch/hermes-agent/blob/7520c4e8b3791f081b2c26d5ea9a0c07b0363401/cron/occurrences.py), [cron/execution_identity.py](https://github.com/nousresearch/hermes-agent/blob/7520c4e8b3791f081b2c26d5ea9a0c07b0363401/cron/execution_identity.py) | Separate scheduled occurrence, execution attempt and delivery identity; avoid replaying an entire job to retry delivery. |
| T1 | [docs/orchestration-v2/README.md](https://github.com/pingdotgg/t3code/blob/42da166d131017335a1158d0b379dd68b8985796/docs/orchestration-v2/README.md), [core-graph-and-data-model.md](https://github.com/pingdotgg/t3code/blob/42da166d131017335a1158d0b379dd68b8985796/docs/orchestration-v2/core-graph-and-data-model.md) | Separate thread, run, attempt, execution node and provider references; child completion cannot finish its parent. |
| T2 | [provider-capability-system.md](https://github.com/pingdotgg/t3code/blob/42da166d131017335a1158d0b379dd68b8985796/docs/orchestration-v2/provider-capability-system.md), [packages/contracts/src/orchestrationV2.ts](https://github.com/pingdotgg/t3code/blob/42da166d131017335a1158d0b379dd68b8985796/packages/contracts/src/orchestrationV2.ts) | Versioned capabilities and explicit unsupported behavior; keep native lifecycle details at adapter boundaries. |
| T3 | [docs/user/thread-sidebar.md](https://github.com/pingdotgg/t3code/blob/42da166d131017335a1158d0b379dd68b8985796/docs/user/thread-sidebar.md), [apps/web/src/components/Sidebar.logic.ts](https://github.com/pingdotgg/t3code/blob/42da166d131017335a1158d0b379dd68b8985796/apps/web/src/components/Sidebar.logic.ts) | Stable ordering, pins, attention, settle/snooze/undo, accessible row labels and bounded live subscriptions. |
| T4 | [testing-strategy.md](https://github.com/pingdotgg/t3code/blob/42da166d131017335a1158d0b379dd68b8985796/docs/orchestration-v2/testing-strategy.md), [apps/server/src/orchestration-v2/SubagentProjection.test.ts](https://github.com/pingdotgg/t3code/blob/42da166d131017335a1158d0b379dd68b8985796/apps/server/src/orchestration-v2/SubagentProjection.test.ts) | Replay at the external transport boundary through real persistence/projections; verify parent/child isolation. |
| T5 | [thread-lineage-and-context-transfer.md](https://github.com/pingdotgg/t3code/blob/42da166d131017335a1158d0b379dd68b8985796/docs/orchestration-v2/thread-lineage-and-context-transfer.md), [apps/server/src/orchestration-v2/EffectOutbox.ts](https://github.com/pingdotgg/t3code/blob/42da166d131017335a1158d0b379dd68b8985796/apps/server/src/orchestration-v2/EffectOutbox.ts) | Explicit handoffs and recoverable side effects. The design README calls the outbox a follow-up, while source already implements one: inspect code and tests before assuming implementation status. |

Both root licenses are MIT. Preserve applicable notices for copied code and
check vendored assets/dependencies separately. Prefer small adaptations with
provenance in PR descriptions; do not copy either runtime or UI wholesale.

## 3. Spark baseline: extend what exists

Paths here are existing source, not proposed modules. Presence means inspected
implementation, not a claim that every acceptance case already passes.

| Area | Current evidence | Upgrade delta |
| --- | --- | --- |
| Agent and tools | `src/core/run_agent/`, `src/core/model_tools.py`, `src/tools/manifest_spec.py`, `src/tools/generated_manifest.py` | Keep `AIAgent` public contract, deterministic lazy discovery and prompt-cache behavior. Add lifecycle adapters at existing boundaries. |
| Session/event storage | `src/core/spark_state.py`: schema version 12, `session_events`, `session_checkpoints`, web turn projections, pending actions, subagent runs/events | Reuse IDs and append compatible metadata. Do not introduce a second generic event store. |
| Web transport | `src/spark_cli/web_server.py`, `web_state.py`, `web_state_schema.json`, `web_projections.py` | Distinguish durable per-session event sequences from the bounded, process-epoch web replay journal. Reconcile snapshots after process loss. |
| Sidebar | `web/src/lib/sessionStore.tsx`, `components/sidebar/SidebarSessions.tsx`, `sidebarRows.ts`, `InboxSidebarSessions.tsx` | Already has project grouping, pins, paging, search and virtualization. Improve stable organization, durable preferences, attention and keyboard behavior. |
| Chat reliability | `web/src/hooks/useChatSessionController.ts`, `useChatStreamController.ts`; `lib/draftStore.ts`, `chatRecovery.ts`, `chatStreamReducer.ts` | Preserve existing drafts, staged attachments, recovery and stream merging. Add graph/capability data without replacing these controllers. |
| Delegation | `src/tools/delegate_tool.py`, `src/agent/subagents.py`; `web/src/hooks/useSubagents.ts`, `components/chat/SubagentsPanel.tsx` | Already persists child runs/transcripts and renders parent-linked detail. Parent currently waits for single/batch delegation. Add explicit async lifecycle, status/cancel and completion delivery. |
| Durable tasks | `src/core/kanban_db.py`, `src/spark_cli/kanban_dispatch.py`, `kanban_worker.py`, `kanban_routes.py` | Existing task dependencies, claims and runs remain the task authority. Harden fencing/reclaim and link task attempts to chat execution. |
| Memory and recall | `src/agent/memory_manager.py`, `src/plugins/memory/`, `src/core/dream.py`, `src/tools/session_search_tool.py` | Already has automatic memory, explicit Dream and session search. Improve provenance, anchored recall and review; do not add another memory backend by default. |
| Skills | `src/tools/skill_usage.py`, `skills_metadata.py`, `skills_guard.py`, `skill_manager_tool.py`; `web/src/lib/skillQuality.ts` | Already has provenance, usage, lifecycle and quality signals. Add edit history/rollback rather than recreating these systems. |
| Automation | `src/cron/jobs.py`, `scheduler.py`, `src/spark_cli/cron_routes.py` | Add occurrence/attempt/delivery accounting after auditing current claims and retry behavior. |
| Desktop and CI | `web/src-tauri/`, `scripts/build_desktop.sh`, `scripts/build_desktop_windows.ps1`, `.github/workflows/{web-quality,python-quality,windows-desktop-beta}.yml` | Keep Tauri, separate source/web/package verification, and test installed builds before platform claims. |

`web/` in abbreviated paths means `src/spark_cli/web/`. Source review found no open
GitHub issues at review time; recheck before creating execution tickets. This plan
creates no issues, PRs, releases, or deployments.

### Concrete risks to reproduce first

- Kanban `heartbeat()` records an event but does not extend the claim expiry;
  reclaim treats expiry as sufficient even with a live PID. Reproduce a long
  worker crossing TTL before changing policy.
- Dispatcher reads an assignee and limits concurrency by assignee, but the spawned
  worker loads inherited configuration. Verify whether assignment selects the
  intended execution profile and which profile owns the board database. Preserve
  those two identities explicitly.
- Kanban worker can auto-close text-only results into `user_review`. Review is
  better than declaring `done`, but evidence must distinguish reported success,
  verified completion and ambiguous termination.
- Subagent lifecycle persistence exists in both lifecycle emission and web
  adaptation. Trace one delegated run to establish the write owner and whether
  duplicate events actually occur; do not assume duplication from call sites alone.
- Some sidebar preferences use browser-local keys. Verify isolation between
  backends/profiles before migrating or sharing preferences.

## 4. Architecture contract to approve in P00

Record decisions in new ADRs under `docs/adr/`; proposed names/modules in this
section do not exist yet. ADR-0001 and ADR-0012 remain binding.

### Identity and lifecycle

Use the existing Spark session ID as **Thread** identity, including compression
lineage. Map the current web `turn_id` to **Run**, rather than renumbering history.
An **Attempt** is one execution/retry of that Run. An **Execution node** identifies
root work, child agent, tool or pending decision, with explicit parent/root refs.
Provider IDs are optional correlation references, never the application's IDs.
A Kanban **Task** remains a durable objective; its task-run attempt links to an
execution run and owning conversation, not a replacement task hierarchy.

Agree an additive envelope containing schema version, event ID, thread/run/attempt
and node refs, causation/command ID, durable sequence, event kind and bounded data.
Keep web journal `(server_epoch, sequence)` separate from the session event cursor;
a snapshot advertises which cursor each stream accepts. No timestamps as ordering
or deduplication keys. Define compression-chain lookup and child visibility once.

Run transitions: `queued -> starting -> running`, optionally waiting for a
respondable decision, then `completed | failed | interrupted | cancelled`.
`reconnecting` is connection state, not persisted execution success/failure.
Stopping first records `cancel_requested`; only worker/provider acknowledgement
or confirmed process loss records the terminal outcome. Root completion alone
finishes a Run. Child completion updates that child and schedules result delivery;
it cannot mark the parent complete. Unknown process outcomes are interrupted or
uncertain, never guessed successful.

### Commands and side effects

Persist command receipts scoped to profile/backend, owning thread, command kind
and caller request ID, with a payload hash. Identical retry returns the same
accepted result; reuse with a different payload fails. Commit acceptance before
publishing. Claim side effects with a fenced attempt token. Process loss between
provider acceptance and local recording is explicitly ambiguous: reconcile if the
adapter can prove state; otherwise require an explicit retry. Do not promise
exactly-once provider execution or replay an uncertain tool action automatically.

Reuse `session_events` for conversation execution. Use existing Kanban run records
for task ownership; do not assume transactions across `state.db` and `kanban.db`.
Coordinate those databases with an idempotent linked-command receipt and retryable
projection updates. Choose one lifecycle persistence owner; transport adapters
publish committed projections, not competing writes.

For async completion, persist result plus a delivery record. Deliver once per
parent/run/result identity at the next safe conversation boundary. A retried
notification must not rerun a child or mutate an active prompt prefix. Introduce
a narrow durable dispatch/delivery queue only where existing records cannot cover
that boundary; avoid a general-purpose orchestration framework in this slice.

### Provider policy, isolation and compatibility

Resolve provider/model choices through `runtime_provider.py`, existing auth/model
routes and configured custom providers. A capability snapshot describes actual
support for interruption, pending decisions, resume/recovery, streaming, child
controls and isolation; unsupported includes a reason. No UI provider-name checks,
no static hardcoded model catalog, no exposure of credentials.

Core scope adapts the existing `AIAgent` runtime and its current provider paths.
Native CLI harness control, native provider forks and cross-provider transcript
handoffs are extensions. A capability is true only when backed by an exercised
adapter path. Do not rebuild toolsets or the system prompt mid-conversation.

Worktree isolation is explicit: use a recorded base commit, branch and absolute
path, inherit no uncommitted changes, and never silently downgrade requested
isolation. Initially support local Git projects only; remote/container modes must
return a clear unsupported result until their filesystem semantics are implemented.
Keep child permission/tool restrictions and no recursive delegation by default.

## 5. Product and UI specification

### Sidebar and navigation

Keep Spark's project-first navigation and existing Inbox. Use T3's interaction
patterns without copying its branding or adding a second sidebar. Proposed layout:
Inbox with attention count; Pinned threads; Projects with expandable threads;
standalone Chats; a collapsed Settled section. Selected project remains explicit
in new-chat creation, and its folder opens when a child chat is created.

Rows lead with title, then one primary status and compact project/model context.
Use distinct running, needs-you, failed/interrupted and unread indicators with
accessible labels. Child work stays nested in the parent detail panel rather than
appearing as unrelated top-level chats. Counts come from backend projections.

Core supports pin/unpin, manual settle/unsettle with Undo, project grouping,
keyboard navigation and reliable search beyond loaded pages. Persist order and
settlement server-side per profile; local expansion/width remains device-local
but backend/profile scoped. Keep existing activity ordering until a user chooses
manual order. Incoming tokens must not reshuffle manually arranged rows. Defer
snooze, automatic settlement, bulk gestures and elaborate drag animation to E05.
Never hide unresolved approvals when settling; return a clear reason or route the
user to the pending decision. Settling does not stop executing work.

### Chat and delegated-work inspector

Retain `PromptBar`, draft recovery, timeline virtualization and existing right
panel. Show a parent summary with child counts, state, provider/model, elapsed time,
verified usage when available, and task/worktree links. Opening a child shows its
transcript/events beside the parent. Child loading/error/offline states must not
replace parent content or steal its scroll anchor.

Offer status, inspect, copy result, and capability-gated Stop; explicit Retry
creates a new attempt and keeps the prior result. A parent Stop explains and
applies the documented child-cancellation policy. Pending decisions retain their
own IDs and revalidate respondability after reconnect. Avoid invented percentages,
cost estimates without pricing evidence, or showing private reasoning as a required
feature. Keep input usable while background work runs, with clear queue behavior.

Retain existing file tree, terminal, previews, changed-files cards, plan cards,
saved outputs and handoff notes. Improving their links to runs/tasks is useful;
rebuilding them is outside the core.

### Responsive and accessible behavior

Verify light/dark at 1440, 1024, 768 and 390px in browser. Use a drawer for narrow
navigation and a child-detail overlay with focus trapping/return. Keep keyboard
alternatives to drag actions, visible focus, reduced motion, labelled controls and
screen-reader status announcements that do not fire for every token. Desktop
minimum window dimensions are a separate constraint from narrow-browser support.

## 6. Team model and execution rules

Capacity assumption: one integrating lead plus three implementation subagents,
about 15 builder-days over five days, plus lead review/QA. Estimates below are
engineer-days, not elapsed promises. Reserve roughly three builder-days for
integration and defects. If providers or migration behavior are unknown at the
end of Day 1, re-estimate before expanding scope.

| Owner | Responsibility | Exclusive/shared boundaries |
| --- | --- | --- |
| Lead | P00 contracts/ADRs, ticket briefs, integration, scope, release evidence | Owns shared schema/config/API contract decisions and final merge order |
| Runtime agent A | P01–P03: lifecycle, receipts, async execution and controls | `src/core/` and delegation lifecycle; one migration author |
| App agent B | P05–P07: sidebar, inspector, frontend reconciliation | `web/src/`; consume fixed contracts and fixtures before backend completion |
| Reliability agent C | P04, P08, P09: worktrees, Kanban, replay/browser harness | Isolated worktree/worker modules and tests; coordinate shared files with A |

Use separate worktrees from the same committed contract baseline; uncommitted
parent changes are not copied. Use descriptive `feat/`, `fix/` or `docs/` branches.
One writer per shared file, migration chain, generated manifest, lockfile and
built web bundle. No broad cleanup, shared-checkout staging, or unrelated edits.
Do not add recursive team management to Spark merely to execute this roadmap.

GitHub Issues are the execution tracker (`docs/agents/issue-tracker.md`). Once
implementation is authorized, create an umbrella issue and one issue per packet;
link dependencies, owner and PR. Use `needs-triage` during discovery,
`needs-info` for unresolved requirements, `ready-for-agent` only with a complete
brief, `ready-for-human` for work requiring a human, and `wontfix` when declined.
Keep live status/evidence in issues; keep scope/dependencies in this plan.

Every delegated brief must contain: packet ID and outcome; base SHA and dependency
SHAs; exact allowed paths and prohibited shared edits; current/target contract;
reference IDs; acceptance scenarios; targeted checks; migration/rollback impact;
and the required completion report. Report changed files, commit/PR, test commands
and exit status, browser evidence, unresolved objections and risks. A reviewer must
verify the acceptance behavior before checking a packet complete. A finished
subagent message alone is not acceptance evidence.

## 7. Five-day critical path

Dependency path: **P00 -> P01 -> P02 -> P03 -> P06 -> P09 -> P10**.
P04 depends on P01/P02; P08 depends on P01/P03; P05 can proceed after P00 against
fixtures; P07 follows P03/P05/P06. P09 begins fixture work on Day 1 and closes only
after all included packets pass. P10 follows the web gate.

| Day | Runtime A | App B | Reliability C | Lead gate |
| --- | --- | --- | --- | --- |
| 1 | P01 additive contracts/persistence | P05 sidebar states/fixtures | P09 replay harness and P04 isolation design | P00 baseline, ADRs and contract freeze; no schema guessing |
| 2 | P02 receipts/dispatch | P05 implementation | P04 worktree lifecycle | Command-to-projection vertical slice with fake external transport |
| 3 | P03 async controls/delivery | P06 child inspector | P08 task claims/profile routing | Real parent/child run; duplicate submit and cancellation replay pass |
| 4 | Integration fixes, weak-provider paths | P07 recovery/a11y/responsive polish | P09 failure matrix and performance | Browser flow, restart, old-data migration and cross-profile checks |
| 5 | Regression fixes | Regression fixes and web build | P09 finish; P10 package smoke with lead | Reviewed core release candidate, evidence, rollback rehearsal |

P00 is roughly 0.5 lead-day. P01–P08 budget about 9 builder-days; P09/P10 roughly
3 builder-days, leaving approximately 3 builder-days contingency. Desktop signing,
provider outages and unavailable Windows access can move platform acceptance past
Day 5. Ship a verified web slice independently and label desktop status separately.

### P00 — Baseline, contracts and decisions (lead; 0.5 day)

- [x] Record branch, SHA, dirty paths, configured test commands and baseline lint/type failures without fixing unrelated files.
- [ ] Use temporary `SPARK_HOME`, synthetic sessions and no external sends. Capture current long-thread, three-chat, project-create, child-run, pending-decision and reconnect behavior.
- [ ] Record repeated first-token latency (separate provider time), backend/gateway readiness, sidebar update/select latency, stream gaps, browser memory and bundle size.
- [x] Write ADRs for execution identity/write ownership, async completion, cursor semantics, compatibility/migration and worktree lifecycle. Resolve the identified Kanban/profile risks.
- [x] Publish contract fixtures/types and assign files before implementation agents start.

**Done when:** documented current/target behavior, evidence locations and bounded
packet briefs exist. Any unknown is explicitly assigned rather than hidden in an
estimate.

### P01 — Additive execution projection (A; 1 day; depends P00; T1/T4)

**Touch:** `src/core/spark_state.py`, `src/agent/subagents.py`,
`src/spark_cli/web_projections.py`, related persistence tests. Proposed new
`src/core/orchestration/` contains small lifecycle/identity helpers only if needed.

- [x] Map existing session/turn/subagent IDs; persist parent/root/attempt relationships and a versioned projection with stable pending-decision IDs.
- [x] Select one lifecycle writer; atomically append durable events and update their projection. Publish only committed data.
- [x] Root terminal closes its Run; child/tool/plan terminal never does. Preserve independent child failure and waiting states.
- [x] Add deterministic migration from schema 12 fixtures, idempotent rerun and rollback guidance. Keep old sessions readable without replaying tools.

**Acceptance:** real SQLite replay produces the same parent/child projection after
restart and duplicate/out-of-order callbacks; compression lineage resolves the
same child. Existing caching goldens and public imports remain unchanged.

### P02 — Idempotent commands and capability boundary (A; 1 day; P01; T2/T5)

**Touch:** `web_server.py`, `runtime_provider.py`, model/provider routes; proposed
receipt/service helpers and additive frontend API types owned through the lead.

- [x] Add durable request receipts for async dispatch, cancel and retry, with payload hash, accepted IDs and committed cursor.
- [x] Repeated accepted request returns its original result; changed payload with reused ID fails. Validate profile/thread authorization before lookup or mutation.
- [x] Expose versioned runtime capabilities including custom model/provider selections, unsupported reasons and stale/offline availability.
- [x] Preserve current conversation endpoints and synchronous `delegate_task` contract. New mode is explicit and feature-gated for the compatibility release.

**Acceptance:** duplicate HTTP/tool dispatch creates one app attempt; lost response
followed by retry returns the same handle; unsupported controls cause no side
effect; receipt tests cover concurrent clients and restart.

### P03 — Background delegation and controls (A; 1.5 days; P02; H1/T1)

**Touch:** `delegate_tool.py`, `agent/subagents.py`, run-agent/CLI/gateway callback
boundaries, narrow proposed execution/delivery service. Keep prompt-cache code out
of scope except invariant tests.

- [x] Return a durable async handle and retain existing sync mode. Implement inspect/status and cooperative child cancellation with ownership validation.
- [x] Bound concurrent children and shared resources per profile; record model, provider, permissions, budget and target directory at dispatch.
- [ ] Deliver stored child result at a safe subsequent parent boundary with a deduplicated delivery identity. Support parent idle, busy, disconnected and stopped states.
- [x] Reconcile startup after worker loss; never claim daemon-thread durability or blindly rerun uncertain work. Record heartbeat/progress separately from deadlines.
- [x] Keep child restrictions; define parent stop cascade, partial batch cancellation and terminal acknowledgement. Failed child cannot complete parent.

**Acceptance:** two children complete in either order while the user switches chats;
parent remains correct; stop one child leaves its sibling running; parent stop
converges; duplicate delivery and gateway restart create no duplicate parent turn.
Exercise CLI and web plus a gateway transport fixture with external sends disabled.

### P04 — Safe coding worktree isolation (C; 1 day; P02; H2)

**Touch:** proposed `src/tools/subagent_worktree.py`, delegation integration owned
by A, checkpoint manager interfaces and temporary-repository tests.

- [x] Record repository root/base commit/branch/path and requested isolation before spawn. Use `feat/subagent-<id>` style branches and profile-scoped metadata.
- [x] Start from committed content; expose that unsaved changes are absent. Validate paths and command arguments; preserve parent dirty files and existing worktrees.
- [x] Run setup in the child checkout with bounded failure reporting. Refuse unsupported local/remote/backend combinations before execution.
- [x] Retain worktrees with commits, dirty files or uncertain inspection. Explicit cleanup only after proof and no active worker; return diff/commit references for lead review.

**Acceptance:** parallel children edit the same filename without collisions; parent
checkout stays unchanged; setup failure, cancel, crash and branch-name collision
are recoverable. No automatic merge or deletion of useful child work.

### P05 — Sidebar organization and durable thread metadata (B; 1.5 days; P00; T3)

**Touch:** `App.tsx`, `sessionStore.tsx`, `sidebarPrefs.ts`, sidebar components and
row tests; backend metadata endpoints/migrations are coordinated with A/lead.

- [x] Extract project wizard/row actions from the large sidebar module where needed; preserve existing virtualization, paging and search.
- [x] Implement consistent row hierarchy/status and durable pin/manual order/settlement fields with versioned migration of eligible local preferences.
- [x] Manual ordering stays stable during stream updates. Server versions resolve concurrent metadata edits; Undo restores prior metadata without undoing newer run state.
- [ ] New project chat appears inside an expanded folder; failed creation preserves the draft. Standalone/project/child identity remains distinct.
- [x] Add keyboard actions, selected-row focus retention, empty/error/loading states and search outside the first page.

**Acceptance:** 1,000-session fixture with mixed projects/pins/settled rows remains
usable; refresh and a second client agree; two profiles/backends do not leak local
state. Unresolved decisions cannot disappear through settle.

### P06 — Delegated-work inspector and contextual task links (B; 1 day; P03; T1/T2)

**Touch:** `ChatPage.tsx`, `SubagentsPanel.tsx`, `useSubagents.ts`, `lib/subagents.ts`,
`apiTypes.ts`, `api_session.ts`, existing project/right-panel components.

- [ ] Render parent/root and child attempts from authoritative snapshots/events with stable selection and bounded transcript paging.
- [ ] Add capability-gated inspect/Stop/Retry, result-copy and task/worktree navigation; show cancel-requested until terminal confirmation.
- [ ] Keep main conversation visible, distinguish child failure from parent failure, and preserve input/attachments/scroll across detail navigation.

**Acceptance:** open child detail during a three-chat run; switch/reconnect/back;
child selection and parent draft remain correct; stale cancel/retry responses do
not affect a newly selected thread. Unknown capability disables the action with a
useful reason.

### P07 — Reconciliation, responsive layout and accessibility (B; 1 day; P05/P06)

**Touch:** existing chat controllers, event bus, draft/recovery stores, sidebar and
right-panel layout; avoid replacing the frontend state architecture.

- [ ] Reconcile snapshot and live events using their declared cursors; cancel stale loads; expired journal/server epoch forces authoritative refresh.
- [ ] Namespace retained local UI state by backend/profile. Preserve drafts/attachments on uncertain submission; never automatically resend a prompt.
- [ ] Verify narrow overlays, keyboard/focus return, reduced motion, screen-reader labels, long titles/content and both themes.

**Acceptance:** refresh during tool/approval, stop while disconnected, reconnect
after restart, and switching across three live chats converge within five seconds
of a successful status snapshot. No duplicated runs, lost draft, stuck spinner or
cross-thread output.

### P08 — Kanban worker ownership and completion evidence (C; 1 day; P01/P03)

**Touch:** `kanban_db.py`, `kanban_dispatch.py`, `kanban_worker.py`, task APIs/tests;
coordinate any session linkage schema with A.

- [x] Carry explicit board-owner profile, execution profile and claim/run token into workers. Resolve configuration/state deliberately instead of relying on inherited environment.
- [x] Fence heartbeat, completion and failure updates by claim token/attempt. Extend lease while owned; reject late writes from reclaimed workers.
- [x] Use recorded worker identity/liveness, not PID alone or elapsed TTL, to decide safe reclaim. Uncertain side effects require review rather than blind rerun.
- [x] Link task runs to conversation/child execution; require changed files, verification and limitations on completion. Auto-closed text-only results remain visibly unverified `user_review`.

**Acceptance:** two dispatchers cannot own one task; a live long worker survives
TTL; a stale worker cannot overwrite its replacement; assigned profiles use the
correct model/state while board updates reach the owning board. Dependency
promotion waits for the existing task review/done policy.

### P09 — Replay, browser and performance release gate (C + lead; 1.5 days; all core)

**Touch:** existing Python tests, frontend tests, `web/e2e/`, efficiency fixtures
and `.github/workflows/web-quality.yml` where coverage needs wiring.

- [x] Add a deterministic provider-transport replay harness using real agent callbacks, command receipts, SQLite, lifecycle policies and frontend projections; do not mock the contract being tested.
- [ ] Cover normal/child-before-parent completion, duplicate dispatch, cancel acknowledgement before terminal, provider failure, lost acknowledgement, gateway restart and weak/unsupported provider behavior.
- [ ] Extend existing multi-chat, recovery, work-recovery, chat-contract and sidebar-scale browser flows; test served production assets as well as dev mode.
- [ ] Cover schema-12 upgrade, old metadata import, profile isolation, two clients, stalled work, pending decisions, empty/deleted source and long-history pagination.
- [ ] Record repeated performance against P00 on the same hardware/fixtures, including 2,000 message rows and 1,000 sessions. Investigate median/p95 regressions above 10%; target warm local message search p95 <=500ms on 10,000 messages, subject to baseline confirmation. Do not mix provider latency with UI processing.

**Acceptance:** reproducible command-to-UI traces and screenshots; no unexplained
regression, failed invariant, unbounded subscriptions or falsely green evidence.
Record exact failures and exclusions rather than relabelling tests to pass.

### P10 — Compatibility rollout, packages and handover (lead + C; 1.5 days; P09)

- [x] Keep new async execution/control paths disabled until core acceptance passes; document exact config keys/defaults in P00 and add migrations through `DEFAULT_CONFIG` when needed.
- [ ] Back up profile databases/config with a consistent SQLite backup, not a live file-only copy. Run additive migrations once and verify old conversations, tasks, drafts and skills remain accessible.
- [ ] Enable in an isolated profile, then a staging/test instance. Record source SHA, served hashed assets, schema/config versions and selected feature flags.
- [ ] Build via existing desktop scripts only after web gates. Smoke installed macOS quit/relaunch, sleep/wake, unavailable backend, Quick Ask handoff and child controls. Run equivalent Windows beta tests on Windows or leave that gate explicitly pending.
- [ ] Rollback: stop workers, disable new dispatch, preserve completed/uncertain attempts, and use the last schema-compatible app. Restore a pre-upgrade backup only with an explicit account of post-backup work that would be lost; do not drop new tables automatically.
- [ ] Update docs/issues/evidence and prepare release notes. Packaging, publishing and production rollout are separate execution steps; this planning change performs none of them.

**Acceptance:** web release candidate plus platform-specific package evidence,
rollback rehearsal and an explicit list of remaining extension/platform work.

## 8. Follow-on feature backlog

Each extension is optional for the core release and needs its own acceptance gate.
Do not use spare Day 5 time to merge an unverified extension.

| Packet | Estimate / owner | Implementation and acceptance |
| --- | --- | --- |
| E01 — Anchored recall and learning review (H3) | 1–2 days; memory agent; after P01 | Extend existing `session_search_tool.py`, SessionDB FTS, memory routes and command palette with discover/read/around-message links, date/project filters, compression/child lineage and source attribution. Reuse existing index; no new vector service. A fresh chat can find an older answer and open the exact unloaded message without self-recall loops or profile leakage. Expose existing Dream/Auto-memory provenance and errors without invoking Dream implicitly or rewriting active cached context. |
| E02 — Auditable skill improvement (H4) | 1–2 days; skills agent; independent of UI core | Extend `skill_manager_tool.py`, `skill_usage.py`, `skills_metadata.py` and skills UI with bounded per-edit snapshots, actor/source-session provenance, before/after diff and guarded rollback. Respect read-only external/bundled sources; preserve supporting files and concurrent edits. Accept when a failed update restores a complete package, rollback refuses newer conflicting edits, and existing guard/size/traversal tests pass. Keep automatic destructive curator changes out of scope. |
| E03 — Scheduled occurrence reliability (H5) | 1.5–2.5 days; automation agent; after P08 | Audit cron claims first; add stable occurrence/execution/delivery identities and explicit retry policy through existing jobs/scheduler/routes. Handle DST, missed slots, restart between schedule advance and claim, duplicate ticks and delivery failure. Accept when duplicate ticks run one owned attempt, delivery retry sends stored output without re-execution, and uncertain provider work is surfaced for review. External delivery uses a local fake adapter in tests. |
| E04 — Context transfer and broader harness support (T2/T5) | 3–5+ days after a discovery spike; runtime lead | Explicit fork/handoff from completed checkpoints, source coverage and a bounded portable artifact. Preserve Spark app IDs and prompt-cache rules; native forks only where supported. Inventory existing external-process providers before choosing one additional harness. Add adapter-specific replay fixtures and auth/resume checks. No claim of T3 provider parity. Never silently switch providers or splice rewritten history into an active thread. |
| E05 — Attention and sidebar refinements (T3) | 1–2 days; app agent; after P05/P07 | Snooze/wake, optional automatic settlement, cross-device manual ordering polish, file-drop attachment handoff and PR links/watch only if demand is established. Persist server scheduling where needed; unresolved decisions/live work block automatic hiding. Undo preserves newer state and attachment references; token streams do not reorder work. Reuse notification preferences/quiet hours and command palette. |

Defer a React state-library replacement, Electron migration, native mobile app,
new marketplace, wholesale Hermes merge, new multi-provider process framework,
and generic distributed scheduler. These add migration/support cost without being
necessary for the first outcome. Revisit through explicit issues and ADRs.

## 9. Verification commands and evidence requirements

Run from the repository root unless a subshell changes directory. Activate `.venv`
before Python, linting, tests or servers. Install missing prerequisites deliberately;
do not repeatedly change dependencies just to make unrelated baseline failures go
away. The commands below are the implementation gate, not tests run by this plan.

```bash
source .venv/bin/activate
pip install -e ".[dev,web]"

# Choose relevant focused subsets while iterating.
python -m pytest tests/tools/test_delegate.py tests/agent/test_subagents.py tests/core/test_kanban_db.py -q
python -m pytest tests/run_agent/test_caching_golden.py tests/tools/test_lazy_manifest.py tests/test_minimal_startup.py -q
python -m pytest tests/spark_cli/test_web_state.py tests/test_web_turn_persistence.py tests/spark_cli/test_web_server.py tests/spark_cli/test_web_server_events.py -q
python scripts/generate_tool_manifest.py --check
ruff check src/
mypy src/agent/ src/spark_cli/
python -m pytest tests/ -m "not slow and not integration" -q
python -m pytest tests/ -q

(cd src/spark_cli/web && npm ci)
(cd src/spark_cli/web && npm run lint && npm test && npm run build)
(cd src/spark_cli/web && npm run test:e2e)
(cd src/spark_cli/web && node e2e/chat-contracts.mjs)
(cd src/spark_cli/web && npm run test:e2e:recovery)
(cd src/spark_cli/web && npm run test:e2e:sidebar)
(cd src/spark_cli/web && npm run test:e2e:baseline)
python src/spark_cli/web/e2e/work-recovery.py
SPARK_E2E_BUILT_WEB=1 python src/spark_cli/web/e2e/work-recovery.py
```

`npm run build` includes TypeScript and the bundle-budget check. Browser tests need
the Node Playwright browser; `work-recovery.py` needs its Python Playwright browser
as configured in `web-quality.yml`. Pytest excludes integration by default; retain
that exclusion when overriding `-m`. Use `-n 0` for serial/shared-state cases as
needed. Existing CI enforces selected Ruff rule families and incremental mypy;
record full-lint baseline debt separately from new failures.

Every accepted packet records SHA/PR, migration/config impact, commands and exit
status, fixture version, exact manual flow, screenshot/report paths, performance
samples, provider/runtime version and remaining limitations. Redact real prompts,
credentials and personal data from fixtures. Screenshots alone do not prove
persistence; passing unit tests alone do not prove browser behavior; web builds do
not prove installed desktop behavior.

## 10. Execution ledger

Implementation is in progress. Fill this table as work is verified;
keep checkboxes above open until acceptance is demonstrated.

| Packet | Owner | State | Commit / PR | Automated evidence | Browser / package evidence | Limitations |
| --- | --- | --- | --- | --- | --- | --- |
| P00 | Lead + baseline agent | Baseline recorded; final gates open | `73c5032`, `89616f95` | Baseline tests and risk reproductions recorded | Repeated browser samples recorded | External gateway timing and remaining create flow pending |
| P01–P04 | Runtime agent + lead | P01/P02/P04 verified; P03 acceptance open | See checkpoints | 45 core/cache tests; 105 delegation/isolation tests | Inspector integration in progress | Completion waits for explicit parent turn; browser acceptance pending |
| P05–P07 | App agent | P05 integrated; P06/P07 in progress | `dff9d0df`, `6409bba` | 405 frontend; 288 web; 33 sidebar tests pass | 1,000-session flow passes | Failed create, responsive themes and inspector acceptance pending |
| P08–P09 | Reliability / lead | P08 verified; P09 in progress | `0357b35a`, `1805f6b`, `a7281b8` | 12,404 local tests pass; 52 worker/task tests pass | Replay and browser/CI agents running | Final performance and failure matrix pending; external services excluded |
| P10 | Lead | Synthetic backup/migration checks pass; rollout pending | See checkpoints | 78 backup/lifecycle tests; mypy 129 pass | No package/release produced | Installed platforms and staging still pending |
| E01–E05 | Unassigned | Backlog | — | — | — | Outside five-day core |

### Implementation checkpoint — 2026-10-15

- User approved execution and parallel delegation. Branch: `feat/app-orchestration-upgrade`; approved roadmap commit `2a41925`, shared ADR0013/fixture commit `73c5032`.
- Preserved the preexisting `HANDOFF_100826.md` to `docs/HANDOFF_100826.md` move outside all commits.
- Baseline full Ruff: **305 findings**, exit 1, captured before source changes. Baseline mypy: **127 source files pass**, exit 0. Logs: `/tmp/spark-upgrade-20261015/{ruff,mypy}-baseline.txt` (local, not release evidence).
- Parallel isolated worktrees: runtime (`feat/durable-child-runtime`), app (`feat/sidebar-metadata`), baseline (`test/spark-baseline-fixture-audit`). Lead owns P04 isolation, shared contracts, integration and checklist review.
- Source tracing confirms the dedicated subagent callback prevents simultaneous lifecycle/web persistence in the normal path; atomicity and duplicate transport delivery remain P01 work. Existing transcript/interrupt APIs will be extended, not duplicated.
- No new packet is accepted yet; only individually evidenced P00 items are checked above.

| Tracker | Issue |
| --- | --- |
| umbrella | https://github.com/automatedigital/spark/issues/129 |
| P00 | https://github.com/automatedigital/spark/issues/130 |
| P01 | https://github.com/automatedigital/spark/issues/131 |
| P02 | https://github.com/automatedigital/spark/issues/132 |
| P03 | https://github.com/automatedigital/spark/issues/133 |
| P04 | https://github.com/automatedigital/spark/issues/134 |
| P05 | https://github.com/automatedigital/spark/issues/135 |
| P06 | https://github.com/automatedigital/spark/issues/136 |
| P07 | https://github.com/automatedigital/spark/issues/137 |
| P08 | https://github.com/automatedigital/spark/issues/138 |
| P09 | https://github.com/automatedigital/spark/issues/139 |
| P10 | https://github.com/automatedigital/spark/issues/140 |

### Runtime foundation milestone — 2026-10-15

- Integrated `3f138c48` (atomic child lifecycle) and `13877a8d` (durable command receipts and capability snapshots), from runtime worktree commits `b7405eff` / `362d97c9`.
- Independent parent verification: **211 passed** in 32.41s across child lifecycle, runtime receipts, subagents, delegation, web events, caching goldens, lazy manifest and minimal-startup tests. Command: `python -m pytest tests/core/test_child_lifecycle.py tests/core/test_runtime_commands.py tests/agent/test_subagents.py tests/tools/test_delegate.py tests/spark_cli/test_web_server_events.py tests/run_agent/test_caching_golden.py tests/tools/test_lazy_manifest.py tests/test_minimal_startup.py -q -n 2`.
- P01/P02 remain in progress: cancellation terminal-state edge review and full async dispatch/control integration are not yet accepted. No speculative packet completion.
- P04 helper `395f3336`: real Git isolation/retention tests pass; integration still pending.
- Reproduced Kanban risk in a temporary home with controlled clock and a live PID: lease stayed at 110 after heartbeat at 105, and reclaim at 111 returned the live worker task to ready. Evidence `/tmp/spark-upgrade-20261015/kanban-risk.json`; P08 must fence/renew ownership.
- Manual Playwright baseline opened and switched a synthetic project chat with no browser errors. Collaborative preview snapshot timed out twice; repository Playwright is the acceptance fallback. Local screenshots `/tmp/spark-upgrade-20261015/baseline-{preview,selected-chat}.png`. Wider P00 matrix remains with baseline agent.

### Sidebar, isolation and worker milestone — 2026-10-15

- Integrated sidebar `dff9d0df` and authoritative guard/router integration `6409bba`. Parent checks: **288 Python web tests**, **33 sidebar tests**, **405 Vitest tests**, frontend lint/types, and the production-wired 1,000-session acceptance flow all passed. The browser mounted 23 rows and requested page offset 50; order during fake streaming, second-client SSE, settlement/Undo conflicts, pending decisions, drafts/attachments, search, project expansion, keyboard focus and scroll recovery passed.
- Integrated async runtime `a67d9ec3`, terminal-state safety `0afe3d2a`, compression control fix `bed0d010`; preserved additive schema 12→15 and opt-in `delegation.async_enabled: false`. **45** independent core/cache/lazy/manifest/runtime-route tests passed after regeneration. Process-local workers do not survive a process crash; lost workers become uncertain without automatic re-execution. Results currently wait for the next explicit parent turn; autonomous wake-up is not implemented, so P03 delivery acceptance stays open.
- Delegation/worktree integration `0829497`: **105** tests passed across existing delegation, async execution and real Git isolation. Synchronous and async children used different worktrees and actual file operations against the same filename; parent unsaved content stayed intact. Setup timeout/collision/retention and cleanup tests passed.
- Integrated worker ownership `0357b35a`: **52** independent Kanban DB, worker-process and gateway task tests passed. Lead corrected external-process provider argument mapping against the real AIAgent constructor and added worker resource cleanup. Old worker binaries must be stopped/restarted to gain fencing.
- Clean-cache parent mypy passes **129 source files**. The baseline worktree recorded 2,706 imported-module errors under its distinct PYTHONPATH context; that observation is retained in its report, but is not the parent checkout's current type-check status. Full Ruff baseline debt remains separate from clean CI/touched-file gates.
- Baseline report/evidence committed in `89616f95`: `docs/performance/app-upgrade-baseline-2026-10-15.{md,json}`. It records a preexisting long-history failure in 1 of 4 trials and obsolete canonical sidebar locators; P09 must retain/fix these gates.
- Parallel follow-ups now own P06/P07 inspector/recovery and P09 transport replay; P00/P03/P05 full acceptance, final browser/performance comparisons, rollout and installed packages remain open. No release or deployment performed.

- Worker follow-up `a7281b8` persists actual task transcripts in the assigned execution profile while keeping task-board writes in the board owner. Isolated worker subprocess tests verify both destinations. Mypy passes all **129 source files** after typed claim fencing; CI lint and generated manifest checks pass.

### Broad local regression milestone — 2026-10-15

- `python -m pytest tests/ -m 'not integration and not network' -q -n 4`: **12,404 passed, 151 skipped, 135 warnings**, exit 0, 493.70 seconds. Log: `/tmp/spark-upgrade-20261015/full-local-pytest.txt`. External services are excluded. Warnings include unawaited MCP coroutines; their provenance has not been compared against the baseline.
- This run began before the assigned-profile transcript follow-up; the later worker changes separately pass all **52** focused worker/task tests and clean-cache mypy (**129 source files**). New inspector/replay/browser changes will receive their own integration checks.
- Three isolated agents continue P06/P07 inspector/recovery, P09 transport replay and P09 browser/CI/performance. Package, staging and production gates remain open.

### Rollout preparation — 2026-10-15

- Fixed an existing backup hazard: SQLite backup failure no longer falls back to raw file copy or reports a complete archive. Backup excludes raw `.db-wal`/`.db-shm`/`.db-journal` companions and exits nonzero on incomplete archives. SQLite connections close on failure; bounded backup progress times out after 30 seconds.
- **78 backup/lifecycle tests passed**, including live-profile WAL restore, corrupt database rejection, configuration/skills/file-draft preservation and additive/idempotent schema-12→15 checks. Browser local-storage drafts and cross-database transactional consistency are separate concerns; workers must be quiesced before a migration backup.
- CI Ruff ratchet and touched-file Ruff pass; mypy passes **129 source files**. Added `docs/development/app-upgrade-rollout.md` and refreshed root docs to distinguish implemented gated foundations from remaining acceptance. No real user state was migrated/restored; no package/staging acceptance claimed.

### Transport replay integration — 2026-10-15

- Integrated `f48d7974`: real SDK HTTP/SSE replay, real child tools/callbacks/SQLite, actual process death, cancellation acknowledgement, decisions, compression and profile isolation. Original report preserves **15 passed / 2 strict expected failures** and pinned-worktree manifest drift rather than calling them accepted gates.
- Fixed lost-ack dispatch retry after compression: resolve authorized family receipts in preflight and again inside the acceptance transaction; new dispatches use the stable compression root. Original handles and owner survive; changed payloads conflict; forks and child transcripts remain outside scope. Added concurrent old-ID/new-ID and legacy leaf-receipt regressions; removed this defect's xfail marker.
- Integrated focused regression: **133 passed, 1 strict xfailed**, exit 0, 18.16s. Unsupported-stream fallback is the remaining reproduced runtime defect, assigned to a new isolated agent. Browser agents also reproduced a virtualizer render loop and sidebar insertion/latency regressions; those remain release objections, not accepted performance.

### Inspector contract and browser gates — 2026-10-15

- `b39c9b5` adds exact per-child capability records while retaining aggregate schema-1 fields. Mixed live/orphaned/failed/uncertain/synchronous children cannot inherit one another's Stop/Retry permissions. HTTP checks observe the same actual profile opt-in setting as dispatch; **6** capability/receipt checks passed.
- Added bounded cursor pages for child events and transcripts. Backend acceptance traverses **2,101 events and 2,101 messages** without full-transcript reads, gaps or duplicates and rejects foreign child access. **114** web-event/history/capability tests passed; CI Ruff and mypy (**130 source files**) pass. Inspector UI integration is still with its agent.
- Integrated browser/CI contribution `336797df`: semantic sidebar gates, bounded repeat runners, temporary production-built recovery and lifecycle path coverage in web-quality. Original evidence records **4/5 long-history** and **2/3 sidebar** attempts passing, not green aggregates. Production-built recovery passed nine checks; hosted CI has not run.
- Same-host comparison records >10% regressions in startup, rendering and selection. Original timing caveats and failed-trial artifacts remain in `docs/performance/app-upgrade-browser-gates-2026-10-15.{md,json}`. A fresh isolated agent owns virtualizer render-loop, sidebar anchor and title-latency fixes; no budgets/assertions are relaxed.

### History and sidebar reliability milestone — 2026-10-15

- Integrated `c152d2ee` (agent source `ba22b46a`): defer row measurement out of React ref commits, retain keyed sizes on history prepend, capture sidebar anchors from the actual DOM offset, and reconcile the initial zero-cursor SSE handoff. Root frontend lint, TypeScript and **411 tests** pass after integration.
- Agent repeated long-history gate: **5/5 passed**, each loading 39 earlier pages, **0 px** sampled drift, no React errors or recovery reloads. Sidebar anchors held **3/3**, fixing the reproduced insertion jump.
- Overall sidebar gate is still **2/3**, exit 1: a title PATCH queued **5,515 ms** before browser transmission, then received headers in 9.4 ms. Its late write overtook the fixture restore. Original failed attempt, request phases and >10% timing regressions remain in `docs/performance/app-upgrade-browser-fixes-2026-10-15.{md,json}`.
- A fresh isolated agent is investigating stale preview requests/connection scheduling. Inspector cursor/worktree integration and stream capability fallback remain with their existing agents. Core release, performance and package gates stay open.

### Runtime replay defects closed — 2026-10-15

- Integrated streaming fix `fb52fe7c` (agent `521feb93`): one non-streaming retry for a pre-output capability rejection using the existing built request. Text/reasoning/tool output blocks this fallback; Stop and unrelated client errors retain normal behavior. No tool redispatch or cached history/schema rewrite.
- Removed the final replay xfail. Combined real SDK replay, fallback, async lifecycle, receipt, worktree, interruption, compression/cache and lazy-startup gates: **230 passed**, exit 0, 36.42s. CI Ruff, manifest (**70 tools / 28 modules / 4 optional guards**) and mypy (**130 source files**) pass. Both reproduced runtime defects are now ordinary passing regressions.
- A separate isolated agent now verifies the actual gateway handler/delivery boundary with external sends disabled. Existing `AIAgent(platform='telegram')` coverage alone is not treated as gateway acceptance. P03/P09 gateway and final app/package gates remain open.

### Integrated web candidate — 2026-10-15

- Integrated preview request scheduling `4052574f` (agent `efdb0298`). Chromium NetLog established HTTP/1.1 socket-pool exhaustion from hidden preview scans and SSE. Visibility-gated observers, abortable reads and serialized polling preserve explicit Start/Stop/navigation. Agent sidebar gate **3/3**, anchors **3/3**; title rendering **15.8–18.6 ms**, with pre-transmission delay **0.533–0.609 ms**. Original failed samples remain in the evidence.
- Integrated inspector source `5311eab` (agent `5b2c478`), preserving both chat-position restoration and the repaired virtualizer measurement owner during conflict resolution. Exact child capabilities, persistent request IDs, cursor history accumulation, worktree references and responsive focus handling are present; final inspector browser contribution is pending integration.
- Root frontend lint/TypeScript/**426 tests pass**. Canonical `npm run build` passes, **239.53 KiB gzip / 600 KiB budget**. The actual Python-served canonical bundle passes **all 9** recovery checks: draft switch/refresh, failed send, late acknowledgement, concurrent tab conflict, thread/profile isolation, uploaded/missing/failed attachments. Daylight 390px and final screenshots inspected. Logs/screenshots: `/tmp/spark-upgrade-20261015/recovery-built-integrated/`.
- Source/manifest/entry hashes and exact limits recorded in `docs/performance/app-upgrade-integrated-web-2026-10-15.json`. This is a web candidate, not installed-package or rollout evidence. Gateway and controlled performance agents continue in separate worktrees; no publishing performed.
