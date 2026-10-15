# App upgrade rollout and rollback

This runbook covers the additive execution/sidebar/worker upgrade tracked in
[PLAN.md](../../PLAN.md). It does not authorize publication or production rollout.
Keep all trials in a disposable `SPARK_HOME` until the recorded browser and
platform gates pass.

## Defaults and compatibility

SessionDB upgrades schema 12 to 15 additively. Sidebar metadata initializes its
own additive table using SessionDB's write transaction helper. Config version is
29; missing delegation values receive defaults without rewriting an active
conversation's cached tool schema or system prompt.

```yaml
delegation:
  async_enabled: false
  worktree_isolation: false
  worktree_setup_commands: []
  worktree_setup_timeout: 120
```

Async dispatch requires an explicit opt-in. `delegate_task` keeps synchronous
mode by default; async/status/cancel/retry use durable request IDs. Retrying an
uncertain HTTP acknowledgement must reuse the same ID and payload. An explicit
execution retry gets a new attempt identity and preserves the earlier outcome.
Inspect capabilities before offering a control. Cooperative interrupt acceptance
does not prove terminal cancellation or the absence of external effects.

Workers run in the owning process, not a durable distributed worker service.
Proven process loss becomes uncertain without automatic provider re-execution.
Stored child results enter the next explicit parent turn once; no idle-parent
wakeup is implemented. Worktree isolation supports local Git checkouts and starts
from committed content. It preserves dirty/committed/uncertain child work and
never merges automatically. Setup argv comes from trusted local configuration.

## Backup before enabling

1. Stop new dispatch and stop/reconcile existing workers. Record running and
   uncertain attempts; never infer safe retry from a silent process.
2. Activate `.venv`, select the intended root/profile, and use `spark backup
   --output /absolute/path/to/pre-upgrade.zip`. The command backs up the default
   Spark root and its profiles, rather than only the selected profile. Confirm
   that its scope matches the intended installation.
3. Require exit 0 and `Backup complete`. Each `.db` uses SQLite's backup API;
   raw WAL/SHM/journal files are excluded. A database snapshot failure yields an
   incomplete archive and nonzero exit; do not use it as the migration backup.
4. Treat the archive as sensitive: it includes configuration and credentials.
   Restore into a disposable directory first. Check SQLite `integrity_check`,
   known conversations/messages, tasks, skills and configuration. A backup can
   preserve files while a browser draft remains in browser storage; verify that
   storage separately before switching origins or clearing it.

SQLite snapshots are consistent per database; there is no cross-database
transaction across `state.db` and `kanban.db`. Quiescing workers prevents their
independent snapshots from racing task completion. Quick state snapshots are
not substitutes for this full pre-upgrade backup.

## Isolated enablement and evidence

Create a temporary home outside user state, seed synthetic conversations/tasks,
and set the flags in that home's `config.yaml`. Use a fresh process and fresh
conversation after configuration changes. Never inject replacement tool schemas
into an active cached conversation.

Record source SHA, Python/Node/platform versions, schema/config versions, flags,
server URL, and hashes of served `web_dist` assets. Run two children in both
completion orders while switching three chats; interrupt one, stop the parent,
refresh/reconnect, and verify drafts, transcript ownership and pending decisions.
Repeat with async disabled. Production-built assets need their own served test;
a development server or successful bundle build is insufficient.

After web acceptance, use the existing desktop build scripts. Record installed
macOS quit/relaunch, sleep/wake, unavailable-backend, Quick Ask and child controls
separately from frozen-backend startup, signing and notarization. Windows checks
require a Windows host and remain pending when one is unavailable.

## Rollback

1. Disable new async/worktree dispatch and gateway task dispatch, then stop the
   affected processes. Preserve completed and uncertain attempts and useful
   worktrees. Restart old Kanban workers only after an ownership audit: old
   binaries do not gain new fencing retroactively.
2. Use an app version verified to read the current schema. Do not decrement
   `schema_version`, drop additive tables, or clear receipts to make an old
   version start. An old binary's successful startup alone is not compatibility
   proof.
3. If restoring a pre-upgrade backup is necessary, first take a consistent
   snapshot of current state and enumerate post-backup work that restoration
   would lose. Restore only with explicit authorization for that loss. Do not
   overlay raw database sidecars on restored snapshots.
4. Validate conversations, tasks, skills, drafts and profiles again. Record the
   exact rollback source/assets/schema and unresolved uncertain work.

## Evidence recorded so far

- [Actual old-source rehearsal](../performance/app-upgrade-rollout-rehearsal-2026-10-15.md)
  creates schema 12 with `0ed3654b`, upgrades twice, verifies old datastore
  read/write on schema 15, and restores both consistent archives using production
  import into disposable roots. It records the exact post-backup loss inventory.
- `tests/core/test_child_lifecycle.py` reconstructs schema 12, upgrades twice and
  verifies legacy child records/events survive.
- `tests/spark_cli/test_backup.py` restores committed live-profile WAL data and
  unchanged config/skills/file drafts without raw sidecars; corrupt databases
  produce nonzero incomplete backups. This is synthetic file-draft evidence,
  not browser local-storage evidence.
- Combined backup/lifecycle check on 2026-10-15: **78 passed**. No real user
  profile was migrated or restored. Installed-package, staging and production
  acceptance remain open in PLAN.md.
