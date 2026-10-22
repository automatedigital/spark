# Spark issue and feature PR plan

Updated: 2026-10-22. Baseline: `64af0d26976714b747dd4f1cc5b495c47c7f7567` (`main`).

Deliver ten independently scoped defect fixes and ten useful features, each implemented by a delegated agent in an isolated worktree with a GitHub issue and pull request. Reference research uses current pinned revisions of [T3 Code](https://github.com/pingdotgg/t3code) and [Hermes Agent](https://github.com/nousresearch/hermes-agent), checked against existing Spark functionality.

## Status

20 packets selected; **12/20 code PRs on GitHub**, 0/20 merged. User resumed all work after pausing the 14 live agents. Eight missing PRs and the I01 portability correction are running in fresh isolated worktrees recovered from preserved commits/dirty source. PR creation and passing acceptance remain distinct.

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
| I01 | Prevent uploads from following symlinks outside their storage root | Draft PR; portability correction running | [#145](https://github.com/automatedigital/spark/issues/145) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-I01-r1 | [#155](https://github.com/automatedigital/spark/pull/155) / `4ab637f8087e` |
| I02 | Preserve existing attachments when uploading duplicate filenames | PR open; CI snapshot passes | [#146](https://github.com/automatedigital/spark/issues/146) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-I02-r1 | [#171](https://github.com/automatedigital/spark/pull/171) / `10ba28f595c5` |
| I03 | Route context and brief requests to the selected backend | PR open; CI pending | [#147](https://github.com/automatedigital/spark/issues/147) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-I03-r1 | [#167](https://github.com/automatedigital/spark/pull/167) / `f60fc342a7ad` |
| I04 | Fence stale token estimate responses after prompt or session changes | PR open; CI snapshot passes | [#148](https://github.com/automatedigital/spark/issues/148) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-I04-r1 | [#172](https://github.com/automatedigital/spark/pull/172) / `810b8f62dbb8` |
| I05 | Preserve exact Unicode and quoted paths in Git Changes | PR open; CI snapshot passes | [#149](https://github.com/automatedigital/spark/issues/149) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-I05-r1 | [#168](https://github.com/automatedigital/spark/pull/168) / `797c0667b6c6` |
| I06 | List nested untracked files and reject directory discard | PR open; CI snapshot passes | [#150](https://github.com/automatedigital/spark/issues/150) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-I06-r1 | [#173](https://github.com/automatedigital/spark/pull/173) / `f3c76d3a6df8` |
| I07 | Make canvas revision checks atomic with saves and deletion | Resumed implementation | [#151](https://github.com/automatedigital/spark/issues/151) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-I07-resume-r3 | Pending |
| I08 | Preserve healthy memory databases during SQLite lock contention | PR open; CI snapshot passes | [#152](https://github.com/automatedigital/spark/issues/152) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-I08-r1 | [#166](https://github.com/automatedigital/spark/pull/166) / `4e8828a6ed22` |
| I09 | Prevent lost cron updates with cross-process mutation locking | PR open; CI pending | [#153](https://github.com/automatedigital/spark/issues/153) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-I09-r1 | [#169](https://github.com/automatedigital/spark/pull/169) / `4231e200ea55` |
| I10 | Preserve file permissions during atomic file and skill edits | PR open; CI snapshot passes | [#154](https://github.com/automatedigital/spark/issues/154) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-I10-r1 | [#175](https://github.com/automatedigital/spark/pull/175) / `0d3caa4cb141` |
| F01 | Recall sent prompts from composer history | PR open; CI snapshot passes | [#156](https://github.com/automatedigital/spark/issues/156) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-F01-r1 | [#176](https://github.com/automatedigital/spark/pull/176) / `a667b806b3b2` |
| F02 | Configure per-job models providers and skills in Schedule | Resumed implementation | [#157](https://github.com/automatedigital/spark/issues/157) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-F02-resume-r3 | Pending |
| F03 | Export sessions as readable redacted Markdown | Resumed implementation | [#158](https://github.com/automatedigital/spark/issues/158) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-F03-resume-r3 | Pending |
| F04 | Save and restore a bounded prompt stash | PR open; CI failure under review | [#159](https://github.com/automatedigital/spark/issues/159) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-F04-ci-review-r2 | [#170](https://github.com/automatedigital/spark/pull/170) / `a94d5487b6f7` |
| F05 | Render safe Mermaid diagrams in chat | Resumed implementation | [#160](https://github.com/automatedigital/spark/issues/160) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-F05-resume-r3 | Pending |
| F06 | Render GitHub-style Markdown callouts | PR open; CI failure under review | [#161](https://github.com/automatedigital/spark/issues/161) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-F06-ci-review-r2 | [#174](https://github.com/automatedigital/spark/pull/174) / `752034ee380b` |
| F07 | Render safe collapsible details in chat Markdown | Resumed implementation | [#162](https://github.com/automatedigital/spark/issues/162) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-F07-resume-r3 | Pending |
| F08 | Add opt-in notification sounds with preview | Resumed implementation | [#163](https://github.com/automatedigital/spark/issues/163) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-F08-resume-r3 | Pending |
| F09 | Browse bounded history of dashboard skill edits | Resumed implementation | [#164](https://github.com/automatedigital/spark/issues/164) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-F09-resume-r3 | Pending |
| F10 | Browse saved scheduled-job output | Resumed implementation | [#165](https://github.com/automatedigital/spark/issues/165) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-F10-resume-r3 | Pending |

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
