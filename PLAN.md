# Spark Web UI, Skills, and Adaptive Codex Plan

## Goal

Make Spark's web UI a clearer and more capable control surface for long-running
agent work. The next release should make the main thread easier to read, make
model and subagent choices understandable and cost-aware, and ship a smaller,
higher-quality skill set with measurable behavior.

This is a web-first programme. Source changes may include the Python/API work
needed to power the web UI, but macOS and Windows desktop rebuilds, installers,
signing, notarization, and release publication are deferred until the web
experience has been reviewed and accepted.

## Stacked Feature-Branch Rule

All implementation must happen on feature branches created from the latest
`origin/main`. Do not implement any source task while `git branch --show-current`
prints `main`, and never use an assistant-specific branch prefix.

Use GitHub stacked pull requests only where one review layer genuinely depends
on the layer below it. Keep the three concerns in separate stacks:

| Stack | Branches, bottom to top | Merge boundary |
| --- | --- | --- |
| Thread | `webui-thread-foundation` -> `webui-thread-interface` -> `webui-thread-polish` | Accepted thread and composer |
| Routing | `adaptive-routing-core` -> `adaptive-routing-web` | Accepted Auto policy and web controls |
| Skills | `skills-invocation` -> `skills-library` -> `skills-web` | Accepted skill contracts, library decisions, and UI |

The thread stack goes first. Start the routing stack from fresh `main` after the
thread stack lands so its composer/thread UI targets the accepted components.
The skills stack may proceed independently where file ownership does not
overlap, but every layer must remain independently reviewable.

GitHub's stacked-PR feature is currently public preview. Verify the current
`gh stack` workflow before source work:

```bash
git fetch origin
git switch main
git pull --ff-only origin main
gh stack --help
gh stack init webui-thread-foundation
```

Use `gh stack add <branch>` for each dependent layer, `gh stack submit` to push
and open the linked PRs, and merge from the bottom up. If the preview tooling is
unavailable or unsuitable, use ordinary same-repository dependent PRs with the
same branch names, base relationships, and review boundaries rather than
collapsing the work into one large PR.

Record the `origin/main` base SHA in the bottom PR of each stack. Keep unrelated
generated, reference, release, and user-owned files out of every branch. The
temporary research clones described below are not Spark dependencies and must
never be copied into or committed with this repository.

## Scope

### In scope

- The main web chat/thread panel, including turn presentation, tool activity,
  reasoning, plans, changed files, approvals, usage, scrolling, and the composer.
- Web controls and supporting backend contracts for main-model, fast-model, and
  delegated-subagent routing.
- Account-aware Codex model discovery, capability display, routing telemetry,
  and cost/token evaluation.
- External-skill integration, improvements to overlapping bundled skills, skill
  invocation metadata, skill quality evals, and clearer Skills UI provenance.
- Local web preview, browser-based visual acceptance, frontend tests, focused
  Python tests, and performance/accessibility checks.

### Out of scope until web acceptance

- Tauri/Rust changes that are only needed for packaged desktop behavior.
- `.app`, `.dmg`, Windows installer, signing, notarization, stapling, and release
  publication.
- Mobile, gateway-platform, or CLI redesign unrelated to shared API contracts.
- A wholesale copy of T3 Code's architecture, styling, dependencies, or source.
- Vendored copies of externally installed Matt Pocock or `i-have-adhd` skills.
- Committing the temporary clones or generated reference screenshots.

## Research Snapshot

Repository research was refreshed on 2026-08-02 from fresh, shallow clones of
each default branch. The stacked-PR workflow and installed-skill state were
refreshed on 2026-08-04 from current primary documentation and the local system.

### GitHub stacked pull requests

- [GitHub's stacked-PR overview](https://docs.github.com/en/pull-requests/get-started/about-stacked-prs)
  defines a stack as dependent same-repository PRs where each layer targets the
  branch below it, CI and branch protection apply throughout, and merges proceed
  bottom-up. The feature is currently public preview.
- [GitHub's creation guide](https://docs.github.com/en/pull-requests/how-tos/create-pull-requests/creating-stacked-pull-requests)
  documents `gh stack init`, `gh stack add`, and `gh stack submit`.
- Transfer to Spark: small dependency-correct review layers and explicit stack
  maps. Do not force independent routing, skills, and thread work into one chain.

### T3 Code

- Repository: [pingdotgg/t3code](https://github.com/pingdotgg/t3code)
- Inspected commit: `e60821f0e0d82a5d671ca3b94719c49d333921c8`
- Most relevant code:
  - `apps/web/src/components/chat/MessagesTimeline.tsx` and
    `MessagesTimeline.logic.ts` derive a turn-oriented timeline, keep the final
    answer visible, fold settled reasoning/tool work behind a duration summary,
    group tool calls, preserve copy/revert actions, show changed files, and keep
    a minimap useful on long threads.
  - `apps/web/src/components/chat/ChatComposer.tsx` combines prompt drafts,
    attachments, contextual chips, model/provider selection, reasoning effort,
    context-window pressure, approvals, stop/redirect behavior, and plan actions
    in one persistent surface.
  - `apps/web/src/components/PlanSidebar.tsx`, `ProposedPlanCard.tsx`, and
    `ChangedFilesTree.tsx` make plans and file outcomes first-class without
    forcing raw tool output into the final response.
  - `apps/web/src/session-logic.ts` derives presentation state before rendering;
    the useful lesson is the typed turn model, not the size of `ChatView.tsx`.
- Transfer to Spark: turn-level hierarchy, compact settled work, visible final
  outcomes, contextual composer controls, and pure tested presentation models.
- Do not transfer: provider-specific assumptions, Effect/TanStack state
  architecture, Electron behavior, or T3 branding.

### i-have-adhd

- Repository: [ayghri/i-have-adhd](https://github.com/ayghri/i-have-adhd)
- Inspected commit: `d05af1e4ac2259846e81686d14180d46d84acc2d`
- `skills/i-have-adhd/SKILL.md` is an explicit, session-persistent output mode:
  action first, numbered bounded steps, state restated, tangents suppressed,
  concrete progress, and matter-of-fact errors. It yields to safety, ambiguity,
  explicit requests for detail, and harness requirements.
- `evals/` compares baseline/candidate/comparator conditions with identical
  prompts, pinned models, isolated configuration, resumable trials, cost caps,
  blinded judging, and release gates for correctness, autonomy, actionability,
  safety, and concision.
- `i-have-adhd` is now externally installed on this machine. Transfer to Spark:
  invocation/provenance support and the paired eval discipline, not a bundled
  copy. Preserve MIT attribution if text or test cases are ever adapted.

### Matt Pocock skills

- Repository: [mattpocock/skills](https://github.com/mattpocock/skills)
- Inspected commit: `2ab958093e83e0ec752e6c1c5932da465bf23e0c`
- The useful system ideas are small composable skills, a deliberate distinction
  between user-invoked orchestration and model-invoked discipline, router skills
  for discoverability, progressive disclosure through context pointers,
  checkable completion criteria, and aggressive removal of duplicated/no-op
  prose.
- The Matt Pocock skills are now externally installed on this machine. High-value
  examples include `research`, `prototype`, `codebase-design`,
  `domain-modeling`, `wayfinder`, `grill-me`, and `grill-with-docs`.
- `diagnosing-bugs`, `tdd`, planning, review, and subagent workflows overlap
  Spark's bundled skills. Improve or replace the bundled canonical skill after
  comparison; do not vendor the external skill or create a second bundled skill
  with a different name for the same behavior.

### Current OpenAI/Codex guidance

- [OpenAI model guidance](https://developers.openai.com/api/docs/guides/latest-model)
  describes GPT-5.6 Sol as the flagship capability model, Terra as the
  intelligence/cost balance, and Luna as the efficient high-volume model. It
  recommends testing the current reasoning effort and one level lower on
  representative workloads instead of assuming maximum effort is best.
- The same guidance treats multi-agent as beta, supports `none`, `low`,
  `medium`, `high`, `xhigh`, and `max` reasoning, and recommends tracking prompt
  cache reads and writes because cache writes and reads have different cost.
- [OpenAI's current model comparison](https://developers.openai.com/api/docs/models/compare)
  confirms that model capability, context, reasoning, and price differ enough
  that routing must be measured rather than hard-coded from model names.
- This machine's account-scoped Codex cache, fetched on 2026-08-02, currently
  exposes `gpt-5.6-sol`, `gpt-5.6-terra`, and `gpt-5.6-luna`. Sol and Terra
  advertise multi-agent v2 while Luna advertises v1. Availability and metadata
  can change; Spark must use the live account catalog and test parent/child
  compatibility before enabling those models in Auto role mappings.

## Current Spark Baseline

- `src/spark_cli/web/src/components/ChatPanel.tsx` is already virtualized and
  supports user/assistant/tool/reasoning/approval rows, search, retry, fork,
  exact-copy behavior, a minimap, streaming recovery, and long-thread guards,
  but it owns too many transport, state, and presentation concerns in one file.
- `src/spark_cli/web/src/components/chat/PromptBar.tsx` already supports
  attachments, `/` commands, `@` context,
  token estimates, a model/reasoning popover, redirect, and stop.
- `src/spark_cli/web/src/components/chat/SessionInfoBar.tsx` already exposes
  input/output/cache tokens, estimated cost, model, and turn count, while
  `src/spark_cli/web/src/components/CodexUsageBadge.tsx` exposes subscription
  windows.
- `src/spark_cli/web/src/components/chat/SubagentsPanel.tsx` and the persisted
  `spark.subagent.lifecycle.v1` events already provide a foundation for visible
  child-agent progress.
- `src/agent/smart_model_routing.py` currently routes only very short/simple
  turns to one fast model. Delegation supports one global child model and
  reasoning effort.
  The web UI does not present these as one understandable routing policy.
- `src/spark_cli/codex_models.py` already prefers an account-scoped live catalog
  and falls back to the local cache, but it reduces model entries to slugs and
  discards capability metadata needed for safe routing controls.
- Spark already ships broad skills for debugging, TDD, planning, review, and
  subagent development. New work must reduce overlap and prompt cost rather than
  merely increase the skill count.

## Product Principles

- Final answers and concrete outcomes remain visually dominant. Active work
  stays expanded; completed reasoning, tools, and subagents collapse into one
  expandable work summary by default.
- Failures, pending approvals, and unresolved user input never disappear into a
  collapsed summary. Raw transcript content remains available and exact.
- Compact changed-file and plan-progress cards sit beneath the answer that
  produced them; the right panel remains the detailed diff/plan workspace.
- The server/session database remains authoritative. UI folds, filters, drafts,
  and optimistic state must reconcile after refresh, reconnect, and chat switch.
- Exact message text, tool results, approvals, retry/fork semantics, and the
  stable SSE recovery contracts must survive the redesign.
- `Auto` is the default for new chats. Explicit model selection pins that model
  for the thread until changed; Auto always shows the effective model, effort,
  route label, fallback, and any bounded escalation.
- Auto routes the main agent and delegated subagents independently, preserves a
  quality/safety floor before minimizing usage, uses latency only as a tie-break,
  and prefers model stability unless a tested threshold is crossed.
- Routing explanations are deterministic policy labels based on observable
  signals, never generated reasoning or hidden chain-of-thought.
- Context management warns early, offers manual removal/summarization, compacts
  automatically only when required to continue safely, preserves pinned context
  and decisions, and visibly records what changed. It never silently drops
  context merely to save tokens.
- Skills earn their prompt cost. User-only orchestration skills consume no
  model-index tokens; overlapping skills have one canonical source of truth;
  external skills retain their source rather than being copied into Spark.
- T3 Code is a visual as well as structural reference: borrow its restrained
  surfaces, spacing, density, composer treatment, work summaries, and thread
  rhythm while retaining Spark branding, color system, typography character,
  terminology, and distinctive controls.
- Visual acceptance means inspecting the rendered web UI at representative
  widths with real long, streaming, tool-heavy, and subagent conversations.

## Confirmed Product Decisions

The 2026-08-04 `grill-me` session resolved these implementation choices:

- Use separate dependency-correct PR stacks, not one monolithic branch or one
  artificial stack spanning unrelated concerns.
- Completed turns are final-answer-first with intermediate work collapsed;
  active work, failures, approvals, and unresolved input remain visible.
- Changed files and plan progress appear as compact inline outcomes linked to
  the authoritative right-panel detail.
- Compare two polished T3-inspired prototypes: calm/spacious and
  dense/operational. Do not spend a prototype on an unrelated visual direction.
- `Auto` is the default model choice; explicit choices remain supported and pin
  the thread. Main-agent and subagent routing are independent.
- Auto permits at most one reasoned escalation per turn, maintains a tested
  quality/safety floor, then minimizes usage, with latency as a tie-break.
- Ship one Auto policy initially. Use sticky routing with hysteresis rather than
  reconsidering models from scratch on every turn.
- Show deterministic route labels such as `Terra · normal coding task` or
  `Escalated to Sol · validation failed`; never expose hidden reasoning.
- Manage context conservatively and visibly; never silently discard it for cost.
- Do not vendor the installed Matt Pocock or `i-have-adhd` skills. Start with
  invocation, provenance, overlap, token-cost, and eval infrastructure; add a
  bundled skill only after the audit proves a gap.
- User-invoked orchestration skills remain available in slash commands and the
  Skills UI but are omitted from the normal model-visible skill index.

## Dependency Map

```text
THREAD STACK
main -> webui-thread-foundation -> webui-thread-interface -> webui-thread-polish
          baseline + model          timeline + composer       visual/perf QA

ROUTING STACK (after accepted thread stack lands)
main -> adaptive-routing-core -> adaptive-routing-web
          metadata + policy          Auto UI + telemetry + eval acceptance

SKILLS STACK (independent where ownership permits)
main -> skills-invocation -> skills-library -> skills-web
          metadata + index       audit + evals       provenance/quality UI

Accepted thread + routing + skills stacks -> integrated web bundle gate
Integrated web acceptance -> separate future desktop build/release plan
```

## Phase 0: Thread Stack, Baselines, and UI Direction

- [x] **BRANCH-01 - Initialize the thread PR stack before source work.** From a
  clean latest `main`, verify `gh stack --help`, run
  `gh stack init webui-thread-foundation`, record the `origin/main` base SHA,
  and confirm the worktree contains only intentional files. Add
  `webui-thread-interface` and `webui-thread-polish` only when their dependency
  boundaries are reached.
  **Done when:** the checked-out branch is `webui-thread-foundation`, the stack
  map/base relationships are recorded, and `git status --short` has no unrelated
  changes.
  **Evidence (2026-08-04):** `origin/main` and local `main` were both at
  `d827339dacb3b5caf5a59f2bab970b398de6316c`; `gh stack --help` reported that
  the command is unavailable, so the documented ordinary dependent-PR fallback
  is active. The clean checkout is now on `webui-thread-foundation`; later
  layers will base `webui-thread-interface` on this branch and
  `webui-thread-polish` on `webui-thread-interface`.

- [x] **BASE-01 - Capture behavior fixtures for the current chat surface.** Add
  redacted fixtures for empty, short, long, streaming, interrupted, reconnecting,
  tool-heavy, reasoning-heavy, approval-pending, changed-file, and parallel
  subagent threads.
  **Files:** `src/spark_cli/web/e2e/fixtures/`, existing session fixture helpers,
  and focused API fixtures under `tests/` only where needed.
  **Done when:** the same fixtures can drive baseline and redesigned UI states
  without network or private data.
  **Evidence (2026-08-04):** `chat-thread-states-v1.json` defines all eleven
  required synthetic states with deterministic timestamps and no network/private
  data; its Node contract test verifies the catalog, redaction rules, unique
  sessions, and state-specific payloads. `node --test`, `jq empty`, all 253
  frontend tests, and `git diff --check` pass.

- [x] **BASE-02 - Freeze the behavioral contracts that the redesign must keep.**
  Add tests for exact assistant copy, retry/edit/fork, paged history, active
  streaming rows, tool-result expansion, approvals, redirect/stop, scroll
  anchoring, minimap navigation, refresh/reconnect, and chat switching.
  **Files:** existing chat tests plus new focused tests beside the extracted
  **Validation:** `cd src/spark_cli/web && npm test`.
  **Evidence (2026-08-04):** deterministic browser contracts cover exact
  assistant copy, edit/retry/fork, paged history, active streaming rows,
  expanded tool results, persisted approvals, minimap navigation, reconnect,
  chat switching, stop, and redirect. The focused history-prepend repro passes
  twice with the same visible row held at exactly `0px` drift after virtualizer
  remeasurement. The broad browser contract, all 289 frontend tests, 97 focused
  web-server tests, lint, and TypeScript pass.

- [x] **BASE-03 - Record web performance and visual baselines.** Measure React
  commits, first render, stream update rate, row measurement churn, scroll drift,
  and memory for 50-, 500-, and 2,000-row fixtures. Capture screenshots at
  1440px, 1024px, and 768px widths in light and dark themes.
  **Files:** `src/spark_cli/web/e2e/`, `src/spark_cli/web/screenshots/baseline/`,
  and existing efficiency metrics helpers.
  **Done when:** raw numbers and screenshots identify the current state; they are
  not acceptance evidence for the redesign.
  **Evidence (2026-08-04):** `baseline-d827339d.json` records all 18 combinations
  of 50/500/2,000 rows, 1440/1024/768px, and light/dark themes with first render,
  React commits, stream rate, row-measurement churn, scroll drift, and browser
  memory. All cases have 7-8 observed stream updates, zero page/console errors,
  zero measured anchor drift, and one atomic screenshot; 18 screenshots were
  captured. Representative wide/light and narrow/dark renders were visually
  inspected and correctly retained as pre-redesign baselines only.

- [x] **UI-01 - Build two polished T3-inspired main-thread prototypes.** Use one
  temporary dev-only route or query flag to compare a calm/spacious transcript
  with a dense/operational transcript. Both must use the same fixture data,
  final-answer-first turn hierarchy, compact outcome cards, composer controls,
  Spark branding, and preserved actions.
  **Files:** temporary components under
  `src/spark_cli/web/src/dev/thread-prototypes/` and one guarded dev entrypoint.
  **Done when:** both run from one documented command and neither is wired into
  production state.
  **Evidence (2026-08-04):** `?thread-prototype=1` loads calm/spacious and
  dense/operational variants from the shared canonical fixture catalog, with a
  fixture picker, preserved actions, final-answer-first hierarchy, outcome
  cards, work/approval states, and composer controls. Browser checks cover both
  variants at 1440/1024/768px, including zero horizontal overflow after fixing
  the narrow dense view; six review screenshots were captured. Frontend tests,
  lint, TypeScript, a temporary production build, and a production-bundle scan
  all pass, with no prototype route/chunk markers in the production output.

- [x] **UI-02 - Review the prototypes in the browser and select one direction.**
  Compare information hierarchy, long-thread scanning, tool density, composer
  reachability, changed-file visibility, and narrow-width behavior with the user.
  **Gate:** do not begin production visual refactoring until one direction and
  any retained elements from the other variants are explicitly recorded.
  **Evidence (2026-08-04):** selected dense/operational as the production
  foundation, retaining the calm variant's final-answer prominence and breathing
  room around outcome cards. The decision and responsive review findings are
  recorded in `docs/web/ui-direction-decision.md` against the six preserved
  1440/1024/768 screenshots.

- [x] **UI-03 - Remove rejected prototype code and capture the decision.** Keep
  only a small screenshot/decision note if useful; production code starts from
  the selected behavior, not by promoting an untested prototype wholesale.
  **Done when:** no temporary prototype route can ship in a production build.
  **Evidence (2026-08-04):** removed the dev-only query entrypoint and all
  temporary `src/dev/thread-prototypes/` source while retaining only the decision
  note and six review screenshots. Frontend tests, lint, TypeScript, temporary
  production build, bundle budget, marker scans, and `git diff --check` pass.

## Phase 1: Turn-Oriented Thread Model

- [x] **THREAD-01 - Define a pure presentation model for one conversation turn.**
  Convert persisted/streaming `ChatMessage` rows into typed turns containing the
  initiating user message, commentary/reasoning, tool activity, approvals,
  subagent activity, final assistant answer, usage, changed files, status, and
  timestamps.
  **Files:** new `src/spark_cli/web/src/lib/threadTimelineModel.ts` and
  `threadTimelineModel.test.ts`.
  **Done when:** mixed persisted/live events produce stable IDs and deterministic
  turn boundaries without React or network state.
  **Evidence (2026-08-04):** `threadTimelineModel.ts` provides a pure typed turn
  model with deterministic explicit and fallback boundaries, user/final-answer
  separation, work, approvals, requested input, subagents, changed files, usage,
  status, and timestamps. Focused and full frontend tests pass.

- [x] **THREAD-02 - Define settled-work folding rules.** Keep an active or
  interrupted turn expanded. For settled turns, retain the final assistant
  answer while folding intermediate reasoning/tool/subagent rows behind a
  summary such as `Worked for 2m 14s · 7 actions`.
  **Depends on:** `THREAD-01`.
  **Done when:** tests cover missing turn IDs, multiple assistant messages,
  redirect/interruption, failed tools, approvals, requested user input, and
  resumed sessions; failures and unresolved interactions cannot be hidden by
  the default fold.
  **Evidence (2026-08-04):** focused tests cover settled final-answer-first folds,
  active streaming, interruption/redirect, tool failure, unresolved and resolved
  approvals, requested input, multiple assistant messages, and resumed sessions.
  Active, failed, interrupted, approval, and input states remain expanded.

- [x] **THREAD-03 - Add structural sharing for unchanged timeline items.** A
  streaming delta should replace only the affected active item; settled turns
  must retain object identity so virtualization and memoization remain useful.
  **Files:** `threadTimelineModel.ts`, tests, and existing transcript merge code.
  **Done when:** tests assert referential stability across representative deltas.
  **Evidence (2026-08-04):** semantic signatures reuse the complete previous
  timeline when unchanged, retain settled-turn identity across active deltas,
  preserve unaffected active work-item identity, and replace only the changed
  streaming answer. Eight focused tests and all 280 frontend tests pass with
  lint, TypeScript, and `git diff --check` clean.

- [x] **THREAD-04 - Extract transport/controller concerns from `ChatPanel.tsx`.**
  Move transcript loading/recovery, stream event reduction, composer actions,
  and timeline derivation into explicit hooks/modules while retaining
  `ChatPanel` as the stable public component.
  **Files:** `ChatPanel.tsx`, new focused modules under
  `src/spark_cli/web/src/hooks/` and `src/spark_cli/web/src/lib/`.
  **Done when:** no behavior is lost, controller modules have focused tests, and
  presentation components do not fetch session state directly.
  **Evidence (2026-08-04):** session/history recovery, pure stream reduction,
  batched stream orchestration, composer actions, and timeline derivation now
  live in focused hooks/modules while `ChatPanel` remains the public component.
  The complete frontend suite passes with 47 files and 324 tests, lint and
  TypeScript pass, 217 focused web-server tests pass, the broad browser contract
  passes, and the strengthened history-prepend contract passes six consecutive
  trials with exact `0px` settled drift. Stream topics are no longer reduced by
  an inline event switch in the presentation component.

## Phase 2: Main Thread Panel Redesign

- [ ] **CHAT-01 - Implement the selected timeline shell.** Use a centered,
  readable content column, a persistent bottom composer, clear active-turn
  status, and responsive gutters. Move visibly toward T3's restrained surfaces,
  spacing, density, and thread rhythm while retaining Spark's brand tokens,
  terminology, typography character, and distinctive controls.
  **Files:** new `src/spark_cli/web/src/components/chat/MessagesTimeline.tsx`,
  existing `src/spark_cli/web/src/components/ChatPanel.tsx`, and shared theme
  styles.
  **Depends on:** `UI-02`, `THREAD-04`.

- [ ] **CHAT-02 - Implement distinct user and assistant message treatments.**
  Preserve user context chips and edit/retry/fork/copy actions. Let assistant
  answers read like the primary document, with exact-copy and usage metadata
  available without permanent visual noise.
  **Files:** new `UserMessageRow.tsx`, `AssistantMessageRow.tsx`, and component
  tests.

- [ ] **CHAT-03 - Implement compact expandable work groups.** Group tool calls,
  reasoning, and subagent status under the turn summary. Show failures and
  unresolved approvals/user input prominently; allow complete raw details and
  stored tool artifacts to be expanded on demand. Completed groups collapse by
  default; active groups remain expanded.
  **Files:** new `TurnWorkGroup.tsx`; existing
  `src/spark_cli/web/src/components/chat/ToolCallBubble.tsx`,
  `ReasoningBubble.tsx`, and `SubagentsPanel.tsx`; and focused tests in the same
  component area.

- [ ] **CHAT-04 - Make changed files a first-class turn outcome.** Reuse the
  authoritative changes/diff data already available to the right panel. Show a
  compact card directly beneath the relevant final answer, with a file tree,
  additions/deletions, and open-diff actions; do not infer success merely from a
  tool call string. Keep the right panel as the detailed workspace.
  **Files:** a new `ChangedFilesCard.tsx`, the existing changes-panel model/API,
  and focused tests.
  **Done when:** changed files reconcile after refresh and a file opens in the
  existing Changes tab at the expected path.

- [ ] **CHAT-05 - Add inline plan presentation.** Render active plan steps and
  proposed plan Markdown as a compact card beneath the relevant answer with a
  shortcut to the existing plan/brief surface. Preserve one authoritative plan
  state in the right panel/backend.
  **Files:** new `PlanCard.tsx`, existing
  `src/spark_cli/web/src/components/chat/BriefPanel.tsx`, plan event adapters,
  and tests.

- [ ] **CHAT-06 - Adapt the minimap from message rows to turn landmarks.** Keep
  user turns, final answers, failures, approvals, and active work visible while
  suppressing repetitive tool noise. Preserve keyboard and pointer navigation.
  **Files:** `TimelineMinimap.tsx`, `timelineMinimapModel.ts`, and tests.

- [ ] **CHAT-07 - Preserve deterministic scroll anchoring.** Cover appending
  tokens, expanding old work, prepending history, switching chats mid-stream,
  jumping via minimap, and returning to the bottom. Never steal the user's
  position while they are reading older content.
  **Files:** `chatScrollState.ts`, row-measurement helpers, timeline components,
  and stress tests.

- [ ] **CHAT-08 - Refine loading, offline, reconnecting, interrupted, and failed
  states.** State labels must come from confirmed backend/session state and
  expire or reconcile after reconnect.
  **Files:** `StatusPill.tsx`, `chatTurnState.ts`, `chatRecovery.ts`,
  `sessionStore.tsx`, and tests.

## Phase 3: Composer and Thread Controls

- [ ] **COMPOSER-01 - Recompose the prompt surface around progressive
  disclosure.** Keep the prompt and send/stop/redirect actions always visible;
  group attachments, context, project, model, reasoning, and advanced controls
  into compact discoverable controls. `Auto` is the default for new chats and
  sits alongside all currently available explicit model choices. An explicit
  choice pins the thread until changed.
  **Files:** split `src/spark_cli/web/src/components/chat/PromptBar.tsx` into
  focused composer components while keeping its public contract stable during
  migration.

- [ ] **COMPOSER-02 - Make context pressure actionable.** Keep the current token
  estimate, show context buckets, and offer remove/summarize actions before the
  threshold is reached. Label estimates separately from provider-reported usage.
  Warn before compaction; automatically compact only when required to continue
  safely; preserve pinned context, approvals, decisions, and recent turns; and
  show exactly what was summarized or omitted. Never silently discard context
  merely to reduce usage.
  **Files:** extracted `ContextWindowMeter.tsx`, context hooks, and tests.

- [ ] **COMPOSER-03 - Keep approvals and requested user input at the point of
  action.** Pending prompts appear directly above the composer, remain after
  refresh, and cannot be mistaken for an ordinary assistant message.
  **Files:** approval/input components, session state adapters, and tests.

- [ ] **COMPOSER-04 - Add responsive and keyboard contracts.** Define behavior
  for narrow panels, right-panel-open layouts, model-picker focus, Escape,
  Enter/Shift+Enter, stop, redirect, attachment menus, and screen readers.
  **Validation:** component tests plus browser acceptance at 1440/1024/768px.

- [ ] **THREAD-PR-01 - Submit and accept the thread stack bottom-up.** Keep
  baseline fixtures/pure timeline/controller work in `webui-thread-foundation`,
  the selected timeline/composer implementation in `webui-thread-interface`, and
  visual refinement/performance/accessibility fixes in
  `webui-thread-polish`. Run `gh stack submit`; review each layer's own diff;
  record focused frontend tests, long-thread/manual-browser evidence, visual
  comparisons, and performance numbers; then merge from the bottom up.
  **Gate:** do not initialize `adaptive-routing-core` until all thread layers are
  accepted and present on `main`.

## Phase 4: Adaptive Codex Routing

- [ ] **MODEL-00 - Initialize the routing stack after the accepted thread stack
  lands.** Fast-forward local `main`, run `gh stack init adaptive-routing-core`,
  and add `adaptive-routing-web` only after the core metadata/policy contract is
  reviewable.
  **Done when:** the bottom PR targets current `main`, the web PR targets
  `adaptive-routing-core`, and neither branch contains thread-stack history that
  has not already landed on `main`.

- [ ] **MODEL-01 - Preserve account-scoped Codex model metadata.** Change model
  discovery from a list of slugs to a backward-compatible catalog containing
  display name, visibility, supported reasoning efforts, context/output limits,
  multi-agent version, and source/freshness when supplied by the live API/cache.
  **Files:** `src/spark_cli/codex_models.py`, `src/agent/model_metadata.py`,
  `src/spark_cli/web_server.py`, `src/spark_cli/web/src/lib/api.ts`, and
  `tests/spark_cli/test_codex_model_flow.py`.
  **Done when:** the account list remains authoritative and stale/offline data is
  visibly distinguished without inventing unavailable models.

- [ ] **MODEL-02 - Define one Auto policy using roles, not hard-coded product
  names.** Add `lead`, `balanced`, `fast`, and `subagent` role settings, each
  resolving to provider, model, reasoning effort, and fallback. `Auto` is the
  sole automatic preset in the first release. Migrate existing `model.default`,
  `smart_model_routing`, and `delegation` settings without breaking old configs.
  **Files:** `src/spark_cli/config.py`, `src/spark_cli/model_config.py`,
  `src/agent/smart_model_routing.py`, `src/tools/delegate_tool.py`, config
  migration tests, and web API types.
  **Default intent when available and validated:** Sol for genuinely difficult
  lead work, Terra for balanced work, and Luna at measured high effort for
  bounded long-running children. Main-agent and delegated-subagent roles resolve
  independently. The role contract, not those names, is stable.

- [ ] **MODEL-03 - Expand deterministic routing classification.** Route from
  request class, tool need, context size, attachments, risk, task duration, and
  explicit user choice. Preserve the current effective model unless a tested
  threshold is crossed; use hysteresis so adjacent turns do not oscillate.
  Character/word count can remain a signal but cannot be the sole definition of
  a simple task.
  **Files:** `src/agent/smart_model_routing.py` and
  `tests/agent/test_smart_model_routing.py`.
  **Done when:** destructive/high-stakes, ambiguous, recovery, code-edit, and
  long-context turns cannot silently downgrade; equivalent consecutive turns
  remain stable; explicit model selection bypasses Auto and stays pinned to the
  thread until changed.

- [ ] **MODEL-04 - Route delegated work by role with bounded escalation.** Let
  Spark select the configured subagent role without adding verbose per-call
  model arguments to the model-visible tool schema. A child may escalate only
  under an explicit tested policy; cap concurrency, iterations, and retries.
  Main turns and children may use different effective models. Permit at most one
  policy-driven escalation per turn/child and never bounce repeatedly between
  models.
  **Files:** `src/tools/delegate_tool.py`, delegation lifecycle payloads,
  `tests/tools/test_delegate.py`, and subagent tests.

- [ ] **MODEL-05 - Test Sol/Terra/Luna compatibility through Spark's actual
  transport.** Cover direct main turns, separate Spark child sessions, batches,
  reasoning efforts, auth modes, unavailable models, and the current v2/v1
  multi-agent metadata mismatch. Do not assume Codex native multi-agent behavior
  and Spark child-agent behavior are equivalent.
  **Gate:** Auto cannot assign a Sol/Terra/Luna role until the account-specific
  matrix passes or a safe fallback is proven.

- [ ] **MODEL-06 - Add one web routing-policy editor.** Replace scattered
  smart/fast/delegation controls with the single `Auto` choice plus an advanced
  role editor in Settings. Keep all explicit account-available models in the
  composer; choosing one pins the thread and bypasses Auto. Show availability,
  effective effort, fallback, live/offline source, and any compatibility warning.
  **Files:** composer model controls, Settings model section, API endpoints/types,
  and component tests.

- [ ] **MODEL-07 - Surface effective routing in the thread.** Record and display
  the actual main model, child model(s), effort, deterministic route label,
  fallback, escalation, token usage, cache usage, and child-agent usage per turn.
  Use concise labels based on observable policy signals, such as
  `Terra · normal coding task`, `Luna high · bounded background research`, or
  `Escalated to Sol · validation failed`. Never expose hidden chain-of-thought.
  Keep the normal view compact and expose policy detail on demand.
  **Files:** agent usage metadata, session persistence/API serializers,
  `src/spark_cli/web/src/components/chat/SessionInfoBar.tsx`, turn metadata
  components, and tests.

- [ ] **MODEL-08 - Build a pinned routing eval matrix.** Use representative
  direct answers, UI work, debugging, plans, research, long-running child tasks,
  safety cases, and failure recovery. Compare fixed Sol/Terra/Luna role mixes
  with the current baseline using identical prompts, toolsets, context, trials,
  and judging rules.
  **Files:** extend `tests/efficiency/fixtures/`, `tests/evals/`, and report
  tooling without committing private prompts.
  **Release gate:** establish and meet a correctness/safety quality floor first;
  among routes that meet it, choose the lowest measured paid-token cost or
  subscription-window consumption, using latency only as a tie-break. No safety
  blocker, no repeated escalation, and no material latency regression outside
  explicitly quality-first work.

- [ ] **ROUTING-PR-01 - Submit and accept the routing stack bottom-up.** Keep
  live metadata, migration, Auto policy, hysteresis, independent child routing,
  and escalation contracts in `adaptive-routing-core`; keep composer/Settings
  controls, deterministic labels, usage telemetry, and web acceptance in
  `adaptive-routing-web`. Run `gh stack submit` and attach the compatibility and
  quality/cost/latency matrices to the relevant PRs.
  **Gate:** Auto cannot become the default until both layers pass and merge.

## Phase 5: Better Skills With Lower Prompt Cost

- [x] **SKILL-00 - Initialize the skills stack from current `main`.** Run
  `gh stack init skills-invocation`; add `skills-library` only after invocation
  and provenance contracts are reviewable, then add `skills-web` for the UI.
  The stack may proceed independently of routing where file ownership does not
  overlap.
  **Done when:** each PR shows only its intended layer and the bottom PR records
  its `origin/main` base SHA.
  **Evidence (2026-08-04):** created the isolated unprefixed
  `skills-invocation` worktree directly from `origin/main` at
  `d827339dacb3b5caf5a59f2bab970b398de6316c`. Commit `4a5f3a67` contains only
  invocation/provenance contracts and focused tests; draft PR #118 targets
  `main`, records the base SHA and planned `skills-library -> skills-web`
  dependency chain, and contains no thread-stack, generated, or external-skill
  files.

- [x] **SKILL-01 - Add an explicit invocation contract.** Support user-invoked
  skills that remain available in slash commands and the Skills UI but omit
  their descriptions from the model-visible skill index. Recognize compatible
  metadata such as `disable-model-invocation: true`; preserve legacy behavior
  for skills without metadata, but honor external orchestration skills that
  declare themselves user-invoked.
  **Files:** `src/agent/skill_utils.py`, `src/agent/prompt_builder.py`,
  `src/agent/skill_commands.py`, `src/tools/skills_tool.py`, Skills API/UI, and
  tests.
  **Done when:** a user-only skill consumes zero model-index description tokens
  and is still directly invokable.
  **Evidence (2026-08-04):** canonical `user_invoked`, `model_invoked`, and
  `both` metadata now honors `disable-model-invocation: true` across prompt
  indexing, model-facing `skills_list`, direct slash commands, `skill_view`, and
  provenance-aware API records. User-only descriptions are absent from the
  model index and its cache manifest while remaining slash/API discoverable;
  external supporting files resolve from their real read-only source. The
  focused invocation, cache, provenance, and API suite passes with 232 tests
  and one skip; `git diff --check` passes. Evidence is published in draft PR
  #118 without vendored or modified external skills.

- [x] **SKILL-02 - Audit the installed engineering skills for overlap.** Compare
  external and bundled triggers, steps, references, completion criteria,
  invocation type, size, usage, provenance, license, and eval coverage. Produce
  a keep-external/improve-bundled/merge-bundled/archive-bundled decision for
  debugging, TDD, planning, review, research, prototyping, grilling, wayfinding,
  domain modeling, handoff, and subagent workflows.
  **Files:** a dated report under `docs/skills/` and machine-readable size/token
  output from existing skill metadata helpers.
  **Gate:** do not vendor an external skill. No new bundled skill is added before
  its nearest installed/bundled skill is named and a gap decision is recorded.
  **Evidence (2026-08-04):** the dated Markdown/JSON audit covers 24 bundled and
  external records with reproducible byte/token measurements, provenance,
  invocation, license, usage, eval coverage, and explicit keep/improve/merge/
  archive decisions. Its schema validator and focused tests pass; no external
  file was copied or modified.

- [x] **SKILL-03 - Integrate and evaluate the externally installed
  `i-have-adhd` skill.** Verify that it is discoverable, user-invoked,
  session-persistent where requested, removable/disableable, correctly
  attributed, and absent from ordinary model-index tokens. Compare its
  action-first behavior against baseline without copying its files into Spark.
  **Files:** skill discovery/session-state contracts and `tests/evals/skills/`.
  **Gate:** create a Spark-bundled action-first skill only if this external skill
  cannot satisfy a documented Spark-specific requirement.
  **Evidence (2026-08-04):** focused contracts verify external discovery,
  user-message invocation without a system-prompt rebuild, session-persistence
  instructions, user-only index exclusion, provenance, read-only source,
  disabling, and safe root detachment. The external installation satisfies the
  requirement, so no bundled copy was added.

- [x] **SKILL-04 - Integrate externally installed orchestration skills.** Verify
  direct invocation, dependency resolution, supporting-file loading, provenance,
  and zero ordinary index cost for `research`, `prototype`, `wayfinder`,
  `grill-me`, `grill-with-docs`, `domain-modeling`, and related user-invoked
  skills. A slash-command invocation must inject instructions as a user message
  without rebuilding the system prompt mid-conversation.
  **Files:** skill discovery, slash-command dispatch, Skills API contracts, and
  focused tests.
  **Evidence (2026-08-04):** external-root discovery now works without a local
  profile skill directory; direct slash invocation, root/reference supporting
  files, canonical provenance, user-only index exclusion, and read-only
  capabilities are covered for the installed orchestration family. The combined
  discovery/invocation/prompt suite passes with 230 tests and one skip.

- [x] **SKILL-05 - Evaluate installed planning/orchestration workflows.** Use
  representative Spark cases to compare `wayfinder`, `grill-me`,
  `grill-with-docs`, `research`, and `prototype` for trigger precision,
  autonomy boundaries, artifact quality, issue-tracker integration, and prompt
  cost. Confirm GitHub Issues operations follow
  `docs/agents/issue-tracker.md` and triage labels follow
  `docs/agents/triage-labels.md`.
  **Done when:** the Skills UI can explain when to use each without introducing
  duplicate bundled wrappers.
  **Evidence (2026-08-04):** the paired corpus covers `wayfinder`, `grill-me`,
  `grill-with-docs`, `research`, and `prototype`, including GitHub issue/triage
  rules, trigger precision, autonomy, artifacts, and index cost. Twenty-one
  shared SKILL-05/06 cases produce 84 two-trial rows; the deterministic offline
  comparator reports `release: true` at zero cost/network use.

- [x] **SKILL-06 - Evaluate external codebase/domain-design references against
  Spark's architecture guidance.** Test `codebase-design` and `domain-modeling`
  against real module seams and the single-context `CONTEXT.md`/`docs/adr/`
  contract. Keep them external and user-invoked where declared; capture only
  Spark-specific architecture guidance in repository docs.
  **Files:** eval cases plus any justified updates under `docs/agents/`,
  `CONTEXT.md`, or `docs/adr/` following their repository rules.
  **Evidence (2026-08-04):** the same isolated corpus includes trigger,
  deep-module/glossary, implementation-boundary, cross-check, `CONTEXT.md`, and
  sparse-ADR cases for `codebase-design` and `domain-modeling`. The existing
  repository architecture contract was sufficient, so no unrelated domain doc
  change was made.

- [x] **SKILL-07 - Improve canonical overlapping skills instead of duplicating
  them.** Candidate bundled improvements include a red-capable tight feedback
  loop for systematic debugging, pre-agreed public seams and vertical slices for
  TDD, and clearer links from bundled skills to better external alternatives.
  Do not edit externally installed files as part of the Spark branch.
  **Depends on:** `SKILL-02`.
  **Done when:** aliases/related-skill links point to one canonical behavior and
  replaced content remains recoverable in git history.
  **Evidence (2026-08-04):** canonical bundled debugging, TDD, planning, review,
  and subagent/provider skills now carry concise boundaries, external
  alternatives, a deterministic red-capable loop, agreed public seams, and
  vertical-slice guidance. `plan` points to `writing-plans` as its canonical
  plan-only mode. Fifteen rewrite-specific cases produce 60 paired rows with a
  clean correctness/safety release gate and no external edits.

- [x] **SKILL-08 - Add paired skill evaluations.** Run baseline, candidate, and
  comparator with pinned model/effort, isolated user configuration, identical
  cases, resumable trials, a hard spend/usage cap, blinded judging, and weighted
  correctness/autonomy/actionability/safety/concision gates.
  **Files:** `tests/evals/skills/`, runner scripts, schemas, and validation tests.
  **Gate:** a new or rewritten bundled skill does not ship until its candidate
  beats baseline without correctness or safety blockers. External integrations
  must pass discovery, invocation, isolation, provenance, and prompt-cost gates.
  **Evidence (2026-08-04):** the checked-in harness pins runtime/effort, isolates
  `HOME`/`SPARK_HOME`, runs identical resumable pairs under hard token/USD caps,
  emits separate blinded packets/condition keys, and applies weighted quality
  and safety floors. Generic integration, SKILL-05/06, and SKILL-07 corpora pass;
  the complete focused skills-library gate passes with 261 tests and one skip,
  isolated Ruff, schema validation, and `git diff --check`. Draft PR #119
  contains this independently reviewable layer above PR #118.

- [ ] **SKILL-09 - Improve the Skills UI quality signals.** Show source,
  invocation type, enabled state, approximate index-token cost, supporting-file
  count, last eval status/date, and duplicate/overlap warnings. Keep provenance
  independent of display category or name.
  **Files:** `src/spark_cli/web/src/pages/SkillsPage.tsx`,
  `src/spark_cli/web/src/pages/SkillsToolsPage.tsx`, Skills API contracts, and
  focused frontend/Python tests.

- [ ] **SKILLS-PR-01 - Submit and accept the skills stack bottom-up.** Keep
  invocation/provenance/index-cost contracts in `skills-invocation`, audited
  library decisions and evals in `skills-library`, and Skills UI signals in
  `skills-web`. Run `gh stack submit`; verify no external skill files were
  vendored or modified; attach discovery/invocation/eval evidence; then merge
  from the bottom up.

## Phase 6: Integrated Web Acceptance

- [ ] **QA-01 - Run focused Python contracts.** At minimum:

  ```bash
  source .venv/bin/activate
  python -m pytest tests/agent/test_smart_model_routing.py -q
  python -m pytest tests/tools/test_delegate.py -q
  python -m pytest tests/agent/test_subagents.py tests/agent/test_subagent_progress.py -q
  python -m pytest tests/spark_cli/test_codex_model_flow.py -q
  python -m pytest tests/agent/test_skill_commands.py tests/tools/test_skills_tool.py -q
  python -m pytest tests/spark_cli/test_web_server.py tests/spark_cli/test_web_server_events.py -q
  ```

- [ ] **QA-02 - Run frontend static and behavioral gates.** Run from
  `src/spark_cli/web/`:

  ```bash
  npm test
  npm run lint
  ```

  Fix new failures. Clearly identify any pre-existing failure with a baseline
  command and evidence; do not silently waive it.

- [ ] **QA-03 - Run long-thread and concurrent-chat stress acceptance.** Exercise
  the 50/500/2,000-row fixtures, two chats streaming at once, switching during
  generation, refresh, reconnect, gateway restart, history prepend, old-work
  expansion, minimap jumps, stop, redirect, subagent completion, Auto model
  stability, one bounded escalation, and context compaction/recovery.
  **Validation:** existing `npm run test:e2e` plus expanded deterministic flows.

- [ ] **QA-04 - Perform visual browser acceptance against the approved
  prototype.** Inspect real rendered states at 1440/1024/768px in light and dark
  themes. Compare hierarchy, spacing, typography, scroll behavior, composer
  reachability, active work, settled work, failures, plans, changed files,
  subagents, and usage controls. Save acceptance screenshots separately from
  baseline shots. Confirm the accepted result is recognizably T3-inspired in
  surface rhythm and information density while remaining recognizably Spark.
  **Gate:** a functioning route or passing tests alone do not complete this task.

- [ ] **QA-05 - Verify accessibility and input behavior.** Test keyboard-only
  navigation, focus restoration, screen-reader names, contrast, reduced motion,
  zoom, selection/copy, long unbroken text, code blocks, and narrow panels.

- [ ] **QA-06 - Compare performance with the Phase 0 baseline.** No material
  regression in stream continuity, first render, scroll stability, or memory.
  The 500-row case should update only the active turn during streaming, and the
  2,000-row case must remain navigable without safe-mode fallback under normal
  fixture load.

- [ ] **QA-07 - Run the practical repository gate.** Activate `.venv`, run
  `ruff check src/`, the relevant pytest subsets, and the full practical suite
  when feasible. Record exact counts and any documented baseline exclusions.

- [ ] **WEB-RELEASE-01 - Build the accepted web bundle only after source
  acceptance.** Run `npm run build`, inspect the generated bundle and budget,
  and verify the served web UI uses the new assets. Generated `web_dist` changes
  belong only to this final web gate, not intermediate source commits.

- [ ] **WEB-RELEASE-02 - Record the integrated stacked-PR evidence.** Link every
  merged layer and include each base SHA, stack map, scope, routing eval summary,
  skill eval summary, focused/full test results, performance comparison,
  screenshots, manual browser flows, known limitations, and explicit note that
  desktop packages were not rebuilt. Confirm all stack branches landed through
  PR review rather than direct source work on `main`.

## Deferred Desktop Gate

After all web stacks and integrated acceptance are complete, create a separate
desktop build/release plan from fresh `main`. That plan must independently cover
macOS and Windows
packaging, Tauri/Rust integration, generated asset inclusion, signing,
notarization/stapling, installers, packaged long-thread/model/skill smoke tests,
versioning, and publication. Web acceptance is a prerequisite for that work, not
proof that packaged desktop behavior is complete.

## Completion Criteria

This plan is complete only when all of the following are true:

- The implementation landed through the documented thread, routing, and skills
  feature stacks, not direct source work on `main`; no branch uses an
  assistant-specific prefix.
- The accepted main thread uses a turn-oriented hierarchy that keeps final
  answers and outcomes visible while preserving expandable raw work.
- Long, concurrent, interrupted, and reconnected chats preserve exact transcript
  content, actions, and scroll state.
- The composer exposes context, main-model, subagent-model, effort, and routing
  policy without overwhelming the default surface. New chats default to Auto;
  explicit model choices pin the thread until changed.
- Sol/Terra/Luna or any later model family is selected from live account
  capabilities and measured evals, with sticky routing, deterministic labels,
  independent child roles, at most one escalation, visible fallbacks, and manual
  overrides.
- Auto meets the correctness/safety floor before optimizing usage, uses latency
  only as a tie-break, and never silently drops context to save tokens.
- New/improved skills have one canonical purpose, appropriate invocation type,
  preserved provenance/attribution, bounded prompt cost, and passing paired eval
  gates; externally installed skills are integrated rather than vendored.
- Frontend tests, focused Python tests, practical repository checks, browser
  visual acceptance, accessibility, and performance gates have recorded evidence.
- The web bundle is built only after source acceptance, and no desktop package or
  cross-platform release is claimed by this plan.
