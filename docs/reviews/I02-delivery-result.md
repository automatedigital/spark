# I02 result

- PR: https://github.com/automatedigital/spark/pull/171 (main; closes #146)
- Head: `10ba28f595c5c39e6c1918b01e2b3dab214d614a`
- Branch: `fix/attachment-upload-identity`
- Worktree: `/Users/joe/.t3/worktrees/spark/t3-e66a7ee7`
- Base: `64af0d26976714b747dd4f1cc5b495c47c7f7567`
- Commit/push/PR creation: exit 0. No merge/release/deploy/watch/nested delegation.

Uploads now create files exclusively and retry collisions with a bounded UUID-suffixed name, retaining original display filenames and each prior byte stream. Project responses now include actual relative/absolute storage paths; global responses return allocated paths. Existing draft staging consumes these paths without ChatPanel edits. Explicit PUT file-write operations remain available for deliberate replacement; multipart uploads never implicitly replace an existing entry.

Changed only:
- src/spark_cli/workspace_routes.py
- src/spark_cli/web/src/lib/api_workspace.ts (response type)
- src/spark_cli/web/src/lib/attachmentStaging.test.ts
- tests/spark_cli/test_workspace_upload_identity.py

## Checks

Python commands activated `/Users/joe/Developer/github/spark/.venv/bin/activate` (checkout .venv absent) with PYTHONPATH set to this checkout's src. Final runs and both servers used synthetic HOME, USERPROFILE and SPARK_HOME. The initial focused pytest invocation assigned USERPROFILE from the pre-assignment HOME in a single export, but the new tests override all three variables with synthetic paths before use; subsequent runs corrected the shell setup. No live profile or real provider calls.

Node verified before frontend acceptance: v22.23.4; executable `/private/tmp/spark-packets-20261022/node-v22.23.4-darwin-arm64/bin/node`. Installed tarball verified against Node's SHA256 file. Default system Node is 25.8.0 and was not used for acceptance.

- `npm ci --prefix src/spark_cli/web --cache /tmp/spark-packets-20261022/npm-cache`: exit 0; no lockfile/dependency edits.
- Baseline route module loaded from pinned commit, then `pytest.main(['tests/spark_cli/test_workspace_upload_identity.py', '-q', '-n', '0', '-m', 'not integration and not network', '-k', 'same_name'])`: 4 failed, 3 deselected, exit 1. Exact harness `/tmp/spark-packets-20261022/I02-baseline-test.py`; log `I02-baseline-test.log`.
- `python -m pytest tests/spark_cli/test_workspace_upload_identity.py tests/spark_cli/test_workspace_file_ops.py tests/spark_cli/test_workspace_git.py tests/test_project_metadata.py tests/test_project_templates.py -q -n 0 -m 'not integration and not network'`: 51 passed, exit 0.
- Final `python -m pytest tests/spark_cli/test_workspace_upload_identity.py -q -n 0 -m 'not integration and not network'`: 7 passed, exit 0.
- `ruff check src/spark_cli/workspace_routes.py tests/spark_cli/test_workspace_upload_identity.py`: exit 0.
- `ruff check src/`: exit 1, 299 existing errors. Base workspace_routes.py via `ruff check --stdin-filename src/spark_cli/workspace_routes.py - < /tmp/spark-packets-20261022/I02-baseline-routes.py` passes, as does changed file; all other Python source files untouched. Log `I02-ruff-all.log`.
- `mypy src/spark_cli/workspace_routes.py`: exit 0. Log `I02-mypy.log`.
- In src/spark_cli/web: `npx vitest run src/lib/attachmentStaging.test.ts src/lib/draftStore.test.ts`: 11 passed, exit 0.
- `npx eslint src/lib/api_workspace.ts src/lib/attachmentStaging.test.ts`: exit 0.
- `npx tsc -b`: exit 0.
- `git diff --check`: exit 0.

## Browser evidence

T3 preview tab `tab_9_2a6f0617-4839-4d5c-85e3-c9fef237b3b0`, isolated FastAPI fixture http://127.0.0.1:18362 and source Vite http://127.0.0.1:18363. Server script `/tmp/spark-packets-20261022/I02-browser-server.py`; no provider/runtime routes mounted. Imported actual api.uploadChatFiles, workspaceApi.uploadWorkspaceFiles, uploadDraftFiles and draftStore modules. Uploaded `report.txt` containing `first` to one thread and `second` to another, for both ordinary and project chat draft scopes. Every POST/read returned 200; original display names retained; response storage paths differed. Reloaded browser page and freshly loaded draftStore; all four drafts reported recovered and read their original bytes. Final assertion returned `{recovered:4, originalBytesVerified:true, labelsPreserved:true}`.

Browser caught `/tmp` vs `/private/tmp` path mapping; resolved relative response mapping and added alias-root tests for nested/root uploads. Initial browser open preceded server readiness and returned chrome-error://chromewebdata/; retry after readiness succeeded. First fixture pass failed on the alias-root error; after fix final passes succeeded.

This is a browser-origin source-module + real-route fixture, not full shipped Chat/Files UI acceptance. Tests also prove same-batch duplicates, six concurrent request clients, forced generated-name collisions, persisted draft reload, and thread separation.

## Integration / remaining checks

I01 dependency: https://github.com/automatedigital/spark/pull/155 at `4ab637f8087e683a0c5ce9afcc2db2ac4ffb33b0` (draft). Both packets intentionally use committed main as instructed. Expected conflicts in both upload handlers. Keep I01 descriptor-pinned directory/no-follow traversal; adapt its `_write_upload` to use exclusive O_EXCL allocation plus bounded collision retries returning the allocated name. Do not overwrite its containment guarantees with I02's baseline pathname writer. Preserve returned actual paths and original display names. Rerun both safety/identity suites after integration. I01 directory-link rejection supersedes this baseline alias-directory success expectation where applicable; retain macOS lexical /tmp path coverage. I01 Windows upload 501 remains unresolved, separate from portable collision naming here.

Unexecuted: native Windows, full shipped Chat/Files UI, full pytest suite, full frontend suite/lint/build, packages, gateway/providers. No PLAN, production web_dist, migrations, manifests or dependency changes. No PR checks watched or polled.

T3 PR registration succeeded (`alreadyLinked:false`); list_thread_pull_requests confirmed #171 with watching:false. PR review/check state was not polled. Final worktree status is clean. Isolated fixture backend and Vite servers stopped after validation.
