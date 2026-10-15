# Spark repository structure

Source map verified for the 2026-10-15 planning review at `0ed3654b`.
[AGENTS.md](AGENTS.md) owns development rules, [CONTEXT.md](CONTEXT.md) owns domain
language, and [PLAN.md](PLAN.md) owns the proposed upgrade. New paths named in the
plan are proposals unless they appear in the current source map below.

## Top level

| Path | Purpose |
| --- | --- |
| `src/` | Python packages and the nested web/desktop application |
| `tests/` | Python unit, integration, replay/efficiency and browser-support tests; markers/config in `pyproject.toml` |
| `docs/` | User/developer guides, integration specifications, `adr/` decisions and `agents/` tracker conventions |
| `scripts/` | Installation, manifest generation, maintenance, web/desktop builds and releases |
| `skills/` | Bundled instruction packs; user-installed skills live outside the checkout |
| `environments/` | Terminal/training environments and backend integrations |
| `assets/`, `docker/` | Branding and container configuration |
| `.github/workflows/` | Python/web quality, supply-chain and Windows desktop beta gates |
| `pyproject.toml` | Python package/extras, entry points, pytest, Ruff and mypy policy |
| `package.json` | Root Node tooling; distinct from the web app's dependency manifest |
| `PLAN.md` | Upgrade packets, dependencies, estimates, acceptance and execution ledger |

## Runtime and backend ownership

| Existing path | Responsibility |
| --- | --- |
| `src/core/run_agent/__init__.py` | Stable `AIAgent` import and composition boundary |
| `src/core/run_agent/turn_loop.py` | Conversation loop; other responsibility-specific modules hold provider payloads, retries, scheduling and persistence transformations |
| `src/core/run_agent/prompt_cache.py` | Cache-sensitive prompt assembly; ADR-0001 golden tests apply |
| `src/core/cli/` | `SparkCLI` and concern mixins; patch helpers in their owning module |
| `src/core/spark_state.py` | `state.db`: sessions/messages, FTS, compression/context state, durable session events/checkpoints, web turn/pending-action and subagent records |
| `src/core/kanban_db.py` | `kanban.db`: durable board tasks, dependencies, claims, task runs and events |
| `src/core/async_runtime.py`, `tool_scheduler.py` | Shared bounded async/blocking execution and tool scheduling |
| `src/core/model_tools.py` | Tool definitions/dispatch and configured dynamic discovery |
| `src/tools/registry.py`, `manifest_spec.py`, `generated_manifest.py` | Lazy handler registry, built-in module metadata and generated deterministic schemas (ADR-0012) |
| `src/core/toolsets.py` | Named tool bundles and core tool membership |
| `src/tools/delegate_tool.py`, `src/agent/subagents.py` | Restricted child execution and bounded/persisted lifecycle callbacks |
| `src/tools/session_search_tool.py`, `checkpoint_manager.py` | Historical recall and filesystem checkpoints |
| `src/agent/` | Prompt/context compression, model/provider helpers, memory and skills internals |
| `src/plugins/memory/`, `src/core/dream.py` | Local/optional memory providers and explicitly invoked/scheduled reflection |
| `src/tools/skill_manager_tool.py`, `skill_usage.py`, `skills_metadata.py`, `skills_guard.py` | Skill mutations, usage/lifecycle, provenance/capabilities and validation |
| `src/spark_cli/main.py`, `commands.py`, `config.py` | Entrypoints, shared slash-command registry and versioned config |
| `src/spark_cli/runtime_provider.py` | Shared provider/credential/model resolution; reuse rather than hardcoding provider routes |
| `src/spark_cli/web_server.py` | FastAPI app, conversation lifecycle, streaming, submission and chat API composition |
| `src/spark_cli/web_state.py`, `web_state_schema.json` | Versioned web envelopes and bounded process-epoch replay journal |
| `src/spark_cli/web_projections.py` | Deterministic plan/changed-file projection helpers |
| `src/spark_cli/*_routes.py` | Domain routes: projects/files, tasks, memory, providers, cron, connectors, admin and others |
| `src/spark_cli/web_runtime.py` | Small shared server/route helpers; not an orchestration engine |
| `src/spark_cli/kanban_dispatch.py`, `kanban_worker.py` | Gateway task claims/spawn and one-shot worker execution |
| `src/gateway/` | Messaging sessions, adapters, dispatch and scheduled ticks |
| `src/cron/` | Scheduled job definitions, execution and delivery |
| `src/acp_adapter/` | Agent Client Protocol integrations |

## Web and desktop application

Paths in this table are relative to `src/spark_cli/`.

| Path | Responsibility |
| --- | --- |
| `web/package.json`, `web/package-lock.json` | React 19 / Vite / TypeScript / Tauri tooling; use this lockfile with `npm ci` |
| `web/src/App.tsx` | App shell, shared providers, global navigation and page composition |
| `web/src/pages/ChatPage.tsx` | Primary Chat workbench and project/right-panel coordination |
| `web/src/components/sidebar/` | Project/session rows, Inbox, project creation and virtualized row model |
| `web/src/lib/sessionStore.tsx`, `sidebarPrefs.ts` | Shared session/project selection/list state and navigation preferences |
| `web/src/hooks/useChatSessionController.ts`, `useChatStreamController.ts` | History/session loading and live stream lifecycle |
| `web/src/hooks/useEventBus.ts` | Shared event transport/subscription and reconnect consumption |
| `web/src/lib/webState.ts`, `chatStreamReducer.ts`, `chatRecovery.ts` | Envelope normalization, stream merge and recovery interpretation |
| `web/src/lib/draftStore.ts`, `web/src/hooks/useChatDraft.ts` | Versioned unsent input and persistence/recovery |
| `web/src/components/chat/` | Composer, timeline, approvals, plans, changed files, recovery and child-agent detail |
| `web/src/hooks/useSubagents.ts`, `web/src/lib/subagents.ts` | Child snapshots, detail loading and live lifecycle reconciliation |
| `web/src/components/workspace/` | Existing file tree, terminal, preview and project panels; Workspace is a legacy path name, not a second product surface |
| `web/src/lib/api.ts`, `apiTypes.ts`, `api_*.ts` | Shared API facade/types and domain clients |
| `web/e2e/` | Multi-chat, recovery, history anchor, sidebar-scale, baseline and Python draft browser flows |
| `web/src/**/*.test.ts` | Frontend unit/contract tests |
| `web/src-tauri/` | Rust shell, capabilities, platform config and native lifecycle |
| `web_dist/` | Tracked generated production bundle served/packaged by Python; regenerate from source, never patch minified files |

The Tauri configuration uses a loading frontend and backend boot process; inspect
existing scripts rather than assuming `web/dist/` alone is the installed product.
Ignored `node_modules/`, Rust targets and frozen sidecars are not source.

## Verification and packaging entry points

- `.github/workflows/python-quality.yml`: selected Ruff families, incremental
  mypy and fast non-integration pytest.
- `.github/workflows/web-quality.yml`: lint/types/Vitest and real-backend browser
  contracts, including separate Python Playwright installation for draft tests.
- `scripts/generate_tool_manifest.py`: regenerate or `--check` built-in schemas.
- `tests/run_agent/test_caching_golden.py`, `tests/tools/test_lazy_manifest.py`,
  `tests/test_minimal_startup.py`: runtime/cache/discovery regression boundaries.
- `scripts/build_desktop.sh`, `scripts/build_desktop_windows.ps1`: desktop builds.
- `scripts/release.py`, signing/notarization scripts: publication/build support;
  inspect the relevant workflow before use. A build does not prove installation.

## Active-profile state (outside source)

The default Spark home is `~/.spark/`, overridden by `SPARK_HOME` or profile
selection. Code resolves it through `get_spark_home()`; display paths through
`display_spark_home()`. This tree shows representative current locations, not a
complete configuration schema.

```text
<active Spark home>/
├── config.yaml                 # Settings
├── .env                        # Secrets
├── SOUL.md                     # Agent identity/preferences
├── state.db                    # Sessions/messages and durable lifecycle data
├── kanban.db                   # Task board and task attempts
├── memories/                   # Local memory
├── sessions/                   # Session files/exports, not the primary SQLite DB
├── skills/                     # User skills and usage metadata
├── dreams/                     # Explicit/scheduled reflection state
├── workspace/wiki/             # Dream review output and wiki
├── logs/
└── dashboard.token             # Dashboard remote API authentication
```

Named profiles are rooted at `~/.spark/profiles/<name>/` by design, independent
of which profile is active. Do not put one profile's state under another profile.
Tests use temporary homes; manual servers and browser fixtures must do the same.
New receipts/worktree/skill-history locations in `PLAN.md` are design work, not
additional existing state directories.
