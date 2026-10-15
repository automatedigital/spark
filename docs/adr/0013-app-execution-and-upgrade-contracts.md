# ADR 0013: Incremental app execution and ownership contracts

Date: 2026-10-15
Status: Accepted for implementation of the approved PLAN.md core slice.

## Decision

Retain the Python AIAgent runtime, FastAPI, React/Vite, Tauri, current provider
resolution and existing SQLite/session interfaces. Extend existing persistence
rather than introducing a parallel orchestration framework. ADR-0001 cache
behavior and ADR-0012 lazy discovery remain mandatory regression gates.

### Identity and committed lifecycle

Thread is the existing session ID (compression lineage remains resolvable). Root
Run is the existing web turn ID where present. An attempt and execution node have
stable app-owned IDs; provider references never substitute for these IDs.
Children carry parent_session_id, root_run_id, attempt_id, parent_node_id and
node_id when available. Legacy callers may lack these references and remain
readable; do not fabricate a historical root run for them.

SessionDB owns durable lifecycle writes. One transaction updates the child
snapshot, appends a deduplicated lifecycle event and, when linked to a session,
its committed session event. Canonical emission delegates to that method; web
callbacks publish committed data and can use the same idempotent persistence
entry point for legacy/fake transports. Each emitted lifecycle event has a stable
event_id. Repeated delivery does not append again. Terminal child state cannot
regress to running because of a delayed callback. Child completion never updates
the root run to complete. Persistence failures cannot be published as committed
success. Old unkeyed APIs remain compatibility surfaces, not new write paths.

Durable session sequences and bounded web-journal (server_epoch, sequence) are
different cursors. The existing web envelope remains compatible. Process loss or
journal expiry requires a fresh authoritative snapshot; never replay a prompt or
tool action merely to reconstruct UI state.

### Commands, async delegation and provider policy

Command receipts are durable and scoped by owning session plus command kind and
caller request ID in the active profile database. Validate ownership first. Store
a canonical payload hash, accepted IDs/result and committed sequence. Same key and
payload returns the original acceptance; another payload conflicts. Commit the
receipt and dispatch intent together before performing external side effects.
Uncertain acceptance after process loss is interrupted/uncertain, never silently
redispatched. No claim of exactly-once provider/tool execution.

Proposed additive config: delegation.async_enabled defaults false;
delegation.worktree_isolation defaults false. Existing synchronous tool arguments
and results remain compatible. Optional async arguments apply only for sessions
with the feature enabled; do not mutate schemas/toolsets in an active thread.
Child permissions and blocked tools remain enforced. Limit concurrent children
per active profile. A cancellation request is not terminal acknowledgement.
Parent Stop cascades cancellation to its owned children; stopping one child leaves
siblings alone. Completion is persisted and delivered once at a safe subsequent
parent boundary, never by rewriting cached historical/system content.

For app controls use existing conversation ownership/auth and compression-chain
validation. Planned routes (JSON shapes may add fields, not remove these):

- GET /api/conversations/{session_id}/subagents: existing snapshot contract.
- GET /api/conversations/{session_id}/subagents/{id}: existing detail contract.
- GET /api/conversations/{session_id}/subagents/capabilities: versioned capability
  snapshot, with explicit supported/reason per control; route before {id}.
- POST /api/conversations/{session_id}/subagents/{id}/interrupt: extend the existing
  endpoint with optional request_id and a receipt-backed acknowledgement; preserve
  its existing response shape. Disable unsupported/stale controls.
- POST /api/conversations/{session_id}/subagents/{id}/retry: request_id and a new
  attempt reference; keep earlier attempt and never retry ambiguous work silently.

Do not introduce controls backed only by UI state. Capabilities reflect exercised
runtime paths, custom providers continue through runtime_provider.py, and secrets
never enter projections. Native provider forks/harness parity are outside core.

### Sidebar metadata ownership

Server-owned metadata is additive in the active profile state.db, isolated by its
session foreign key. A dedicated sidebar metadata module owns its table; only the
runtime agent edits SessionDB's numbered migration chain. Metadata changes do not
change transcript or execution status.

GET /api/sidebar/threads returns schema_version:1, entries keyed by session ID,
with pinned:boolean, settled:boolean, position:number|null, revision:integer.
PATCH /api/sidebar/threads/{session_id} accepts expected_revision and explicitly
changed fields. Compare-and-swap revision prevents lost concurrent edits; conflict
returns current metadata. Existing sessions have default metadata. Settle rejects
live work and unresolved decisions for the core slice. A persisted metadata event
triggers normal client reload/reconciliation. Undo uses the current revision and
restores metadata only; it cannot undo a newer run. Never let token activity
reshuffle manual order. Device-local expansion/width remains backend/profile scoped.

### Worktree and task-worker isolation

Requested local Git isolation starts at the recorded parent commit, not unstaged
or staged changes. Use feat/subagent-<id> branches and profile-local metadata with
absolute repository/worktree paths. Non-local filesystem/backends explicitly
reject unsupported isolation. Setup failures preserve evidence. Cleanup requires
no live worker, clean status and no child commits; any uncertainty retains files.
No automatic merge, force-reset or deletion of useful work.

A Kanban board-owner home differs from an assigned execution-profile home. Pass
both explicitly to worker setup; use owned claim/run tokens for writes and lease
renewal. Keep Kanban task state in kanban.db and link session execution by stable
references; do not pretend there is an atomic transaction across both databases.
Late writes from reclaimed workers must fail. Unknown side effects require review
rather than automatic rerun. Text-only auto-close remains unverified user_review.

### Gateway notification and execution lifetimes

A session routing key is not a worker ownership token. Callback cleanup and
approval waiters must belong to the execution that registered them; stale cleanup
cannot remove a replacement's callback or report a user decision that never occurred.

Normal parent completion ends that turn's notification callback while authorized
async children can continue within their existing permissions. A later ordinary
explicit parent turn must preserve those children. Explicit Stop revokes all
owned live execution contexts; replacing an overlapping, superseded root must
also fence its late tool calls. These are separate events from normal completion.
An earlier child cannot borrow a later turn's approval callback. If its required
responder is unavailable, report that limitation rather than fabricate approval
or denial. Tests must cross normal completion, sequential turns, Stop and overlap.

## Delivery and rollback

Single migration writer; independent agents own disjoint modules/worktrees.
Commit contracts before implementation. Keep new async dispatch opt-in until
real SQLite replay and browser failure flows pass. Additive schema keeps old
transcripts readable. Disable dispatch before rollback, stop/reconcile active
workers, and preserve uncertain results. Use a schema-compatible app; restoring
an old backup is a separate action that must account for newer user work.

No roadmap packet is complete until its acceptance evidence is recorded. Runtime
baselines, fixtures and any unsupported installed-platform checks are tracked in
PLAN.md and the corresponding GitHub issues.
