# App upgrade release notes — draft, unreleased

The approved upgrade improves parallel work, chat organization and recovery.
Implementation acceptance and release gates are tracked separately in
[PLAN.md](../../PLAN.md). Gateway approval ownership, final performance and
installed-platform acceptance remain open.

- Background delegation returns durable child handles, supports inspection and
  cooperative cancellation, and delivers stored results once at the next
  explicit parent turn. Existing synchronous delegation remains available.
- Explicit local Git worktree isolation gives coding children separate checkouts
  while retaining useful work for review. The parent checkout stays intact.
- Sidebar pins, ordering and settlement persist in the active profile, with
  revision conflict handling, Undo and guards for active work or pending decisions.
- The child inspector shows paged transcripts/events, exact supported controls,
  copied results and execution references. Verified task links open their board;
  an explicit worktree action opens the owned checkout as a project.
- Drafts, attachments, child selection and detached scroll survive chat switching
  and reconnects. Hidden previews release reads; long-history measurements retain
  stable anchors and substantially reduce render commits in the controlled runs.
- Task workers fence updates by their current claim and attempt, persist execution
  transcripts in the assigned profile, and retain uncertain outcomes for review.

Async delegation and worktree isolation default to **off**. Workers are
process-local; lost execution becomes uncertain. Idle-parent autonomous wake,
automatic merging and remote worktree execution are outside this core slice.
Schema 12→15 migration is additive; config version is 29. The
[rollout runbook](app-upgrade-rollout.md) covers consistent backups, isolated
enablement and the post-backup loss inventory required before restoring old state.

Current parent evidence includes 435 frontend tests, 147 backend navigation/core
checks, type checking of 133 source files, and canonical served-bundle navigation
(6 flows) and inspector (11 flows). Earlier runtime/gateway and draft-recovery
evidence remains in the execution ledger. These counts are scoped checks, not a
claim that the final combined suite or hosted CI has run on the release candidate.
Signing/building, installed macOS QA, Windows QA, staging and publishing require
their own recorded outcomes.
