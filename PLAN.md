# Spark issue and feature PR plan

Updated: 2026-10-22. Baseline: `64af0d26976714b747dd4f1cc5b495c47c7f7567` (`main`).

Deliver ten independently scoped defect fixes and ten useful features, each implemented by a delegated agent in an isolated worktree with a GitHub issue and pull request. Reference research uses current pinned revisions of [T3 Code](https://github.com/pingdotgg/t3code) and [Hermes Agent](https://github.com/nousresearch/hermes-agent), checked against existing Spark functionality.

## Status

20 packets selected; 1/20 implementation PRs created (draft), 0/20 accepted, 0/20 accepted, 0/20 merged. Placeholder rows are allocation slots, not confirmed findings. The lead alone updates this plan. PR creation, validation, merge and release are separate states; completion requires reviewed evidence, not an agent summary.

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
| I01 | Prevent uploads from following symlinks outside their storage root | Draft PR; Windows regression open | [#145](https://github.com/automatedigital/spark/issues/145) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-I01-r1 | https://github.com/automatedigital/spark/pull/155 |
| I02 | Preserve existing attachments when uploading duplicate filenames | Queued | [#146](https://github.com/automatedigital/spark/issues/146) | — | Pending |
| I03 | Route context and brief requests to the selected backend | Implementing | [#147](https://github.com/automatedigital/spark/issues/147) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-I03-r1 | Pending |
| I04 | Fence stale token estimate responses after prompt or session changes | Queued | [#148](https://github.com/automatedigital/spark/issues/148) | — | Pending |
| I05 | Preserve exact Unicode and quoted paths in Git Changes | Queued | [#149](https://github.com/automatedigital/spark/issues/149) | — | Pending |
| I06 | List nested untracked files and reject directory discard | Queued | [#150](https://github.com/automatedigital/spark/issues/150) | — | Pending |
| I07 | Make canvas revision checks atomic with saves and deletion | Queued | [#151](https://github.com/automatedigital/spark/issues/151) | — | Pending |
| I08 | Preserve healthy memory databases during SQLite lock contention | Implementing | [#152](https://github.com/automatedigital/spark/issues/152) | node:delegated-task:command%3Amcp%3A273d5d45-83a6-415e-b4af-fa08d28d167f%3Adelegate-task%3Aspark-20261022-I08-r1 | Pending |
| I09 | Prevent lost cron updates with cross-process mutation locking | Queued | [#153](https://github.com/automatedigital/spark/issues/153) | — | Pending |
| I10 | Preserve file permissions during atomic file and skill edits | Queued | [#154](https://github.com/automatedigital/spark/issues/154) | — | Pending |
| F01 | Recall sent prompts from composer history | Queued | [#156](https://github.com/automatedigital/spark/issues/156) | — | Pending |
| F02 | Configure per-job models providers and skills in Schedule | Queued | [#157](https://github.com/automatedigital/spark/issues/157) | — | Pending |
| F03 | Export sessions as readable redacted Markdown | Queued | [#158](https://github.com/automatedigital/spark/issues/158) | — | Pending |
| F04 | Save and restore a bounded prompt stash | Queued | [#159](https://github.com/automatedigital/spark/issues/159) | — | Pending |
| F05 | Render safe Mermaid diagrams in chat | Queued | [#160](https://github.com/automatedigital/spark/issues/160) | — | Pending |
| F06 | Render GitHub-style Markdown callouts | Queued | [#161](https://github.com/automatedigital/spark/issues/161) | — | Pending |
| F07 | Render safe collapsible details in chat Markdown | Queued | [#162](https://github.com/automatedigital/spark/issues/162) | — | Pending |
| F08 | Add opt-in notification sounds with preview | Queued | [#163](https://github.com/automatedigital/spark/issues/163) | — | Pending |
| F09 | Browse bounded history of dashboard skill edits | Queued | [#164](https://github.com/automatedigital/spark/issues/164) | — | Pending |
| F10 | Browse saved scheduled-job output | Queued | [#165](https://github.com/automatedigital/spark/issues/165) | — | Pending |

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
