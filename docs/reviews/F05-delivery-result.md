# F05 — published implementation handoff

- PR: https://github.com/automatedigital/spark/pull/184 (OPEN, not draft, base main)
- Issue: https://github.com/automatedigital/spark/issues/160 (PR closes it on merge)
- Exact local, remote branch, and GitHub PR head: `2a64ae895e089a5867376ec037ac9781d693d01c`
- Remote branch: `feat/render-safe-mermaid-diagrams-in-chat`
- New bound worktree: `/Users/joe/.t3/worktrees/spark/t3-3f92e595`
- New local branch: `feat/render-safe-mermaid-diagrams-in-chat-resume`
- Original/stopped worktree: `/Users/joe/.t3/worktrees/spark/t3-162af6c0`
- Original/stopped branch: `feat/render-safe-mermaid-diagrams-in-chat`
- Original/stopped HEAD and recovery base: `64af0d26976714b747dd4f1cc5b495c47c7f7567`
- Recovery: `git merge --ff-only 64af0d26976714b747dd4f1cc5b495c47c7f7567` exited 0 (already at stopped HEAD). Applied its binary tracked diff and copied exactly five relevant nonignored source/test files. No artifacts/dependencies/venv copied. Stopped checkout remained read-only; final binary tracked diff byte-matched the original recovery patch (`cmp`, exit 0). New checkout is clean after commit.
- Publication: normal `git push origin HEAD:refs/heads/feat/render-safe-mermaid-diagrams-in-chat`, exit 0. No existing branch PR was found before creating #184. T3 `link_pull_request` succeeded immediately after creation; final `list_thread_pull_requests` confirms #184 linked and watching=false.
- GitHub checks at the single handoff read: `lint-types-tests`, `e2e`, and `pinned-and-lockfile` QUEUED. No polling/watcher, merge, release, or deploy.

## Changes

Eight scoped files only: Markdown.tsx dispatch, MermaidBlock.tsx, mermaidSafety.ts/test, e2e/mermaid-fixture.tsx, e2e/mermaid.mjs, nested package.json/package-lock.json.

Completed, committed Mermaid fences lazily render SVG. Live tails and incomplete fences remain code; safeMode and existing large-response fallback remain plain. Source/Diagram toggle, copy success/denial status, readable errors with source, dark/daylight rerender, serialized global renderer config, cancellation fencing and measurement-node cleanup are included. Policy rejects HTML/entities/config/actions/styles/external assets before import/render, uses Mermaid strict security and HTML-labels=false, strips active SVG features through DOMPurify, and never binds Mermaid click handlers. Caps: 8,000 source characters, 150 lines, 100 layout edges, 500,000 SVG characters. Unsupported styling/interactivity intentionally falls back to source.

Exact direct pins: mermaid 12.2.0 and dompurify 3.4.17 (deduped with Mermaid's copy). No existing dependency version/resolution changed; tinyexec only loses dev=true because it is now also a runtime transitive dependency. No PLAN.md, production web_dist, migrations, generated manifest, root-checkout work, or other packet edits. F06/F07 may require small Markdown.tsx dispatch integration; this PR is independent from the committed baseline and is the sole nested dependency/lockfile writer.

## Environment and exact final checks

For all Python/frontend acceptance commands, sourced `/tmp/f05-env.sh`, which activates `/Users/joe/Developer/github/spark/.venv/bin/activate`, sets PYTHONPATH to this checkout's src, puts `/Users/joe/.nvm/versions/node/v22.22.1/bin` first in PATH, and sets synthetic HOME/USERPROFILE/SPARK_HOME under `/tmp/spark-packets-20261022/f05-home`. Browser runner creates a further fresh synthetic HOME/USERPROFILE/SPARK_HOME and asserts imports resolve to this checkout. No real provider calls.

Verified `node --version` = v22.22.1 and `node -p process.execPath` = `/Users/joe/.nvm/versions/node/v22.22.1/bin/node`. Homebrew node@22 actually resolved to v25.8.0 and was not used for acceptance.

1. `NODE_OPTIONS=--dns-result-order=ipv4first npm ci --prefer-offline --fetch-retries=1 --fetch-timeout=60000`: exit 0, 399 installed/400 audited. Log `f05-evidence/npm-ci-retry.log`.
2. `npm install --package-lock-only --ignore-scripts --prefer-offline`: exit 0; `cmp package-lock.json /tmp/f05-recovered-lock.json`: exit 0. Exact direct-pin validation: exit 0. Log `f05-evidence/lock-verify.log`. Post-commit `git diff --exit-code HEAD -- src/spark_cli/web/package-lock.json`: exit 0.
3. `npm run lint`: exit 0. Log `f05-evidence/lint-final2.log`.
4. `npm test -- --maxWorkers=4`: exit 0, 79 files / 470 tests passed. Log `f05-evidence/vitest-final2.log`.
5. `npx tsc -b`: exit 0. Log `f05-evidence/types-final2.log`.
6. `npx vite build --outDir /tmp/spark-packets-20261022/f05-final-build/web_dist`: exit 0. Log `f05-evidence/build-final.log`. Temporary output avoids touching tracked web_dist. Build warns about deferred chunks larger than 500 kB.
7. From `/tmp/spark-packets-20261022/f05-final-build/web`, `node /Users/joe/.t3/worktrees/spark/t3-3f92e595/src/spark_cli/web/scripts/check-bundle-budget.mjs`: exit 0, initial gzip 244.04 KiB / 600 KiB. Log `f05-evidence/bundle-budget-final.log`. Inspected manifest confirms Mermaid is dynamic and outside the startup graph.
8. `PYTHON=/Users/joe/Developer/github/spark/.venv/bin/python PLAYWRIGHT_BROWSERS_PATH=/Users/joe/Library/Caches/ms-playwright MERMAID_OUTPUT=/tmp/spark-packets-20261022/f05-evidence/browser-complete npm run test:e2e:mermaid`: exit 0. Log `f05-evidence/browser-complete.log`.
9. `python -m pytest tests/spark_cli/test_web_state.py -m 'not integration and not network' -q -n 0`: exit 0, 14 passed in 15.41s. Log `f05-evidence/pytest.log`.
10. `npm ls mermaid dompurify`: exit 0; exact pins/dedupe confirmed. Log `f05-evidence/dependencies.log`.
11. `git diff --check`: exit 0. Normal git push, PR create, remote-SHA/PR verification, stopped-diff comparison and final clean-status checks: exit 0.

## Browser evidence

Structured result: `/tmp/spark-packets-20261022/f05-evidence/browser-complete/result.json`.
Screenshots visually inspected: `browser-complete/diagram.png` (daylight flowchart) and `browser-complete/chat.png` (saved dark-theme Beta sequence diagram).

Passed flows: partial streaming stays code without requesting Mermaid; safeMode stays plain; valid SVG; source toggle and exact copied bytes; denied clipboard feedback; dark/daylight rerender; invalid syntax readable source fallback; HTML/links/config/styles/images blocked with no malicious requests/execution; diagram size and existing large-response caps; concurrent flowchart/sequence renders; unmount during actual measurement cancels publication and removes temporary nodes; 24-message/36k-character saved Chat Alpha navigation via Jump to latest; saved Beta navigation; reload and reopen saved Beta; switch from Alpha to Beta during a provider-free fake diagram stream, then return to two completed SVGs. No page errors. Real SessionDB and backend chat pipeline were used, with no provider calls.

Reload evidence explicitly reopens Beta (matching existing multi-chat e2e behavior); automatic selected-chat restoration is not claimed. Long history is explicitly jumped to latest rather than relying on automatic initial scroll.

## Baseline debt, earlier attempts, and limits

- `ruff check src/`: exit 1, 299 existing errors. Log `f05-evidence/ruff.log`. No Python source changed.
- `npm audit --audit-level=high`: exit 1, one high advisory against unchanged Vite 7.3.6 (fix advertised as 7.3.7). Baseline and candidate audit output byte-identical (`cmp`, exit 0). Logs `f05-evidence/audit.log` and `audit-baseline.log`. Existing audit gates are retained; unrelated dependency upgrades are outside F05.
- First cold `npm ci`: exit 1 ETIMEDOUT on @lezer/markdown; retry used cached packages plus IPv4-first and passed. Initial lint/test commands started before install completed and exited 127 (tools missing); they were rerun successfully after installation. Initial premature npx type attempt was terminated, then rerun successfully with local TypeScript.
- Earlier browser attempts exited 1 on fixture assumptions: fresh-profile onboarding, virtualized long history, stale SVG satisfying a navigation wait, and expecting selected-chat restoration on reload. Fixture now opts out of onboarding, jumps long history explicitly, scopes waits to session IDs, and reopens saved Beta after reload. Final browser run above is green. No unrelated product navigation/scroll changes were made.
- Full Python suite, runtime/cache goldens, generic recovery/sidebar suites, installed macOS/Windows packages, real providers and production deployment were not run. No runtime/cache/tool/schema changes or package/deploy claims.
- This publishes a complete bounded F05 source path and code PR; baseline audit/Ruff failures prevent claiming all repository gates are green. CI was queued at handoff.

Issue evidence published: https://github.com/automatedigital/spark/issues/160#issuecomment-6343772468
