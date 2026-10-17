# P10 disposable local rollout and rollback — 2026-10-17

Functional acceptance ran on source `99be7b43e1de8caf7c7f90e48f67c241ce0396bd`,
macOS arm64, Python 3.11.7. No provider, external messaging, user profile,
installed app, external staging or production was used. No timing claim is made.

## Reproduction and results

From this checkout (use a new output directory on each run):

```sh
source /Users/joe/Developer/github/spark/.venv/bin/activate
export PYTHONPATH="$PWD/src"
python tests/fixtures/app_upgrade/isolated_rollout_rehearsal.py --output /tmp/spark-p10-new-local
python tests/fixtures/app_upgrade/rollout_rehearsal.py --output /tmp/spark-p10-new-oldstore
python -m pytest tests/run_agent/test_async_delegation.py tests/core/test_child_lifecycle.py tests/spark_cli/test_backup.py -m 'not integration and not network' -q -n 0
```

Both drivers exited 0. Focused suite: **99 passed in 4.84s** (test-run output,
not performance acceptance). The new driver reuses the existing replay fixture
and worktree acceptance function; it replaces the SDK transport/system/tool
setup, not dispatch, workers, callbacks, Git worktrees or SQLite lifecycle.
The actual delegation config loader reads the disposable profile config.

[Local-instance machine evidence](app-upgrade-isolated-rollout-2026-10-17.json)
records exact source, URLs, asset SHA-256 values, handles and states. In order:

1. Enabled `delegation.async_enabled` and `delegation.worktree_isolation` in a
   new temporary profile, config 29/schema 15. Dispatched a real child through
   the synthetic SDK boundary and waited for completion and worker cleanup.
2. Reused the real two-child async worktree flow: children start at committed
   content in distinct checkouts, relative file writes stay in each child,
   parent dirty content survives, and useful child changes remain after drain.
3. Started a disposable loopback Uvicorn app with both flags enabled. HTTP `/`
   and all three referenced hashed JS/CSS assets returned 200 and byte-matched
   tracked `web_dist`; `/api/status` reported the exact temporary home. Stopped
   the server cleanly. This is the requested **local staging/test instance**.
4. A separate process dispatched another real worker, waited until it entered
   the synthetic SDK call, recorded its durable handle, then exited with
   `os._exit`. No simulated PID-liveness patch was used.
5. Disabled both flags. Reopened SQLite: reconciliation changed exactly one
   lost attempt to `uncertain`, then zero on repeat. The completed attempt
   remained completed. A current schema-compatible source read/write probe
   survived reopen; schema stayed 15. No table/receipt was removed.
6. A fresh process read the disabled config and rejected new async dispatch
   with an error, zero SDK calls and no additional attempts. This fresh-process
   boundary matters because the CLI retains its loaded runtime configuration.
7. Restarted the local source app with flags off, fetched and verified the same
   served assets and home again, then stopped it cleanly. Completed and uncertain
   attempts survived without re-execution. Final inventory: three completed
   attempts (including the two worktree children), one uncertain attempt.

## Backup rollback and compatibility boundary

[Fresh old-source machine evidence](app-upgrade-oldstore-rollback-2026-10-17.json)
repeats the existing actual `0ed3654b` schema-12 datastore creation, live-WAL
consistent backup, additive migration to 15, repeat migration/open, old datastore
read/write on 15, and production backup/import into separate disposable profiles.
Both archives pass integrity checks and exclude raw WAL/SHM/journal sidecars.

Restoring the earlier archive was tested only in a separate disposable root.
It loses exactly the later user message, old-datastore assistant message,
post-backup command receipt and sidebar pin listed in that report. The original
current archive remains available. This old-source check proves datastore module
compatibility, **not full old-app/native runtime compatibility**. The local app
rollback uses the current source known compatible with schema 15, flags disabled;
there is no claim that a complete earlier app binary was exercised.

## Remaining release gates

The separate browser agent owns multi-chat/reconnect/decision/browser-draft
acceptance. Controlled performance capture requires its own exclusive window.
Installed macOS native quit/relaunch, real sleep/wake, unavailable-backend,
Quick Ask and child controls remain separate gates. This environment is macOS;
no genuine Windows runtime was available or tested. External staging,
production rollout, signing, publishing and release remain unperformed.
PLAN and issue acceptance updates belong to the parent; this evidence closes
only this bounded local functional rehearsal, not all P10 or the full PLAN.
