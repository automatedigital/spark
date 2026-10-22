# I08 result

Implemented and pushed. PR: https://github.com/automatedigital/spark/pull/166 (main; closes #152). Registered with T3 link_pull_request successfully. No merge, release, watch or check polling performed; remote review/check outcome not inspected.

Head: 4e8828a6ed220ed3d098030f3773ea2a27335970
Base: 64af0d26976714b747dd4f1cc5b495c47c7f7567
Branch: fix/memory-sqlite-lock-recovery
Worktree: /Users/joe/.t3/worktrees/spark/t3-a020bce6
Local and remote head match; working tree clean.

Only owned files changed:
- src/plugins/memory/holographic/store.py
- tests/plugins/memory/test_holographic_recovery.py

Recovery now requires SQLite CORRUPT or NOTADB primary codes, including extended codes masked with 0xFF. Non-corruption DatabaseErrors and errors without codes close the failed connection and propagate. No healthy database/sidecar rename or removal. Production timeout and garbage-file quarantine recovery unchanged.

Real SQLite test uses two connections, DELETE journal mode, BEGIN EXCLUSIVE and a 50 ms connection timeout. Initialization raises SQLITE_BUSY without changing DB bytes or quarantining; after rollback/release, reopening returns the original fact ID/content. Negative injected cases: BUSY, BUSY_SNAPSHOT, LOCKED, LOCKED_SHAREDCACHE, IOERR, IOERR_READ, READONLY, FULL, ERROR and missing code. These preserve database and synthetic WAL/SHM bytes, propagate the exact error and close the failed connection. Positive cases retain real garbage-file recovery and injected CORRUPT/CORRUPT_VTAB recovery.

Environment for every pytest command:
```sh
source /Users/joe/Developer/github/spark/.venv/bin/activate
export PYTHONPATH="$PWD/src"
export SPARK_HOME="$(mktemp -d /tmp/spark-I08-home.XXXXXX)"
```
All profiles/data synthetic; no external-provider calls.

Exact checks and exits:
1. New recovery tests against original base store (temporarily restored only the owned store file, then restored fixed file via shell EXIT trap):
   `python -m pytest tests/plugins/memory/test_holographic_recovery.py -m 'not integration and not network' -q -n 0`
   Exit 1; 11 failed, 5 passed in 0.80s. Real lock and all ten negative codes fail. Log: /tmp/I08-before.log.
2. Final focused:
   `python -m pytest tests/plugins/memory/test_holographic_recovery.py -m 'not integration and not network' -q -n 0`
   Exit 0; 16 passed in 2.96s.
3. Focused plus neighbors:
   `python -m pytest tests/plugins/memory/test_holographic_recovery.py tests/plugins/memory/test_holographic_dedup.py tests/plugins/memory/test_holographic_auto_extract.py -m 'not integration and not network' -q -n 0`
   Exit 0; 25 passed in 2.04s. Log: /tmp/I08-after.log.
4. `ruff check src/plugins/memory/holographic/store.py tests/plugins/memory/test_holographic_recovery.py`
   Exit 0; all checks passed.
5. `ruff check src/`
   Exit 1; 299 errors, pre-existing baseline debt. Ran same check with original base store; `cmp /tmp/I08-ruff-baseline.log /tmp/I08-ruff-src.log` exit 0 (identical entire output). Logs retained at those paths. No new lint errors.
6. `git diff --check` before commit and `git diff HEAD^ HEAD --check` after commit: exit 0.
7. Commit and push: exit 0; remote SHA confirmed with `git ls-remote origin refs/heads/fix/memory-sqlite-lock-recovery`.

During test development, first run had 10 failures from scanning an autouse-fixture directory as a file; narrowed snapshots to memory_store.db* before before/after verification. This was a corrected test setup issue, not baseline debt.

Limitations: no full-suite, browser, installed-package or external-provider validation claimed. Real contention tested locally with SQLite; other failure codes are injected at initialization. No retry policy added; lock errors propagate to existing callers. No unrelated paths, PLAN.md, manifests, lockfiles or web_dist edited; no delegation.
