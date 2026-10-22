# F06 CI review and resumed handoff

PR: https://github.com/automatedigital/spark/pull/174 (registered with T3)
Issue: https://github.com/automatedigital/spark/issues/161
Remote head: 752034ee380b03e8d64de172543900582915e38c
Remote branch: feat/render-github-style-markdown-callouts
Local branch: feat/render-github-style-markdown-callouts-ci-review
Worktree: /Users/joe/.t3/worktrees/spark/t3-ab0f3717
Baseline: 64af0d26976714b747dd4f1cc5b495c47c7f7567

Existing implementation renders NOTE, TIP, IMPORTANT, WARNING and CAUTION as labeled notes through a named parseCallout helper and discriminated callout block. Generic/unknown/incomplete quotes and literal fenced markers remain unchanged. Body Markdown and nested rendering are bounded; icons are decorative and labels are uniquely associated. Seven scoped files already committed/pushed. No new source correction, commit, push, hosted rerun, merge, release or monitoring occurred during this review. Worktree clean; no PLAN, bundle, lockfile, migration or manifest changes.

## Original hosted failure and bounded comparison

Inspected latest web-quality run 39789900554, e2e job 119862856805:
https://github.com/automatedigital/spark/actions/runs/39789900554/job/119862856805
Head matches the PR. Production child inspector gate failed at e2e/subagent-controls.py:261: assert abs(before - after) < 100, with (1000, 1410), exit 1. Full fetched failed-job log: /tmp/spark-packets-20261022/F06-hosted-failure.log. Original lead log retained at PR174-ci-failure.log. Hosted lint/types/unit tests succeeded; subsequent navigation and longthread gates were skipped.

One unchanged full original inspector gate ran on candidate and one on baseline, sequentially, with temporary production builds. Both exited 0, all 11 checks, scroll 1000.0 -> 1000.0 px, zero page errors, 21 observed production assets and 21 ETag/conditional-304 revalidations each. The scroll fixture emits ordinary synthetic history with no callout markers; inspector script and scroll ownership code are identical between commits. This does not establish the cause of the historical failure, or prove Linux hosted CI is fixed. No introduced cause reproduced or attributable; retain the failed hosted run as UNVERIFIED/open. No assertion, threshold, security gate or instrumentation was changed. No diagnostic retries.

Exact build and reproduction commands (run from src/spark_cli/web, environment below):
- npx vite build --outDir /tmp/spark-packets-20261022/F06-candidate-build --emptyOutDir: exit 0
- SPARK_E2E_BUILT_WEB=1 SPARK_E2E_ASSET_DIR=/tmp/spark-packets-20261022/F06-candidate-build SPARK_E2E_REPORTS=/tmp/spark-packets-20261022/F06-candidate-inspector python ./e2e/subagent-controls.py: exit 0
- Temporarily detached this same isolated worktree at baseline; npx vite build --outDir /tmp/spark-packets-20261022/F06-baseline-build --emptyOutDir: exit 0
- SPARK_E2E_BUILT_WEB=1 SPARK_E2E_ASSET_DIR=/tmp/spark-packets-20261022/F06-baseline-build SPARK_E2E_REPORTS=/tmp/spark-packets-20261022/F06-baseline-inspector python ./e2e/subagent-controls.py: exit 0
- Restored local descriptive branch and candidate head after baseline check.

Logs: F06-candidate-build.log, F06-candidate-inspector.log, F06-baseline-build.log, F06-baseline-inspector.log under /tmp/spark-packets-20261022. Full report.json, backend logs, DOM snapshots and screenshots in the two F06-*-inspector directories. Contracts cover real temporary backend/SQLite/SSE with explicit provider-free capability fixtures: three live chats/drafts/attachment/scroll, controls and uncertain receipts, late acknowledgements, child result reconciliation, paged history, reconnect, keyboard/mobile/reduced motion, backend restart and failed project creation.

## Fresh local validation

Environment: source /Users/joe/Developer/github/spark/.venv/bin/activate (checkout has no .venv); PYTHONPATH=/Users/joe/.t3/worktrees/spark/t3-ab0f3717/src; PATH prepends /Users/joe/.nvm/versions/node/v22.22.1/bin. Actual node --version v22.22.1 and node -p process.execPath /Users/joe/.nvm/versions/node/v22.22.1/bin/node. Python Playwright 1.62.0; Node Playwright frozen-lock version 1.59.1. HOME and USERPROFILE=/tmp/spark-packets-20261022/F06-home; SPARK_HOME=/tmp/spark-packets-20261022/F06-state. Inspector additionally creates its own temporary Spark home. Explicit PLAYWRIGHT_BROWSERS_PATH=/Users/joe/Library/Caches/ms-playwright selects installed binaries only. No live Spark state or provider calls. Reusable exact environment/check scripts: F06-env.sh and F06-checks.sh in the report directory.

- npm --prefix src/spark_cli/web ci: exit 0; frozen lock, no dependency edits.
- npm run lint: exit 0 (F06-eslint.log)
- npx tsc -b: exit 0 (F06-types.log)
- npm test: exit 0, 79 files / 457 tests (F06-vitest.log), including focused callout regressions.
- Existing scripts/check-bundle-budget.mjs evaluated unchanged except replacing distDir in memory with temporary candidate path: exit 0, 243.30 KiB gzip / 600 KiB (F06-budget.log). Exact harness in F06-checks.sh; tracked script untouched.
- ruff check src/: exit 1, 299 findings in unchanged Python files (F06-ruff.log), baseline debt.
- python -m pytest tests/spark_cli/test_session_export.py -m 'not integration and not network' -q -n 0: exit 0, 6 passed (F06-pytest.log).
- spark --help: exit 0 (F06-cli-help.log); CLI import/argument smoke only.
- ./node_modules/.bin/vite --host 127.0.0.1 --port 5196 --strictPort served mounted Markdown fixture. CALLOUT_BASE_URL=http://127.0.0.1:5196 CALLOUT_SCREENSHOT=/tmp/spark-packets-20261022/F06-callouts.png node e2e/markdown-callouts.mjs: exit 0 (F06-callouts.log). All five named notes in accessibility tree; ordinary/unknown quotes; literal fence; keyboard Tab/Enter link; eight themes contrast >=4.5; stream split/completion; safe mode; no page errors. Screenshot visually inspected. Dev server stopped intentionally with Ctrl-C (130).
- git diff --check: exit 0; git status --short empty.
- git ls-remote origin refs/heads/feat/render-github-style-markdown-callouts confirms exact remote SHA above.

Existing npm audit reports one high-severity dependency finding; build has existing >500 KiB chunk warning. No dependency changes. Full local runtime pytest/mypy, external services, installed desktop/package/release and other hosted browser gates not rerun. Local macOS passes do not resolve the historical Linux CI failure.

Integration: F06 then F07. Rebase F07's separately named details helper/variant over this parser; expected nearby conflicts in BlockNode, parser dispatch and Markdown switch/memo equality. Retain both helpers and variants. No nested delegation or root-checkout access.
