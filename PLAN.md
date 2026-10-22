# Spark issue and feature PR plan

Updated: 2026-10-22. Baseline: `64af0d26976714b747dd4f1cc5b495c47c7f7567` (`main`).

Deliver ten independently scoped defect fixes and ten useful features, each implemented by a delegated agent in an isolated worktree with a GitHub issue and pull request. Reference research uses current pinned revisions of [T3 Code](https://github.com/pingdotgg/t3code) and [Hermes Agent](https://github.com/nousresearch/hermes-agent), checked against existing Spark functionality.

## Status

**Merge/release phase active:** independent reviews are checking the published heads. Main is unchanged while concrete source blockers and shared-file integration are repaired. Desktop target: `1.4.0` (minor release for the ten features); no release is published yet.

**Delivery complete: 20/20 code PRs are published on GitHub — ten fixes and ten features.** All twenty branch heads match their GitHub PR heads and all are linked to the parent T3 thread. All assigned implementation/review workers have ended. No PR has been merged or release published. Validation and remaining acceptance gates are recorded below; publication does not imply every CI/native gate passed.

The previous upgrade plan and its unfinished performance/native gates are preserved in [the historical plan](docs/plans/app-upgrade-2026-10-15.md). Existing issues #130, #139 and #140 retain those gates. No historical acceptance is silently carried forward.

## Delivery rules

- Confirm each defect from current source and a focused reproduction; identify upstream source and the absent Spark capability for every feature.
- Each packet records issue, agent task ID, allowed paths, dependencies, acceptance flow and PR evidence. Use descriptive `fix/` and `feat/` branches.
- Isolated worktrees start at the committed baseline. Preserve unrelated dirty work; use synthetic `SPARK_HOME`; activate `.venv` for Python and verify Node 22 for frontend checks.
- Keep one writer for shared migrations, manifests, lockfiles and production bundles. Source PRs must disclose pending bundle/browser/package gates.
- Agents create and link their PRs, report exact head SHA/check results, and do not merge, publish releases or poll PRs. The lead checks results and links all deliverables to this thread.
- Run focused regressions and relevant lint/type/manifest/cache gates. Web/chat/gateway behavior also requires the documented browser flows. Do not mark unexecuted checks as passed.

## Packet tracker

| ID | Outcome | Status | Issue | Agent task | PR / evidence |
| --- | --- | --- | --- | --- | --- |
| I01 | Prevent uploads from following symlinks outside their storage root | Draft published; introduced typing errors fixed; Windows runtime unverified | [#145](https://github.com/automatedigital/spark/issues/145) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-I01-r1 | [#155](https://github.com/automatedigital/spark/pull/155) / `6ef55a4ef7ea` |
| I02 | Preserve existing attachments when uploading duplicate filenames | PR published; CI snapshot passes | [#146](https://github.com/automatedigital/spark/issues/146) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-I02-r1 | [#171](https://github.com/automatedigital/spark/pull/171) / `10ba28f595c5` |
| I03 | Route context and brief requests to the selected backend | PR published; CI pending | [#147](https://github.com/automatedigital/spark/issues/147) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-I03-r1 | [#167](https://github.com/automatedigital/spark/pull/167) / `f60fc342a7ad` |
| I04 | Fence stale token estimate responses after prompt or session changes | PR published; CI snapshot passes | [#148](https://github.com/automatedigital/spark/issues/148) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-I04-r1 | [#172](https://github.com/automatedigital/spark/pull/172) / `810b8f62dbb8` |
| I05 | Preserve exact Unicode and quoted paths in Git Changes | PR published; CI snapshot passes | [#149](https://github.com/automatedigital/spark/issues/149) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-I05-r1 | [#168](https://github.com/automatedigital/spark/pull/168) / `797c0667b6c6` |
| I06 | List nested untracked files and reject directory discard | PR published; CI snapshot passes | [#150](https://github.com/automatedigital/spark/issues/150) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-I06-r1 | [#173](https://github.com/automatedigital/spark/pull/173) / `f3c76d3a6df8` |
| I07 | Make canvas revision checks atomic with saves and deletion | PR published; CI pending | [#151](https://github.com/automatedigital/spark/issues/151) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-I07-resume-r3 | [#177](https://github.com/automatedigital/spark/pull/177) / `64ced2ca8271` |
| I08 | Preserve healthy memory databases during SQLite lock contention | PR published; CI snapshot passes | [#152](https://github.com/automatedigital/spark/issues/152) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-I08-r1 | [#166](https://github.com/automatedigital/spark/pull/166) / `4e8828a6ed22` |
| I09 | Prevent lost cron updates with cross-process mutation locking | PR published; CI e2e:CANCELLED | [#153](https://github.com/automatedigital/spark/issues/153) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-I09-r1 | [#169](https://github.com/automatedigital/spark/pull/169) / `4231e200ea55` |
| I10 | Preserve file permissions during atomic file and skill edits | PR published; CI snapshot passes | [#154](https://github.com/automatedigital/spark/issues/154) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-I10-r1 | [#175](https://github.com/automatedigital/spark/pull/175) / `0d3caa4cb141` |
| F01 | Recall sent prompts from composer history | PR published; CI snapshot passes | [#156](https://github.com/automatedigital/spark/issues/156) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-F01-r1 | [#176](https://github.com/automatedigital/spark/pull/176) / `a667b806b3b2` |
| F02 | Configure per-job models providers and skills in Schedule | PR published; CI pending | [#157](https://github.com/automatedigital/spark/issues/157) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-F02-resume-r3 | [#179](https://github.com/automatedigital/spark/pull/179) / `eb31f7fbfc02` |
| F03 | Export sessions as readable redacted Markdown | PR published; CI pending | [#158](https://github.com/automatedigital/spark/issues/158) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-F03-resume-r3 | [#182](https://github.com/automatedigital/spark/pull/182) / `314b876c4bde` |
| F04 | Save and restore a bounded prompt stash | PR published; bounded CI review complete; hosted failure remains open | [#159](https://github.com/automatedigital/spark/issues/159) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-F04-ci-review-r2 | [#170](https://github.com/automatedigital/spark/pull/170) / `a94d5487b6f7` |
| F05 | Render safe Mermaid diagrams in chat | PR published; local checks pass; CI queued at handoff | [#160](https://github.com/automatedigital/spark/issues/160) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-F05-resume-r3 | [#184](https://github.com/automatedigital/spark/pull/184) / `2a64ae895e08` |
| F06 | Render GitHub-style Markdown callouts | PR published; bounded CI review complete; hosted failure remains open | [#161](https://github.com/automatedigital/spark/issues/161) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-F06-ci-review-r2 | [#174](https://github.com/automatedigital/spark/pull/174) / `752034ee380b` |
| F07 | Render safe collapsible details in chat Markdown | PR published; CI pending | [#162](https://github.com/automatedigital/spark/issues/162) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-F07-resume-r3 | [#183](https://github.com/automatedigital/spark/pull/183) / `bab154185503` |
| F08 | Add opt-in notification sounds with preview | PR published; CI pending | [#163](https://github.com/automatedigital/spark/issues/163) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-F08-resume-r3 | [#180](https://github.com/automatedigital/spark/pull/180) / `7dcdcc106b98` |
| F09 | Browse bounded history of dashboard skill edits | PR published; CI pending | [#164](https://github.com/automatedigital/spark/issues/164) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-F09-resume-r3 | [#178](https://github.com/automatedigital/spark/pull/178) / `5b125dccd120` |
| F10 | Browse saved scheduled-job output | PR published; CI pending | [#165](https://github.com/automatedigital/spark/issues/165) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-F10-resume-r3 | [#181](https://github.com/automatedigital/spark/pull/181) / `e4081d9053b0` |

## Research and acceptance evidence

- Backend/tool audit: [six confirmed defects](docs/reviews/spark-backend-audit-2026-10-22.md), with 149 existing focused tests passing. B1, B2 and B5 selected for I08–I10; B3/B4/B6 retained as follow-up findings outside the requested ten fixes.
- Web/API/gateway audit: [seven current findings](docs/reviews/spark-web-audit-2026-10-22.md); five isolated API reproductions, two frontend source traces. Browser acceptance remains open.
- Current upstream comparison: [pinned source review](docs/reviews/spark-reference-audit-2026-10-22.md). T3 `f054d1b8018721bd997d99cbb918a7b17bf098a4`; Hermes `8237c7f8ec179c88857f24a174509d985af704b7`. Selected research F01/F02/F03/F07/F08/F09/F10/F12/F13/F14; packet numbering below is the authoritative delivery mapping.

### Lead source checks

Isolated cron CRUD probes on the baseline confirmed three candidates: `every 0m` is accepted, `update_job` permits changing the durable job ID, and updating legacy `skill` leaves the old canonical `skills` value in place. These require audit reconciliation and separate acceptance scoping before selection; they are not yet counted as delivered fixes.

### Research task identities

All use inherited Codex `gpt-6.1-sol`, medium reasoning, default service tier, read-only source scope.

- backend: `node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-audit-backend-r1` (running).
- web: `node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-audit-web-r1` (running).
- features: `node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-audit-features-r1` (running).

## Packet scopes and dependencies

- **I01**: src/spark_cli/workspace_routes.py upload handlers and a new focused upload safety test module. Dependency: none. Acceptance: finding W05 in the web audit.
- **I02**: workspace upload handlers, upload response mapping in ChatPanel if needed, focused attachment tests. Dependency: I01: same upload handlers; launch after its PR is ready. Acceptance: finding W06 in the web audit.
- **I03**: web/src/lib/context.ts, summarize-file call in ChatPanel.tsx, focused transport tests. Dependency: none. Acceptance: finding W01 in the web audit.
- **I04**: web/src/hooks/useTokenEstimate.ts, optional signal parameter in context.ts, hook tests. Dependency: I03: shared context client; launch after its PR is ready. Acceptance: finding W02 in the web audit.
- **I05**: workspace_routes.py Git status/numstat parser and focused Git route tests. Dependency: none; keep away from upload handler changes. Acceptance: finding W03 in the web audit.
- **I06**: workspace_routes.py Git status invocation and revert validation, focused Git tests. Dependency: I05: shared Git parser; launch after its PR is ready. Acceptance: finding W04 in the web audit.
- **I07**: src/spark_cli/canvas_routes.py and new focused concurrency tests. Dependency: none. Acceptance: finding W07 in the web audit.

- **I08**: src/plugins/memory/holographic/store.py and tests/plugins/memory/test_holographic_recovery.py. Dependency: none. Acceptance: finding B1 in the backend audit.

- **I09**: src/cron/jobs.py and focused tests/cron concurrency tests. Dependency: none. Acceptance: finding B2 in the backend audit.

- **I10**: src/tools/file_operations.py, src/tools/skill_manager_tool.py and their focused tests. Dependency: none. Acceptance: finding B5 in the backend audit.

- **F01** (F01): new lib/composerPromptHistory.ts, PromptBar.tsx, narrow ChatPanel history prop, focused tests. Dependency: coordinate composer props with F04; no source dependency. Acceptance: History from loaded user messages only, Up/Down caret guards, restore unsent draft, editable recall with no automatic send; thread changes retire history ownership.

- **F02** (F02): cron_routes.py, api_cron.ts, CronJob type in apiTypes.ts, CronPage.tsx, focused tests. Dependency: I09 owns jobs.py locking; do not edit jobs.py. F10 owns separate output component/module.. Acceptance: Expose existing backend model/provider/ordered skills on create/edit/clear. Reuse resolved providers and installed skills. Do not hardcode providers or add custom URLs/scripts. Prefer canonical skills patches to avoid legacy-skill bug. Real fixture round trips, no provider calls.

- **F03** (F03 and B01): new spark_cli/session_export_markdown.py, session_export.py, core/cli/session_ops_mixin.py export dispatch, commands.py export help, focused tests. Dependency: include mandatory B01 nested export sanitation as a bounded prerequisite in this PR. Acceptance: Add /export --format markdown, retain JSON default. Recursively redact nested tool arguments/outputs and preserve input objects; synthetic fake secrets absent in final bytes. Treat nested redaction as required prerequisite, no automatic publishing or Gist calls. Include roles/timestamps and safely fenced code.

- **F04** (F07): new lib/promptStashStore.ts and chooser component, narrow ComposerMoreMenu/PromptBar integration, tests. Dependency: F01 also touches composer; keep helper/component independent and minimal integration hunks. Acceptance: Explicitly saved text-only prompts, bounded list, restore without silently discarding a nonempty draft, delete, backend/profile-scoped persistence, honest storage failure. No attachment capture claim.

- **F05** (F08): new diagram component/helper, Markdown.tsx minimal dispatch, focused tests; sole owner web/package.json and package-lock.json if needed. Dependency: sole lockfile writer; F06/F07 may touch Markdown.tsx but own separate components/parser variants. Acceptance: Lazy strict Mermaid rendering completed fences only; partial streaming remains code. Source/copy/error fallback, safeMode and size caps, block hostile links/HTML. Exact-pin dependency using verified Node22 nested lockfile. Do not update unrelated deps.

- **F06** (F09): markdownParse.ts callout parser variant, Markdown renderer dispatch, small callout component, tests. Dependency: F07 shares parser: keep separate named parse helper and discriminated variant; document integration order F06 then F07. Acceptance: NOTE TIP IMPORTANT WARNING CAUTION accessible callouts, generic blockquotes unchanged. Test multiline, stream splits, unknown markers, code fences, keyboard/screenreader labels/theme.

- **F07** (F10): markdownParse.ts details parser variant, new Details renderer, Markdown minimal dispatch, tests. Dependency: F06 shares parser; avoid wholesale parser rewrite, integrate F06 before F07. Acceptance: Narrow details/summary grammar only, native accessible disclosure, literal malformed/streaming fallback. No arbitrary HTML/events/attributes. Fences inside details, escaping, copyability and bounded rendering.

- **F08** (F12): notificationPolicy.ts, small sound helper, NotificationBell.tsx and existing settings controls, tests. Dependency: none; no lockfile or external audio asset required. Acceptance: Opt-in completion/input sounds, explicit gesture preview, respect existing quiet/project mute/dedupe policy. Cooldown across simultaneous completions, handle autoplay denial, no per-token audio and no external sound services.

- **F09** (F13): new profile-local skill history helper, dashboard skill save route seam, SkillsToolsPage history drawer, focused tests. Dependency: I10 edits skill_manager_tool.py permissions; do not edit that file. No DB migration.. Acceptance: Read-only before/after history for dashboard edits ONLY; clearly label coverage excludes external editors and agent edits. Atomic bounded snapshots, profile isolation, concurrent save behavior; no rollback button or broad ledger claims.

- **F10** (F14): new cron output route/helper or focused cron_routes extension, API helper, standalone output drawer and CronPage entry point, tests. Dependency: F02 edits cron types/page; keep separate module/component and minimal entry-point hunk. Do not edit jobs.py.. Acceptance: List/read/copy existing saved per-job Markdown output, newest first. Call it saved output history, not authoritative attempts/delivery. Bound page size/read bytes, validate IDs and exact safe filenames, reject symlink/traversal, missing/pruned files gracefully. No provider run needed.

### I01 draft review

PR #155 at `4ab637f8087e683a0c5ce9afcc2db2ac4ffb33b0`: 25 focused and 69 combined neighbor tests pass; 13 regression tests failed before repair. Scoped Ruff passes; full-source 299 errors match baseline. Browser-origin multipart smoke passes, shipped UI unverified. **Unaccepted:** unsupported platforms including Windows return 501 for normal uploads; lead requires a portability correction before acceptance.

### Implementation delegation

All **20 dedicated implementation agents have been created**: I01–I10 and F01–F10, each in an isolated worktree with its own scoped branch/PR assignment. The three completed research agents are additional. Agent tasks preserve inherited Codex gpt-6.1-sol, medium reasoning and default service tier. Concurrent shared-file hunks are reviewed/rebased in the recorded integration order; only F05 may write the npm lockfile. No agent may write the tracker or production bundle.

I01 portability correction is delegated in a fresh isolated worktree, starting from PR155 head; it updates that same PR and must preserve normal Windows uploads rather than returning blanket 501.

### I08 lead verification

PR [#166](https://github.com/automatedigital/spark/pull/166), head `4e8828a6ed220ed3d098030f3773ea2a27335970`: lead reviewed the two-file diff and independently ran recovery/dedup/auto-extract neighbors with isolated SPARK_HOME and this worktree src: **25 passed**, exit 0. Agent records 11 failing-before regressions, 16 focused/25 neighbors passing, scoped Ruff clean, identical 299 full-source baseline Ruff errors. CI snapshot: frontend lint/types/tests and mypy passed; remaining checks still running. No full-suite/package/provider acceptance claimed; not merged.

### I03 lead review

PR [#167](https://github.com/automatedigital/spark/pull/167), head `f60fc342a7adb265c8073b278149089032357b28`: lead reviewed the three-file transport/test diff and independently reran **39 focused tests**, exit 0, using verified Node v22.22.1. Agent records 13 baseline failures, **468 full frontend tests**, clean lint/TypeScript and rendered Summarize/brief fixtures passing against the selected backend with authorization. Synthetic provider responses; stale token estimate behavior belongs to I04. Hosted CI and package/bundle acceptance remain unverified.

I03 lead environment correction: the first independent 39-test run passed under the shell-default Node **25.8.0**, so it was not valid Node-22 acceptance. The lead then explicitly prepended `/Users/joe/.nvm/versions/node/v22.22.1/bin`, verified version/executable, and repeated the same 39 tests successfully under **v22.22.1**. The earlier run is retained as a non-acceptance attempt.

## Resume checkpoint — 2026-10-22

- User requested all sub-agent work finished and every PR on GitHub. Pause revoked; stopped checkouts are preserved read-only while new delegated tasks recover their work.
- GitHub confirms twelve code PRs: #155, #166–#176. All twelve are registered to the parent T3 thread; #144 is the separate tracker PR.
- Snapshot passes on #155, #166–#168, #171–#173, #175–#176; #169 e2e still running. #155 still has a known Windows compatibility blocker despite passing CI.
- #170 fails the third repeated longthread browser attempt after two passes; #174 fails inspector scroll drift `(1000, 1410)`. F04/F06 bounded review tasks must inspect exact artifacts and compare/reproduce before any fix or retry. No assertion is waived, no blind CI rerun.
- Original interrupted tasks I04/I06/I10/F01/F06 produced committed/pushed PRs around interruption; their PR bodies and source/check snapshots are retained as evidence, not inferred from terminal task status.

I01 capacity reassignment: recovery round3 failed before execution with `Selected model is at capacity. Please try a different model.` Original work remains preserved. A fresh live-catalog Codex `gpt-6-astra` task (medium/default options) owns the same PR155 correction: `node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-I01-portability-astra-r4`. No duplicate live worker or new PR.

### I07 delivery and lead verification

GitHub PR [#177](https://github.com/automatedigital/spark/pull/177), exact published head `64ced2ca82718903da24cb53f4c34eaaa5c9f022`, preserves the stopped commit. Lead reviewed the canvas source diff and independently reran concurrency/routes/tool neighbors: **26 passed**, exit 0. Agent two-tab fixture demonstrates 200/409 conflict, reload and stale-save-after-delete rejection. Windows lock runtime and full-app/package flows remain unverified; CI pending. [Full evidence](docs/reviews/I07-canvas-delivery-result.md).

## Published feature checkpoint

GitHub confirms F09 #178, F02 #179, F08 #180, F10 #181, F03 #182 and F07 #183 in addition to the earlier thirteen code PRs. All are registered to this thread. **F05 Mermaid is the sole unpublished packet**. Reports arriving after PR publication are still reconciled before delivery acceptance.

F02 #179: published head `eb31f7fbfc02e8ba2b78d6c3c09de894fc36ab4e`; agent evidence **129 Python / 448 frontend tests**, browser create/edit/order/clear round trip, lint/types/mypy and isolated build pass. F08 #180 reports **456 frontend tests** and real Chromium sound preview; installed desktop audio unverified. F09 #178 reports **65 Python / 448 frontend tests** and read-only history browser flow; Windows/packages unverified.

I01 portability recovery is published at `8987f857f2dd2ce1da96a4f04de7e738402faaf7`: **74 tests pass, 11 native-Windows cases skip** locally. Blanket501 is removed, but draft acceptance still requires Windows runtime evidence. New Ubuntu mypy-ratchet has ten Windows-API attribute/return errors; the lead fetched the actual completed job log via jobs API and delegated a focused platform-typing correction, not a blind rerun.

### Final handoff receipts for F03 / F07 / F10

- F03 #182: published head `314b876c4bde42f7696235461c4729ce80d94472`; **166 focused tests**, changed-file Ruff/full app mypy and real SQLite CLI export flow pass. Mandatory nested redaction included; manifest import check timed out twice and remains unverified.
- F07 #183: published head `bab15418550385c1ca73a3480900733a6f98a962`; **464 frontend tests**, Node22 lint/types/build/budget and toggle/copy/safety browser fixture pass. Browser find did not reveal collapsed content; F06 must integrate first.
- F10 #181: published head `e4081d9053b004e375eca472c86aaa00027ddce9`; **88 Python / 448 frontend tests**, browser saved-output flow, lint/types/build/budget pass. Windows output browsing remains unsupported/unverified; no claim of native Windows feature acceptance.

All three stopped checkouts remain preserved, recovery checkouts clean, and exact commands/limits are in the corresponding linked delivery reports.

### F06 bounded CI review complete

PR #174 remains at `752034ee380b03e8d64de172543900582915e38c`. The original hosted `(1000, 1410)` scroll failure is **unverified/open**. One unchanged candidate inspector gate and one baseline gate pass all 11 checks with `1000 → 1000px`, no page errors. No introduced cause reproduced, no source change/push/CI rerun or threshold relaxation. Fresh lint/types/**457 frontend tests**, isolated build/budget, six pytest cases and callout browser flow pass. [Review evidence](docs/reviews/F06-ci-delivery-result.md). This closes the bounded investigation, not the failed hosted acceptance gate.

### F04 bounded CI review complete

PR #170 remains at `a94d5487b6f747a612a11591b0a9fac1c0350fbf`. Latest hosted artifact establishes duplicate history cursor failure. Local candidate fixed-three-attempt batch: **startup navigation timeout**, then **two passes**; baseline comparison passes. Hosted duplicate-cursor failure remains unreproduced/unresolved. Lint/types, eight stash tests and feature browser flow pass. No source change/push/speculative fix/CI rerun or relaxed assertion. [Exact evidence](docs/reviews/F04-ci-delivery-result.md). Bounded review is finished; hosted acceptance is still open.

### I01 type correction delivered

PR #155 published head `6ef55a4ef7ea53924c94ed962f776cd9db582151`, verified via GitHub. Eight-line platform-guard/narrowing repair resolves the ten introduced Ubuntu mypy errors without suppressions. Standard and explicit Linux mypy pass **133 files**; upload neighbors **74 pass / 11 native-Windows skips**; scoped Ruff passes. Windows-target static diagnostics fall from 40 to 31 with no new upload-helper errors, but native Windows runtime remains unverified. PR stays draft. [Exact evidence](docs/reviews/I01-type-delivery-result.md). This assigned correction is complete; no CI success or native acceptance inferred.

## Final publication verification — 2026-10-22

- [x] Ten independently scoped issue-fix code PRs published, linked and remote heads verified.
- [x] Ten independently scoped feature code PRs published, linked and remote heads verified.
- [x] Original paused worktrees, uncommitted source and unrelated handoff move preserved.
- [x] All assigned sub-agent implementation/review work has ended; no queued/running child remains.
- [x] PRs, exact heads and check snapshot retained in [the publication manifest](docs/reviews/october-2026-pr-manifest.json).

F05 #184 publishes lazy strict Mermaid rendering with source/copy/error fallback, size caps, sanitation, themes and cancellation. Agent checks: **470 frontend / 14 backend tests**, lint/types/build/initial bundle budget and persisted-chat browser flows pass. Exact-pinned Mermaid/DOMPurify are the sole programme dependency changes. Existing Vite audit advisory is byte-identical to baseline; repository Ruff retains 299 baseline errors. [Full handoff](docs/reviews/F05-delivery-result.md).

### Remaining acceptance and integration boundaries

- I01 #155 remains draft: Windows implementation and cross-platform typing are present, but native Windows runtime proof is missing (11 tests skipped locally). F10 Windows saved-output browsing remains unsupported/unverified.
- F04 #170 and F06 #174 retain failed hosted browser gates after bounded candidate/base comparisons did not reproduce an attributable source defect. No speculative fix, blind rerun or threshold relaxation was made.
- Other hosted checks may still be queued/running; the manifest is a snapshot, not a monitoring claim. F03 manifest-import timeout and baseline lint/type/audit findings remain disclosed in reports.
- Independent PRs require integration/rebase in recorded order: I01→I02 upload handlers, I03→I04 context transport, I05→I06 Git status, F06→F07 Markdown parser; retain F05 diagram dispatch alongside both. F01/F04 composer and F02/F10 Schedule page hunks also need reconciliation. Source PRs do not include a combined production bundle.
- No full integrated branch/browser/package/rollout acceptance is claimed. These PRs are delivered for review; merging and release remain separate work.

## Merge and release review — 2026-10-22

User authorized: independently review every PR, merge safe work, rebuild apps and release. Four review agents cover all twenty actual heads; lead owns the isolated combined branch and all bundle/lockfile/version writes.

- Backend: #166/#169/#175/#178 source-safe; #182 blocked by structured/numeric credential export leakage.
- Composer: #167/#172 source-safe, #180 source-safe pending required e2e; #176 blocked by demonstrated unsent-draft loss on recall/navigation; #170 held for the unresolved hosted history gate.
- Rendering/Schedule: #183 source-safe; #174 hosted browser failure; #184 inherited Vite audit and independent browser validation; #179 stable skill identity mismatch; #181 Windows unsupported output API exposed by UI.
- Workspace: all five original heads held for demonstrated file/lock boundary defects. No blanket merge of the original heads.

Integration now retains all twenty original heads and expected conflict resolutions in a separate checkout. Upload containment/identity composition, credential redaction, composer draft preservation and cron identity/capability repairs are separately delegated. Vite exact pin updated to **7.3.7**, npm reports **zero vulnerabilities**; existing audit/security threshold retained. Added Linux/Windows persistence contract gate so native Windows upload/lock proof cannot be inferred from macOS-only checks.

Apple agreement: service returned 403; account holder reports agreement accepted. Immediate recheck still returned 403 for team GW2S46PJR7. Recheck at notarization stage; do not distribute an ad-hoc or unnotarized Mac release as signed/notarized.

### Review findings and first integrated repairs

All twenty original heads independently reviewed. Workspace review holds #155/#171/#168/#173/#177 for demonstrated permission, UTF-8 component budget, Git raw-byte transport, newly exposed symlink discard and canvas target/lock lifetime defects. Full verdicts are in docs/reviews/october-merge-* reports. No original unsafe head is approved merely because CI passed.

Integrated anchored/exclusive upload allocation (`a38698e`), structured credential-field redaction (`a0662f6`), and lead upload permission/byte-budget fix. New permission/multibyte tests fail **3/3 before** and focused upload set passes **51 / 11 Windows skips** after; an ancestor substitution at root-open is rejected. First combined frontend checks pass **548 tests**, lint and TypeScript. Standard mypy with explicit checkout PYTHONPATH passes **137 files**; an initial run lacking checkout import ownership produced unrelated import-scope errors and is not acceptance.

Remaining source repairs: composer durable original draft, cron skill identity/output capability, Git unsupported-name/exact-discard boundaries, canvas lexical target and profile-owned lock identity. Native Linux/Windows persistence contracts and final integrated browser/runtime checks remain required before merge.

### Integrated repair checkpoint

- Anchored immutable uploads and structured export credential redaction integrated. Lead added UTF-8 byte-budget collision allocation and restored search-only ancestor compatibility with inode confirmation.
- Scheduler-resolvable skill identities and honest saved-output capability/UI integrated; **100 backend tests pass** independently.
- Git non-UTF-8 rows are safely disabled; normal names remain exact; literal pathspecs and lexical symlink discard preserve unrelated targets. Combined Git/files/upload set: **118 pass / 11 Windows-only skips**, exit 0.
- Canvas and composer source repairs remain active; no merge or release yet.
- **Apple notarization preflight now succeeds** after the account holder accepted the agreement: service reports successfully received submission history. The earlier 403 blocker is cleared. This is credential/service readiness, not artifact notarization.

### Canvas repair integrated

Canvas lexical target validation and profile-owned stable lock identities integrated at `3a3e2005`. Lead independently reran concurrency/routes/tool cases: **38 passed**, exit 0. Unsafe final symlinks are rejected, reads verify file identity, and project Files/Git actions cannot remove the new profile lock sidecars. Detailed evidence: [canvas repair](docs/reviews/october-canvas-boundaries-result.md).

A fresh independent storage/backend review now examines the corrected combined snapshot. Composer repair is still running. Full non-network Python suites are running sequentially (parallel-safe selection followed by serial selection). Native Windows persistence proof and final combined browser gates remain unchecked; no GitHub merge or desktop release yet.
