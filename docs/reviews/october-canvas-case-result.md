# Canvas case-alias P1 repair

Ready for cherry-pick: `5cc70f4841017511c43831c756413589253795bf`

- Base: `16d9d8d9a398fe46361a5bf5aa46cf056aea9732`.
- Isolated checkout: `/tmp/spark-canvas-case-fix-20261022`.
- Branch: `fix/canvas-case-alias-lock`.
- Commit: `fix: share canvas locks across filesystem case aliases`.
- Exactly two committed files: `src/spark_cli/canvas_routes.py` and `tests/spark_cli/test_canvas_concurrency.py`.
- Did not edit `/tmp/spark-review-release-20261022` or the root checkout/handoff. No PR, push, merge, release or bundle regeneration. Lead-owned full runtime was not duplicated.

## Correction and evidence

Lock keys now hash owning directory `st_dev:st_ino` plus the case-folded ASCII canvas filename. Owner case, Unicode-normalization and symlink aliases therefore share identity without relying on path spelling. Keys exist before canvas creation and stay unchanged across atomic replacement, deletion and recreation. No canvas inode key, runtime case probe or additional persistent registry was introduced. Locks remain outside project trees in profile metadata, and the final-symlink/lexical destination protections from `3a3e2005` remain unchanged.

On case-sensitive filesystems, distinct case-spelled canvases conservatively share a lock, but reads, revisions, writes and deletion retain their distinct lexical data paths. The regression exercised both independent writes and deletion of just one file on a real case-sensitive APFS volume.

The real-filesystem contention regression runs for global and project scopes. It verifies the aliases address the same inode, pauses the real first writer before atomic replace while holding its real lock, starts the second writer, then releases and requires exactly the first success and second HTTP 409 with the winning revision. Only these two case-alias tests skip when the filesystem is actually case-sensitive. Portable filename lifecycle and owner alias identity tests run in both modes.

## Exact commands and exits

All Python/lint/type commands below ran from `/tmp/spark-canvas-case-fix-20261022`, after:

```sh
source /Users/joe/Developer/github/spark/.venv/bin/activate
export PYTHONPATH=/tmp/spark-canvas-case-fix-20261022/src
```

The unchanged pinned probe ran before the edit with:

```sh
mkdir -p /tmp/spark-canvas-case-evidence-20261022/before-home /tmp/spark-canvas-case-evidence-20261022/before-profile
export HOME=/tmp/spark-canvas-case-evidence-20261022/before-home USERPROFILE=/tmp/spark-canvas-case-evidence-20261022/before-home SPARK_HOME=/tmp/spark-canvas-case-evidence-20261022/before-profile
python /tmp/spark-merge-review-20261022/storage-r2-case-probe.py > /tmp/spark-canvas-case-evidence-20261022/probe-before.log 2>&1
```

Exit **1**: reproduced `same_data_inode: true`, different lock keys, two successful same-revision saves, final name A, safety assertion failure.

After the edit, the unchanged pinned probe and remaining checks used:

```sh
mkdir -p /tmp/spark-canvas-case-evidence-20261022/after-home /tmp/spark-canvas-case-evidence-20261022/after-profile
export HOME=/tmp/spark-canvas-case-evidence-20261022/after-home USERPROFILE=/tmp/spark-canvas-case-evidence-20261022/after-home SPARK_HOME=/tmp/spark-canvas-case-evidence-20261022/after-profile
python /tmp/spark-merge-review-20261022/storage-r2-case-probe.py > /tmp/spark-canvas-case-evidence-20261022/probe-after.log 2>&1
```

Exit **1**, with a different cause: the probe synchronously waits for writer B while writer A holds the now-shared lock, and only releases A after B returns. Its ten-second `release.wait(10)` assertion expires, causing A to return HTTP 500. This pinned probe is not a passing post-fix gate: its release schedule cannot handle correct mutual exclusion. It was run unchanged as requested; the committed regression supplies the corrected two-worker/event schedule and requires one success/one 409 without replacing real persistence or locking.

```sh
python -m pytest tests/spark_cli/test_canvas*.py -q -n 0 -m 'not integration and not network' > /tmp/spark-canvas-case-evidence-20261022/canvas-tests.log 2>&1
```

Exit **0**, 36 passed in 2.78s.

```sh
python -m pytest tests/spark_cli/test_canvas_routes.py tests/spark_cli/test_canvas_concurrency.py tests/tools/test_canvas_tool.py -q -n 0 -m 'not integration and not network' > /tmp/spark-canvas-case-evidence-20261022/canvas-all-tests.log 2>&1
```

Exit **0**, 43 passed in 3.35s on host case-insensitive APFS, including both real case-alias contention cases and prior final-symlink/project-sidecar process regressions.

Temporary case-sensitive test volume setup (all exit **0**):

```sh
hdiutil create -size 128m -type SPARSE -fs 'Case-sensitive APFS' -volname SparkCanvasCaseTest /tmp/spark-canvas-case-evidence-20261022/case-sensitive
mkdir -p /tmp/spark-canvas-case-evidence-20261022/case-volume
hdiutil attach /tmp/spark-canvas-case-evidence-20261022/case-sensitive.sparseimage -mountpoint /tmp/spark-canvas-case-evidence-20261022/case-volume -nobrowse
python -m pytest tests/spark_cli/test_canvas_routes.py tests/spark_cli/test_canvas_concurrency.py tests/tools/test_canvas_tool.py -q -n 0 -m 'not integration and not network' --basetemp=/tmp/spark-canvas-case-evidence-20261022/case-volume/pytest -rs > /tmp/spark-canvas-case-evidence-20261022/canvas-case-sensitive-tests.log 2>&1
hdiutil detach /tmp/spark-canvas-case-evidence-20261022/case-volume
```

Pytest exit **0**, 41 passed, 2 skipped in 3.31s. Exactly the two actual same-inode case-alias cases skipped; case-distinct independent data test ran. Image is detached. Setup/attach/detach logs are in the evidence directory; hdiutil printed command deprecation warnings only.

```sh
ruff check src/spark_cli/canvas_routes.py tests/spark_cli/test_canvas_concurrency.py > /tmp/spark-canvas-case-evidence-20261022/ruff.log 2>&1
mypy --follow-imports=silent src/spark_cli/canvas_routes.py > /tmp/spark-canvas-case-evidence-20261022/mypy.log 2>&1
git diff --check
git merge-base --is-ancestor 3a3e2005 HEAD
git add src/spark_cli/canvas_routes.py tests/spark_cli/test_canvas_concurrency.py
git commit -m "fix: share canvas locks across filesystem case aliases"
git status --short
```

Each exit **0**. Ruff: all checks passed. Scoped mypy: no issues in one source file. Commit created successfully; worktree clean.

## Limits

- Real macOS case-insensitive and case-sensitive APFS tested. Native Windows and Linux not executed here; scoped mypy follows imports silently and is not a full repository typecheck.
- Directory identity assumes the owner directory itself remains the same object. Hostile ancestor replacement remains outside this narrow repair, as before. Other filesystem writers do not participate in canvas CAS.
- Stop old servers using prior path-derived or legacy sidecar locks before adoption: mixed versions have different lock namespaces.
- No browser, full runtime, production bundle, package, signing, deployment or release claim. These remain lead-owned gates.
- No relevant memory guidance was found or used in implementing this correction.
