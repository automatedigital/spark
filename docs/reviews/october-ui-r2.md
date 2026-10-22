# Combined UI review, round 2

Verdict: **BLOCKED** by one reproduced P2 integration defect. Reviewed exact source `2424ad77afe3a293c529569b7a0ca39a3606858d` in own clean checkout `/Users/joe/.t3/worktrees/spark/t3-f9ed1dc3`, detached from older initial HEAD before review. No source edits, commits, pushes, merges, publication, hosted reruns, watchers or delegation. PR185 linked to this thread.

## Finding UI-R2-01 — bind Mermaid completion to its parsed code block

P2; F05 Mermaid + F07 details integration. `src/spark_cli/web/src/components/Markdown.tsx:211-220`, especially line 217; helper `src/spark_cli/web/src/components/mermaidSafety.ts:19-26`.

`completedCodeFences(segment.text)` counts fences inside disclosures, while `parseBlocks` returns a disclosure as one top-level details/literal node. The renderer increments `fenceIndex` only for top-level code nodes. Thus a following Mermaid block borrows the completion flag of the code inside details. An unfinished or malformed Mermaid fence can be promoted to an SVG diagram on final/nonstreaming rendering. This violates F05's explicit completed-fence contract; it is a combined-source defect, not evidence that the old hosted failures are fixed or caused by these features. No sanitization bypass or code execution is claimed.

Reproducer (no closing fence after A-->B):

~~~~text
<details>
<summary>Evidence</summary>
```text
plain
```
</details>

```mermaid
graph LR
A-->B
~~~~

Actual parser: `[details, code(lang=mermaid)]`; completion flags `[true, false]`. Renderer consumes `true` for the Mermaid node. Real mounted Markdown in T3 preview produced one `Rendered Mermaid diagram`. Control with only the unfinished Mermaid source produced zero diagrams and ordinary code. A malformed closing line ` ```bad ` reproduces the same mismatch. Screenshot visually inspected.

Independent executable reproduction:

- Start this exact checkout's Vite from `src/spark_cli/web`: `/Users/joe/.nvm/versions/node/v22.22.1/bin/node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5297 --strictPort`.
- With shared `.venv` active and `PLAYWRIGHT_BROWSERS_PATH=/Users/joe/Library/Caches/ms-playwright`, run `/Users/joe/.nvm/versions/node/v22.22.1/bin/node /tmp/spark-merge-review-20261022/ui-r2-mermaid-probe.mjs`.
- Exit **1**, assertion `details then incomplete: incomplete Mermaid must stay code`, actual **1**, expected **0**. Control passed with 0. `ui-r2-mermaid-probe.json`, `ui-r2-mermaid-probe.log`, `ui-r2-mermaid-failure.png` are beside this report.

Required disposition: preserve completion ownership for the actual parsed code node, with combined disclosure/code/Mermaid coverage. Retain the incomplete/malformed/live-tail/safe-mode rules and existing assertions. No speculative fix was made in review.

## Prior findings and combined-source checks

- F01 #176 original unsent draft loss: discharged for this snapshot by source inspection and fresh real ChatPanel/SQLite/replay browser pass. Recovery is synchronously flushed before destructive recall, keyed by the confirmed backend/profile/project/thread draft scope; browse state also includes panel owner. No cleanup writes through a replacement owner. Recovery remains independently available through A/B/A, unmount/reload and explicit accepted/rejected send; restore swaps rather than drops edited text. Storage failure blocks destructive recall. Fresh cross-history/stash flow retires browse/caret and preserves restored stash through Down and A/B/A. No automatic sends; exactly two explicit fixture sends, no provider calls.
- F02 #179 skill identifier contract: discharged by current catalog/path resolution, actual ID payloads and fresh browser/backend tests. Duplicate display labels remain distinct folder IDs, nested paths persist and scheduler instructions load in the saved order. Ambiguous installed paths fail closed; canonical empty skills beat legacy skill values. UI option labels are strings compatible with the custom Select.
- F10 #181 capability honesty: discharged by backend capability predicate shared with safe accessor and disabled-by-default UI. Fresh supported and actual-backend unsupported simulations pass: disabled Outputs, visible reason, output endpoint still 503. Directory-relative/no-follow/regular-file/read/paging boundaries retained. Native Windows remains a separate gate.
- F05 #184 inherited Vite advisory: exact Vite 7.3.7 source/lock pin retained, frozen install succeeds and reports zero vulnerabilities. Final hosted supply-chain gate still required. The new UI-R2-01 blocks a clean combined source verdict regardless of audit success.
- F06/F07 callout/details union, dispatch, memo comparison, literal fallback, details-aware segment boundaries and bounded callout recursion are retained. Focused parser/SSR tests pass; the independently reproduced Mermaid completion mismatch is an uncovered cross-feature case.
- I03 #167 / I04 #172: resolved context client retains shared fetchJSON backend/auth capture and optional AbortSignal. Token estimate cleanup retires callbacks before abort and clears old estimates during debounce. Focused transport/ownership tests pass. Existing backend/profile application reload semantics remain; no broader same-ID live profile epoch guarantee is inferred.
- F08 #180: source retains default-off sound preferences, gesture previews, semantic terminal/decision classification, bounded dedupe/cooldown, quiet/mute policy and existing SSE auth. Focused tests pass; physical installed-app audio not tested.
- F09 #178: encoded skill IDs and keyed drawer ownership retained; history uses profile-local lock and bounded atomic storage, escaped before/after text and honest dashboard-only coverage. Fresh backend history tests pass. No new skill-history browser run here.
- F03 #182 export is assigned to the other backend reviewer; no independent full export verdict is made here.

## Fresh checks and exits

All Python/test/server commands activated `/Users/joe/Developer/github/spark/.venv`. Python import path was this checkout's `src`; browser fixtures further synthesize HOME/USERPROFILE/SPARK_HOME. Actual Node verified **v22.22.1**, `/Users/joe/.nvm/versions/node/v22.22.1/bin/node`. No live profile/provider used.

- `npm ci --ignore-scripts --prefix src/spark_cli/web`: exit 0, zero vulnerabilities reported; `ui-r2-npm-ci.log`.
- In web directory, `npx vitest run src/lib/composerPromptHistory.test.ts src/lib/composerPromptRecovery.test.ts src/lib/promptStashStore.test.ts src/lib/context.test.ts src/hooks/useTokenEstimate.test.ts src/components/markdownCallout.test.ts src/components/markdownDetails.test.ts src/components/mermaidSafety.test.ts src/lib/notificationSound.test.ts`: exit 0, **9 files / 104 tests**; `ui-r2-focused.log`.
- `python -m pytest tests/spark_cli/test_cron_overrides.py tests/test_cron_output_routes.py tests/spark_cli/test_skill_history.py -q -n 0 -m 'not integration and not network'`: exit 0, **36 passed**; `ui-r2-python.log`.
- `COMPOSER_HISTORY_OUTPUT=/tmp/spark-merge-review-20261022/ui-r2-composer node src/spark_cli/web/e2e/composer-history.mjs`: exit 0; six compound acceptance flows, no page errors, two explicit synthetic sends; `ui-r2-composer.log`, `ui-r2-composer/result.json`.
- `node src/spark_cli/web/e2e/cron-overrides.mjs`: exit 0; `ui-r2-cron-overrides.log` records fixture evidence directory.
- `node src/spark_cli/web/e2e/cron-outputs.mjs`: exit 0; supported and unsupported backend/UI flows; `ui-r2-cron-outputs.log`.
- T3 preview status/open/navigation/evaluation: successful real combined Markdown probe on own tab. Then repository-documented Playwright workflow used for executable evidence; no preview failure/fallback claim.
- `node /tmp/spark-merge-review-20261022/ui-r2-mermaid-probe.mjs`: exit 1, intentional finding reproduction as above.
- `git diff --check`: exit 0; final `git status --short` empty; exact reviewed HEAD unchanged.
- One initial manual Vite start used a doubled relative source path and exited 1 (MODULE_NOT_FOUND); corrected command above started successfully. This setup error is separate from the reproduced source assertion.

## Limits and final gates

Read AGENTS.md, CONTEXT.md, STRUCTURE.md, original composer/rendering reviews, recovery/cron repair reports and exact bounded F04/F06 CI comparison reports. Did not duplicate lead's full frontend/Python/lint/type/build runs or build generated bundles. No installed package/native Windows/physical audio acceptance, real providers, release, publication, hosted job reruns or monitoring.

F04 historical repeated-longthread duplicate cursor `before_id=2401` and F06 inspector scroll `(1000,1410)` remain unresolved. Bounded local comparisons in `docs/reviews/F04-ci-delivery-result.md` and `F06-ci-delivery-result.md` do not attribute or close those hosted failures. No thresholds/assertions were weakened; no speculative fixes proposed for them. Required final hosted browser/CI gates in PR185, generated production bundle verification, and separate macOS/Windows package/install/release gates remain mandatory after fixing the source finding. This review does not authorize merge/build/release by itself and does not claim the other backend review is complete.
