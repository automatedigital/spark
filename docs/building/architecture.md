---
sidebar_position: 1
title: "Architecture"
description: "Spark Agent internals - major subsystems, execution paths, data flow, and where to read next"
---

# Architecture

Use this page to get your bearings in the Spark codebase. Each section links to the deeper doc for that subsystem.

## What Runs What

Every entry point — the CLI, the messaging gateway, the ACP editor server, batch jobs — feeds into one class: `AIAgent` in `run_agent.py`. Platform differences live at the edges, not in the core.

```text
                        Entry Points
  CLI (cli.py)    Gateway (gateway/run.py)    ACP (acp_adapter/)
  Batch Runner    API Server                  Python Library

                       ↓ all routes through ↓

                     AIAgent (run_agent.py)

   Prompt          Provider       Tool
   Builder         Resolution     Dispatch
   (prompt_        (runtime_      (model_
    builder.py)     provider.py)   tools.py)

   Compression    3 API Modes    Tool Registry
   & Caching      chat_compl.    (registry.py)
                  codex_resp.    47 tools
                  anthropic      19 toolsets

              ↓                          ↓
 Session Storage                  Tool Backends
 (SQLite + FTS5)                  Terminal (6 backends)
 spark_state.py                   Browser (5 backends)
 gateway/session.py               Web (4 backends)
                  MCP (dynamic)
                  File, Vision, etc.
```

## Directory Map

```text
spark-agent/
 run_agent.py              # AIAgent - core conversation loop (~10,700 lines)
 cli.py                    # SparkCLI - interactive terminal UI (~10,000 lines)
 model_tools.py            # Tool discovery, schema collection, dispatch
 toolsets.py               # Tool groupings and platform presets
 spark_state.py           # SQLite session/state database with FTS5
 spark_constants.py       # SPARK_HOME, profile-aware paths
 batch_runner.py           # Batch trajectory generation

 agent/                    # Agent internals
    prompt_builder.py     # System prompt assembly
    context_engine.py     # ContextEngine ABC (pluggable)
    context_compressor.py # Default engine - lossy summarization
    prompt_caching.py     # Anthropic prompt caching
    auxiliary_client.py   # Auxiliary LLM for side tasks (vision, summarization)
    model_metadata.py     # Model context lengths, token estimation
    models_dev.py         # models.dev registry integration
    anthropic_adapter.py  # Anthropic Messages API format conversion
    display.py            # KawaiiSpinner, tool preview formatting
    skill_commands.py     # Skill slash commands
    memory_manager.py    # Memory manager orchestration
    memory_provider.py   # Memory provider ABC
    trajectory.py         # Trajectory saving helpers

 spark_cli/               # CLI subcommands and setup
    main.py               # Entry point - all `spark` subcommands (~6,000 lines)
    config.py             # DEFAULT_CONFIG, OPTIONAL_ENV_VARS, migration
    commands.py           # COMMAND_REGISTRY - central slash command definitions
    auth.py               # PROVIDER_REGISTRY, credential resolution
    runtime_provider.py   # Provider -> api_mode + credentials
    models.py             # Model catalog, provider model lists
    model_switch.py       # /model command logic (CLI + gateway shared)
    setup.py              # Interactive setup wizard (~3,100 lines)
    skin_engine.py        # CLI theming engine
    skills_config.py      # spark skills - enable/disable per platform
    skills_hub.py         # /skills slash command
    tools_config.py       # spark tools - enable/disable per platform
    plugins.py            # PluginManager - discovery, loading, hooks
    callbacks.py          # Terminal callbacks (clarify, sudo, approval)
    gateway.py            # spark gateway start/stop

 tools/                    # Tool implementations (one file per tool)
    registry.py           # Central tool registry
    approval.py           # Dangerous command detection
    terminal_tool.py      # Terminal orchestration
    process_registry.py   # Background process management
    file_tools.py         # read_file, write_file, patch, search_files
    web_tools.py          # web_search, web_extract
    browser_tool.py       # 10 browser automation tools
    code_execution_tool.py # execute_code sandbox
    delegate_tool.py      # Subagent delegation
    mcp_tool.py           # MCP client (~2,200 lines)
    credential_files.py   # File-based credential passthrough
    env_passthrough.py    # Env var passthrough for sandboxes
    ansi_strip.py         # ANSI escape stripping
    environments/         # Terminal backends (local, docker, ssh, modal, daytona, singularity)

 gateway/                  # Messaging platform gateway
    run.py                # GatewayRunner - message dispatch (~9,000 lines)
    session.py            # SessionStore - conversation persistence
    delivery.py           # Outbound message delivery
    pairing.py            # DM pairing authorization
    hooks.py              # Hook discovery and lifecycle events
    mirror.py             # Cross-session message mirroring
    status.py             # Token locks, profile-scoped process tracking
    builtin_hooks/        # Always-registered hooks
    platforms/            # 18 adapters: telegram, discord, slack, whatsapp,
                          #   signal, matrix, mattermost, email, sms,
                          #   dingtalk, feishu, wecom, wecom_callback, weixin,
                          #   bluebubbles, qqbot, homeassistant, webhook, api_server

 acp_adapter/              # ACP server (VS Code / Zed / JetBrains)
 cron/                     # Scheduler (jobs.py, scheduler.py)
 plugins/memory/           # Memory provider plugins
 plugins/context_engine/   # Context engine plugins
 environments/             # RL training environments (Atropos)
 skills/                   # Bundled skills (always available)
 optional-skills/          # Official optional skills (install explicitly)
 tests/                    # Pytest suite (~3,000+ tests)
```

## Data Flow

### CLI Session

```text
User input → SparkCLI.process_input()
  → AIAgent.run_conversation()
    → prompt_builder.build_system_prompt()
    → runtime_provider.resolve_runtime_provider()
    → API call (chat_completions / codex_responses / anthropic_messages)
    → tool_calls? → model_tools.handle_function_call() → loop
    → final response → display → save to SessionDB
```

### Gateway Message

```text
Platform event → Adapter.on_message() → MessageEvent
  → GatewayRunner._handle_message()
    → authorize user
    → resolve session key
    → create AIAgent with session history
    → AIAgent.run_conversation()
    → deliver response back through adapter
```

### Cron Job

```text
Scheduler tick → load due jobs from jobs.json
  → create fresh AIAgent (no history)
  → inject attached skills as context
  → run job prompt
  → deliver response to target platform
  → update job state and next_run
```

## Recommended Reading Order

Start here, then follow the chain that matches what you're building:

1. **This page** — orient yourself
2. **[Agent Loop Internals](./agent-loop.md)** — how AIAgent works turn by turn
3. **[Prompt Assembly](./prompt-assembly.md)** — how the system prompt is built
4. **[Provider Runtime Resolution](./provider-runtime.md)** — how providers are selected
5. **[Adding Providers](./adding-providers.md)** — practical guide for a new provider
6. **[Tools Runtime](./tools-runtime.md)** — tool registry, dispatch, environments
7. **[Session Storage](./session-storage.md)** — SQLite schema, FTS5, session lineage
8. **[Gateway Internals](./gateway-internals.md)** — messaging platform gateway
9. **[Context Compression & Prompt Caching](./context-compression-and-caching.md)**
10. **[ACP Internals](./editor-extension-internals.md)** — IDE integration
11. **[Environments, Benchmarks & Data Generation](./environments.md)** — RL training

## Subsystem Summaries

### Agent Loop

`AIAgent` in `run_agent.py` is the synchronous orchestration engine. It handles provider selection, prompt construction, tool execution, retries, fallback, callbacks, compression, and persistence. Three API modes support different provider backends.

→ [Agent Loop Internals](./agent-loop.md)

### Prompt System

- **`prompt_builder.py`** — Assembles the system prompt from personality (SOUL.md), memory (MEMORY.md, USER.md), skills, context files (AGENTS.md, .spark.md), tool-use guidance, and model-specific instructions
- **`prompt_caching.py`** — Applies Anthropic cache breakpoints for prefix caching
- **`context_compressor.py`** — Summarizes middle conversation turns when context exceeds thresholds

→ [Prompt Assembly](./prompt-assembly.md), [Context Compression & Prompt Caching](./context-compression-and-caching.md)

### Provider Resolution

One shared resolver used by CLI, gateway, cron, ACP, and auxiliary calls. Maps `(provider, model)` tuples to `(api_mode, api_key, base_url)`. Handles 18+ providers, OAuth flows, credential pools, and alias resolution.

→ [Provider Runtime Resolution](./provider-runtime.md)

### Tool System

Central tool registry with 47 tools across 19 toolsets. Tool files self-register at import time. The registry handles schema collection, dispatch, availability checking, and error wrapping. Terminal tools support 6 backends (local, Docker, SSH, Daytona, Modal, Singularity).

→ [Tools Runtime](./tools-runtime.md)

### Session Persistence

SQLite-based session storage with FTS5 full-text search. Sessions have lineage tracking (parent/child across compressions), per-platform isolation, and atomic writes with contention handling.

→ [Session Storage](./session-storage.md)

### Messaging Gateway

Long-running process with 18 platform adapters, unified session routing, user authorization (allowlists + DM pairing), slash command dispatch, hook system, cron ticking, and background maintenance.

→ [Gateway Internals](./gateway-internals.md)

### Plugin System

Three discovery sources: `~/.spark/plugins/` (user), `.spark/plugins/` (project), and pip entry points. Plugins register tools, hooks, and CLI commands. Two specialized plugin types: memory providers (`plugins/memory/`) and context engines (`plugins/context_engine/`). Both are single-select, configured via `spark plugins` or `config.yaml`.

→ [Plugin Guide](/docs/guides/build-a-plugin), [Memory Provider Plugin](./memory-provider-plugin.md)

### Cron

First-class agent tasks (not shell scripts). Jobs store in JSON, support multiple schedule formats, can attach skills and scripts, and deliver to any platform.

→ [Cron Internals](./cron-internals.md)

### ACP Integration

Exposes Spark as an editor-native agent over stdio/JSON-RPC for VS Code, Zed, and JetBrains.

→ [ACP Internals](./editor-extension-internals.md)

### RL / Environments / Trajectories

Full environment framework for evaluation and RL training. Integrates with Atropos, supports multiple tool-call parsers, and generates ShareGPT-format trajectories.

→ [Environments, Benchmarks & Data Generation](./environments.md), [Trajectories & Training Format](./trajectory-format.md)

## Design Principles

| Principle | What it means in practice |
|-----------|--------------------------|
| **Prompt stability** | System prompt doesn't change mid-conversation. No cache-breaking mutations except explicit user actions (`/model`). |
| **Observable execution** | Every tool call is visible via callbacks. Progress updates in CLI (spinner) and gateway (chat messages). |
| **Interruptible** | API calls and tool execution can be cancelled mid-flight by user input or signals. |
| **Platform-agnostic core** | One AIAgent class serves CLI, gateway, ACP, batch, and API server. Platform differences live in the entry point. |
| **Loose coupling** | Optional subsystems (MCP, plugins, memory providers, RL environments) use registry patterns and check_fn gating, not hard dependencies. |
| **Profile isolation** | Each profile (`spark -p <name>`) gets its own SPARK_HOME, config, memory, sessions, and gateway PID. Multiple profiles run concurrently. |

## Import Dependency Chain

```text
tools/registry.py  (no deps - imported by all tool files)
       ↓
tools/*.py  (each calls registry.register() at import time)
       ↓
model_tools.py  (imports tools/registry + triggers tool discovery)
       ↓
run_agent.py, cli.py, batch_runner.py, environments/
```

Tool registration happens at import time, before any agent instance is created. Adding a new tool requires an import in `model_tools.py`'s `_discover_tools()` list.
