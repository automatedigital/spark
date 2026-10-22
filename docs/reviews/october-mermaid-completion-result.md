# Mermaid parsed-block completion repair

Result: UI-R2-01 repaired and committed for root cherry-pick. No push, PR creation, merge, watcher, release, bundle, lockfile, PLAN or workflow edit.

- Commit: `f177392ad55553c044b1335fd1b906aa6bed3219`
- Parent/base: `16d9d8d9a398fe46361a5bf5aa46cf056aea9732`
- Branch: `fix/mermaid-block-completion`
- Isolated checkout: `/Users/joe/.t3/worktrees/spark/t3-16897076`
- Final working tree: clean.

## Change and preserved behavior

`parseBlocks` now records optional `closed` metadata on the actual code node at its existing closing-line boundary. A bare triple-backtick line with optional whitespace yields true; EOF and malformed closing lines yield false. Markdown uses that owned flag instead of a separate unstructured fence scan. The obsolete `completedCodeFences` helper is removed, and code memo equality includes closure.

Existing parsed block types, code content, language, and malformed-line consumption are preserved; the only parser result addition is code `closed`. Existing caller-created code nodes remain type-compatible because the field is optional. No parser-contract expectations were weakened. Original independent/duplicate fence, malformed fence and virtual-tail assertions now inspect parser-owned flags. Added parser cases cover details bodies, invalid/literal details, nested details, callouts, and closure-only memo updates.

Mermaid dispatch remains top-level only. Nested Mermaid in details/callouts continues rendering ordinary copyable code. Live segments remain ineligible even if virtually closed. Safe mode, giant response fallbacks, hostile-source sanctions, lazy loading, size/line checks and all unchanged Mermaid renderer sanitization/configuration limits remain in place.

Allowed files committed:

- `src/spark_cli/web/src/components/Markdown.tsx`
- `src/spark_cli/web/src/components/markdownParse.ts`
- `src/spark_cli/web/src/components/mermaidSafety.ts`
- `src/spark_cli/web/src/components/mermaidSafety.test.ts`
- NEW `src/spark_cli/web/e2e/mermaid-completion.mjs`

Existing `e2e/mermaid.mjs` was not edited or run; its independent harness repair remains lead-owned.

## Environment and exact commands/exits

Read AGENTS.md, CONTEXT.md, STRUCTURE.md, PLAN F05/F06/F07 scope, accepted ADR-0013, supplied `ui-r2.md` and `ui-r2-mermaid-probe.mjs`, existing parser/SSR/streaming and Mermaid tests. Initial `git status --short` was empty. The thread-owned branch initially pointed at old root `b3e4ea3a`; after verifying that it was the current clean checkout, moved it to the specified object using:

```
git switch --detach 16d9d8d
git branch -f fix/mermaid-block-completion 16d9d8d
git switch fix/mermaid-block-completion
```

Exit 0. An initial attempt to create an extra worktree with the same branch exited 255 because the branch already existed; no extra worktree was created.

All test/server invocations first sourced `/Users/joe/Developer/github/spark/.venv/bin/activate` and prepended `/Users/joe/.nvm/versions/node/v22.22.1/bin` to PATH. `node --version` -> `v22.22.1`; `node -p process.execPath` -> `/Users/joe/.nvm/versions/node/v22.22.1/bin/node` (exit 0). Manual source server/probe exported isolated `SPARK_HOME=/tmp/spark-mermaid-completion-state` and checkout-root `PYTHONPATH=$PWD/src`; no Python runtime/provider was launched. New browser fixture additionally launches Chromium with synthetic HOME/USERPROFILE/SPARK_HOME and own `src` PYTHONPATH; exact synthetic HOME is in its result.json. Browser commands set `PLAYWRIGHT_BROWSERS_PATH=/Users/joe/Library/Caches/ms-playwright`.

Commands below are relative to checkout root unless stated otherwise. All logs are in `/tmp/spark-merge-review-20261022/`.

1. `npm ci --ignore-scripts --prefix src/spark_cli/web`: exit 0; 399 packages installed, zero reported vulnerabilities. Log `mermaid-completion-npm-ci.log`. No lockfile changes.
2. In `src/spark_cli/web`: `node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5297 --strictPort`: server started successfully, serving this checkout's real Markdown. Stopped explicitly after probes (SIGINT exit 130). Log `mermaid-completion-vite.log`. An earlier launch before npm ci finished exited 1, MODULE_NOT_FOUND; corrected after install. This setup error is separate from defect reproduction.
3. BEFORE edits: `node /tmp/spark-merge-review-20261022/ui-r2-mermaid-probe.mjs`: exit 1; control actual 0, details+incomplete actual 1 versus expected 0. Log `mermaid-completion-before.log`, preserved JSON `mermaid-completion-before.json`.
4. AFTER edits: same exact review probe: exit 0; both cases actual 0. Log `mermaid-completion-after.log`, preserved JSON `mermaid-completion-after.json`. The supplied probe hardcodes the old reviewed SHA `2424ad77...` in its JSON; that metadata is stale. Its URL served our checkout at verified base `16d9d8d9` before and this repair after. No probe assertions were changed.
5. In web directory: `npx vitest run src/components/Markdown.test.ts src/components/markdownParse.streaming.test.ts src/components/mermaidSafety.test.ts src/components/markdownDetails.test.ts src/components/markdownCallout.test.ts`: exit 0; 5 files, 101 tests. Log `mermaid-completion-focused.log`.
6. `MERMAID_COMPLETION_OUTPUT=/tmp/spark-merge-review-20261022/mermaid-completion-browser node src/spark_cli/web/e2e/mermaid-completion.mjs`: exit 0; **38 actual mounted Markdown browser checks**, no page errors and only fixture-local requests, zero provider calls. Log `mermaid-completion-browser.log`; results `mermaid-completion-browser/result.json`; visually inspected screenshot `mermaid-completion-browser/combined.png` shows details -> callout -> ordinary code plus the completed top-level Mermaid SVG.
7. In web directory: `npm test`: exit 0; **88 files / 562 tests pass**. Log `mermaid-completion-full-tests.log`.
8. In web directory: `npm run lint`: exit 0. Log `mermaid-completion-lint.log`.
9. In web directory: `npx tsc -b`: exit 0. Log `mermaid-completion-types.log`.
10. `git diff --check` and `git diff --cached --check`: exit 0. Initial diff check caught and removed one new blank EOF line before committing.
11. `git add` explicitly listed only the five allowed files above; `git commit -m "fix: bind Mermaid completion to parsed code blocks"`: exit 0; `git status --short` empty.

The new browser probe covers incomplete alone; details/code + incomplete/malformed/complete; invalid and nested details literal fallback; callout/code; details/callout/code; callout/details/code; stream prefixes; virtual closure; actual closing line while live and after finalization; completed prefix during a longer stream; independent duplicate diagram sources; safe mode; >20k committed and streaming fallback; nested Mermaid as code; hostile source, 8,000-character and 150-line limits; final combined diagram. No backend or provider fixture is needed for this isolated rendering defect.

T3 preview status/open/navigation were also exercised. Initial open occurred before Vite started and returned `chrome-error://chromewebdata/`; corrected navigation after server startup succeeded. Browser acceptance evidence above uses the explicitly requested repository Playwright fixture workflow, not a claimed preview failure fallback.

## Limits / root acceptance

This is source and mounted-component browser evidence, not packaged/served production bundle, persisted Chat lifecycle, native macOS/Windows installation, physical audio, or hosted CI acceptance. No full Python run (lead owns it), build/bundle generation, real provider, external service, PR mutation or release action occurred. All unchanged renderer safety checks remain in source; this narrow browser probe exercises sanctions and character/line limits, not every unchanged sanitizer/output/edge limit anew. PR185 remains held for root integration, remaining fixes, native CI and final browser gates. Existing F04/F06 hosted failures are not closed by this repair.
