# I01 PR155 platform typing repair

- PR: https://github.com/automatedigital/spark/pull/155 (existing draft).
- Exact published head: `6ef55a4ef7ea53924c94ed962f776cd9db582151`.
- Base: `8987f857f2dd2ce1da96a4f04de7e738402faaf7`.
- Isolated T3 checkout: `/Users/joe/.t3/worktrees/spark/t3-c99a918b`, branch `fix/upload-cross-platform-types`. This newly provisioned checkout was already named as requested; initial attempt to create another worktree with that branch failed without mutation. Inspected ownership, then used this clean isolated checkout and `git merge --ff-only` to the requested base (exit 0).
- Only changed file: `src/spark_cli/workspace_routes.py`, 8 insertions / 3 deletions. Commit `fix: guard platform-specific upload types`.

## Change

Use mypy-recognized `sys.platform` guards at Windows handle creation, directory traversal, and final upload writing. Narrow the platform-specific directory value with assertions. Precisely cast the ctypes HANDLE return to int, matching its configured c_void_p restype. No ignore/suppression/config changes. Existing Windows reparse rejection, directory pinning, handle sharing/cleanup and CRT ownership transfer remain; POSIX no-follow writes remain. Upload behavior and containment policy unchanged.

## Verification and exact exits

All Python/mypy/ruff commands activate `/Users/joe/Developer/github/spark/.venv/bin/activate`. Mypy/tests use `PYTHONPATH="$PWD/src"` and disposable HOME/USERPROFILE/SPARK_HOME/CODEX_HOME. No live user state or providers.

1. Before edit: `mypy src/agent/ src/spark_cli/`: **exit 1**, exactly the 10 errors from the supplied completed Ubuntu job log; 133 files. Log `/tmp/I01-types-before.log`.
2. After edit, same standard command: **exit 0**, no issues in 133 files. Log `/tmp/I01-types-after.log`.
3. `mypy --platform linux src/agent/ src/spark_cli/`: **exit 0**, no issues in 133 files. Log `/tmp/I01-types-linux.log`.
4. `mypy --platform win32 --cache-dir /tmp/I01-types-win-cache src/agent/ src/spark_cli/`: **exit 1**, 31 existing diagnostics across 6 files, none in upload helpers. Log `/tmp/I01-types-win.log`. Same command with `--shadow-file src/spark_cli/workspace_routes.py /tmp/I01-types-original-workspace.py` using the exact base file: **exit 1**, 40 diagnostics. Log `/tmp/I01-types-win-before.log`. Diagnostic file/message Counter comparison: **exit 0**, no new Windows-target diagnostics; 9 removed. Remaining errors concern unrelated Unix APIs/type-ignore comments; no suppression introduced.
5. `python -m pytest tests/spark_cli/test_workspace_upload_safety.py tests/spark_cli/test_workspace_file_ops.py tests/spark_cli/test_workspace_git.py tests/test_project_metadata.py tests/test_project_templates.py -q -n 0 -m 'not integration'`: **exit 0**, **74 passed, 11 skipped in 23.01s**. Log `/tmp/I01-types-tests.log`. Existing real multipart route tests cover ordinary/nested/replacement uploads, linked roots, rejected links and controlled swaps.
6. `ruff check src/spark_cli/workspace_routes.py tests/spark_cli/test_workspace_upload_safety.py`: **exit 0**.
7. `ruff check src/`: **exit 1**, 299 baseline diagnostics. Log `/tmp/I01-types-ruff.log`; Counter comparison against `/tmp/I01-ruff-baseline.log`: **exit 0**, identical diagnostic code/message counts.
8. `git diff --check`: **exit 0**.
9. Scoped commit, normal `git push origin HEAD:refs/heads/fix/upload-symlink-containment`, and `git ls-remote`: **exit 0**. Remote head matches the exact SHA above. No force push.

## Open acceptance / boundaries

Native Windows runtime proof remains **unverified**; 11 Windows-only tests skipped on macOS. Windows-target static checking is not Windows runtime evidence. Keep PR draft and original Windows acceptance open. No browser repetition for this typing-only change; previous browser evidence is in I01-portability-result.md. No full-suite, package, installed-platform or hosted-CI-success claim. No PR monitoring/retries, second PR, merge/release, extra agents, package/lockfile/bundle/manifest/PLAN changes.
