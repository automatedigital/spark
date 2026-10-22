# Integrated upload composition result

Commit: `a38698ec889d373354543e35b62aabb38fe6f414`
Branch: `fix/integrated-upload-identity`
Worktree: `/Users/joe/.t3/worktrees/spark/t3-849079db`
Parent/base: `f3a71c2ef34196feafb62bef8e03fdb4baca98a2`

The fresh checkout was already on the requested branch, clean at b3e4ea3a. `git merge --ff-only f3a71c2ef34196feafb62bef8e03fdb4baca98a2` exited 0. Read AGENTS.md, CONTEXT.md, STRUCTURE.md, accepted ADRs 0001/0012/0013, the W05/W06 audit, and I01/I02 review reports. No lead-checkout edits, delegation, PR creation, push, release, or monitoring.

## Scoped change

Only these three files are committed (218 insertions, 32 deletions):

- `src/spark_cli/workspace_routes.py`
- `tests/spark_cli/test_workspace_upload_identity.py`
- `tests/spark_cli/test_workspace_upload_safety.py`

I01's root resolution, descriptor-relative POSIX directory walk, no-follow final writer and Windows pinned ancestor handles remain the foundation. The typed generic writer accepts `int | Path`. POSIX final creation now uses O_CREAT|O_EXCL|O_NOFOLLOW against the pinned dir_fd. Windows final creation uses CreateFileW CREATE_NEW (1), OPEN_REPARSE_POINT and existing ancestor pinning. Windows error codes 80/183 become FileExistsError for allocation retry; collision inspection opens existing entries read-attributes-only without reparse traversal, allowing a concurrent creator to finish its own write.

Bounded collision allocation retries only existing regular files, with UUID-suffixed candidate names. Existing symlinks, reparse points, directories and special files remain rejected, including generated candidates. No attachment overwrite, pathname write fallback, or truncation occurs. Exhaustion is HTTP 409. Both routes retain the display filename and return actual allocated relative/absolute storage paths using canonical root spelling. POSIX checks directory inode identity before creation and after writing, rejecting detected directory swaps rather than returning a redirected saved path. Explicit existing project PUT replacement is tested; multipart upload defaults never replace.

Regression coverage includes sequential/batch duplicates, six concurrent same-name requests for both scopes, forced regular collisions, bounded exhaustion, aliased roots, pre-existing symlinks, read-boundary and final-open swaps, generated-candidate symlink swaps, collision plus directory swaps, and a real final-syscall directory swap proving writes stay on the pinned inode. Every original containment/sentinel assertion remains meaningful. Default-overwrite assertions were changed to verify unique storage and retained original bytes. Existing Windows swap wrapper was adapted to the CREATE_NEW helper argument.

## Environment and exact checks

All Python/test/type commands activated `/Users/joe/Developer/github/spark/.venv/bin/activate` because this checkout has no `.venv`. `PYTHONPATH="$PWD/src"` selected this checkout. Runtime commands exported a disposable HOME first, then USERPROFILE="$HOME", SPARK_HOME="$HOME/profile", CODEX_HOME="$HOME/codex" before imports. No live profile/providers used.

Logs below are in `/tmp/spark-merge-review-20261022/`.

1. Before edits: `python -m pytest tests/spark_cli/test_workspace_upload_identity.py tests/spark_cli/test_workspace_upload_safety.py -q -n 0 -m 'not integration and not network'`: **exit 1**, 7 identity failures, 30 safety passes, 11 Windows skips (31.90s). `upload-before.log`.
2. Initial composition, before extra regressions: same command, **exit 0**, 37 passed, 11 skipped (32.25s). `upload-after.log`.
3. Broader final-neighbor run: `python -m pytest tests/spark_cli/test_workspace_upload_identity.py tests/spark_cli/test_workspace_upload_safety.py tests/spark_cli/test_workspace_file_ops.py tests/spark_cli/test_workspace_git.py tests/test_project_metadata.py tests/test_project_templates.py -q -n 0 -m 'not integration and not network'`: **exit 0**, 114 passed, 11 skipped (70.12s). `upload-final-tests.log`. This preceded the final two added final-syscall directory-swap cases.
4. Added final-syscall cases: `python -m pytest tests/spark_cli/test_workspace_upload_safety.py -q -n 0 -m 'not integration and not network' -k 'collision_retry_directory_swap'`: **exit 0**, 2 passed, 47 deselected (1.80s). `upload-pinned-test.log`.
5. Final committed focused suites: command from (1), **exit 0**, 47 passed, 11 skipped (21.09s). `upload-final-focused.log`.
6. `ruff check src/spark_cli/workspace_routes.py tests/spark_cli/test_workspace_upload_identity.py tests/spark_cli/test_workspace_upload_safety.py`: **exit 0**. `git diff --check`: **exit 0**. Base workspace_routes.py checked via `ruff check --stdin-filename src/spark_cli/workspace_routes.py - < upload-base-routes.py`: **exit 0**.
7. CI static lint gate: `ruff check src/ --select UP015,F,B,I,W,UP028,UP031,UP035,UP037,UP042 --ignore B027`: **exit 0**. `upload-ruff-portable.log`.
8. Full `ruff check src/`: **exit 1**, 298 unrelated baseline diagnostics. `upload-ruff-all.log`. Both base and edited route pass; other src files untouched.
9. `mypy src/agent/ src/spark_cli/`: **exit 0**, no issues in 137 source files. `upload-mypy.log`.
10. `mypy --platform win32 --cache-dir /tmp/spark-merge-review-20261022/mypy-win src/agent/ src/spark_cli/`: **exit 1**, 40 existing errors in 8 files. Same command with `--shadow-file src/spark_cli/workspace_routes.py /tmp/spark-merge-review-20261022/upload-base-routes.py`: **exit 1**, same 40 errors. Normalized file/message Counter comparison: **exit 0**, identical, none in upload helpers. `upload-mypy-win.log`, `upload-mypy-win-base.log`, `upload-win-comparison.log`.
11. Git scoped add/commit, `git rev-parse HEAD`, and final clean `git status --porcelain`: **exit 0**.

Intermediate lint caught an exception-chain omission and test import ordering; both corrected. An intermediate broadened test run collected an accidental test edit that was corrected before the final run; it was terminated rather than used as acceptance evidence (`upload-tests.log`, exit 143). An initial Windows comparison assertion incorrectly excluded all workspace_routes errors, including existing PTY errors outside uploads; corrected range-specific comparison above passes.

## Limits

Native Windows runtime remains unverified: 11 Windows-only cases skip on macOS. Static Windows comparison is not runtime proof. Final focused tests exercise real multipart FastAPI routes via TestClient; no new browser, full shipped Chat/Files UI, gateway, provider, package, full pytest or release claim. Existing I02 frontend/draft mapping was left intact and not revalidated here. No generated bundle, manifest, lockfile, PLAN or other source changes.

POSIX descriptor pinning prevents symlink redirection; it cannot prevent an actor from relocating an already-open inode outside the original tree, or modifying files after upload completion. Detected directory changes reject the response and may leave the safely created new file in the pinned directory; no unsafe pathname cleanup is attempted. Windows incompatible handle contention can still reject a request rather than weakening ancestor pinning. OS/write failures may leave a partial newly-created file; previous attachments remain untouched.

Final Linux-target portable type gate: `mypy --platform linux src/agent/ src/spark_cli/`: **exit 0**, no issues in 137 source files. `upload-mypy-linux.log`. Final `git status --porcelain` remains empty at the exact commit above.
