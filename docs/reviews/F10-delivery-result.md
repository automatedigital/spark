# F10 — published

PR: https://github.com/automatedigital/spark/pull/181 (open, main base, T3-linked, no watcher)
Head: e4081d9053b004e375eca472c86aaa00027ddce9
Remote branch: feat/browse-saved-scheduled-job-output
New local branch: feat/browse-saved-scheduled-job-output-resume
New worktree: /Users/joe/.t3/worktrees/spark/t3-8d6f1789
Stopped worktree (read-only): /Users/joe/.t3/worktrees/spark/t3-f1525cf6
Stopped branch: feat/browse-saved-scheduled-job-output
Stopped HEAD/base: 64af0d26976714b747dd4f1cc5b495c47c7f7567

## Recovery and implementation

Fast-forwarded the new checkout to the stopped HEAD (already at base), applied its tracked binary diff, copied only five relevant nonignored source/test files. Stopped checkout untouched. Committed seven scoped files; no jobs.py, PLAN.md, migration, manifest, dependency, lockfile or production web_dist changes.

Outputs on a job card opens a standalone Saved output history drawer. Lists newest first (20 by default, server maximum 50) with timestamp keyset paging; reads/copies plain Markdown, caps reads at 256 KiB and labels truncation/copy scope. Displays empty/pruned/error states. Does not claim attempt or delivery authority. Canonical 12-hex IDs, exact valid timestamp filenames, descriptor-relative no-follow access at every cron directory level, regular-file enforcement and nonblocking reads reject traversal, symlinks and special files. Uses active profile at request time.

## Exact acceptance checks

Python commands used activation of /Users/joe/Developer/github/spark/.venv/bin/activate, PYTHONPATH pointing to this checkout's src, and temporary HOME/USERPROFILE/SPARK_HOME. Browser fixture sets those variables in subprocesses and launches only registered cron routes, not the full app/scheduler/providers.

- `python -m pytest tests/test_cron_output_routes.py -q -n 0 -m 'not integration'`: exit 0, 18 passed.
- `python -m pytest tests/test_cron_output_routes.py tests/cron/test_jobs.py tests/cron/test_file_permissions.py tests/spark_cli/test_cron.py -q -n 0 -m 'not integration and not network'`: exit 0, 88 passed.
- `ruff check src/spark_cli/cron_output_routes.py src/spark_cli/cron_routes.py tests/test_cron_output_routes.py`: exit 0.
- `ruff check src/`: exit 1, 299 existing errors outside changed files; log /tmp/spark-packets-20261022/F10-ruff-all.log.
- `mypy --follow-imports=silent src/spark_cli/cron_output_routes.py src/spark_cli/cron_routes.py`: exit 0, no issues in two source files.
- Node acceptance PATH: /tmp/spark-packets-20261022/node-v22.23.4-darwin-arm64/bin. `node --version`: v22.23.4; `node -p process.execPath`: /private/tmp/spark-packets-20261022/node-v22.23.4-darwin-arm64/bin/node, both exit 0.
- `npm ci --offline --cache /tmp/spark-packets-20261022/npm-cache --prefix src/spark_cli/web`: final exit 0, 298 packages, no dependency/lock changes.
- In web: `npm run lint`: final exit 0, log F10-eslint.log.
- In web: `npm test`: exit 0, 78 files / 448 tests, log F10-vitest.log.
- In web: `npx tsc -b && npx vite build --outDir /tmp/spark-packets-20261022/F10-build`: exit 0; log F10-build.log. No production web_dist mutation.
- Existing bundle check adapted only in /tmp to point to isolated build: `node /tmp/spark-packets-20261022/F10-budget.mjs`: exit 0, static entry gzip 242.60 KiB / 600 KiB budget.
- `PYTHON=/Users/joe/Developer/github/spark/.venv/bin/python SCREENSHOT=/tmp/spark-packets-20261022/F10-output-drawer-resume.png node src/spark_cli/web/e2e/cron-outputs.mjs`: exit 0. Real filesystem + cron API + real CronPage, no providers. Newest read and copy, literal script text (no execution), older pagination, 262144-byte truncated copy, file pruned between list/read and recovery, 390px drawer, Escape + focus restoration, empty history. Screenshot visually inspected; drawer fits and text is readable.
- `git diff --check` / cached equivalent: exit 0. Clean checkout after commit.
- Normal `git push origin HEAD:refs/heads/feat/browse-saved-scheduled-job-output`: exit 0. `git ls-remote` confirms exact head above. `gh pr view 181` verifies branch/head/base/URL; T3 list confirms linked open PR, watching=false.

## Setup retries and limits

The Homebrew node@22 path actually resolves to Node 25.8.0; it was excluded from acceptance. Initial npm install ran there before verification was corrected. An overlapping offline install returned ENOTEMPTY (190); final standalone Node22 install passed. A premature frontend lint ran before install completion and returned 127; rerun after installation passed. No dependency edits were made.

Safe saved-output access currently requires POSIX dir_fd/O_NOFOLLOW primitives. Unsupported platforms explicitly return 503; Windows browsing is unverified. Full Python suite, unrelated chat/recovery browser suites, desktop packages, deployment and release are unexecuted. Build reports existing >500 kB chunk warning; bundle gate passes.

F02 integration may need manual reconciliation of minimal CronPage and cron route-registration hunks. All larger F10 additions are separate modules. No merge, deployment, release or PR polling performed.
