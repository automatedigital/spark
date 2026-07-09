# CLAUDE.md

Claude Code guidance for this repository. `AGENTS.md` is the canonical and more
detailed guide; this file is the compact Claude-specific version.

## Start Here

```bash
source .venv/bin/activate
pip install -e ".[dev]"
```

Always activate `.venv` before running Python, tests, linters, or local servers.

Common commands:

```bash
spark                               # Start interactive TUI
spark setup                         # Interactive config wizard
spark doctor                        # Diagnose environment

python -m pytest tests/ -q
python -m pytest tests/ -k "test_name" -q
python -m pytest tests/ -m "not slow" -q
ruff check src/
mypy src/agent/ src/spark_cli/
```

## Architecture

All Python source lives under `src/`:

- `core/` - agent runtime, CLI orchestration, session DB, tool routing
- `core/run_agent/` - `AIAgent`; import with `from core.run_agent import AIAgent`
- `core/cli/` - `SparkCLI` package plus concern mixins
- `agent/` - prompt, context, memory, model, and adapter internals
- `spark_cli/` - CLI entrypoint, commands, setup, web UI/server
- `tools/` - tool implementations and registry
- `gateway/` - messaging gateway, sessions, platform adapters
- `cron/`, `acp_adapter/`, `plugins/` - scheduler, editor integrations, backends

Tool discovery flows through:

```text
src/core/spark_constants.py
       |
src/tools/registry.py
       ↑
src/tools/*.py
       ↑
src/core/model_tools.py
       ↑
src/core/run_agent/, src/core/cli/, src/core/batch_runner.py
```

Slash commands are defined in `src/spark_cli/commands.py` as `CommandDef`
entries in `COMMAND_REGISTRY`. CLI dispatch, gateway hooks, help text, Telegram
menus, Slack routing, and autocomplete derive from that registry.

## Adding Things

Add a tool in three places:

1. Create `src/tools/your_tool.py`, implement the handler, and register it.
2. Add the import to `_discover_tools()` in `src/core/model_tools.py`.
3. Add it to `_SPARK_CORE_TOOLS` or another toolset in `src/core/toolsets.py`.

All tool handlers must return JSON strings.

Add a slash command in three places:

1. Add a `CommandDef` in `src/spark_cli/commands.py`.
2. Add CLI handling in `SparkCLI.process_command()` or the relevant mixin.
3. If gateway-available, add gateway handling in `src/gateway/run.py`.

Config settings live in `DEFAULT_CONFIG` in `src/spark_cli/config.py`; bump
`_config_version` when existing user configs need migration. `.env` metadata
lives in `OPTIONAL_ENV_VARS`.

## Critical Rules

Use profile-aware paths:

```python
from core.spark_constants import get_spark_home, display_spark_home

config_path = get_spark_home() / "config.yaml"
print(f"Saved to {display_spark_home()}/config.yaml")
```

Never hardcode `~/.spark` or `Path.home() / ".spark"` for Spark state. Tests
that mock `Path.home()` must also set `SPARK_HOME`.

Do not alter past context, change toolsets, reload memories, or rebuild system
prompts mid-conversation. The valid place to alter context is during context
compression.

Do not edit ignored build artifacts as source. If a generated bundle has stale
local content, clean it as generated output and make the source edit in the real
tracked file.

## Web UI And Gateway Checks

For chat/session/gateway changes, test in the local web UI or Codex preview.
Exercise long conversations, multiple chats, and switching chats while responses
are still generating. Verify loading, streaming, offline, complete, reconnect,
refresh, and gateway-restart states.

Backend session/task state should be the source of truth. UI-only status should
expire, reconcile, or be replaced by confirmed backend state.

## Known Pitfalls

- Use `curses`, not `simple_term_menu`, for interactive menus.
- Do not use `\033[K` under `prompt_toolkit`'s `patch_stdout`; use space-padding.
- Do not mention unavailable cross-tool names in static tool schema descriptions.
- `_last_resolved_tool_names` is process-global in `model_tools.py`.
- Tool handlers must not catch `KeyboardInterrupt` or `SystemExit`; catch
  `Exception`, not `BaseException`.
- Optional SDKs should not break tool discovery; guard imports with
  `try/except ImportError` or import inside the function that needs them.
- Tests must not write to the real `~/.spark/`; use the existing test fixtures.

## User State

```text
~/.spark/
├── config.yaml
├── .env
├── memories/
├── sessions/
├── skills/
└── profiles/
```
