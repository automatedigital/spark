# Spark Agent - Development Guide

## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues for `automatedigital/spark` via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the default labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, and `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repo using root `CONTEXT.md` and `docs/adr/`. See `docs/agents/domain.md`.

Instructions for AI coding assistants and developers working in this repository.
Keep this file focused on rules that change how work should be done. Put long
architecture notes in `docs/` when they are not needed on every agent run.

## Read Before Changing Code

- This file is the canonical development guide; `CLAUDE.md` is a compact entry point.
- Read `CONTEXT.md` for domain language, `STRUCTURE.md` for source ownership, and
  relevant accepted decisions in `docs/adr/` before changing architecture.
- `PLAN.md` tracks the approved app upgrade. Check individual items only after
  their acceptance evidence passes; integrated foundations do not close browser,
  rollout or package gates. Keep evidence in GitHub Issues too.
- Inspect `git status` first. Preserve unrelated dirty work and stage only the
  intended files. Use descriptive `feat/`, `fix/` or `docs/` branches.
- Review references at the commit pinned in the plan. Adapt small, tested pieces;
  preserve applicable upstream license notices when copying code.

## Quick Start

```bash
source .venv/bin/activate
pip install -e ".[dev,web]"
```

Always activate `.venv` before running Python, tests, linters, or local servers.

Useful commands:

```bash
spark                               # Start interactive TUI
spark setup                         # Interactive config wizard
spark doctor                        # Diagnose environment

python -m pytest tests/ -q                          # Full suite
python -m pytest tests/ -k "test_name" -q           # Focused test
python -m pytest tests/ -m "not slow and not integration" -q  # Skip slow/external tests
python -m pytest tests/ -m "not integration" -q     # Skip external services
ruff check src/
mypy src/agent/ src/spark_cli/
python scripts/generate_tool_manifest.py --check
```

The web extra is required for dashboard work and tests importing FastAPI routes.
For the shared web/desktop frontend, use Node.js 22 and the nested npm lockfile:

```bash
(cd src/spark_cli/web && npm ci)
(cd src/spark_cli/web && npm run dev)
(cd src/spark_cli/web && npm run lint && npm test && npm run build)
(cd src/spark_cli/web && npm run test:e2e)
(cd src/spark_cli/web && npm run test:e2e:recovery)
(cd src/spark_cli/web && npm run test:e2e:sidebar)
```

Keep `.venv` active for browser suites that launch Python. The Node and Python
Playwright suites need their respective browser installations; see
`.github/workflows/web-quality.yml`. Manual servers and browser fixtures must use
an isolated `SPARK_HOME`, not the user's live profile.

Before pushing, run the relevant focused tests while iterating, then run
`ruff check src/`, the relevant pytest subset, and the full suite when practical
or required by the change. The pytest timeout is 30 seconds per test.

## Repo Map

All Python source lives under `src/`.

```text
src/
├── core/             # Agent runtime, CLI orchestration, session DB, tool routing
│   ├── run_agent/    # AIAgent loop; __init__.py is the public import target
│   ├── cli/          # SparkCLI package plus concern mixins
│   ├── spark_state.py
│   ├── model_tools.py
│   ├── toolsets.py
│   └── spark_constants.py
├── agent/            # Prompt/context/memory/model internals
├── spark_cli/        # CLI entrypoint, commands, setup, web UI/server
├── tools/            # Tool implementations and registry
├── gateway/          # Messaging gateway, session handling, platform adapters
├── acp_adapter/      # ACP integrations
├── cron/             # Scheduler
└── plugins/          # Memory and connector backends
```

The React/Vite source is `src/spark_cli/web/src/`; the Tauri shell is
`src/spark_cli/web/src-tauri/`. `src/spark_cli/web_dist/` is the packaged web
bundle, not the source. `web_server.py` owns chat lifecycle; domain routes live
in `src/spark_cli/*_routes.py`. `web_state.py` owns bounded web replay envelopes;
`core/spark_state.py` owns durable session events and projections. These cursors
are distinct. See `STRUCTURE.md` for the detailed map.

Other important directories:

```text
tests/       # Pytest suite
skills/      # Built-in skill library
docs/        # Durable architecture, specs, guides
scripts/     # Install and maintenance scripts
```

User state is outside the repo under `SPARK_HOME`:

```text
~/.spark/
├── config.yaml
├── .env
├── memories/
├── sessions/
├── skills/
└── profiles/
```

## Architecture Anchors

`AIAgent` is imported from `core.run_agent` and lives in `src/core/run_agent/__init__.py`.
The `core.run_agent` namespace is intentionally stable:

```python
from core.run_agent import AIAgent
```

Built-in tool discovery uses a deterministic schema manifest (ADR-0012):

```text
tools/manifest_spec.py + tools/*.py registrations
       -> scripts/generate_tool_manifest.py
       -> tools/generated_manifest.py
       -> core/model_tools.py -> tools/registry.py (schema-only entries)
       -> owning handler imported once on first invocation
```

Configured MCP discovery remains eager; unconfigured optional features remain
lazy. `_discover_tools()` is a compatibility hook, not a list of eager built-in
imports. Keep `from core.run_agent import AIAgent` stable; the conversation loop
is in `core/run_agent/turn_loop.py` and caching logic in `prompt_cache.py`.

`SparkCLI` lives in `src/core/cli/__init__.py` and is composed from concern
mixins such as `commands_mixin`, `display_mixin`, `streaming_mixin`,
`status_bar_mixin`, `voice_mixin`, `callbacks_mixin`, `tui_mixin`,
`model_mixin`, `agent_setup_mixin`, `info_mixin`, and `session_ops_mixin`.
When patching a helper used by a mixin, patch the owning module, for example
`core.cli.commands_mixin._cprint`.

Slash commands are defined in `src/spark_cli/commands.py` as `CommandDef`
entries in `COMMAND_REGISTRY`. CLI dispatch, gateway hooks, help text,
Telegram menus, Slack routing, and autocomplete derive from that registry.
Adding an alias should only require updating `aliases=` on the existing
`CommandDef`.

## Adding Things

### Tools

Adding a normal built-in tool requires registration, discovery metadata and a
toolset entry:

1. Create `src/tools/your_tool.py`, implement the handler, and call
   `registry.register(...)`.
2. Add the module to `BUILTIN_TOOL_MODULES` in `src/tools/manifest_spec.py`;
   maintain optional dependency guards/metadata there when applicable. Regenerate
   with `python scripts/generate_tool_manifest.py` and verify with `--check`.
3. Add the tool to `_SPARK_CORE_TOOLS` or another toolset in
   `src/core/toolsets.py`.

All tool handlers must return a JSON string. Optional SDK imports must use
`try/except ImportError` or be imported inside the function that needs them so
missing optional dependencies do not break all tool discovery.

Agent-level tools such as todo and memory are intercepted by the agent loop
before `handle_function_call()`. Use `src/tools/todo_tool.py` as the pattern.

### Slash Commands

Adding a slash command usually requires:

1. Add a `CommandDef` in `src/spark_cli/commands.py`.
2. Add CLI handling in `SparkCLI.process_command()` or the relevant CLI mixin.
3. If gateway-available, add gateway handling in `src/gateway/run.py`.

For persistent settings, use `save_config_value()` from
`core/cli/config_state.py`.

### Config

For `config.yaml` settings, add the option to `DEFAULT_CONFIG` in
`src/spark_cli/config.py` and bump `_config_version` when existing user configs
need migration.

For `.env` variables, add metadata to `OPTIONAL_ENV_VARS` in
`src/spark_cli/config.py`.

## Critical Rules

### Prompt Caching

Do not alter past context, change toolsets, reload memories, or rebuild system
prompts mid-conversation. Cache-breaking can dramatically increase cost and
latency. The valid place to alter context is during context compression.

Skill slash commands should inject instructions as user messages, not mutate the
system prompt mid-thread.

### Profile Safety

Spark supports isolated profiles. State paths must be profile-aware.

Use `get_spark_home()` for code paths:

```python
from core.spark_constants import get_spark_home

config_path = get_spark_home() / "config.yaml"
```

Use `display_spark_home()` for user-facing messages:

```python
from core.spark_constants import display_spark_home

print(f"Config saved to {display_spark_home()}/config.yaml")
```

Never hardcode `~/.spark` or `Path.home() / ".spark"` in code that reads or
writes Spark state. Tests that mock `Path.home()` must also set `SPARK_HOME`.

Profile operations are HOME-anchored by design: `_get_profiles_root()` returns
`Path.home() / ".spark" / "profiles"`, not `get_spark_home() / "profiles"`, so
any active profile can list all profiles.

Gateway platform adapters that connect with unique credentials should acquire a
scoped token lock in `connect()` or `start()` and release it in `disconnect()` or
`stop()`. See `src/gateway/platforms/telegram.py`.

### Generated Files

Do not edit ignored build artifacts as source. If generated bundles contain
stale local copies, clean them only as generated remnants and make the source
change in the real tracked file.

`src/tools/generated_manifest.py` is regenerated by its script, never hand-edited.
The production bundle in `src/spark_cli/web_dist/` is tracked: regenerate it from
verified frontend source at the web release gate, following the existing build
workflow. Do not have several agents regenerate bundles or lockfiles at once.

## Coordinating Implementation Work

Use `PLAN.md` packet IDs when executing the upgrade. Give each delegated task an
outcome, committed base, dependencies, allowed paths, contract fixtures, acceptance
flows, checks and expected report. Separate worktrees begin at committed content;
they do not include the parent's uncommitted changes.

Assign one writer for migrations, shared API schemas/config, generated manifests,
lockfiles and production bundles. Parallel agents should work on independent
paths. Integrate in dependency order and rerun relevant checks after integration.
Record evidence in the issue before marking its packet complete. Do not equate a
child's final message with verified completion.

## Execution And Persistence Invariants

- Reuse Spark session, turn, subagent and Kanban run identities. A durable Task,
  conversation Run and delegated Subagent are different concepts (`CONTEXT.md`).
- Only authoritative root completion may finish a parent run. Child/tool
  completion and interrupt acknowledgement are not parent completion.
- Persist lifecycle transitions before publishing them. Avoid competing writes
  in runtime and transport callbacks; define one owner when changing this path.
- Web replay journal sequence/epoch and durable session event sequence are
  distinct. Reconnect beyond retention or after process loss must reconcile a
  snapshot; never auto-replay an uncertain prompt or tool action.
- Gate runtime-specific controls on actual capabilities. Preserve existing
  provider/custom-model resolution and child tool/permission restrictions.
- Fence worker updates by their owned attempt/claim. Never infer success from
  silence, an expired lease, a spinner, or a child's summary.
- Apply execution ownership to notification callbacks and approval waiters too.
  A retired worker's cleanup must not remove a replacement worker's registration
  or resolve its pending decisions.
- Requested worktree isolation must be explicit. Preserve dirty/committed child
  work and reject unsupported isolation rather than silently sharing paths.

These rules constrain new work; the upgrade plan identifies existing paths that
still need reconciliation. They are not claims that the upgrade has shipped.

## Web UI And Gateway Work

The web UI and VPS path are common places for long-thread and multi-chat bugs.
When changing chat/session/gateway behavior:

- Test in the local web UI or Codex preview, not only with unit tests.
- Exercise long conversations, multiple chats, and switching while chats are
  still generating.
- Verify that "loading", "streaming", "offline", and "complete" states recover
  from reconnects, refreshes, gateway restarts, and stale browser state.
- Treat backend session/task state as the source of truth. UI-only status should
  expire, reconcile, or be replaced by confirmed backend state.
- Check project-scoped chats: new project chats should appear under the project
  folder, and the folder should open when the chat is created.
- For performance work, measure first-token latency, gateway startup time,
  stream continuity, and sidebar/session refresh behavior.

When testing manually, leave a short note in the ticket or final response with
the exact flow tested and whether preview/browser behavior matched expectations.

Use replay fixtures at external provider/process boundaries for lifecycle work;
exercise real persistence and projections. Keep the cache goldens, lazy manifest
and minimal-startup tests in the gate for runtime/tool changes. A command-line
pytest marker overrides the default: retain `not integration` unless external
services are intended; run serial/shared-state tests with `-n 0` as needed.

Compare measured latency/stream/sidebar behavior against a recorded baseline.
Report baseline lint/type debt separately from new failures. Web builds, served
assets, installed macOS packages and installed Windows packages are separate
claims requiring separate evidence. Packaging and publishing are separate steps;
see the build/release workflows and do not infer platform success from compilation.

## Known Pitfalls

- Do not use `simple_term_menu` for interactive menus. Use `curses` instead.
- Do not use `\033[K` under `prompt_toolkit`'s `patch_stdout`; use
  space-padding instead.
- Do not mention tools from other toolsets in static schema descriptions. Add
  dynamic cross-references in `get_tool_definitions()` in `model_tools.py`.
- `_last_resolved_tool_names` is process-global in `model_tools.py`;
  `delegate_tool.py` saves and restores it around child agent runs.
- Tool handlers must not catch `KeyboardInterrupt` or `SystemExit`. Catch
  `Exception`, not `BaseException`.
- `cronjob_tools.py` validates prompt type and enforces a 50,000-character
  limit before threat scanning and persistence; keep those guards in place.
- Tests must not write to the real `~/.spark/`. The `_isolate_spark_home`
  autouse fixture in `tests/conftest.py` redirects `SPARK_HOME`.

## Test Markers

| Marker | Purpose |
| --- | --- |
| `integration` | Requires real external services and is skipped by default |
| `slow` | Takes more than one second; useful to skip while iterating |
| `network` | Hits real network endpoints |
| `serial` | Cannot run in parallel because of shared global state |

## Skin System

Skins are pure data in `src/spark_cli/skin_engine.py` or user YAML files under
`~/.spark/skins/<name>.yaml`. They customize banner colors, spinner faces and
verbs, tool prefix, branding text, and response-box styling. Activate with
`/skin <name>` or the `display.skin` config key.
