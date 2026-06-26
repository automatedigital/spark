# Improve Spark Codebase Maintainability, Reliability, and Product Coherence

## Goal

Make Spark easier to change without losing the product qualities that matter most:
prompt caching remains stable, profiles stay isolated, Chat remains responsive,
tools stay predictable, and contributors can find the right code path quickly.

This plan intentionally replaces the completed tactical chat-streaming plan that
is still recoverable from git history. The new focus is broader codebase
improvement, not a single incident.

## Recommended Strategy

Start with stabilization and navigability, then extract architecture. The codebase
already has many features and tests; the highest leverage is to make change safer:
establish quality ratchets, align product language, split the largest orchestration
files behind compatibility boundaries, and keep docs/graph context current as the
shape changes.

The main bet: do not attempt a big-bang rewrite. Build thin seams around existing
behavior, pin invariants with tests, move code in small vertical slices, and keep
public behavior compatible until each migration is proven.

## Current Baseline

Collected on 2026-06-25 from local source and existing docs/graph.

- `src/core/run_agent/__init__.py`: 10,719 lines. The `run_agent.py` split began,
  but `AIAgent` still carries most of the loop.
- `src/gateway/run.py`: 9,737 lines. Gateway orchestration, session hygiene,
  command handling, cron ticking, adapter setup, and delivery logic still share
  one file.
- `src/spark_cli/main.py`: 7,713 lines. CLI entrypoint, model flows, update logic,
  auth/login, profile commands, and service management are still concentrated.
- `src/spark_cli/web_server.py`: 7,277 lines. Dashboard auth, settings, OAuth,
  sessions, chat, cron, workspace/project APIs, and static mounting share one
  FastAPI module.
- Frontend hotspots: `src/spark_cli/web/src/lib/api.ts` has 2,494 lines and
  `src/spark_cli/web/src/components/ChatPanel.tsx` has 2,039 lines.
- `ruff check src/ --statistics --exit-zero`: 7,049 findings, 6,030 auto-fixable.
  The biggest buckets are whitespace, old typing syntax, unsorted imports, and
  deprecated imports.
- `mypy src/agent/ src/spark_cli/`: 464 errors. Most are concentrated in
  `agent/auxiliary_client.py`, `spark_cli/web_server.py`,
  `agent/error_classifier.py`, `spark_cli/config.py`, `agent/insights.py`, and
  `agent/anthropic_adapter.py`.
- The glossary says **Workspace** is deprecated in favor of **Chat** and
  **Project**, but workspace naming still appears in 119 source/test/doc files.
- Local Tauri build outputs under `src/spark_cli/web/src-tauri/target/` and
  `src/spark_cli/web/src-tauri/resources/` are ignored and not tracked, but they
  are large enough to pollute local audits if commands do not exclude them.
- Only one GitHub Actions workflow is present: web supply-chain lockfile checking.
  There is no broad CI gate for Python tests, ruff, mypy ratchets, or frontend tests
  visible in `.github/workflows/`.

## Non-Goals

- Do not rewrite the agent loop, gateway, or dashboard from scratch.
- Do not change prompt caching semantics while moving code.
- Do not change active toolsets mid-conversation.
- Do not break existing `/api/workspace/...` clients while renaming internals to
  Project/Chat language.
- Do not make all of `mypy` strict in one pass.
- Do not land broad formatting churn mixed with behavior changes.
- Do not add new product surfaces while core reliability and naming are being
  cleaned up.

## Invariants To Protect

- Prompt caching: byte-exact cached prompt behavior must remain stable unless a
  dedicated ADR and migration test approve a change.
- Profile isolation: all state paths use `get_spark_home()`; user-facing text uses
  `display_spark_home()`.
- Public command compatibility: aliases, help, Telegram/Slack command maps, and
  autocomplete continue to derive from `COMMAND_REGISTRY`.
- Tool availability honesty: schemas only reference tools that are actually
  available for the current toolset/platform.
- Interruptibility: terminal commands, tool calls, API calls, gateway delivery, and
  web turns remain cancellable.
- User-visible Chat truth: the UI does not claim a turn is done until backend turn
  state agrees.

## Phase 0 - Confirm Direction And Freeze Baselines

- [x] Confirm the first strategic priority: stabilization/navigability before new
  feature work.
- [x] Commit or intentionally preserve the current empty `PLAN.md` replacement so
  later diffs are clean.
- [x] Save baseline command outputs under a lightweight docs or references note:
  file-size hotspots, `ruff` statistics, `mypy` error counts by file, and current
  test command health.
- [x] Add a short "refactor safety checklist" to this plan and reuse it for every
  phase.
- [x] Create a tracking issue or local checklist for each phase so tactical PRs stay
  small.
- [x] Decide whether tracked `src/spark_cli/web_dist/` assets should remain in git.
  Recommended answer: keep them for packaging if needed, but exclude them from
  code-audit scripts and graph/search defaults.

## Phase 1 - Quality Ratchet Before Architecture Work

### Ruff

- [x] Run `source venv/bin/activate && ruff check src/ --fix` in a dedicated
  mechanical PR for safe auto-fixes only.
- [x] Review any unsafe fixes separately; do not batch them with behavior changes.
- [x] Add or update CI so `ruff check src/` must pass for changed Python files.
- [x] Add a repository-local audit command that excludes ignored generated Tauri
  output and tracked frontend bundles when measuring source hotspots.

### Mypy

- [x] Add missing stubs where low-risk, especially `types-PyYAML` and
  `types-requests`, if dependency policy allows.
- [x] Create a mypy baseline report by file and error code.
- [x] Gate a first strict subset: small, central modules with few errors.
- [x] For large error clusters, set per-module budgets and require that every PR
  touching a module does not increase its error count.
- [x] Start with high-signal typed contracts around provider/runtime resolution,
  config normalization, and web chat/session DTOs.

### Tests And CI

- [x] Add a Python CI workflow with at least:
  `python -m pytest tests/ -m "not slow and not integration" -q`,
  `ruff check src/`, and the current mypy ratchet command.
- [x] Add a frontend CI workflow for `npm ci`, `npm run test`, `npm run lint`, and
  `npm run build` in `src/spark_cli/web`.
- [x] Keep full-suite local verification as the pre-push bar, but use smaller CI
  gates to keep feedback fast.
- [x] Add a test selector note for rapid iteration: agent loop, gateway, web server,
  frontend, tools, profiles, and prompt caching.

## Phase 2 - Align Product Language: Chat, Project, Artifact

The glossary deprecates **Workspace** as a user-facing concept. The code still has
`workspace_routes.py`, `/api/workspace/...`, `WorkspacePreviewPanel`, and many tests
using workspace language.

Recommended migration: keep `/api/workspace/...` as a compatibility API while
renaming internal concepts and UI text toward **Project** and **Chat**.

- [x] Inventory each workspace reference and classify it:
  public compatibility route, internal implementation name, UI copy, docs, tests,
  migration/OpenClaw legacy, or unrelated Google Workspace.
- [x] Update user-facing docs and UI text first where compatibility risk is low.
- [x] Introduce a `project_routes.py` or project service layer that owns the
  canonical names while `workspace_routes.py` delegates for backwards
  compatibility.
- [x] Rename frontend components where low-risk:
  `WorkspacePreviewPanel` to `ProjectPreviewPanel`,
  `WorkspaceTerminalPanel` to `ProjectTerminalPanel`, etc.
- [x] Keep compatibility tests for `/api/workspace/...` routes until a deliberate
  API deprecation window exists.
- [x] Add tests that public API responses do not accidentally reintroduce deprecated
  user-facing language where the product should say Project or Chat.
- [x] Update `CONTEXT.md` only if a new domain term is resolved. Do not use it as a
  refactor scratchpad.

## Phase 3 - Split The Dashboard Backend Into Routers And Services

`src/spark_cli/web_server.py` is the best next extraction target after quality
ratchets because it is large, user-facing, and already organized into conceptual
regions.

Target shape:

- `spark_cli/web_app.py`: FastAPI app construction, middleware, lifespan, SPA mount.
- `spark_cli/web/events.py`: SSE bus, event queues, event drop accounting.
- `spark_cli/web/chat_routes.py`: conversation create/send/retry/interrupt/stream.
- `spark_cli/web/chat_service.py`: active turn state, agent lifecycle, persistence.
- `spark_cli/web/config_routes.py`: config/env/model settings endpoints.
- `spark_cli/web/oauth_routes.py`: OAuth/session/device flows.
- `spark_cli/web/admin_routes.py`: gateway control, update actions, diagnostics.
- `spark_cli/web/project_routes.py`: project files, previews, manifests, terminal.
- `spark_cli/web/schemas.py`: Pydantic request/response models.

Steps:

- [x] Add route-level tests that capture current behavior before moving code.
- [x] Extract Pydantic models and pure helpers first; no route behavior changes.
- [x] Extract SSE/event bus behind a tiny interface and update tests to use it.
- [x] Extract active web turn state into a service with direct unit tests.
- [x] Move config/env/model endpoints into a router.
- [x] Move OAuth endpoints into a router.
- [x] Move conversation endpoints into a router.
- [x] Move project/workspace compatibility endpoints behind the naming plan from
  Phase 2.
- [x] Keep `web_server.py` as the import-compatible app entry until downstream
  scripts and docs are updated.
- [x] After each extraction, run:
  `source venv/bin/activate && python -m pytest tests/spark_cli/test_web_server.py tests/spark_cli/test_web_server_events.py -q`
  plus relevant frontend tests if API contracts changed.

## Phase 4 - Finish The `AIAgent` Decomposition Without Breaking Caching

ADR-0001 already says the `run_agent` split must preserve byte-exact cache
behavior. Continue that spirit: move behavior only behind golden tests.

Target shape:

- `core/run_agent/__init__.py`: public `AIAgent` facade and constructor.
- `core/run_agent/conversation_loop.py`: main iteration loop and loop decisions.
- `core/run_agent/provider_calls.py`: interruptible API call lifecycle and streaming
  adapters.
- `core/run_agent/tool_loop.py`: tool-call execution, ordering, parallelism, and
  agent-level tool interception.
- `core/run_agent/message_state.py`: message alternation, sanitization, tool-pair
  repair, history snapshots.
- `core/run_agent/persistence.py`: session persistence, memory flushing, trajectory
  saving.
- `core/run_agent/fallbacks.py`: provider fallback and retry policy integration.

Steps:

- [x] Confirm or add a golden test that serializes provider request payloads,
  system prompt blocks, cache-control positions, tool schema order, and ephemeral
  layers.
- [x] Add targeted tests around message alternation and tool pair repair before
  moving that code.
- [x] Extract pure message helpers first.
- [x] Extract provider-call helpers second, keeping streaming callback behavior
  byte-for-byte equivalent where possible.
- [x] Extract tool-loop behavior third, preserving parallel result ordering and
  interactive-tool sequencing.
- [x] Extract persistence/memory flush behavior last, because it is cross-cutting.
- [x] Update architecture docs immediately after each extraction so the maps do not
  point contributors at stale `run_agent.py` paths.
- [x] Run focused verification after each slice:
  `source venv/bin/activate && python -m pytest tests/run_agent/ tests/tools/test_interrupt.py -q`.

## Phase 5 - Split Gateway Runtime Around Stable Adapter Contracts

`src/gateway/run.py` is a second orchestration hotspot. It should become a thin
runner around explicit services, while platform adapters keep their existing
behavior.

Target shape:

- `gateway/runner.py`: `GatewayRunner` lifecycle and top-level orchestration.
- `gateway/commands.py`: slash command resolution and handlers.
- `gateway/session_hygiene.py`: compression thresholds and session repair.
- `gateway/authz.py`: allowlists, pairing, and internal-event bypass rules.
- `gateway/delivery_runtime.py`: outbound delivery and formatting.
- `gateway/cron_tick.py`: scheduler tick ownership.
- `gateway/adapter_registry.py`: adapter creation and token lock enforcement.

Steps:

- [x] Add platform adapter conformance tests for connect/start/stop/disconnect,
  token locks, message normalization, media placeholders, and delivery errors.
- [x] Extract slash-command handling into a module that still consumes
  `spark_cli.commands.resolve_command()`.
- [x] Extract authorization and pairing checks with tests for each platform class.
- [x] Extract session hygiene and preserve context-compression thresholds.
- [x] Extract cron tick ownership without changing the 60-second gateway tick.
- [x] Keep `gateway/run.py` as the import-compatible entrypoint until docs and
  service commands move.
- [x] Run:
  `source venv/bin/activate && python -m pytest tests/gateway/ -q`.

## Phase 6 - Type Provider And Model Runtime Boundaries

The mypy baseline points at provider/model code as a concentrated risk area:
`agent/auxiliary_client.py`, `agent/anthropic_adapter.py`,
`agent/error_classifier.py`, `agent/model_metadata.py`, `spark_cli/auth.py`, and
`spark_cli/config.py`.

Recommended direction: define typed DTOs at the boundaries, not throughout every
provider implementation at once.

- [x] Create typed provider runtime records for provider id, model id, API mode,
  base URL, credential source, timeout policy, and request overrides.
- [x] Make `resolve_runtime_provider()` return one typed object instead of loose
  dicts where practical.
- [x] Make auxiliary client fallback decisions consume typed provider records.
- [x] Normalize error classification into typed constructors rather than
  unstructured `dict[str, object]` splats.
- [x] Add tests for 401/403 credential refresh, 429/5xx fallback, timeout handling,
  and provider-specific API mode selection.
- [x] Use these typed seams to reduce mypy errors in the high-risk files without
  broad rewrites.

## Phase 7 - Harden Tool Runtime And Toolset Contracts

The tool system is powerful and extensible; the improvement target is predictable
availability and safer cross-tool guidance.

- [x] Add a tool manifest snapshot test for core tool names, toolsets, and schema
  ordering.
- [x] Add tests that optional SDK import failures disable only the relevant tool.
- [x] Add tests that schema post-processing never mentions unavailable tools.
- [x] Add a small typed wrapper for `ToolEntry` handler signatures and check
  handler return values are JSON strings in tests.
- [x] Add a registry health command or test helper that reports unavailable tools
  with their missing env vars or import errors.
- [x] Review large tool files (`browser_tool.py`, `web_tools.py`, `mcp_tool.py`,
  `terminal_tool.py`) for extraction only after registry contracts are pinned.

Review decision:

- `browser_tool.py` (3,002 lines): extract session lifecycle/cleanup and backend
  health first; leave action handlers and registry schemas in place until the
  lifecycle module has direct tests.
- `web_tools.py` (2,378 lines): extract backend client/config resolution before
  summarization or extraction flow; this keeps availability checks and provider
  errors isolated.
- `mcp_tool.py` (2,264 lines): extract MCP loop/server task lifecycle before tool
  schema conversion; dynamic registry behavior should stay behind the Phase 7
  registry contracts.
- `terminal_tool.py` (1,722 lines): extract env config/session lifecycle before
  command execution; approval and sudo behavior should remain in the public tool
  path until narrower golden tests cover it.

## Phase 8 - Split Frontend Data Layer And Chat State

Frontend hotspots are `api.ts` and `ChatPanel.tsx`. The recent streaming fixes made
state truth much better; now the improvement is keeping that behavior testable.

Target shape:

- `src/lib/api/`: grouped clients for sessions, chat, config, projects, tools,
  cron, OAuth, and admin actions.
- `src/lib/events/`: typed SSE subscription and reconnection logic.
- `src/lib/chatTurnState.ts`: already-pure or extracted turn state reducer.
- `src/components/chat/`: presentational message list, composer, status row,
  virtualizer integration, and tool rows.
- `src/pages/ChatPage.tsx`: page composition only.

Steps:

- [x] Split `api.ts` into domain clients while preserving exported compatibility
  names until all callers move.
  - [x] First safe slice: moved model endpoints into `src/lib/api/model.ts` while
    preserving `api.getModelStatus()` and related compatibility methods.
  - [x] Moved session/chat, config/env, cron, skills/tools, OAuth, admin, and
    project/workspace endpoints into `src/lib/api/*` clients while preserving
    existing `api.*` method names.
- [x] Extract event subscription/recovery logic with tests for dropped SSE,
  missed `turn_done`, and backend-active polling.
- [x] Keep streaming markdown and virtualizer stress tests as permanent guards.
- [x] Rename workspace-facing components according to Phase 2.
- [x] Add a Playwright smoke for the core Chat loop if the existing tooling is
  acceptable in CI.
- [x] Run `cd src/spark_cli/web && npm run test && npm run lint && npm run build`.

## Phase 9 - Keep Documentation And Graph Context Honest

Several docs still mention old file shapes such as `run_agent.py` and `cli.py`.
Because agents and contributors rely on these maps, stale architecture docs become
real engineering drag.

- [x] Update `docs/building/architecture.md` after each extraction.
- [x] Update `docs/building/agent-loop.md` to describe the current
  `core/run_agent/` package rather than the old monolith path.
- [x] Update `docs/building/context-compression-and-caching.md` when compression
  ownership moves.
- [x] Update `docs/building/tools-runtime.md` if registry/toolset contracts change.
- [x] Add a lightweight docs freshness check: docs should not point to deleted or
  renamed source files.
- [x] Run `graphify update .` after code changes so graphify-backed exploration
  remains useful.
- [x] Create ADRs only for hard-to-reverse trade-offs. Likely ADR candidates:
  internal Project naming with `/api/workspace` compatibility, provider runtime
  typed contracts, and web backend router boundaries.

## Refactor Safety Checklist

Use this before merging any phase slice.

- [x] Is the change behavior-preserving, or does it clearly say what behavior
  changes?
- [x] Are prompt-caching-sensitive payloads covered if `AIAgent` changed?
- [x] Are profile paths still resolved through `get_spark_home()` and
  `display_spark_home()`?
- [x] Are command aliases/help/autocomplete/gateway menus still registry-derived?
- [x] Are public API routes backwards compatible or explicitly covered by a
  migration/deprecation note?
- [x] Are tests focused on the moved behavior, not just import success?
- [x] Did docs and graphify context get updated when architecture changed?
- [x] Did generated artifacts stay out of source diffs unless intentionally
  required for packaging?

## Suggested Milestone Order

1. Phase 0: confirm direction and save baselines.
2. Phase 1: quality ratchets and CI.
3. Phase 2: naming inventory and low-risk Chat/Project language cleanup.
4. Phase 3: web backend extraction, starting with events and active turn service.
5. Phase 4: finish `AIAgent` decomposition under cache golden tests.
6. Phase 6: provider/model typed contracts, because this helps both agent and web
   backend reliability.
7. Phase 5: gateway extraction once command/provider contracts are clearer.
8. Phase 8: frontend data/chat state split.
9. Phase 9: documentation and graph upkeep throughout, not at the end.

## Verification Commands

Run narrow commands during each phase, and the full suite before pushing.

```bash
source venv/bin/activate
ruff check src/
mypy src/agent/ src/spark_cli/
python -m pytest tests/ -m "not slow and not integration" -q
python -m pytest tests/run_agent/ tests/tools/test_interrupt.py -q
python -m pytest tests/spark_cli/ tests/cli/ -q
python -m pytest tests/gateway/ -q
cd src/spark_cli/web && npm run test
cd src/spark_cli/web && npm run lint
cd src/spark_cli/web && npm run build
graphify update .
python scripts/check_docs_source_links.py
```

## Current Open Decision

Decision 1: The first milestone is stabilization/navigability before new feature
work.

Rationale: Spark already has a lot of product surface area; the best compounding
improvement is to make future changes cheaper and safer before adding more
surface area.
