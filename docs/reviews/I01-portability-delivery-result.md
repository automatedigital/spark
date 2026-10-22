# I01 portability recovery — published, draft acceptance remains

- Existing PR: https://github.com/automatedigital/spark/pull/155 (open, draft; T3 linked; watching=false).
- Issue: https://github.com/automatedigital/spark/issues/145; evidence comment submitted with gh.
- Exact published head: `8987f857f2dd2ce1da96a4f04de7e738402faaf7`.
- Original implementation head preserved: `4ab637f8087e683a0c5ce9afcc2db2ac4ffb33b0`.
- Commit: `fix: support contained uploads on Windows and linked roots`.
- Push: `git push origin HEAD:refs/heads/fix/upload-symlink-containment`, exit 0, normal fast-forward. `git ls-remote` and `gh pr view` independently report the exact published SHA above.
- Original stopped worktree: `/Users/joe/.t3/worktrees/spark/t3-944843b3`, actual branch `fix/upload-containment-portability-review`, HEAD `4ab637f8087e683a0c5ce9afcc2db2ac4ffb33b0`, two tracked dirty files, no relevant nonignored untracked files. Left untouched.
- New isolated checkout: `/Users/joe/.t3/worktrees/spark/t3-0249df39`, bound branch `fix/upload-containment-resume`.
- Recovery: clean new baseline `64af0d26976714b747dd4f1cc5b495c47c7f7567` fast-forwarded to stopped HEAD with `git merge --ff-only`; applied stopped checkout's `git diff HEAD --binary` as `/tmp/I01-recovery.patch`. No venv/node_modules/build artifacts copied.
- Owned files only: `src/spark_cli/workspace_routes.py`, `tests/spark_cli/test_workspace_upload_safety.py`. Checkout clean after commit.

## Behavior

Removed blanket Windows HTTP 501. Windows now uses CreateFileW OPEN_REPARSE_POINT with attribute/tag inspection before truncation; directory handles retain all canonical ancestors without write/delete sharing until upload completes. Final handles transfer ownership to a CRT descriptor for regular-file checking and writing. Unsafe/malformed/incompatible targets return 400. POSIX retains descriptor-relative O_NOFOLLOW final writes and directory walks. Actual resolved project/workspace roots define the boundary, allowing intentional linked project/profile roots while rejecting links below them. Ordinary/nested uploads and existing regular-file replacement remain. W06 naming behavior is unchanged.

Microsoft API reference checked for handle/share/reparse semantics: https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew . This source review is not Windows runtime evidence.

## Exact checks and exits

Python and Ruff runs activated `/Users/joe/Developer/github/spark/.venv/bin/activate`; `PYTHONPATH="$PWD/src"` selects the new checkout. Test fixtures isolate SPARK_HOME/CODEX_HOME plus HOME/USERPROFILE, and the browser server used disposable equivalents. No live profile/providers.

1. `python -m pytest tests/spark_cli/test_workspace_upload_safety.py -q -n 0 -m 'not integration'`: exit 0, **30 passed, 11 skipped**, 27.39s. `/tmp/I01-portability-focused.log`.
2. `python -m pytest tests/spark_cli/test_workspace_upload_safety.py tests/spark_cli/test_workspace_file_ops.py tests/spark_cli/test_workspace_git.py tests/test_project_metadata.py tests/test_project_templates.py -q -n 0 -m 'not integration'`: exit 0, **74 passed, 11 skipped**, 90.72s. `/tmp/I01-portability-tests.log`.
3. `ruff check src/spark_cli/workspace_routes.py tests/spark_cli/test_workspace_upload_safety.py`: exit 0, all checks passed.
4. `ruff check src/`: exit 1, **299 baseline errors**. `/tmp/I01-portability-ruff.log`; diagnostic-code/message Counter comparison against existing `/tmp/I01-ruff-baseline.log`: exit 0, identical diagnostic message counts.
5. `git diff --check`: exit 0.
6. T3 browser fixture on `http://127.0.0.1:18645`, `/tmp/I01-browser-server.py`, disposable `/tmp/I01-resume-home.aOQmKu`:
   - Browser FormData nested project normal upload: 200, saved entry.
   - Global normal upload: 200, correct absolute_path/saved entry.
   - Project/global final external symlink: 400, no saved entry.
   - Project destination-directory symlink: 400, no saved entry.
   - Independent Python filesystem assertions: exit 0, both normal files have `resume-browser-bytes`; outside sentinel remains `original`.
   - Initial browser open preceded server readiness and returned chrome-error; after server startup, corrected navigation succeeded. Snapshot failed with `Preview automation snapshot timed out after 15000ms.` Browser evaluate/fetch succeeded. Server stopped after validation.
7. Commit, push, PR body update, and remote SHA verification: exit 0. No force push or second PR.

Tests preserve internal/external/dangling symlink attacks, nested link rejection before directory creation, directory/read/final-open swaps, traversal, and ordinary replacement. Added linked-root success with nested-escape rejection, linked profile success, native Windows handle/junction/path/stream cases, directory target protection, and POSIX FIFO protection.

## Limitations / acceptance still needed

- **Native Windows runtime proof missing.** Eleven Windows-only tests skipped on macOS. Implementation is present; this is not a claim of completed Windows acceptance. Existing python-quality is Ubuntu-only. Existing Windows beta workflow runs worktree locking and packaged lifecycle tests, not this upload module; dispatch would not prove uploads. No workflow/dependency changes made within owned scope.
- Windows incompatible write/delete handles can cause a 400 upload rejection; pinning is deliberately conservative. This is temporary contention behavior, not a blanket unsupported-platform failure.
- POSIX pins directory identity through renames; writes remain in the originally opened inode rather than a substituted symlink. Hostile inode relocation outside the boundary and hard-link attacks remain outside the symlink guarantee. Intentional root links establish the actual resolved boundary at request entry.
- Browser smoke exercised the real multipart routes from a fixture page, not the shipped Chat/Files UI. No screenshot, full UI, long-chat/gateway/provider/package/full-suite claims.
- Draft stays pending lead acceptance and native Windows proof. No merge/release/deployment, dependency writes, generated bundles, extra agents, or PR watch/poll.

## Additional recovery verification — t3-aef52cec

The requested recovery was already published when this worker inspected GitHub. No duplicate implementation commit was needed. Remote and PR head were independently verified as `8987f857f2dd2ce1da96a4f04de7e738402faaf7`.

- This worker's isolated checkout: `/Users/joe/.t3/worktrees/spark/t3-aef52cec`; renamed branch `fix/upload-containment-portability-review-resume`.
- Fast-forwarded baseline to stopped HEAD `4ab637f8087e683a0c5ce9afcc2db2ac4ffb33b0`, applied its binary dirty diff, then discovered the existing published recovery. Reversed only that locally applied patch and fast-forwarded to published HEAD, which contains all recovered changes plus error mapping and additional regressions. No original-checkout mutation; its two dirty files remain. Current checkout is clean.
- Re-ran `python -m pytest tests/spark_cli/test_workspace_upload_safety.py tests/spark_cli/test_workspace_file_ops.py tests/spark_cli/test_workspace_git.py tests/test_project_metadata.py tests/test_project_templates.py -q -n 0 -m 'not integration'`: exit 0, **74 passed, 11 skipped in 19.70s**. Log `/tmp/I01-reverify-tests.log`. Activated `/Users/joe/Developer/github/spark/.venv`; checkout `PYTHONPATH`; disposable HOME/USERPROFILE/SPARK_HOME/CODEX_HOME.
- CLI TestClient fixture exercised real multipart upload endpoints, including normal/nested uploads, replacement, linked roots, rejected final/directory links and deterministic swaps. Browser evidence above belongs to the prior published recovery; browser was not repeated by this worker.
- Scoped Ruff: exit 0. Full `ruff check src/`: exit 1, 299 errors (`/tmp/I01-reverify-ruff.log`). `git diff --check`: exit 0.
- `git push origin HEAD:refs/heads/fix/upload-symlink-containment`: exit 0, Everything up-to-date. `git ls-remote` and `gh pr view 155` confirm exact SHA. Existing PR remains draft. T3 link/list confirms linked, watching=false.
- Native Windows runtime proof is still missing; no applicable existing Windows upload CI job is available. All prior limitations and draft acceptance gates above remain. No merge, deployment, extra agent, or PR monitoring.
