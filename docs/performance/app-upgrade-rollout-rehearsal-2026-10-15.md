# Disposable migration and rollback rehearsal — 15 October 2026

Passed against current source `60fae7c6`, using the actual SessionDB and Kanban
modules extracted from pre-upgrade commit `0ed3654b`. This establishes datastore
behavior with synthetic state, not installed-app or production compatibility.

Reproduce from the repository root with an unused output directory:

```sh
source .venv/bin/activate
python tests/fixtures/app_upgrade/rollout_rehearsal.py --output /tmp/new-spark-rollout-rehearsal
```

The completed command exited 0. [Evidence JSON](app-upgrade-rollout-rehearsal-2026-10-15.json)
records source identities, archive SHA-256 hashes, members and restore counts.
Raw log: `/tmp/spark-upgrade-20261015/rollout-rehearsal.txt`.

- Actual old code created schema 12, a conversation/message, completed child and
  task in an isolated profile. Production backup captured committed WAL data
  while the old connection remained open, without copying raw database sidecars.
- Current code migrated to schema 15, retained the legacy records and task, and
  opened idempotently again. Config, skills and a synthetic file draft retained
  their original contents. New sidebar metadata and command receipts worked.
- The old datastore module read the additive schema and appended a message
  without decrementing schema 15 or dropping new tables. This is a narrow
  read/write datastore check; no claim is made about a complete old runtime.
- Production backup/import restored both archives into separate disposable
  roots. Alias output alone was redirected to disposable directories, preventing
  writes to the real `~/.local/bin`. SQLite integrity checks passed for state and
  task databases. The older backup restored schema 12 and its one message;
  the newer backup restored schema 15 and all three messages.
- Restoring the older archive omitted the post-backup user message, later
  datastore-writer message, command receipt and sidebar pin, as expected. This
  loss inventory must precede any authorization to restore real user state.

No real user profile, providers, workers or external sends were involved.
The draft fixture is a file, not browser IndexedDB/localStorage. Worker shutdown,
uncertain-attempt/worktree preservation, browser drafts, staging, installed macOS
and Windows behavior still require their respective gates. This rehearsal does
not close P10's combined rollout or platform checklist items.
