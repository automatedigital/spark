# Windows upload metadata reparse boundary handoff

Commit: `855714135219db0053b425066baeefa359c29ad5`
Base: `54677d12` (shared integrated directory-pinning repair)
Branch: `fix/windows-upload-reparse-boundary`
Checkout: `/Users/joe/.t3/worktrees/spark/t3-90a87188`

Only the three authorized files changed:
- `src/spark_cli/workspace_routes.py`
- `tests/spark_cli/test_workspace_upload_safety.py`
- `tests/spark_cli/test_workspace_upload_identity.py`

The clean, older thread checkout was advanced to the explicitly requested shared base before editing. No integration/root checkout edits, push, PR, merge, watch, packaging, publication, manifest, lockfile or bundle changes. Scoped commit succeeded; git status is clean.

## Before / after

Before: directory handles with FILE_LIST_DIRECTORY activate sharing checks and deny rename, but child directory creation, upload creation, and collision inspection still use full paths. The previous report correctly left metadata-only FSCTL mutation unresolved. MS-FSA explicitly accepts FILE_WRITE_ATTRIBUTES authorization for FSCTL_SET_REPARSE_POINT, so denying generic-write sharing cannot establish that metadata mutation is impossible.

After: Windows `_upload_directory` yields the native directory HANDLE as an integer (POSIX still yields its fd). Canonical ancestors remain pinned without delete sharing. After opening the volume root, every ancestor/descent open uses a single basename with NtCreateFile OBJECT_ATTRIBUTES.RootDirectory. Upload directory descent uses FILE_OPEN_IF rather than path mkdir. New files use FILE_CREATE (exclusive CREATE_NEW equivalent); collision inspection uses FILE_OPEN. All relative operations retain FILE_OPEN_REPARSE_POINT and inspect opened-object attributes, rejecting reparses and wrong kinds. File opens use FILE_NON_DIRECTORY_FILE; directory opens use FILE_DIRECTORY_FILE. FILE_SYNCHRONOUS_IO_NONALERT and SYNCHRONIZE preserve synchronous CRT writing. CRT ownership transfer and close paths remain intact.

`_write_upload` and collision inspection receive the pinned directory HANDLE directly and never construct a path-based child open. This is the containment boundary even when an empty directory's metadata changes. `_verify_upload_directory` branches on sys.platform, never sends a native HANDLE to os.fstat, and compares FILE_ID_INFO volume/id from the pinned object and a separately opened expected path. The expected path opener rejects final reparses; ancestor redirection produces an identity mismatch. Acknowledgement checks are additional checks, not a path-stat substitute for handle-relative creation. Normal uploads, intentional root/profile links, immutable collisions, filename byte budgets, existing attachment identity, and POSIX behavior retain their existing regression coverage.

## New bounded native tests (NOT executed on this macOS host)

`_set_windows_mount_point` constructs a real IO_REPARSE_TAG_MOUNT_POINT REPARSE_DATA_BUFFER and calls DeviceIoControl(FSCTL_SET_REPARSE_POINT). Its CreateFileW contender requests exactly FILE_WRITE_ATTRIBUTES (0x100), FILE_SHARE_READ (1), OPEN_EXISTING and OPEN_REPARSE_POINT | BACKUP_SEMANTICS. Acquiring that metadata-only contender is asserted, not silently ignored.

An unpinned control must successfully set the same junction and read the outside sentinel through it. A malformed buffer, missing filesystem feature, or unsupported operation therefore fails the native test rather than yielding false containment evidence. No native test is skipped on Windows.

A direct pinned-handle test exercises the metadata-only contender and actual FSCTL. It requires either successful mutation or concrete access/sharing denial (5/32), with outside bytes unchanged. It does not claim generic-write sharing prevents metadata mutation.

Six endpoint cases (project/global x upload read/final exclusive open/directory descent) inject actual FSCTL mutation. Each requires the entire outside tree to remain exactly the original sentinel. A successful mutation must yield HTTP 400 with no saved acknowledgement; a concrete denied mutation must still permit an ordinary successful upload with matching response bytes. Existing native final-link, junction, linked-root/profile, ordinary upload, rename/generic-write and collision cases remain present. The final-handle instrumentation accepts the new root_handle parameters.

Portable tests independently inspect NtCreateFile root handle, basename, dispositions, share masks, desired access, synchronous flags and no-reparse flags for directory descent, ancestor opening, new file creation and collision inspection. Separate identity tests prove native HANDLEs never reach os.fstat and both matched/mismatched identities close their inspection handle.

## Primary sources reviewed

- https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-fsa/4aeefef8-92c3-4abc-af7a-a610caf8a165 — section 2.1.5.10.37, line 48 authorizes FILE_WRITE_DATA OR FILE_WRITE_ATTRIBUTES; empty-directory rules are also explicit. This is why the previous share-only fix is insufficient as an argument.
- https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntcreatefile — RootDirectory and relative ObjectName; FILE_CREATE/OPEN/OPEN_IF; DIRECTORY/NON_DIRECTORY, OPEN_REPARSE_POINT and synchronous IO/SYNCHRONIZE requirements.
- https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntifs/ns-ntifs-_reparse_data_buffer — actual mount-point buffer layout and UTF-16 offsets/lengths.
- https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_id_info — volume serial plus 128-bit id identifies the opened object for comparison.

## Commands and exits

All Python/Ruff/mypy commands activated `/Users/joe/Developer/github/spark/.venv/bin/activate`. Acceptance used this checkout's `PYTHONPATH="$PWD/src"`, synthetic HOME/USERPROFILE `/tmp/spark-merge-review-20261022/windows-metadata-home`, SPARK_HOME beneath its `profile`; pytest fixtures also isolate state. No editable install changed shared environment bindings.

1. Before regression: temporarily substitute `git show 54677d12:src/spark_cli/workspace_routes.py` in this owned checkout inside a Python try/finally, run `python -m pytest tests/spark_cli/test_workspace_upload_safety.py tests/spark_cli/test_workspace_upload_identity.py -k 'relative_open_contract or directory_identity_uses' -q -n 0 -m 'not integration'`, then restore current source in finally. Exit 1; 6 failed, 74 deselected. Four failures are the absent root_handle API; two are the invalid native-HANDLE-to-os.fstat behavior. Log `windows-metadata-before.log`. This is API/mock regression evidence, NOT before-fix native exploitation proof.
2. After portable contracts: same selection, exit 0; 6 passed, 74 deselected. Log `windows-metadata-contract.log`.
3. Focused broader suite: `python -m pytest tests/spark_cli/test_workspace_upload_safety.py tests/spark_cli/test_workspace_upload_identity.py tests/spark_cli/test_workspace_file_ops.py tests/spark_cli/test_workspace_git.py -q -n 0 -m 'not integration and not network'` — exit 0; 125 passed, 20 Windows-only skips, 73.05s. Log `windows-metadata-focused.log`. This run preceded the addition of the two portable identity tests; source implementation is the same.
4. Final upload suites including both added identity tests: `python -m pytest tests/spark_cli/test_workspace_upload_safety.py tests/spark_cli/test_workspace_upload_identity.py -q -n 0 -m 'not integration and not network'` — exit 0; 60 passed, 20 Windows-only skips, 8.62s. Log `windows-metadata-final-upload.log`.
5. CI Ruff: `ruff check src/ --select UP015,F,B,I,W,UP028,UP031,UP035,UP037,UP042 --ignore B027` — exit 0. Log `windows-metadata-ci-ruff.log`.
6. Scoped Ruff: `ruff check src/spark_cli/workspace_routes.py tests/spark_cli/test_workspace_upload_safety.py tests/spark_cli/test_workspace_upload_identity.py` — exit 0. Log `windows-metadata-scoped-ruff.log`.
7. Full Ruff: `ruff check src/` — exit 1; 298 findings outside the clean changed source file, same count as previous report. Log `windows-metadata-full-ruff.log`. No unrelated cleanup.
8. `mypy src/agent/ src/spark_cli/` — exit 0, success in 137 source files. Log `windows-metadata-mypy.log`.
9. `git diff --check` — exit 0. Scoped commit — exit 0; clean git status.

## Limits and parent gate

No native Windows runtime, endpoint/browser or FSCTL enforcement result is claimed from this macOS host. The actual old failure remains job 119931403494 / `windows-contract-final-failure.log`; it does not prove this commit passes. The parent must run native Windows CI on the integrated commit, including the unpinned control, direct metadata contender, six FSCTL endpoint cases, existing directory-swap tests and normal/collision/link/identity cases. An unpinned control failure is a real unresolved native-test prerequisite/behavior to inspect, not a reason to skip or declare safety. Native passing evidence is still required before merge/release claims. No user-facing browser flow changed; local evidence is endpoint tests plus portable API checks, not native OS proof.
