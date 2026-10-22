# F07 delivered

PR: https://github.com/automatedigital/spark/pull/183
Head SHA: bab15418550385c1ca73a3480900733a6f98a962
Base: main at assigned 64af0d26976714b747dd4f1cc5b495c47c7f7567
Remote branch: feat/render-safe-collapsible-details-in-chat-markdown
New worktree: /Users/joe/.t3/worktrees/spark/t3-f0a8fb20
New local branch: feat/render-safe-collapsible-details-in-chat-markdown-resume
Original worktree (read-only, preserved): /Users/joe/.t3/worktrees/spark/t3-f0630eda
Original local branch: feat/render-safe-collapsible-details-in-chat-markdown
Original HEAD: 64af0d26976714b747dd4f1cc5b495c47c7f7567
Recovery: git merge --ff-only of original HEAD; applied its git diff HEAD --binary; copied only MarkdownDetails.tsx, markdownDetails.test.ts and e2e/markdown-details.html. No original checkout changes. New worktree was clean before recovery.

## Exact validation

Commands run in src/spark_cli/web unless otherwise specified. Node v22.22.0, executable /private/tmp/spark-f07-tools/node-v22.22.0-darwin-arm64/bin/node; PATH prepended /tmp/spark-f07-tools/node-v22.22.0-darwin-arm64/bin. Installed node@22 was verified and actually resolves to v25.8.0, so was not used for acceptance. npm ci --ignore-scripts exited 0 before acceptance (under system Node25; unchanged package/lock). It reported 1 high vulnerability in the existing lock; no dependency changes were authorized.

- npm run lint: exit 0.
- ./node_modules/.bin/eslint src/components/Markdown.tsx src/components/MarkdownDetails.tsx src/components/markdownParse.ts src/components/markdownDetails.test.ts e2e/markdown-details.mjs: exit 0 after final fixture edits.
- HOME=/tmp/spark-f07-profile/home USERPROFILE=/tmp/spark-f07-profile/home SPARK_HOME=/tmp/spark-f07-profile/spark npm test: exit 0, 79 files / 464 tests. Log /tmp/spark-f07-test-isolated.log. Earlier full run also passed 464 tests; isolated rerun is acceptance evidence.
- npx tsc -b && npx vite build --outDir /tmp/spark-f07-build: combined exit 0, both commands passed. Log /tmp/spark-f07-build.log. Production web_dist was never changed.
- node /Users/joe/.t3/worktrees/spark/t3-f0a8fb20/src/spark_cli/web/scripts/check-bundle-budget.mjs from /tmp/spark-f07-budget/web, with sibling web_dist symlink to /tmp/spark-f07-build: exit 0, 243.13 KiB initial graph gzip vs 600 KiB budget. Standard Vite >500kB chunk warning remains.
- node e2e/markdown-details.mjs: exit 0 after final fixture changes. Log /tmp/spark-f07-browser.log. Runner creates and cleans synthetic HOME/USERPROFILE/SPARK_HOME, starts isolated Vite on a free port and launches Chromium with a synthetic home; no backend/provider calls. Tests native default/open, Enter and pointer expand/collapse, code clipboard exact bytes, zero unrelated transcript mutations, partial/malicious/safe-mode literal fallback and completion recovery; zero page errors. Screenshot /var/folders/px/w5ttjwk56dg761_zbyj1c2bw0000gn/T/spark-f07-details.png visually inspected.
- Native Chromium window.find probe: found:true, open:false, selected:"". Automatic find/reveal is not supported/proven by this browser probe. Native keyboard/pointer disclosure is verified.
- Collaborative browser navigated to fixture but snapshot failed twice with `Preview automation snapshot timed out after 15000ms.` Switched to repository Playwright browser flow. Initial navigation before server readiness failed ERR_CONNECTION_REFUSED and recovered once server was ready.
- git diff --check: exit 0.
- At repo root, source /Users/joe/Developer/github/spark/.venv/bin/activate; export PYTHONPATH=$PWD/src; ruff check src/: exit 1, 299 baseline errors in untouched Python files. Concise rerun log /tmp/spark-f07-ruff.log, same 299 errors. No Python source changed; pytest and Python mypy not run. No runtime/cache/tool startup surface changed.

## Delivery

Commit bab15418550385c1ca73a3480900733a6f98a962. First push was rejected by GitHub with generic `(failed)`; remote branch absent and auth valid. One bounded verbose normal push succeeded (exit 0). No force push. PR created against main and immediately T3 linked. No merge, deploy, release, PR watch or polling.

## Scope and integration

Chat responses can now render a deliberately narrow, line-based disclosure syntax: `<details>` or `<details open>`, followed immediately by a text-only `<summary>Title</summary>`, a Markdown body, and a standalone `</details>`. Native HTML disclosure controls support keyboard/pointer toggling without transcript state updates. Bodies retain Markdown formatting and code copying.

Missing/invalid summaries, attributes, nested disclosures, incomplete streaming blocks and disclosures above 6,000 characters stay literal. Fenced tags and escaped tags remain text. No general HTML rendering or new dependency is enabled; existing safe-mode and large-response fallbacks remain active.

Closes #162.

Validation (Node v22.22.0, executable `/private/tmp/spark-f07-tools/node-v22.22.0-darwin-arm64/bin/node`):
- `npm run lint`: exit 0; final scoped ESLint including the browser runner: exit 0.
- `npm test` with synthetic HOME/USERPROFILE/SPARK_HOME: exit 0, 79 files / 464 tests pass.
- `npx tsc -b`: exit 0.
- `npx vite build --outDir /tmp/spark-f07-build`: exit 0; normal chunk-size warning. Tracked web_dist untouched.
- Bundle-budget script against the temporary build: exit 0, initial graph 243.13 KiB gzip / 600 KiB budget.
- `node e2e/markdown-details.mjs`: exit 0. Real Chromium fixture imports the production Markdown component; verifies default/open state, Enter and pointer toggles, exact clipboard copying, zero unrelated transcript mutations, partial/malicious/safe-mode fallbacks and completion recovery. No page errors. Uses an isolated Vite server and synthetic browser/server profile directories; no backend/provider calls.
- Native `window.find` returned true but did not open the disclosure or select text in this Chromium build; automatic browser find/reveal is not claimed. Pointer/keyboard reveal and copy work.
- Collaborative preview navigated successfully but snapshot timed out twice; browser evidence came from the repository Playwright path.
- `git diff --check`: exit 0.
- Required `ruff check src/`: exit 1, 299 existing errors in unchanged Python files. Python pytest/mypy and installed desktop checks were not run for this frontend-only change.

Recovery: read-only stopped checkout `t3-f0630eda` was at baseline 64af0d26976714b747dd4f1cc5b495c47c7f7567 with uncommitted implementation. Fast-forwarded the new bound checkout to that exact HEAD, then recovered its tracked diff and only relevant untracked source/tests. No stopped-checkout edits or cleanup.

Integration: merge F06's callout parser changes before F07. Both touch markdownParse.ts and Markdown dispatch; retain each narrow variant, boundary handling and tests when rebasing. This PR deliberately stays based on the assigned baseline rather than incorporating another packet. No PLAN, manifests, migrations, dependencies, lockfiles or production bundles changed.

## Remote verification

`git ls-remote --heads origin refs/heads/feat/render-safe-collapsible-details-in-chat-markdown` returned bab15418550385c1ca73a3480900733a6f98a962 (exit 0). `gh pr view 183 --json url,state,headRefName,headRefOid,baseRefName,isDraft,statusCheckRollup` returned OPEN, non-draft, main target and the same SHA (exit 0). CI pending at handoff: lint-types-tests queued; e2e in progress. No watching/polling performed. T3 link_pull_request succeeded; list_thread_pull_requests confirms #183 linked and watching:false. Working tree clean. Manual isolated Vite server stopped after validation; automated runner also stopped its own server/browser and removed its synthetic profile.
