# Canvas path / lock boundary fix

Commit: `558ddbae69c656d327196e7dd057fbf17da0081c`
Branch: `fix/canvas-path-lock-boundaries`
Worktree: `/Users/joe/.t3/worktrees/spark/t3-b0a94deb`
Base: fast-forwarded with `git merge --ff-only a9bb2a7` to `a9bb2a7b` before edits.
Only committed paths:
- `src/spark_cli/canvas_routes.py`
- `tests/spark_cli/test_canvas_concurrency.py`

No lead candidate checkout edits, extra agents, PR, push, merge of the fix, or release.
Working tree clean after scoped commit. Ready for lead cherry-pick.

## Implementation

Canvas identity is the resolved owning directory plus the lexical canvas filename.
Actual project-root symlinks and aliases remain supported. The final canvas filename
is never resolved into a symlink target. Final symlinks (including dangling links)
and nonregular files are rejected with HTTP 400; unsafe entries are omitted from
listing. Reads use O_NOFOLLOW where available and verify fstat/lstat identities
before reading bytes on all platforms. Read revisions come from the opened file.
Writes recheck inside the lock and before replacement, then atomically replace the
lexical destination. Deletes unlink the lexical destination.

Stable lock files now live at `<SPARK_HOME>/canvas-locks/<sha256>.lock`, keyed by
canonical owner + lexical filename, with filesystem case normalization. Project
aliases share identity, separate canvases remain independent, and locks are never
removed during save/delete/error cleanup. Old project sidecars are deliberately
left alone; deleting/reverting one cannot affect the new metadata lock inode.
Temporary files still have unique names and conservative per-request cleanup.

## Evidence

- Final focused route/concurrency/tool suite: **38 passed**.
- Canvas plus workspace Git/file/upload-safety neighbors: **115 passed, 11 skipped**.
- Including upload-identity neighbors: **115 passed, 11 skipped, 7 failed**.
  All seven failures independently reproduce using archived `a9bb2a7` source with
  the same upload-identity tests (**7 failed**): missing `_save_new_upload`, filename
  collisions, and missing response `path`. No upload files changed here.
- Standard `mypy src/agent/ src/spark_cli/`: **success, 137 source files**.
- Scoped Ruff on both owned files: **passed**.
- Full `ruff check src/`: **298 existing findings**. Baseline/candidate scans using
  matching configuration roots both yield exactly the same 298 findings, with
  **0 added / 0 removed**.
- `git diff --check`: **passed**.

Tests use actual FastAPI routes, filesystem operations, flock/msvcrt code paths,
threads, and spawned processes. Regression coverage proves:
- Global/project GET, PUT, DELETE reject existing and dangling final symlinks;
  listing excludes them, and outside sentinel bytes remain unchanged.
- A link inserted while waiting for the lock is rejected for read/save/delete.
- A link inserted at os.open cannot leak sentinel content, including simulated
  absence of O_NOFOLLOW (identity-check fallback).
- A link inserted during serialization rejects the write and cleans its temp file.
- A link inserted immediately at Path.replace cannot redirect the atomic save:
  the lexical link is replaced while outside sentinel bytes remain unchanged.
- A real spawned writer through a second project alias stays blocked while the
  canonical lock is held, even after actual Git Revert removes a legacy project
  sidecar and another sidecar is created/deleted. Metadata inode stays unchanged;
  another canvas can save independently. Contender completes after release.
- Same-revision writers yield exactly one winner (threads in both scopes and
  spawned processes); delete waits for save; stale saves cannot recreate deleted
  canvases; explicit recreation remains supported.

## Reproduction and logs

Activate `/Users/joe/Developer/github/spark/.venv/bin/activate` (this new worktree
has no local `.venv`). Set `PYTHONPATH="$PWD/src"`, synthetic
`HOME=/tmp/spark-canvas-boundaries-home`, and
`SPARK_HOME=/tmp/spark-canvas-boundaries-home/profile` for checks.

Focused command:
`python -m pytest tests/spark_cli/test_canvas_concurrency.py tests/spark_cli/test_canvas_routes.py tests/tools/test_canvas_tool.py -q -n 0 -m 'not integration and not network'`

Neighbor command adds `tests/spark_cli/test_workspace_git.py`,
`tests/spark_cli/test_workspace_file_ops.py`, and
`tests/spark_cli/test_workspace_upload_safety.py` to the focused selection.
The broader run also adds `tests/spark_cli/test_workspace_upload_identity.py`.

Logs in `/tmp/spark-merge-review-20261022/`:
- `canvas-boundaries-final-tests.log` (38 passed)
- `canvas-boundaries-focused.log` (115 passed, 11 skipped)
- `canvas-boundaries-tests.log` (broader run with seven baseline failures)
- `canvas-boundaries-baseline-upload.log` (same seven failures on a9bb2a7 source)
- `canvas-boundaries-mypy.log`
- `canvas-boundaries-ruff.log`
- `canvas-boundaries-ruff-baseline.log`

## Limits / handoff

No browser run: this changes filesystem/API boundaries only; real HTTP tests cover
GET/PUT/DELETE/list behavior. No frontend code or bundle changed. Full Python suite,
installed packages and release were not exercised. Windows locking branch remains
in place but native Windows execution was not available; POSIX fallback read safety
was exercised by disabling O_NOFOLLOW in a test.

Lock coordination is profile-scoped. Stop older server processes when adopting the
new implementation: older code uses project sidecars and cannot coordinate with
the new metadata lock namespace. Arbitrary external writers do not honor API locks;
late final-link swaps are contained by lexical replace/unlink and guarded reads.
This is a focused final-component fix, not directory-descriptor sandboxing against
hostile replacement of entire canonical ancestor directories.
