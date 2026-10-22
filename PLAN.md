# Spark issue and feature PR plan

Updated: 2026-10-22. Baseline: `64af0d26976714b747dd4f1cc5b495c47c7f7567` (`main`).

Deliver ten independently scoped defect fixes and ten useful features, each implemented by a delegated agent in an isolated worktree with a GitHub issue and pull request. Reference research uses current pinned revisions of [T3 Code](https://github.com/pingdotgg/t3code) and [Hermes Agent](https://github.com/nousresearch/hermes-agent), checked against existing Spark functionality.

## Status

**Complete: all twenty code PRs merged and Desktop 1.4.0 released.** All twenty code PRs and tracker #144 merged through [#185](https://github.com/automatedigital/spark/pull/185) into main at `824ea1e4e17444e34fe1c14b6581d29d54d205e9`. GitHub confirms all twenty issues closed. Exact reviewed head `98e393d4` passed all eight hosted checks, including native Windows persistence and every retained browser gate. Desktop **1.4.0** is [published](https://github.com/automatedigital/spark/releases/tag/desktop-v1.4.0) from that merge commit. macOS is Developer ID signed/notarized/stapled; Windows is an unsigned x64 beta. All three public release downloads were retrieved without authentication and verified against local SHA-256 hashes.

Publication and merge evidence are retained below. Historical failed checks are superseded by final exact-head passing acceptance, with all source repairs and test preconditions documented. Package signing/notarization/lifecycle and public asset verification passed separately, as recorded below.

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
| I01 | Prevent uploads from following symlinks outside their storage root | Merged via #185; final CI passed | [#145](https://github.com/automatedigital/spark/issues/145) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-I01-r1 | [#155](https://github.com/automatedigital/spark/pull/155) / `6ef55a4ef7ea` |
| I02 | Preserve existing attachments when uploading duplicate filenames | Merged via #185; final CI passed | [#146](https://github.com/automatedigital/spark/issues/146) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-I02-r1 | [#171](https://github.com/automatedigital/spark/pull/171) / `10ba28f595c5` |
| I03 | Route context and brief requests to the selected backend | Merged via #185; final CI passed | [#147](https://github.com/automatedigital/spark/issues/147) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-I03-r1 | [#167](https://github.com/automatedigital/spark/pull/167) / `f60fc342a7ad` |
| I04 | Fence stale token estimate responses after prompt or session changes | Merged via #185; final CI passed | [#148](https://github.com/automatedigital/spark/issues/148) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-I04-r1 | [#172](https://github.com/automatedigital/spark/pull/172) / `810b8f62dbb8` |
| I05 | Preserve exact Unicode and quoted paths in Git Changes | Merged via #185; final CI passed | [#149](https://github.com/automatedigital/spark/issues/149) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-I05-r1 | [#168](https://github.com/automatedigital/spark/pull/168) / `797c0667b6c6` |
| I06 | List nested untracked files and reject directory discard | Merged via #185; final CI passed | [#150](https://github.com/automatedigital/spark/issues/150) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-I06-r1 | [#173](https://github.com/automatedigital/spark/pull/173) / `f3c76d3a6df8` |
| I07 | Make canvas revision checks atomic with saves and deletion | Merged via #185; final CI passed | [#151](https://github.com/automatedigital/spark/issues/151) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-I07-resume-r3 | [#177](https://github.com/automatedigital/spark/pull/177) / `64ced2ca8271` |
| I08 | Preserve healthy memory databases during SQLite lock contention | Merged via #185; final CI passed | [#152](https://github.com/automatedigital/spark/issues/152) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-I08-r1 | [#166](https://github.com/automatedigital/spark/pull/166) / `4e8828a6ed22` |
| I09 | Prevent lost cron updates with cross-process mutation locking | Merged via #185; final CI passed | [#153](https://github.com/automatedigital/spark/issues/153) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-I09-r1 | [#169](https://github.com/automatedigital/spark/pull/169) / `4231e200ea55` |
| I10 | Preserve file permissions during atomic file and skill edits | Merged via #185; final CI passed | [#154](https://github.com/automatedigital/spark/issues/154) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-I10-r1 | [#175](https://github.com/automatedigital/spark/pull/175) / `0d3caa4cb141` |
| F01 | Recall sent prompts from composer history | Merged via #185; final CI passed | [#156](https://github.com/automatedigital/spark/issues/156) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-F01-r1 | [#176](https://github.com/automatedigital/spark/pull/176) / `a667b806b3b2` |
| F02 | Configure per-job models providers and skills in Schedule | Merged via #185; final CI passed | [#157](https://github.com/automatedigital/spark/issues/157) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-F02-resume-r3 | [#179](https://github.com/automatedigital/spark/pull/179) / `eb31f7fbfc02` |
| F03 | Export sessions as readable redacted Markdown | Merged via #185; final CI passed | [#158](https://github.com/automatedigital/spark/issues/158) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-F03-resume-r3 | [#182](https://github.com/automatedigital/spark/pull/182) / `314b876c4bde` |
| F04 | Save and restore a bounded prompt stash | Merged via #185; final CI passed | [#159](https://github.com/automatedigital/spark/issues/159) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-F04-ci-review-r2 | [#170](https://github.com/automatedigital/spark/pull/170) / `a94d5487b6f7` |
| F05 | Render safe Mermaid diagrams in chat | Merged via #185; final CI passed | [#160](https://github.com/automatedigital/spark/issues/160) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-F05-resume-r3 | [#184](https://github.com/automatedigital/spark/pull/184) / `2a64ae895e08` |
| F06 | Render GitHub-style Markdown callouts | Merged via #185; final CI passed | [#161](https://github.com/automatedigital/spark/issues/161) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-F06-ci-review-r2 | [#174](https://github.com/automatedigital/spark/pull/174) / `752034ee380b` |
| F07 | Render safe collapsible details in chat Markdown | Merged via #185; final CI passed | [#162](https://github.com/automatedigital/spark/issues/162) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-F07-resume-r3 | [#183](https://github.com/automatedigital/spark/pull/183) / `bab154185503` |
| F08 | Add opt-in notification sounds with preview | Merged via #185; final CI passed | [#163](https://github.com/automatedigital/spark/issues/163) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-F08-resume-r3 | [#180](https://github.com/automatedigital/spark/pull/180) / `7dcdcc106b98` |
| F09 | Browse bounded history of dashboard skill edits | Merged via #185; final CI passed | [#164](https://github.com/automatedigital/spark/issues/164) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-F09-resume-r3 | [#178](https://github.com/automatedigital/spark/pull/178) / `5b125dccd120` |
| F10 | Browse saved scheduled-job output | Merged via #185; final CI passed | [#165](https://github.com/automatedigital/spark/issues/165) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-F10-resume-r3 | [#181](https://github.com/automatedigital/spark/pull/181) / `e4081d9053b0` |

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

### Composer recovery and production bundle

Integrated composer repair `2424ad77` preserves the original unsent draft in the existing durable draft store before recall, captured by backend/profile/project/thread identity. Restore swaps safely with edited recall, survives explicit accepted/rejected sends, and retires history when stash is restored. Agent pinned-base reproduction fails before the fix; real ChatPanel/replay/SQLite browser flow passes after. [Exact evidence](docs/reviews/october-composer-draft-recovery-result.md).

Final combined Node **22.22.1** validation: **555 tests**, ESLint, TypeScript/build and bundle budget pass; npm audit reports **zero vulnerabilities**. Canonical tracked web bundle regenerated by the lead alone. Fresh UI review targets `2424ad77`; final hosted browser/native checks remain pending.

The first new persistence workflow failed at configuration parsing before any job: actionlint confirms `runner` context is invalid in job-level env. Corrected those paths to the valid `github.workspace` context; no test/gate was removed. Local actionlint now passes. GitHub draft integration PR: [#185](https://github.com/automatedigital/spark/pull/185), linked to T3.

### Independent storage re-review — hold

Fresh review of `3a3e2005` confirms all earlier concrete upload/Git/export/canvas target/sidecar findings repaired, with **18 targeted tests passed**. It reproduces a new P1 case-alias lock split on the actual case-insensitive macOS filesystem: `board` and `Board` address one data file but `normcase` creates different lock keys, allowing two acknowledged same-revision saves. [Report](docs/reviews/october-storage-r2.md). A narrowly scoped canvas case-identity repair is delegated; candidate remains draft/unmerged. The independent UI review is running.

### Final review repairs and Windows evidence

Canvas case-alias repair `fa3653ab` uses owning directory identity plus a conservatively case-folded ASCII filename. Real case-insensitive APFS contention now yields one success and one 409; distinct data paths remain independent on case-sensitive APFS. Agent checks: **43 passed** on case-insensitive APFS and **41 passed / 2 alias skips** on a temporary case-sensitive APFS volume. Lead combined upload/canvas contracts: **94 passed / 11 Windows-only skips**. [Exact report](docs/reviews/october-canvas-case-result.md). The original pinned probe's release schedule deadlocks a correctly shared lock; its post-fix timeout is disclosed, and corrected event-scheduled regressions prove contention instead.

Native Windows workflow now executes. Job `119919216239` reports **176 passed / 32 skipped / 4 failed**. Two upload assertions assumed Windows always prevented a directory rename, but a successful rename preserved the old attachment under the pinned directory and left the outside sentinel unchanged; lead corrected the assertion to track the actual rename outcome. Two real source defects are delegated: cron malformed-JSON repair publishes while its read handle is open (Windows denies replacement), and skill history reads a byte before acquiring the Windows byte lock (Windows denies that read during contention). Neither native failure is waived.

Independent UI re-review discharges original draft/skill-ID/output-capability blockers, but reproduces a combined details/Mermaid completion-index mismatch. A complete code fence inside details can lend its completion flag to a later incomplete Mermaid fence. A narrow parsed-block completion repair is delegated. [Review](docs/reviews/october-ui-r2.md).

Full non-serial non-network Python selection: **12,692 passed / 163 skipped**, exit 0 in 490.33s. Serial selection is still running. Lead composer and stash browser flows pass. Mermaid source/safety fixtures pass, but the persisted-chat harness initially required a conditional Jump button while already at the latest row; the harness now establishes a loaded, detached scroll state before requiring the actual button. Its final result remains pending.

Lead Mermaid browser gate now passes all ten fixture/persisted-chat/stream-navigation flows with no page errors at `/tmp/spark-merge-review-20261022/final-mermaid-browser-r3`. Harness fixes are committed separately: establish loaded history and scroll away before clicking the conditional Jump control; preserve exact diagram and navigation assertions. This existing gate does not cover the newly found disclosure completion mismatch, whose separate repair/probe remains required.

### Windows persistence repair integrated

Integrated `e368615b` from repair commit `168e89d2`: cron closes the permissive source reader before atomic repair publication while retaining its encompassing mutation lock; skill history acquires its Windows byte lock before initializing the lock byte and never reads a potentially locked byte. Four portable regressions fail against the pinned old source and pass after; agent broader checks **296 passed**, scoped/CI Ruff and CI mypy pass. [Evidence](docs/reviews/october-windows-persistence-result.md). Native Windows rerun remains pending final source/bundle push; no native success inferred from macOS tests.

### Full Python validation complete

Both required local non-network selections passed sequentially: **12,692 passed / 163 skipped** in the parallel-safe selection, then **182 passed / 15 skipped** in the serial selection (396.43s). No failures. These broad runs started before the last narrow canvas/Windows repair commits; their final affected persistence subset was rerun after integration: **210 passed / 11 Windows-only skipped**, exit 0. Final CI Ruff family gate and mypy (**137 source files**) also pass, exit 0. The full tool manifest check passes (**70 tools, 28 isolated modules, four optional guards**). Native Windows and final combined hosted gates remain separately required.

### Final source repair integrated

Integrated `f84744d8` from `f177392a`: each parsed code node now owns its real closing-fence flag, and memo equality includes closure. The renderer no longer indexes an independent fence list that includes disclosure contents. Agent pinned before/after probe fails then passes; **38 mounted-browser checks**, **562 frontend tests**, lint and TypeScript pass. [Exact repair evidence](docs/reviews/october-mermaid-completion-result.md). No remaining concrete source finding is left unassigned; lead final combined checks are running, followed by the final hosted native/browser gates.

Hosted web-quality now retains composer/history+stash, Mermaid+disclosure completion, and Schedule override/output capability browser flows in addition to existing multi-chat/recovery/production inspector/navigation/sidebar/three-attempt longthread gates. Actionlint passes both modified workflows; no original gate or assertion was removed.

### Final integrated frontend and bundle

Lead final source run under Node **22.22.1** passes **562 tests**, frontend lint, TypeScript, canonical production build/budget and **38 mounted completion checks**, all exit 0. Tracked production bundle regenerated from the repaired parser source. Persisted Mermaid gate reached the final switch-away/return stage with no page errors; its snapshot showed the restored earlier viewport, where virtualized latest diagram nodes are absent. The harness now invokes the actual Jump to latest control after returning before requiring two completed SVGs, retaining both exact count and stream/navigation assertions. This is a viewport precondition correction, not a source-failure waiver.

### Final candidate pushed for hosted acceptance

All concrete source findings from both independent review rounds were repaired; the subsequent native Windows gate exposed the additional upload pinning blocker below. Lead final persisted Mermaid gate now passes **10 checks**, including two complete SVGs after switching away during the synthetic stream, returning and using the actual Jump to latest control; no page errors. Earlier harness failures and their viewport preconditions remain in the evidence. Final canonical bundle, **562 frontend tests**, lint/types/build/budget, **38 completion-browser checks**, **210 persistence tests** (11 native Windows skips locally), CI Ruff, mypy, manifest and both broad Python selections pass.

PR #185 retains all twenty original heads and tracker ancestry. Source fixes are ready for final hosted acceptance; the candidate remains draft until final native Windows/Linux, Python, supply-chain and all browser gates pass. Main remains unchanged; no app release is claimed.

### Native Windows containment blocker — candidate remains held

Final-head Windows job [119931403494](https://github.com/automatedigital/spark/actions/runs/39809449513/job/119931403494) reports **185 passed / 32 skipped / four upload failures**. The earlier cron reader/skill byte-lock defects now pass. The corrected directory-swap test exposes a real containment escape: Windows metadata-only directory handles permit rename; the route returns 200 for a new collision-safe filename written through the replacement directory link, outside the pinned original directory. Preserving the outside `note.txt` alone was insufficient evidence because a different newly allocated filename escaped. The earlier harness-only interpretation is withdrawn.

A focused repair is delegated to correct actual Windows access/share pinning semantics and add a direct native handle rename/release contract plus an assertion that the entire outside directory remains unchanged. No test is skipped, no failure waived, and no merge/build/release is authorized by the passing local macOS tests alone. Current source/CI candidate remains held until this native boundary is proven.

### Windows pinning repair and remaining protocol boundary

Integrated `54677d12` from `9401af29`: directory handles request FILE_LIST_DIRECTORY as well as FILE_READ_ATTRIBUTES so rename/delete sharing restrictions participate in Windows access checks. Whole-outside-tree assertions now detect new unique escaped filenames; new native cross-process tests require rename and generic-write denial while pinned and success after release. Lead local upload subset passes; native proof remains pending. [Repair report](docs/reviews/october-windows-upload-pinning-result.md).

One bounded protocol objection remains in that report: a metadata-only FILE_WRITE_ATTRIBUTES handle may set a junction on an empty directory without requesting generic write. [Microsoft MS-FSA](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-fsa/4aeefef8-92c3-4abc-af7a-a610caf8a165) explicitly permits FSCTL_SET_REPARSE_POINT when either FILE_WRITE_DATA or FILE_WRITE_ATTRIBUTES is granted. A final targeted task must exercise the actual FSCTL with a valid unpinned control, and retain whole-outside-tree containment at that boundary. If sharing does not exclude it, child creation/descent must be anchored to the owned Windows directory handle rather than following mutable paths. No further Windows CI push/merge occurs until that boundary is handled; no generic-write-only test is treated as metadata proof.

### Windows metadata boundary repair integrated

Integrated `39aabc9c` from `85571413`: Windows directory descent, exclusive file creation and collision inspection now use single-basename NtCreateFile operations relative to owned directory handles. Every open retains no-reparse/type checks; synchronous CRT transfer and handle cleanup remain explicit. Return-path verification compares native volume/file identities and rejects changed/reparse destinations. The containment mechanism no longer relies on pathname traversal remaining stable during a metadata-only mutation.

New native tests construct an actual mount-point FSCTL_SET_REPARSE_POINT request using FILE_WRITE_ATTRIBUTES only, first requiring a successful unpinned control. Six project/global endpoint injection cases exercise upload-read, final-file-open and directory-descent boundaries, requiring the entire outside tree unchanged and no false successful acknowledgement. Rename/generic-write/ordinary/collision/linked-profile cases remain. Portable API/identity tests fail before and pass after. Agent local final uploads: **60 passed / 20 native Windows skips**, CI Ruff and mypy pass. [Full report](docs/reviews/october-windows-upload-metadata-result.md). Lead integrated upload/neighbors and native CI remain required before closing the blocker.

Lead integrated Windows-handle repair verification: **127 upload/files/Git tests passed / 20 native Windows skips**, CI Ruff and mypy (**137 files**) exit 0. Candidate is pushed for native validation including actual metadata-only FSCTL controls and all six injection cases. No further source repair is currently active; merge waits for exact-head hosted gates.

### Native handle gate: error classification correction

Windows job [119942605618](https://github.com/automatedigital/spark/actions/runs/39812611488/job/119942605618) at `5c54f7f9` reports **205 passed / 32 skipped / two failures**. Ordinary/linked/collision uploads, rename controls, metadata FSCTL control/read/descent cases and the repaired persistence contracts pass. Final-open FSCTL cases receive native **WinError 1921** (filename cannot be resolved) before file creation; the helper classifies it as an unexpected OS error and returns 500 instead of the required unsafe-target 400. Lead adds 1921 to the existing reparse/unsafe error mapping and keeps every native assertion; whole-outside-tree assertions now run before HTTP assertions so containment is checked even on status failures. Three portable new-file/descent/collision regressions fail against the previous mapping and are rerun after correction. Final native rerun remains required.

The three new error-classification cases fail before and pass after; final local upload selection **63 passed / 20 native Windows skips**, scoped/CI Ruff and mypy pass. Native error 1921 remains a rejection; the source changes its API status to 400 and does not enable a retry/fallback or modify the handle-relative writer. Pushed for final native and hosted acceptance.

## Final merge and release evidence

- [x] All 20 original code PRs, tracker #144 and integration #185 verified merged on GitHub; original heads retained.
- [x] All 20 outcome issues verified closed, with final acceptance evidence recorded.
- [x] Exact accepted head `98e393d4`: all eight hosted gates pass. Windows persistence: **210 passed / 32 platform skips**.
- [x] Final hosted browser job: **505 backend lifecycle/cache/discovery tests**, 38 mounted completion checks, composer/stash/Schedule/Mermaid flows, multi-chat/recovery, production inspector/navigation, three sidebar and three longthread attempts pass. Inspector detached scroll **1000 → 1000 px**.
- [x] Final main merge commit verified: `824ea1e4e17444e34fe1c14b6581d29d54d205e9`. Desktop manifests agree at **1.4.0**.
- [x] macOS signed/notarized/stapled DMG; actual DMG app passes Gatekeeper and isolated native lifecycle/UI checks. SHA-256 recorded.
- [x] Windows unsigned x64 beta installer and packaged lifecycle. [Run 39817219208](https://github.com/automatedigital/spark/actions/runs/39817219208) uses exact main merge SHA.
- [x] GitHub desktop-v1.4.0 release published; tag target and all public asset bytes/hashes verified.

Windows output browsing is honestly disabled where secure filesystem capability is absent. Existing full Ruff debt remains 298 findings outside the enforced clean families; no acceptance threshold was weakened. Unrelated dirty handoff work and all stopped child checkouts remain preserved.

### Package/release completion
Both builds succeeded from 824ea1e4. macOS DMG notarization was Accepted, stapling validates, and the app extracted from the DMG passes strict signing and Gatekeeper as Notarized Developer ID. Normal native app launch, chat/files rendering, terminal/preview/SSE checks, process suspend/resume and clean quit/relaunch persistence pass in isolated state. Windows build and packaged lifecycle pass in run 39817219208; installer remains explicitly unsigned beta. [Full release evidence](docs/reviews/october-desktop-1.4.0-release.md). Public release and checksum file are published; final download verification remains to be recorded below.

### Final public verification
Unauthenticated public downloads of Spark.dmg, Spark_1.4.0_x64-setup.exe and SHA256SUMS.txt all match their local and GitHub SHA-256 digests and byte sizes. Release desktop-v1.4.0 is published as latest, not draft/prerelease; tag resolves to the exact source build commit 824ea1e4. [Public verification](docs/reviews/october-release-public-verification.json). All original implementation and corrective sub-agent work is finished. No programme acceptance gate remains unchecked; older measurements/failures above are historical evidence, not current status. Windows retains its stated unsigned-beta/output-capability limitations.
