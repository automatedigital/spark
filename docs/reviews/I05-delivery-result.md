# I05 implementation result

PR: https://github.com/automatedigital/spark/pull/168 (registered with T3)
Issue: https://github.com/automatedigital/spark/issues/149 (Closes in PR)
Head: 797c0667b6c6bfd2c58232d94374d55c97d2c126
Branch: fix/git-path-parsing
Worktree: /Users/joe/.t3/worktrees/spark/t3-3e4dea21
Base: 64af0d26976714b747dd4f1cc5b495c47c7f7567
Local/remote head verified equal; worktree clean.

Only src/spark_cli/workspace_routes.py and tests/spark_cli/test_workspace_git.py committed. Porcelain v1 -z and numstat -z preserve exact path strings and consume rename/copy records correctly. Git output is decoded without universal-newline translation to retain embedded CR. No uploads, PLAN, production bundle, migration, manifest, dependency or lockfile edits. No root checkout mutations or delegation.

## Exact checks

All Python commands: activated /Users/joe/Developer/github/spark/.venv/bin/activate because checkout .venv is absent; PYTHONPATH=/Users/joe/.t3/worktrees/spark/t3-3e4dea21/src. Test/server HOME, USERPROFILE and SPARK_HOME were synthetic under /tmp; tests use temporary isolated profiles. No provider calls.

- python -m pytest tests/spark_cli/test_workspace_git.py -m 'not integration and not network' -q -n 0 => exit 0, 29 passed in 53.26s.
- python -m pytest tests/spark_cli/test_workspace_file_ops.py -m 'not integration and not network' -q -n 0 => exit 0, 12 passed in 15.11s.
- ruff check src/spark_cli/workspace_routes.py tests/spark_cli/test_workspace_git.py => exit 0.
- mypy src/spark_cli/workspace_routes.py => exit 0, no issues found.
- ruff check src/ => exit 1, 299 errors. Committed-base archive scanned from its own root also gives exit 1 / 299 errors. cmp current/baseline logs => exit 0; verified baseline debt, no new Ruff failures. Logs: I05-ruff.log, I05-ruff-baseline.log, I05-mypy.log in this folder.
- git diff --check => exit 0.
- node --version => v22.22.1; node -p process.execPath => /Users/joe/.nvm/versions/node/v22.22.1/bin/node. Default v25 and misleading node@22 Homebrew symlink were not used for browser acceptance.
- npm ci --prefix src/spark_cli/web --ignore-scripts => exit 0, 298 packages; tracked dependencies/lockfiles unchanged.

## Browser/CLI fixture evidence

Temporary harness /tmp/spark-I05-browser mounts the actual unchanged WorkspaceChangesPanel against actual workspace FastAPI routes and disposable Git repo, via Node22 Vite. python /tmp/spark-I05-browser/check.py => exit 0. Exact café.txt row loaded with +2 count, expanded real +unicode fixture/+second line diff, Revert confirmation deleted the actual file, UI reconciled to clean, no page errors. Screenshots: /tmp/spark-packets-20261022/I05-expanded.png and I05-reverted.png. Browser used synthetic HOME/USERPROFILE/SPARK_HOME; Playwright browser binary cache explicitly points to installed cache, not profile state.

T3 preview open succeeded but navigation failed with ERR_CONNECTION_REFUSED, then 'Preview automation navigate timed out after 15000ms.' Used local Python Playwright after these two failures. Initial temporary Vite config bundling failed on vite/internal resolution; --configLoader native corrected the harness without changing dependencies/source.

Regression uses real disposable Git repos and HTTP TestClient through status -> returned exact path -> diff -> revert -> clean status for tracked/untracked Unicode, spaces, tabs, LF, CR, literal arrow, literal quotes, backslash and leading/trailing whitespace. Rename fixture proves destination/count parsing, following-record alignment and binary null counts; rename destination diff passes.

## Remaining checks and integration

Staged-rename discard is pre-existing unsupported behavior outside parser ownership: real fixture git mv base.txt 'renamed café.txt', then POST revert for that returned destination gives HTTP 500, pathspec did not match HEAD. Parser/diff acceptance for rename passes; full rename revert acceptance remains unresolved and needs separately owned revert semantics.

Full pytest, broad mypy, frontend lint/unit/build, full-app/chat smoke, installed macOS/Windows package checks, real providers and external services not run. No merge/release/deploy or PR monitoring performed.

I06/W04 should integrate after this change and add --untracked-files=all to status --porcelain=v1 -z. Expected overlap is the status invocation hunk; retain the NUL parser. No upload overlap.
