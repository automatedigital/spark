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

## Feature-Branch Rule

All implementation must happen on a feature branch created from the latest
`origin/main`. Do not implement any source task while `git branch --show-current`
prints `main`.

The intended branch is:

```bash
git fetch origin
git switch main
git pull --ff-only origin main
git switch -c webui-next
```

Record the base SHA in the first implementation PR. Keep unrelated generated,
reference, release, and user-owned files out of the branch. The temporary
research clones described below are not Spark dependencies and must never be
copied into or committed with this repository.

## Scope

### In scope

- The main web chat/thread panel, including turn presentation, tool activity,
  reasoning, plans, changed files, approvals, usage, scrolling, and the composer.
- Web controls and supporting backend contracts for main-model, fast-model, and
  delegated-subagent routing.
- Account-aware Codex model discovery, capability display, routing telemetry,
  and cost/token evaluation.
- New skills, improvements to overlapping existing skills, skill invocation
  metadata, skill quality evals, and clearer Skills UI provenance.
- Local web preview, browser-based visual acceptance, frontend tests, focused
  Python tests, and performance/accessibility checks.

### Out of scope until web acceptance

- Tauri/Rust changes that are only needed for packaged desktop behavior.
- `.app`, `.dmg`, Windows installer, signing, notarization, stapling, and release
  publication.
- Mobile, gateway-platform, or CLI redesign unrelated to shared API contracts.
- A wholesale copy of T3 Code's architecture, styling, dependencies, or source.
- Committing the temporary clones or generated reference screenshots.

## Research Snapshot

Research was refreshed on 2026-08-02 from fresh, shallow clones of each default
branch and from current primary documentation.

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
- Transfer to Spark: an opt-in action-first skill and the paired eval discipline.
  Preserve MIT attribution if text or test cases are adapted.

### Matt Pocock skills

- Repository: [mattpocock/skills](https://github.com/mattpocock/skills)
- Inspected commit: `2ab958093e83e0ec752e6c1c5932da465bf23e0c`
- The useful system ideas are small composable skills, a deliberate distinction
  between user-invoked orchestration and model-invoked discipline, router skills
  for discoverability, progressive disclosure through context pointers,
  checkable completion criteria, and aggressive removal of duplicated/no-op
  prose.
- High-value candidates for Spark are `research`, `prototype`,
  `codebase-design`, `domain-modeling`, `writing-great-skills`, and `handoff`.
- `diagnosing-bugs`, `tdd`, `grill-with-docs`, planning, review, and subagent
  workflows overlap Spark's installed skills. Improve or replace the existing
  canonical skill after comparison; do not install a second skill with a
  different name for the same behavior.

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
  compatibility before enabling a Sol-to-Luna preset.

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

- Final answers and concrete outcomes remain visually dominant; intermediate
  work is available without becoming the main reading path.
- Running work stays expanded and legible. Settled work becomes compact but is
  never deleted from the transcript.
- The server/session database remains authoritative. UI folds, filters, drafts,
  and optimistic state must reconcile after refresh, reconnect, and chat switch.
- Exact message text, tool results, approvals, retry/fork semantics, and the
  stable SSE recovery contracts must survive the redesign.
- Model routing is transparent, account-aware, reversible, and measured. A user
  can always see the effective model/effort and override the default.
- Skills earn their prompt cost. User-only skills should consume no model-index
  tokens; overlapping skills should have one canonical source of truth.
- Visual acceptance means inspecting the rendered web UI at representative
  widths with real long, streaming, tool-heavy, and subagent conversations.

## Dependency Map

```text
BRANCH -> BASELINE -> UI PROTOTYPES -> USER ACCEPTANCE
                              |
                              +-> THREAD MODEL -> TIMELINE -> COMPOSER -> USAGE UI
                              |
LIVE MODEL METADATA -> ROUTING POLICY -> ROUTING UI -> ROUTING EVALS
                              |
SKILL INVOCATION CONTRACT -> SKILL AUDIT -> NEW/IMPROVED SKILLS -> SKILL EVALS

THREAD + ROUTING + SKILLS -> INTEGRATED WEB QA -> ACCEPTED WEB BUNDLE

Accepted web bundle -> separate future desktop build/release plan
```

## Phase 0: Branch, Baselines, and UI Direction

- [ ] **BRANCH-01 - Create the implementation branch before source work.** Run
  the feature-branch commands above, record the `origin/main` base SHA, and
  confirm the worktree contains only intentional files.
  **Done when:** `git branch --show-current` prints `webui-next` and
  `git status --short` has no unrelated changes.

- [ ] **BASE-01 - Capture behavior fixtures for the current chat surface.** Add
  redacted fixtures for empty, short, long, streaming, interrupted, reconnecting,
  tool-heavy, reasoning-heavy, approval-pending, changed-file, and parallel
  subagent threads.
  **Files:** `src/spark_cli/web/e2e/fixtures/`, existing session fixture helpers,
  and focused API fixtures under `tests/` only where needed.
  **Done when:** the same fixtures can drive baseline and redesigned UI states
  without network or private data.

- [ ] **BASE-02 - Freeze the behavioral contracts that the redesign must keep.**
  Add tests for exact assistant copy, retry/edit/fork, paged history, active
  streaming rows, tool-result expansion, approvals, redirect/stop, scroll
  anchoring, minimap navigation, refresh/reconnect, and chat switching.
  **Files:** existing chat tests plus new focused tests beside the extracted
  models/components.
  **Validation:** `cd src/spark_cli/web && npm test`.

- [ ] **BASE-03 - Record web performance and visual baselines.** Measure React
  commits, first render, stream update rate, row measurement churn, scroll drift,
  and memory for 50-, 500-, and 2,000-row fixtures. Capture screenshots at
  1440px, 1024px, and 768px widths in light and dark themes.
  **Files:** `src/spark_cli/web/e2e/`, `src/spark_cli/web/screenshots/baseline/`,
  and existing efficiency metrics helpers.
  **Done when:** raw numbers and screenshots identify the current state; they are
  not acceptance evidence for the redesign.

- [ ] **UI-01 - Build three deliberately different main-thread prototypes.** Use
  one temporary dev-only route or query flag to compare: a T3-inspired compact
  turn timeline, a calmer document-style transcript, and a denser operations
  timeline. Each variant must use the same fixture data and preserve the same
  actions.
  **Files:** temporary components under
  `src/spark_cli/web/src/dev/thread-prototypes/` and one guarded dev entrypoint.
  **Done when:** all three run from one documented command and none is wired into
  production state.

- [ ] **UI-02 - Review the prototypes in the browser and select one direction.**
  Compare information hierarchy, long-thread scanning, tool density, composer
  reachability, changed-file visibility, and narrow-width behavior with the user.
  **Gate:** do not begin production visual refactoring until one direction and
  any retained elements from the other variants are explicitly recorded.

- [ ] **UI-03 - Remove rejected prototype code and capture the decision.** Keep
  only a small screenshot/decision note if useful; production code starts from
  the selected behavior, not by promoting an untested prototype wholesale.
  **Done when:** no temporary prototype route can ship in a production build.

## Phase 1: Turn-Oriented Thread Model

- [ ] **THREAD-01 - Define a pure presentation model for one conversation turn.**
  Convert persisted/streaming `ChatMessage` rows into typed turns containing the
  initiating user message, commentary/reasoning, tool activity, approvals,
  subagent activity, final assistant answer, usage, changed files, status, and
  timestamps.
  **Files:** new `src/spark_cli/web/src/lib/threadTimelineModel.ts` and
  `threadTimelineModel.test.ts`.
  **Done when:** mixed persisted/live events produce stable IDs and deterministic
  turn boundaries without React or network state.

- [ ] **THREAD-02 - Define settled-work folding rules.** Keep an active or
  interrupted turn expanded. For settled turns, retain the final assistant
  answer while folding intermediate reasoning/tool/subagent rows behind a
  summary such as `Worked for 2m 14s · 7 actions`.
  **Depends on:** `THREAD-01`.
  **Done when:** tests cover missing turn IDs, multiple assistant messages,
  redirect/interruption, failed tools, approvals, and resumed sessions.

- [ ] **THREAD-03 - Add structural sharing for unchanged timeline items.** A
  streaming delta should replace only the affected active item; settled turns
  must retain object identity so virtualization and memoization remain useful.
  **Files:** `threadTimelineModel.ts`, tests, and existing transcript merge code.
  **Done when:** tests assert referential stability across representative deltas.

- [ ] **THREAD-04 - Extract transport/controller concerns from `ChatPanel.tsx`.**
  Move transcript loading/recovery, stream event reduction, composer actions,
  and timeline derivation into explicit hooks/modules while retaining
  `ChatPanel` as the stable public component.
  **Files:** `ChatPanel.tsx`, new focused modules under
  `src/spark_cli/web/src/hooks/` and `src/spark_cli/web/src/lib/`.
  **Done when:** no behavior is lost, controller modules have focused tests, and
  presentation components do not fetch session state directly.

## Phase 2: Main Thread Panel Redesign

- [ ] **CHAT-01 - Implement the selected timeline shell.** Use a centered,
  readable content column, a persistent bottom composer, clear active-turn
  status, and responsive gutters. Keep Spark's visual identity rather than
  cloning T3 colors or branding.
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
  unresolved approvals prominently; allow complete raw details and stored tool
  artifacts to be expanded on demand.
  **Files:** new `TurnWorkGroup.tsx`; existing
  `src/spark_cli/web/src/components/chat/ToolCallBubble.tsx`,
  `ReasoningBubble.tsx`, and `SubagentsPanel.tsx`; and focused tests in the same
  component area.

- [ ] **CHAT-04 - Make changed files a first-class turn outcome.** Reuse the
  authoritative changes/diff data already available to the right panel. Show a
  compact file tree with additions/deletions and open-diff actions; do not infer
  success merely from a tool call string.
  **Files:** a new `ChangedFilesCard.tsx`, the existing changes-panel model/API,
  and focused tests.
  **Done when:** changed files reconcile after refresh and a file opens in the
  existing Changes tab at the expected path.

- [ ] **CHAT-05 - Add inline plan presentation.** Render active plan steps and
  proposed plan Markdown as a collapsible turn card with a shortcut to the
  existing plan/brief surface. Preserve one authoritative plan state.
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
  group attachments, context, project, main model, subagent model, reasoning,
  and advanced controls into compact discoverable controls.
  **Files:** split `src/spark_cli/web/src/components/chat/PromptBar.tsx` into
  focused composer components while keeping its public contract stable during
  migration.

- [ ] **COMPOSER-02 - Make context pressure actionable.** Keep the current token
  estimate, show context buckets, and offer remove/summarize actions before the
  threshold is reached. Label estimates separately from provider-reported usage.
  **Files:** extracted `ContextWindowMeter.tsx`, context hooks, and tests.

- [ ] **COMPOSER-03 - Keep approvals and requested user input at the point of
  action.** Pending prompts appear directly above the composer, remain after
  refresh, and cannot be mistaken for an ordinary assistant message.
  **Files:** approval/input components, session state adapters, and tests.

- [ ] **COMPOSER-04 - Add responsive and keyboard contracts.** Define behavior
  for narrow panels, right-panel-open layouts, model-picker focus, Escape,
  Enter/Shift+Enter, stop, redirect, attachment menus, and screen readers.
  **Validation:** component tests plus browser acceptance at 1440/1024/768px.

## Phase 4: Adaptive Codex Routing

- [ ] **MODEL-01 - Preserve account-scoped Codex model metadata.** Change model
  discovery from a list of slugs to a backward-compatible catalog containing
  display name, visibility, supported reasoning efforts, context/output limits,
  multi-agent version, and source/freshness when supplied by the live API/cache.
  **Files:** `src/spark_cli/codex_models.py`, `src/agent/model_metadata.py`,
  `src/spark_cli/web_server.py`, `src/spark_cli/web/src/lib/api.ts`, and
  `tests/spark_cli/test_codex_model_flow.py`.
  **Done when:** the account list remains authoritative and stale/offline data is
  visibly distinguished without inventing unavailable models.

- [ ] **MODEL-02 - Define routing roles instead of hard-coded product names.**
  Add `lead`, `balanced`, `fast`, and `subagent` role settings, each resolving to
  provider, model, reasoning effort, and fallback. Migrate existing
  `model.default`, `smart_model_routing`, and `delegation` settings without
  breaking old configs.
  **Files:** `src/spark_cli/config.py`, `src/spark_cli/model_config.py`,
  `src/agent/smart_model_routing.py`, `src/tools/delegate_tool.py`, config
  migration tests, and web API types.
  **Default intent when available and validated:** Sol for genuinely difficult
  lead work, Terra for balanced work, and Luna at measured high effort for
  bounded long-running children. The role contract, not those names, is stable.

- [ ] **MODEL-03 - Expand deterministic routing classification.** Route from
  request class, tool need, context size, attachments, risk, task duration, and
  explicit user choice. Character/word count can remain a signal but cannot be
  the sole definition of a simple task.
  **Files:** `src/agent/smart_model_routing.py` and
  `tests/agent/test_smart_model_routing.py`.
  **Done when:** destructive/high-stakes, ambiguous, recovery, code-edit, and
  long-context turns cannot silently downgrade.

- [ ] **MODEL-04 - Route delegated work by role with bounded escalation.** Let
  Spark select the configured subagent role without adding verbose per-call
  model arguments to the model-visible tool schema. A child may escalate only
  under an explicit tested policy; cap concurrency, iterations, and retries.
  **Files:** `src/tools/delegate_tool.py`, delegation lifecycle payloads,
  `tests/tools/test_delegate.py`, and subagent tests.

- [ ] **MODEL-05 - Test Sol/Terra/Luna compatibility through Spark's actual
  transport.** Cover direct main turns, separate Spark child sessions, batches,
  reasoning efforts, auth modes, unavailable models, and the current v2/v1
  multi-agent metadata mismatch. Do not assume Codex native multi-agent behavior
  and Spark child-agent behavior are equivalent.
  **Gate:** the Sol-to-Luna preset remains opt-in until the account-specific
  matrix passes or a safe fallback is proven.

- [ ] **MODEL-06 - Add one web routing-policy editor.** Replace scattered
  smart/fast/delegation controls with a clear preset plus advanced role editor.
  Show availability, effective effort, fallback, live/offline source, and any
  compatibility warning. Preserve a manual per-thread override.
  **Files:** composer model controls, Settings model section, API endpoints/types,
  and component tests.

- [ ] **MODEL-07 - Surface effective routing in the thread.** Record and display
  the actual model, effort, route reason, fallback, token usage, cache usage, and
  child-agent usage per turn. Keep the normal view compact and expose detail on
  demand.
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
  **Release gate:** no correctness or safety blocker; equal or better weighted
  quality; lower measured paid-token cost or subscription-window consumption;
  and no material latency regression outside explicitly quality-first work.

## Phase 5: Better Skills With Lower Prompt Cost

- [ ] **SKILL-01 - Add an explicit invocation contract.** Support user-invoked
  skills that remain available in slash commands and the Skills UI but omit
  their descriptions from the model-visible skill index. Keep existing skills
  model-invoked by default for compatibility.
  **Files:** `src/agent/skill_utils.py`, `src/agent/prompt_builder.py`,
  `src/agent/skill_commands.py`, `src/tools/skills_tool.py`, Skills API/UI, and
  tests.
  **Done when:** a user-only skill consumes zero model-index description tokens
  and is still directly invokable.

- [ ] **SKILL-02 - Audit the installed engineering skills for overlap.** Compare
  triggers, steps, references, completion criteria, size, usage, and eval
  coverage. Produce a keep/improve/merge/archive decision for debugging, TDD,
  planning, review, research, prototyping, handoff, and subagent workflows.
  **Files:** a dated report under `docs/skills/` and machine-readable size/token
  output from existing skill metadata helpers.
  **Gate:** no new skill is added before its nearest existing skill is named and
  a duplication decision is recorded.

- [ ] **SKILL-03 - Add an opt-in action-first output skill.** Adapt the useful
  behavior from `i-have-adhd`: next action first, bounded numbered steps,
  restated state, concrete wins, suppressed tangents, and safety/task overrides.
  Make it user-invoked and session-persistent with an explicit off command.
  **Files:** new skill under `skills/productivity/`, license/attribution, skill
  session-state support if needed, and tests.

- [ ] **SKILL-04 - Add a primary-source research skill.** It should define the
  question, prefer first-party sources, cite every material claim, use a
  background child only when useful, and save one concise research artifact at
  the repository's existing documentation location.
  **Files:** new or adapted skill under `skills/research/`, references only where
  branch-specific detail earns its token cost, and eval cases.

- [ ] **SKILL-05 - Add a throwaway prototype skill.** Support a logic branch and
  a UI branch. UI prototypes must present multiple meaningfully different
  variants from one route, state the question they answer, use one run command,
  and be removed or isolated before production merge.
  **Files:** new skill under `skills/software-development/` with concise linked
  references and eval cases.

- [ ] **SKILL-06 - Add codebase-design and skill-authoring references.** Adapt
  the deep-module/seam vocabulary and the invocation/progressive-disclosure/
  completion-criterion guidance. Keep manually requested reference skills
  user-invoked to avoid permanent prompt cost.
  **Files:** selected skills under `skills/software-development/` and
  `skills/productivity/`, preserving licenses and attribution.

- [ ] **SKILL-07 - Improve canonical overlapping skills instead of duplicating
  them.** Candidate improvements include a red-capable tight feedback loop for
  `systematic-debugging`, pre-agreed public seams and vertical slices for TDD,
  and stronger domain language/context handling in `grill-with-docs`.
  **Depends on:** `SKILL-02`.
  **Done when:** aliases/related-skill links point to one canonical behavior and
  replaced content remains recoverable in git history.

- [ ] **SKILL-08 - Add paired skill evaluations.** Run baseline, candidate, and
  comparator with pinned model/effort, isolated user configuration, identical
  cases, resumable trials, a hard spend/usage cap, blinded judging, and weighted
  correctness/autonomy/actionability/safety/concision gates.
  **Files:** `tests/evals/skills/`, runner scripts, schemas, and validation tests.
  **Gate:** a new or rewritten skill does not become bundled/default until its
  candidate beats baseline without correctness or safety blockers.

- [ ] **SKILL-09 - Improve the Skills UI quality signals.** Show source,
  invocation type, enabled state, approximate index-token cost, supporting-file
  count, last eval status/date, and duplicate/overlap warnings. Keep provenance
  independent of display category or name.
  **Files:** `src/spark_cli/web/src/pages/SkillsPage.tsx`,
  `src/spark_cli/web/src/pages/SkillsToolsPage.tsx`, Skills API contracts, and
  focused frontend/Python tests.

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
  expansion, minimap jumps, stop, redirect, and subagent completion.
  **Validation:** existing `npm run test:e2e` plus expanded deterministic flows.

- [ ] **QA-04 - Perform visual browser acceptance against the approved
  prototype.** Inspect real rendered states at 1440/1024/768px in light and dark
  themes. Compare hierarchy, spacing, typography, scroll behavior, composer
  reachability, active work, settled work, failures, plans, changed files,
  subagents, and usage controls. Save acceptance screenshots separately from
  baseline shots.
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

- [ ] **WEB-RELEASE-02 - Open the feature-branch PR with evidence.** Include the
  base SHA, scope, routing eval summary, skill eval summary, focused/full test
  results, performance comparison, screenshots, manual browser flows, known
  limitations, and explicit note that desktop packages were not rebuilt.

## Deferred Desktop Gate

After the web PR is accepted and merged, create a separate desktop build/release
plan from fresh `main`. That plan must independently cover macOS and Windows
packaging, Tauri/Rust integration, generated asset inclusion, signing,
notarization/stapling, installers, packaged long-thread/model/skill smoke tests,
versioning, and publication. Web acceptance is a prerequisite for that work, not
proof that packaged desktop behavior is complete.

## Completion Criteria

This plan is complete only when all of the following are true:

- The implementation landed from `webui-next`, not direct work on `main`.
- The accepted main thread uses a turn-oriented hierarchy that keeps final
  answers and outcomes visible while preserving expandable raw work.
- Long, concurrent, interrupted, and reconnected chats preserve exact transcript
  content, actions, and scroll state.
- The composer exposes context, main-model, subagent-model, effort, and routing
  policy without overwhelming the default surface.
- Sol/Terra/Luna or any later model family is selected from live account
  capabilities and measured evals, with visible fallbacks and overrides.
- New/improved skills have one canonical purpose, appropriate invocation type,
  preserved attribution, bounded prompt cost, and passing paired eval gates.
- Frontend tests, focused Python tests, practical repository checks, browser
  visual acceptance, accessibility, and performance gates have recorded evidence.
- The web bundle is built only after source acceptance, and no desktop package or
  cross-platform release is claimed by this plan.
