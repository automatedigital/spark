# App upgrade release notes — draft, unreleased

The approved upgrade improves parallel work, chat organization and recovery.
Implementation acceptance and release gates are tracked separately in
[PLAN.md](../../PLAN.md). Final performance and installed-platform acceptance remain open.

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

Consolidated parent evidence includes 12,456 local nonserial Python tests, 182
earlier serial runtime tests, 448 frontend tests, clean static checks and nine
canonical production recovery flows. Final dev/production inspector (11 flows)
and navigation (six flows), multi-chat, sidebar, recovery and explicit legacy-pin
import pass. These are local receipts; hosted CI is not inferred.

P10 local functional rehearsal on `99be7b43` now records enabled and flags-off
loopback source-app instances with identical served asset hashes, schema 15 and
config 29. Real async/worktree workers use a synthetic SDK boundary; completed
and genuinely process-lost uncertain attempts survive disabled dispatch and
restart without replay. The focused runtime/lifecycle/backup suite passes 99
tests. See the [dated evidence](../performance/app-upgrade-isolated-rollout-2026-10-17.md).
Actual old-source datastore migration/backup/restore was repeated; full earlier
app/native compatibility remains unproven. Installed macOS and genuine Windows
QA, continuing-owner performance acceptance, external rollout and publication
remain separate gates. The candidate production quiescence run passes and returns
to the live-turn census; continuing-owner controls fail their observation wait
before measurement and remain unverified.

The standard macOS build produced Developer ID signed app/DMG artifacts. Packaged
HTTP checks and native draft/child restoration, clean quit/relaunch and backend-loss
recovery pass in an isolated installed copy. Apple notarization fails with HTTP 403
because a developer agreement is missing/expired; Gatekeeper reports an unnotarized
Developer ID. Real sleep/wake, full global Quick Ask focus and live-child native
Stop/Retry remain untested. See [native evidence](../performance/app-upgrade-desktop-2026-10-17.md).
These drafts do not announce a release.
