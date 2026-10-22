# F04 result

PR: https://github.com/automatedigital/spark/pull/170
Issue: https://github.com/automatedigital/spark/issues/159 (closed on merge by PR)
Head: a94d5487b6f747a612a11591b0a9fac1c0350fbf
Branch: feat/save-and-restore-a-bounded-prompt-stash
Worktree: /Users/joe/.t3/worktrees/spark/t3-90b5acbf
Base: 64af0d26976714b747dd4f1cc5b495c47c7f7567 (main)

Implemented explicit browser-local text stash: max 20 prompts, max 16,000 characters each, exact Unicode/multiline text, confirmed backend/profile key, chooser/save/restore/delete, nonempty draft replacement confirmation, honest persistence failures. No attachment/context capture or replacement. Scope unavailable until backend confirms identity. Invalid versioned data is preserved and reported. Capacity rejects new saves, without silently evicting old ones. No upstream code copied.

Only 7 scoped files committed. Working tree clean after commit/push. No root checkout changes, nested delegation, lockfile/dependency changes, PLAN, migrations, manifests or web_dist changes. No merge/release/deploy or PR watcher.

## Validation

Node: v22.22.1; executable /Users/joe/.nvm/versions/node/v22.22.1/bin/node.
Python activated through /Users/joe/Developer/github/spark/.venv/bin/activate; PYTHONPATH set to this checkout src. Fixture seeds/server receive synthetic HOME/USERPROFILE/SPARK_HOME; configured model points to unreachable loopback, no real providers. The browser sends no chat request.

From src/spark_cli/web, with HOME=USERPROFILE=/tmp/spark-packets-20261022/F04-home and SPARK_HOME=/tmp/spark-packets-20261022/F04-home/spark:

- npm run lint: exit 0; F04-lint.log.
- npm test: exit 0; 79 files / 456 tests (8 stash regressions); F04-vitest.log.
- npx tsc -b: exit 0; F04-types.log.
- npx vite build --outDir /tmp/spark-packets-20261022/F04-build: exit 0; F04-build.log. Deliberately did not run default build into tracked production web_dist.
- Existing bundle checker evaluated from a data module with only distDir replaced to point at isolated output: exit 0; 243.87 KiB gzip, budget 600 KiB; F04-budget.log. Reproduce:

  node --input-type=module - <<'JS'
  import { readFileSync } from 'node:fs';
  const source = readFileSync('scripts/check-bundle-budget.mjs', 'utf8').replace('resolve(process.cwd(), "../web_dist")', '"/tmp/spark-packets-20261022/F04-build"');
  await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
  JS

- PLAYWRIGHT_BROWSERS_PATH=/Users/joe/Library/Caches/ms-playwright PYTHON=/Users/joe/Developer/github/spark/.venv/bin/python STASH_OUTPUT=/tmp/spark-packets-20261022/F04-browser-retry node e2e/prompt-stash.mjs: exit 0; F04-browser-retry.log. Real checkout backend and actual ChatPanel/PromptBar: explicit save; reload; Keep current draft preserves text; Replace draft text restores exact Unicode/multiline text; empty draft restore; quota failed save/delete preserve saved item and draft while reporting failure; deletion persists after reload; compact 390px access and Escape dismissal. No provider send. Inspected screenshots: F04-browser-retry/storage-failure.png and mobile-chooser.png. Browser matched expected behavior.
- Initial browser attempt: exit 1, page.goto 30s cold Vite load timeout before feature interactions; F04-browser.log. Increased bounded startup allowance to 90s (DOMContentLoaded), full retry passed. No implementation failure observed.
- node --check e2e/prompt-stash.mjs: exit 0.
- git diff --check and git diff --cached --check: exit 0.
- ruff check src/ (repo root, activated venv): exit 1; 299 pre-existing findings in unchanged Python source; F04-ruff.log. Baseline lint debt, no Python edits in this PR.

All logs above live in /tmp/spark-packets-20261022/.

## Integration / remaining checks

F01 integration is recommended first, but this independent implementation intentionally starts at requested committed base. Expected rebase conflicts: PromptBar import/props/toolbar alongside F01 history; retain both features. ChatPanel adds only stashScope={draft.stashScope}; useChatDraft exposes its existing confirmed identity as stashScope. No ComposerMoreMenu edit: shared Saved prompts toolbar button works at both wide and compact widths, minimizing overlap.

Full pytest/mypy were not run: frontend-only changes; relevant TypeScript, unit and real-backend browser checks passed. No real-provider, installed desktop, cross-platform, packaging, or deployment validation claimed. CI state is pending/unobserved; no polling or watching performed.

PR registration verified through T3 link_pull_request and list_thread_pull_requests: PR #170 linked, watching=false. GitHub confirms OPEN against main at the exact head above. Issue evidence: https://github.com/automatedigital/spark/issues/159#issuecomment-6342336104 .
