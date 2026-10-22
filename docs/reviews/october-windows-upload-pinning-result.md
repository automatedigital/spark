# Windows upload directory pinning handoff

- Commit: `9401af2939600ce512cdf4da544b342e88d02a09`
- Base: `f046bac94bf2939888d45161a805698f504c5e65`
- Branch: `fix/windows-upload-directory-pinning`
- Isolated checkout: `/Users/joe/.t3/worktrees/spark/t3-3dc3c3da`
- Changed only `src/spark_cli/workspace_routes.py` and `tests/spark_cli/test_workspace_upload_safety.py`. Clean git status after commit. No push, PR creation, merge, release, or watchers.

## Repair and evidence

`_windows_upload_handle` now requests `FILE_LIST_DIRECTORY | FILE_READ_ATTRIBUTES` (`0x81`) for directories, retaining `FILE_SHARE_READ` only. New-file and collision-inspection access/share/disposition/flags are unchanged. Canonical intentional root/profile links, per-component no-reparse checks, exclusive CREATE_NEW, collision handling, attachment modes and filename byte budgets are unchanged.

Primary Microsoft sources:

- https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-fsa/8c0e3f4f-0729-49f4-a14d-7f7add593819 — MS-FSA 2.1.5.1.2.2 gates sharing conflicts on data/execute/delete access in both the new and existing open. Attribute-only `0x80` does not participate. Directory bit `0x1` participates; denying delete sharing therefore rejects the DELETE access needed for rename. Denying write sharing rejects a generic-write contender as well.
- https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-smb/d524144c-3cfc-49c3-903c-284e5adbd60a — directory access mask defines FILE_LIST_DIRECTORY as `0x00000001`.
- https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilea — FILE_SHARE_DELETE documents delete access as permitting both rename and delete, with share restrictions lasting until handle closure and across process contexts.

The existing actual-rename tracking remains intact on every platform. The four project/global × collision/noncollision cases now assert the entire outside tree is exactly `{note.txt: original}`, detecting escaped newly generated filenames, while retaining successful-upload bytes in the actual original/pinned directory and the earlier attachment assertion.

New portable ctypes mock checks exact CreateFileW arguments independently for directory, new-file and collision inspection. Before the source repair, against the pinned base with only test edits, it failed specifically on directory desired access (actual 128, expected 129); the other two API cases and four strengthened directory-swap cases passed on macOS. This is an API regression proof, not native enforcement proof.

New native Windows test owns a real directory handle and launches a separate Python process to attempt rename or acquire a generic-write directory handle. It requires ERROR_SHARING_VIOLATION (32) while pinned and success for the same operation after CloseHandle. The rename case verifies the directory actually moved after release. These tests are not skipped on Windows; they were skipped on this macOS host.

## Commands and exits

All Python/ruff/mypy runs activated `/Users/joe/Developer/github/spark/.venv/bin/activate`. Acceptance pytest/mypy used `PYTHONPATH="$PWD/src"`, synthetic HOME/USERPROFILE `/tmp/spark-merge-review-20261022/windows-pinning-home` and SPARK_HOME beneath its `profile` directory; pytest fixtures also isolate profile state.

1. Before source edit: `PYTHONPATH="$PWD/src" python -m pytest tests/spark_cli/test_workspace_upload_safety.py -k 'access_contract or directory_swap_at_write' -q -n 0 -m 'not integration'` — exit 1, 1 failed / 6 passed. Log: `windows-pinning-base-tests.log`.
2. After source edit: `python -m pytest tests/spark_cli/test_workspace_upload_safety.py tests/spark_cli/test_workspace_upload_identity.py tests/spark_cli/test_workspace_file_ops.py tests/spark_cli/test_workspace_git.py -q -n 0 -m 'not integration and not network'` with acceptance environment above — exit 0, 121 passed / 13 native Windows skips in 57.09s. Log: `windows-pinning-focused.log`.
3. CI Ruff: `ruff check src/ --select UP015,F,B,I,W,UP028,UP031,UP035,UP037,UP042 --ignore B027` — exit 0. Log: `windows-pinning-ruff.log`.
4. Same CI Ruff selection on `tests/spark_cli/test_workspace_upload_safety.py` — exit 0.
5. `ruff check src/spark_cli/workspace_routes.py tests/spark_cli/test_workspace_upload_safety.py` — exit 0. Log: `windows-pinning-scoped-ruff.log`.
6. `ruff check src/` — exit 1, 298 findings outside the two clean changed files. Log: `windows-pinning-full-ruff.log`. No broad lint cleanup attempted.
7. `mypy src/agent/ src/spark_cli/` with acceptance environment above — exit 0, success in 137 source files. Log: `windows-pinning-mypy.log`. An initial invocation without checkout PYTHONPATH followed installed imports and emitted 2717 errors; corrected by selecting this checkout's imports, not source/type-check configuration changes.
8. Base comparison: `PYTHONPATH="$PWD/src" mypy src/agent/ src/spark_cli/ --shadow-file src/spark_cli/workspace_routes.py /tmp/spark-merge-review-20261022/windows-pinning-base-workspace_routes.py` — exit 0, success in 137 files. Shadow file was extracted with `git show f046bac9:src/spark_cli/workspace_routes.py`. Log: `windows-pinning-base-mypy.log`.
9. `git diff --check` — exit 0. Scoped commit — exit 0; clean status.

## Limits / lead gate

This host is macOS: no native Windows execution is claimed. The lead must run the final Windows CI on the integrated commit, including the strengthened four swap cases and the new direct-handle tests. Native job `119931403494` / `windows-contract-final-failure.log` is the prior actual containment failure, not evidence that this repair passes.

The separate-process generic-write case exercises denial of the common mutation handle, not an actual FSCTL_SET_REPARSE_POINT call. Microsoft MS-FSA's reparse-set algorithm (https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-fsa/4aeefef8-92c3-4abc-af7a-a610caf8a165) also mentions FILE_WRITE_ATTRIBUTES authorization; no stronger claim about arbitrary metadata-only FSCTL mutations is made from this directory-share change. Existing native junction and final-link rejection tests remain in the focused suite. Keep the native gate mandatory; this bounded repair does not provide local native or exhaustive filesystem/filter-driver proof.
