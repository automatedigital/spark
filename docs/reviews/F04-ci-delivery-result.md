# F04 CI review result

PR: https://github.com/automatedigital/spark/pull/170 (existing PR; linked to this T3 thread, watching=false)
Remote branch: feat/save-and-restore-a-bounded-prompt-stash
Remote/head SHA: a94d5487b6f747a612a11591b0a9fac1c0350fbf
Review branch: feat/save-and-restore-a-bounded-prompt-stash-ci-review
Isolated worktree: /Users/joe/.t3/worktrees/spark/t3-7297c9c0
Base: 64af0d26976714b747dd4f1cc5b495c47c7f7567

Renamed fresh T3 branch, then git merge --ff-only a94d5487b6f747a612a11591b0a9fac1c0350fbf: exit 0. No root checkout touched. No source edits or new commits/pushes justified. Existing seven-file implementation remains on GitHub: explicitly saved bounded text-only prompts, backend/profile browser-local persistence, safe restore confirmation, delete, honest storage errors. No attachment/context capture claim.

## Hosted failure and attribution

Run https://github.com/automatedigital/spark/actions/runs/39789747849 , job 119862296942, head a94d5487b6f747a612a11591b0a9fac1c0350fbf, attempt 1. Downloaded browser-gates-1 artifact ID 12431607729 (exit 0) into F04-hosted-artifact. Latest fetched failed-job log: F04-hosted-failed.log. Run metadata, original lead log, failure.json and screenshot diagnostic reviewed before any local gate run. No hosted rerun or monitoring.

Artifact path relative to /tmp/spark-packets-20261022/:
F04-hosted-artifact/tmp/spark-browser-gates/longthread/attempt-03/run-01/failure.json
F04-hosted-artifact/tmp/spark-browser-gates/longthread/attempt-03/run-01/screenshots/dark-2000-w1440-failure.json

Exact assertion: History paging made no forward progress at before_id=2401, baseline-capture.mjs:350. Hosted attempts 1/2 exit 0; third exit 1, no suite timeout. Cursor sequence 2501,2451,2401,2401; duplicate requests returned HTTP 200. No page or console errors. No evidence that an HTTP timeout caused this hosted failure. Source root cause remains unverified, not attributed to stash or declared baseline debt. Gate and pagination controller are unchanged from base; only the existing documented seven stash files differ.

## Fresh verification

Activated /Users/joe/Developer/github/spark/.venv/bin/activate (checkout has no .venv). PYTHONPATH points to this checkout src. PATH explicitly starts /Users/joe/.nvm/versions/node/v22.22.1/bin; verified node --version v22.22.1 and node -p process.execPath /Users/joe/.nvm/versions/node/v22.22.1/bin/node. PYTHON=/Users/joe/Developer/github/spark/.venv/bin/python, PLAYWRIGHT_BROWSERS_PATH=/Users/joe/Library/Caches/ms-playwright. Fixture/check HOME and USERPROFILE=/tmp/spark-packets-20261022/F04-ci-home, SPARK_HOME under its spark directory. Browser fixtures create their own additional temporary Spark home. No real provider calls. The stash fixture explicitly counts zero /api/chat calls.

All following paths are under /tmp/spark-packets-20261022. Frontend commands run in src/spark_cli/web except gate command can run from repo root.

- npm ci --prefix src/spark_cli/web: exit 0; F04-ci-npm-ci.log. No lockfile edits. Reports one existing high severity dependency advisory; no dependency mutation attempted.
- npm run lint: exit 0; F04-ci-lint.log.
- npx tsc --noEmit -p tsconfig.app.json: exit 0; F04-ci-types.log.
- npx vitest run src/lib/promptStashStore.test.ts: exit 0, 1 file/8 tests; F04-ci-unit.log.
- node src/spark_cli/web/e2e/browser-gates.mjs --suite longthread --repeat 3 --output-dir /tmp/spark-packets-20261022/F04-ci-candidate: aggregate exit 1; F04-ci-candidate.log and F04-ci-candidate/gate.json. One original batch only: attempt 1 exit 1, page.goto timeout 30000ms before history requests; attempts 2/3 exit 0, full 2000-row history and stream checks passed. All three timeout=false at suite level. Exact hosted cursor failure not reproduced. Gate unchanged, including original 30s navigation bound and assertions. Each attempt builds temporary source output, no tracked web_dist mutation.
- Temporarily detached this same isolated worktree at base 64af0d26, ran node src/spark_cli/web/e2e/browser-gates.mjs --suite longthread --repeat 1 --output-dir /tmp/spark-packets-20261022/F04-ci-baseline: exit 0; F04-ci-baseline.log and gate.json. One baseline comparison only; same case/thresholds. Restored review branch, exit 0. Baseline pass does not classify the historical intermittent failure. Other browser/test processes were active on the shared host; no comparative latency/performance claim.
- STASH_OUTPUT=/tmp/spark-packets-20261022/F04-ci-stash-browser node e2e/prompt-stash.mjs: exit 0; F04-ci-stash-browser.log. Real checkout backend/ChatPanel/PromptBar, provider-free. Reload persistence; cancel preserves nonempty draft; explicit replacement preserves exact Unicode/multiline text; empty-draft restore; quota-failed save/delete preserve draft/item and display honest error; deletion survives reload; 390px chooser access and Escape dismissal. Six flow checks, zero provider calls. Inspected mobile-chooser.png and storage-failure.png in F04-ci-stash-browser; expected rendering confirmed.
- ruff check src/: exit 1, 299 baseline findings in unchanged Python; F04-ci-ruff.log. Same count as original handoff. No new Python changes.
- git diff --check: exit 0; git status --short empty.
- git ls-remote origin refs/heads/feat/save-and-restore-a-bounded-prompt-stash: exit 0, exact a94d5487b6f747a612a11591b0a9fac1c0350fbf.

## Outcome / remaining blocker

No demonstrated introduced source cause, so no speculative fix, push, hosted rerun or expanded instrumentation. Hosted e2e failure remains historical and unresolved; do not treat this PR as CI-green or merge-ready. Assertions/thresholds/security gates untouched. Fresh focused checks and feature browser acceptance pass. Original F04-result.md retains full frontend suite/build/bundle evidence; those full checks were not repeated here. Full pytest/mypy, installed desktop, packaging, real-provider and deployment checks not run. No CLI feature exists for this composer-only packet; browser plus helper tests cover the intended path. No PLAN, web_dist, migration, manifest, lockfile or dependency changes. No merge/release/deploy, nested delegation or watcher.

F01 integration overlap remains PromptBar import/props/toolbar, plus narrow ChatPanel/useChatDraft seams; retain both history and stash behavior during rebase. Updated PR description with exact new evidence and open gate; no duplicate PR. T3 link/list confirmed PR #170 linked, watching=false.
