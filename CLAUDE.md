# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Environment

```bash
source venv/bin/activate   # ALWAYS activate before running Python
pip install -e ".[dev]"    # Install with dev extras
```

All Python source lives under `src/` — packages: `core`, `agent`, `spark_cli`, `tools`, `gateway`, `cron`, `acp_adapter`, `plugins`.

## Commands

```bash
# Run
spark                               # Start interactive TUI
spark setup                         # Interactive config wizard
spark doctor                        # Diagnose + fix environment

# Test
python -m pytest tests/ -q                          # Full suite (~3000 tests, ~3 min)
python -m pytest tests/test_model_tools.py -q       # Single module
python -m pytest tests/ -k "test_name" -q           # Single test
python -m pytest tests/ -m "not slow" -q            # Skip slow tests
python -m pytest tests/ --cov=src -q                # Run with coverage (requires pytest-cov)

# Lint / type check
ruff check src/                     # Linter (line-length=100, Python 3.11 target)
mypy src/agent/ src/spark_cli/      # Type checking (strict on agent/ + spark_cli/)
```

## Architecture

### Dependency Chain

```
src/tools/registry.py  (no deps — imported by all tool files)
       ↑
src/tools/*.py  (each calls registry.register() at import time)
       ↑
src/core/model_tools.py  (imports registry + triggers _discover_tools())
       ↑
src/core/run_agent.py, src/core/cli.py, environments/
```

### Key Classes

- **`AIAgent`** (`src/core/run_agent.py`) — core conversation loop. `chat()` for simple use; `run_conversation()` for full control. Synchronous; uses OpenAI message format.
- **`SparkCLI`** (`src/core/cli.py`) — prompt_toolkit interactive TUI. `process_command()` dispatches slash commands via `resolve_command()`.
- **`SessionDB`** (`src/core/spark_state.py`) — SQLite session store with FTS5 full-text search.
- **Slash Command Registry** (`src/spark_cli/commands.py`) — single `COMMAND_REGISTRY` list of `CommandDef` objects drives CLI dispatch, gateway hooks, Telegram menus, Slack routing, and autocomplete. Adding an alias only requires updating `aliases=` on the `CommandDef`.

### Adding a Tool (3 files)

1. Create `src/tools/your_tool.py` — implement handler, call `registry.register(...)`. All handlers must return a JSON string.
2. Add import to `_discover_tools()` in `src/core/model_tools.py`.
3. Add to `_SPARK_CORE_TOOLS` or a toolset in `src/tools/toolsets.py`.

### Adding a Slash Command (3 files)

1. Add `CommandDef` to `COMMAND_REGISTRY` in `src/spark_cli/commands.py`.
2. Add handler in `SparkCLI.process_command()` in `src/core/cli.py`.
3. If gateway-available, add handler in `src/gateway/run.py`.

### Adding Config

- `config.yaml` options: add to `DEFAULT_CONFIG` in `src/spark_cli/config.py`; bump `_config_version` to trigger migration.
- `.env` variables: add to `OPTIONAL_ENV_VARS` in `src/spark_cli/config.py`.

## Critical Rules

### Profile Safety — Use `get_spark_home()`

Never hardcode `~/.spark` or `Path.home() / ".spark"`. Always use:

```python
from spark_constants import get_spark_home, display_spark_home
config_path = get_spark_home() / "config.yaml"   # code paths
print(f"Saved to {display_spark_home()}/config.yaml")  # user messages
```

Hardcoding breaks profiles. Tests must mock both `Path.home()` and set `SPARK_HOME` env var.

### Prompt Caching Must Not Break

Do NOT alter past context, change toolsets, or rebuild system prompts mid-conversation. Cache-breaking forces dramatically higher costs. The only valid context alteration is during context compression.

### Known Pitfalls

- **Interactive menus**: Use `curses` (stdlib), not `simple_term_menu` — rendering bugs in tmux/iTerm2.
- **ANSI in spinner**: Do not use `\033[K` (erase-to-EOL) under `prompt_toolkit`'s `patch_stdout`. Use space-padding instead.
- **Cross-tool schema references**: Do not mention tools from other toolsets in schema descriptions — add cross-references dynamically in `get_tool_definitions()` in `model_tools.py`.
- **`_last_resolved_tool_names`** is process-global in `model_tools.py`; `delegate_tool.py` saves/restores it around subagent execution.
- **Tool handlers must not swallow `KeyboardInterrupt`/`SystemExit`**: `registry.dispatch()` re-raises these so Ctrl-C and process exit work correctly. Catch only `Exception` in handlers, not `BaseException`.
- **Optional tool deps**: Heavy or rarely-used imports (`firecrawl`, `exa_py`, `edge_tts`, etc.) must be imported inside the function that needs them, with a clear `ImportError` message. Never import optional SDKs at module top without a `try/except ImportError`.

### Test Isolation

Tests must not write to `~/.spark/`. The `_isolate_spark_home` autouse fixture in `tests/conftest.py` redirects `SPARK_HOME` to a temp dir. Profile tests must also mock `Path.home()`.

## Skin/Theme System

Skins are pure data in `src/spark_cli/skin_engine.py` (`_BUILTIN_SKINS` dict) or user YAML at `~/.spark/skins/<name>.yaml`. No code changes needed for new skins. Activate with `/skin <name>` or `display.skin` in config.

## Git Workflow

All changes go through pull requests — never push directly to `main`.

```bash
# Start work on a feature branch
git checkout -b feat/short-description

# When ready to ship
git push -u origin feat/short-description
gh pr create --repo automatedigital/spark --base main --title "..." --body "..."
```

Branch naming: `feat/`, `fix/`, `chore/`, `docs/` prefix. Keep it short and kebab-case.

When the user runs `/createpr` (or asks to create a PR):
1. Check which branch is active — if on `main`, ask the user what branch name to use and create it first.
2. Stage and commit any uncommitted changes.
3. Push the branch and open the PR against `main`.

## User State (not in repo)

```
~/.spark/           # default SPARK_HOME (overridable via env var or --profile)
├── config.yaml     # runtime config
├── .env            # API keys
├── memories/       # holographic memory store
├── sessions/       # SQLite conversation history
├── skills/         # user-installed skills
└── profiles/       # named isolated instances
```
