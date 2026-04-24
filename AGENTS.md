# Spark Agent - Development Guide

Instructions for AI coding assistants and developers working on the spark-agent codebase.

## Development Environment

```bash
source venv/bin/activate  # ALWAYS activate before running Python
```

## Project Structure

```
spark-agent/
├── src/                  # All Python source
│   ├── core/             # Agent runtime
│   │   ├── run_agent.py      # AIAgent class — core conversation loop
│   │   ├── cli.py            # SparkCLI class — interactive CLI (prompt_toolkit)
│   │   ├── spark_state.py    # SessionDB — SQLite session store (FTS5 search)
│   │   ├── model_tools.py    # Tool orchestration, _discover_tools(), handle_function_call()
│   │   ├── toolsets.py       # Toolset definitions (_SPARK_CORE_TOOLS, etc.)
│   │   ├── spark_constants.py # get_spark_home(), display_spark_home(), SPARK_HOME resolution
│   │   └── batch_runner.py   # Parallel batch processing
│   ├── agent/            # Agent internals
│   │   ├── prompt_builder.py     # System prompt assembly
│   │   ├── context_compressor.py # Auto context compression
│   │   ├── context_engine.py     # Context window management
│   │   ├── prompt_caching.py     # Anthropic prompt caching
│   │   ├── anthropic_adapter.py  # Anthropic SDK adapter
│   │   ├── auxiliary_client.py   # Auxiliary LLM client (vision, summarization)
│   │   ├── memory_manager.py     # Memory read/write orchestration
│   │   ├── memory_provider.py    # Memory provider abstraction
│   │   ├── model_metadata.py     # Model context lengths, token estimation
│   │   ├── models_dev.py         # models.dev registry integration
│   │   ├── smart_model_routing.py # SMART/FAST model routing
│   │   ├── display.py            # KawaiiSpinner, tool preview formatting
│   │   ├── skill_commands.py     # Skill slash commands (shared CLI/gateway)
│   │   └── trajectory.py         # Trajectory saving helpers
│   ├── spark_cli/        # CLI entry point and subcommands
│   │   ├── main.py           # Entry point — all `spark` subcommands
│   │   ├── config.py         # DEFAULT_CONFIG, OPTIONAL_ENV_VARS, migration
│   │   ├── commands.py       # Slash command definitions + SlashCommandCompleter
│   │   ├── callbacks.py      # Terminal callbacks (clarify, sudo, approval)
│   │   ├── setup.py          # Interactive setup wizard
│   │   ├── skin_engine.py    # Skin/theme engine — CLI visual customization
│   │   ├── banner.py         # ASCII banner rendering
│   │   ├── doctor.py         # `spark doctor` diagnostics
│   │   ├── profiles.py       # `spark profile` subcommand
│   │   ├── skills_config.py  # `spark skills` — enable/disable skills per platform
│   │   ├── tools_config.py   # `spark tools` — enable/disable tools per platform
│   │   ├── skills_hub.py     # `/skills` slash command (search, browse, install)
│   │   ├── models.py         # Model catalog, provider model lists
│   │   ├── model_switch.py   # Shared /model switch pipeline (CLI + gateway)
│   │   ├── auth.py           # Provider credential resolution
│   │   ├── web/              # React/Vite web dashboard source
│   │   └── web_server.py     # FastAPI web server for dashboard
│   ├── tools/            # Tool implementations (one file per tool)
│   │   ├── registry.py       # Central tool registry (schemas, handlers, dispatch)
│   │   ├── approval.py       # Dangerous command detection
│   │   ├── terminal_tool.py  # Terminal orchestration
│   │   ├── process_registry.py # Background process management
│   │   ├── file_tools.py     # File read/write/search/patch
│   │   ├── web_tools.py      # Web search/extract (Parallel + Firecrawl)
│   │   ├── vision_tools.py   # Image analysis
│   │   ├── browser_tool.py   # Browser automation
│   │   ├── code_execution_tool.py # execute_code sandbox
│   │   ├── delegate_tool.py  # Subagent delegation
│   │   ├── mcp_tool.py       # MCP client
│   │   ├── todo_tool.py      # Agent-level todo tool (intercepted before handle_function_call)
│   │   ├── memory_tool.py    # Agent-level memory tool
│   │   ├── tts_tool.py       # Text-to-speech
│   │   ├── transcription_tools.py # Audio transcription
│   │   ├── image_generation_tool.py # Image generation
│   │   └── environments/     # Terminal backends (local, docker, ssh, modal, daytona, singularity)
│   ├── gateway/          # Messaging platform gateway
│   │   ├── run.py            # Main loop, slash commands, message dispatch
│   │   ├── session.py        # SessionStore — conversation persistence
│   │   ├── hooks.py          # Event hooks system
│   │   └── platforms/        # Adapters: telegram, discord, slack, whatsapp, signal,
│   │                         #   matrix, mattermost, wecom, weixin, dingtalk, feishu,
│   │                         #   bluebubbles, email, sms, homeassistant, qqbot
│   ├── acp_adapter/      # ACP server (VS Code / Zed / JetBrains integration)
│   ├── cron/             # Scheduler (jobs.py, scheduler.py)
│   └── plugins/          # Memory backends (Honcho, Mem0, Supermemory, etc.)
├── environments/         # RL training environments (Atropos)
├── skills/               # Skill library (~26 categories)
├── tests/                # Pytest suite (~3000 tests)
├── scripts/              # Install script and utilities
├── docs/                 # Full documentation (guides, developer-guide, reference, specs)
```

**User config:** `~/.spark/config.yaml` (settings), `~/.spark/.env` (API keys)

## File Dependency Chain

```
src/core/spark_constants.py  (no deps — SPARK_HOME resolution, imported everywhere)
       |
src/tools/registry.py  (no other deps — imported by all tool files)
       ↑
src/tools/*.py  (each calls registry.register() at import time)
       ↑
src/core/model_tools.py  (imports tools/registry + triggers _discover_tools())
       ↑
src/core/run_agent.py, src/core/cli.py, src/core/batch_runner.py, environments/
```

---

## AIAgent Class (run_agent.py)

```python
class AIAgent:
    def __init__(self,
        model: str = "anthropic/claude-opus-4.6",
        max_iterations: int = 90,
        enabled_toolsets: list = None,
        disabled_toolsets: list = None,
        quiet_mode: bool = False,
        save_trajectories: bool = False,
        platform: str = None,           # "cli", "telegram", etc.
        session_id: str = None,
        skip_context_files: bool = False,
        skip_memory: bool = False,
        # ... plus provider, api_mode, callbacks, routing params
    ): ...

    def chat(self, message: str) -> str:
        """Simple interface — returns final response string."""

    def run_conversation(self, user_message: str, system_message: str = None,
                         conversation_history: list = None, task_id: str = None) -> dict:
        """Full interface — returns dict with final_response + messages."""
```

### Agent Loop

The core loop is inside `run_conversation()` — entirely synchronous:

```python
while api_call_count < self.max_iterations and self.iteration_budget.remaining > 0:
    response = client.chat.completions.create(model=model, messages=messages, tools=tool_schemas)
    if response.tool_calls:
        for tool_call in response.tool_calls:
            result = handle_function_call(tool_call.name, tool_call.args, task_id)
            messages.append(tool_result_message(result))
        api_call_count += 1
    else:
        return response.content
```

Messages follow OpenAI format: `{"role": "system/user/assistant/tool", ...}`. Reasoning content is stored in `assistant_msg["reasoning"]`.

---

## CLI Architecture (cli.py)

- **Rich** for banner/panels, **prompt_toolkit** for input with autocomplete
- **KawaiiSpinner** (`src/agent/display.py`) — animated faces during API calls, `┊` activity feed for tool results
- `load_cli_config()` in cli.py merges hardcoded defaults + user config YAML
- **Skin engine** (`src/spark_cli/skin_engine.py`) — data-driven CLI theming; initialized from `display.skin` config key at startup; skins customize banner colors, spinner faces/verbs/wings, tool prefix, response box, branding text
- `process_command()` is a method on `SparkCLI` — dispatches on canonical command name resolved via `resolve_command()` from the central registry
- Skill slash commands: `src/agent/skill_commands.py` scans `~/.spark/skills/`, injects as **user message** (not system prompt) to preserve prompt caching

### Slash Command Registry (`src/spark_cli/commands.py`)

All slash commands are defined in a central `COMMAND_REGISTRY` list of `CommandDef` objects. Every downstream consumer derives from this registry automatically:

- **CLI** — `process_command()` resolves aliases via `resolve_command()`, dispatches on canonical name
- **Gateway** — `GATEWAY_KNOWN_COMMANDS` frozenset for hook emission, `resolve_command()` for dispatch
- **Gateway help** — `gateway_help_lines()` generates `/help` output
- **Telegram** — `telegram_bot_commands()` generates the BotCommand menu
- **Slack** — `slack_subcommand_map()` generates `/spark` subcommand routing
- **Autocomplete** — `COMMANDS` flat dict feeds `SlashCommandCompleter`
- **CLI help** — `COMMANDS_BY_CATEGORY` dict feeds `show_help()`

### Adding a Slash Command

1. Add a `CommandDef` entry to `COMMAND_REGISTRY` in `src/spark_cli/commands.py`:
```python
CommandDef("mycommand", "Description of what it does", "Session",
           aliases=("mc",), args_hint="[arg]"),
```
2. Add handler in `SparkCLI.process_command()` in `src/core/cli.py`:
```python
elif canonical == "mycommand":
    self._handle_mycommand(cmd_original)
```
3. If the command is available in the gateway, add a handler in `src/gateway/run.py`:
```python
if canonical == "mycommand":
    return await self._handle_mycommand(event)
```
4. For persistent settings, use `save_config_value()` in `src/core/cli.py`

**CommandDef fields:**
- `name` — canonical name without slash (e.g. `"background"`)
- `description` — human-readable description
- `category` — one of `"Session"`, `"Configuration"`, `"Tools & Skills"`, `"Info"`, `"Exit"`
- `aliases` — tuple of alternative names (e.g. `("bg",)`)
- `args_hint` — argument placeholder shown in help (e.g. `"<prompt>"`, `"[name]"`)
- `cli_only` — only available in the interactive CLI
- `gateway_only` — only available in messaging platforms
- `gateway_config_gate` — config dotpath (e.g. `"display.tool_progress_command"`); when set on a `cli_only` command, the command becomes available in the gateway if the config value is truthy. `GATEWAY_KNOWN_COMMANDS` always includes config-gated commands so the gateway can dispatch them; help/menus only show them when the gate is open.

**Adding an alias** requires only adding it to the `aliases` tuple on the existing `CommandDef`. No other file changes needed — dispatch, help text, Telegram menu, Slack mapping, and autocomplete all update automatically.

---

## Adding New Tools

Requires changes in **3 files**:

**1. Create `src/tools/your_tool.py`:**
```python
import json, os
from tools.registry import registry

def check_requirements() -> bool:
    return bool(os.getenv("EXAMPLE_API_KEY"))

def example_tool(param: str, task_id: str = None) -> str:
    return json.dumps({"success": True, "data": "..."})

registry.register(
    name="example_tool",
    toolset="example",
    schema={"name": "example_tool", "description": "...", "parameters": {...}},
    handler=lambda args, **kw: example_tool(param=args.get("param", ""), task_id=kw.get("task_id")),
    check_fn=check_requirements,
    requires_env=["EXAMPLE_API_KEY"],
)
```

**2. Add import** in `model_tools.py` `_discover_tools()` list.

**3. Add to `toolsets.py`** — either `_SPARK_CORE_TOOLS` (all platforms) or a new toolset.

The registry handles schema collection, dispatch, availability checking, and error wrapping. All handlers MUST return a JSON string.

**Path references in tool schemas**: If the schema description mentions file paths (e.g. default output directories), use `display_spark_home()` (`from core.spark_constants import display_spark_home`) to make them profile-aware. The schema is generated at import time, which is after `_apply_profile_override()` sets `SPARK_HOME`.

**State files**: If a tool stores persistent state (caches, logs, checkpoints), use `get_spark_home()` (`from core.spark_constants import get_spark_home`) for the base directory — never `Path.home() / ".spark"`. This ensures each profile gets its own state.

**Agent-level tools** (todo, memory): intercepted by `run_agent.py` before `handle_function_call()`. See `todo_tool.py` for the pattern.

---

## Adding Configuration

### config.yaml options:
1. Add to `DEFAULT_CONFIG` in `src/spark_cli/config.py`
2. Bump `_config_version` (currently 5) to trigger migration for existing users

### .env variables:
1. Add to `OPTIONAL_ENV_VARS` in `src/spark_cli/config.py` with metadata:
```python
"NEW_API_KEY": {
    "description": "What it's for",
    "prompt": "Display name",
    "url": "https://...",
    "password": True,
    "category": "tool",  # provider, tool, messaging, setting
},
```

### Config loaders (two separate systems):

| Loader | Used by | Location |
|--------|---------|----------|
| `load_cli_config()` | CLI mode | `cli.py` |
| `load_config()` | `spark tools`, `spark setup` | `src/spark_cli/config.py` |
| Direct YAML load | Gateway | `src/gateway/run.py` |

---

## Skin/Theme System

The skin engine (`src/spark_cli/skin_engine.py`) provides data-driven CLI visual customization. Skins are **pure data** — no code changes needed to add a new skin.

### Architecture

```
src/spark_cli/skin_engine.py    # SkinConfig dataclass, built-in skins, YAML loader
~/.spark/skins/*.yaml           # User-installed custom skins (drop-in)
```

- `init_skin_from_config()` — called at CLI startup, reads `display.skin` from config
- `get_active_skin()` — returns cached `SkinConfig` for the current skin
- `set_active_skin(name)` — switches skin at runtime (used by `/skin` command)
- `load_skin(name)` — loads from user skins first, then built-ins, then falls back to default
- Missing skin values inherit from the `default` skin automatically

### What skins customize

| Element | Skin Key | Used By |
|---------|----------|---------|
| Banner panel border | `colors.banner_border` | `banner.py` |
| Banner panel title | `colors.banner_title` | `banner.py` |
| Banner section headers | `colors.banner_accent` | `banner.py` |
| Banner dim text | `colors.banner_dim` | `banner.py` |
| Banner body text | `colors.banner_text` | `banner.py` |
| Response box border | `colors.response_border` | `cli.py` |
| Spinner faces (waiting) | `spinner.waiting_faces` | `display.py` |
| Spinner faces (thinking) | `spinner.thinking_faces` | `display.py` |
| Spinner verbs | `spinner.thinking_verbs` | `display.py` |
| Spinner wings (optional) | `spinner.wings` | `display.py` |
| Tool output prefix | `tool_prefix` | `display.py` |
| Per-tool emojis | `tool_emojis` | `display.py` → `get_tool_emoji()` |
| Agent name | `branding.agent_name` | `banner.py`, `cli.py` |
| Welcome message | `branding.welcome` | `cli.py` |
| Response box label | `branding.response_label` | `cli.py` |
| Prompt symbol | `branding.prompt_symbol` | `cli.py` |

### Built-in skins

- `default` — Classic Spark gold/kawaii (the current look)
- `ares` — Crimson/bronze war-god theme with custom spinner wings
- `mono` — Clean grayscale monochrome
- `slate` — Cool blue developer-focused theme

### Adding a built-in skin

Add to `_BUILTIN_SKINS` dict in `src/spark_cli/skin_engine.py`:

```python
"mytheme": {
    "name": "mytheme",
    "description": "Short description",
    "colors": { ... },
    "spinner": { ... },
    "branding": { ... },
    "tool_prefix": "┊",
},
```

### User skins (YAML)

Users create `~/.spark/skins/<name>.yaml`:

```yaml
name: cyberpunk
description: Neon-soaked terminal theme

colors:
  banner_border: "#FF00FF"
  banner_title: "#00FFFF"
  banner_accent: "#FF1493"

spinner:
  thinking_verbs: ["jacking in", "decrypting", "uploading"]
  wings:
    - ["⟨⚡", "⚡⟩"]

branding:
  agent_name: "Cyber Agent"
  response_label: " ⚡ Cyber "

tool_prefix: "▏"
```

Activate with `/skin cyberpunk` or `display.skin: cyberpunk` in config.yaml.

---

## Important Policies
### Prompt Caching Must Not Break

Spark-Agent ensures caching remains valid throughout a conversation. **Do NOT implement changes that would:**
- Alter past context mid-conversation
- Change toolsets mid-conversation
- Reload memories or rebuild system prompts mid-conversation

Cache-breaking forces dramatically higher costs. The ONLY time we alter context is during context compression.

### Working Directory Behavior
- **CLI**: Uses current directory (`.` → `os.getcwd()`)
- **Messaging**: Uses `MESSAGING_CWD` env var (default: home directory)

### Background Process Notifications (Gateway)

When `terminal(background=true, notify_on_complete=true)` is used, the gateway runs a watcher that
detects process completion and triggers a new agent turn. Control verbosity of background process
messages with `display.background_process_notifications`
in config.yaml (or `SPARK_BACKGROUND_NOTIFICATIONS` env var):

- `all` — running-output updates + final message (default)
- `result` — only the final completion message
- `error` — only the final message when exit code != 0
- `off` — no watcher messages at all

---

## Profiles: Multi-Instance Support

Spark supports **profiles** — multiple fully isolated instances, each with its own
`SPARK_HOME` directory (config, API keys, memory, sessions, skills, gateway, etc.).

The core mechanism: `_apply_profile_override()` in `src/spark_cli/main.py` sets
`SPARK_HOME` before any module imports. All 119+ references to `get_spark_home()`
automatically scope to the active profile.

### Rules for profile-safe code

1. **Use `get_spark_home()` for all SPARK_HOME paths.** Import from `core.spark_constants`.
   NEVER hardcode `~/.spark` or `Path.home() / ".spark"` in code that reads/writes state.
   ```python
   # GOOD
   from core.spark_constants import get_spark_home
   config_path = get_spark_home() / "config.yaml"

   # BAD — breaks profiles
   config_path = Path.home() / ".spark" / "config.yaml"
   ```

2. **Use `display_spark_home()` for user-facing messages.** Import from `core.spark_constants`.
   This returns `~/.spark` for default or `~/.spark/profiles/<name>` for profiles.
   ```python
   # GOOD
   from core.spark_constants import display_spark_home
   print(f"Config saved to {display_spark_home()}/config.yaml")

   # BAD — shows wrong path for profiles
   print("Config saved to ~/.spark/config.yaml")
   ```

3. **Module-level constants are fine** — they cache `get_spark_home()` at import time,
   which is AFTER `_apply_profile_override()` sets the env var. Just use `get_spark_home()`,
   not `Path.home() / ".spark"`.

4. **Tests that mock `Path.home()` must also set `SPARK_HOME`** — since code now uses
   `get_spark_home()` (reads env var), not `Path.home() / ".spark"`:
   ```python
   with patch.object(Path, "home", return_value=tmp_path), \
        patch.dict(os.environ, {"SPARK_HOME": str(tmp_path / ".spark")}):
       ...
   ```

5. **Gateway platform adapters should use token locks** — if the adapter connects with
   a unique credential (bot token, API key), call `acquire_scoped_lock()` from
   `gateway.status` in the `connect()`/`start()` method and `release_scoped_lock()` in
   `disconnect()`/`stop()`. This prevents two profiles from using the same credential.
   See `src/gateway/platforms/telegram.py` for the canonical pattern.

6. **Profile operations are HOME-anchored, not SPARK_HOME-anchored** — `_get_profiles_root()`
   returns `Path.home() / ".spark" / "profiles"`, NOT `get_spark_home() / "profiles"`.
   This is intentional — it lets `spark -p coder profile list` see all profiles regardless
   of which one is active.

## Known Pitfalls

### DO NOT hardcode `~/.spark` paths
Use `get_spark_home()` from `core.spark_constants` for code paths. Use `display_spark_home()`
for user-facing print/log messages. Hardcoding `~/.spark` breaks profiles — each profile
has its own `SPARK_HOME` directory. This was the source of 5 bugs fixed in PR #3575.

### DO NOT use `simple_term_menu` for interactive menus
Rendering bugs in tmux/iTerm2 — ghosting on scroll. Use `curses` (stdlib) instead. See `src/spark_cli/tools_config.py` for the pattern.

### DO NOT use `\033[K` (ANSI erase-to-EOL) in spinner/display code
Leaks as literal `?[K` text under `prompt_toolkit`'s `patch_stdout`. Use space-padding: `f"\r{line}{' ' * pad}"`.

### `_last_resolved_tool_names` is a process-global in `model_tools.py`
`_run_single_child()` in `delegate_tool.py` saves and restores this global around subagent execution. If you add new code that reads this global, be aware it may be temporarily stale during child agent runs.

### Tool handlers must not catch `KeyboardInterrupt` or `SystemExit`
`registry.dispatch()` re-raises `KeyboardInterrupt` and `SystemExit` so Ctrl-C and graceful shutdown work correctly. Handlers should only catch `Exception`, never `BaseException`.

### Optional tool dependencies must use `try/except ImportError`
Heavy or infrequently-used SDKs (e.g., `firecrawl`, `exa_py`, `edge_tts`, `fal_client`) must NOT be imported at module top without a guard. Pattern:
```python
try:
    from some_sdk import SomeClient
except ImportError:
    SomeClient = None  # type: ignore[assignment,misc]
```
Then check `if SomeClient is None: raise ImportError("Install with: pip install 'spark-agent[extra]'")` inside the function that uses it. This ensures that missing optional dependencies only fail the specific tool — not the entire tool discovery process.

### Cron job prompts are validated before storage
`cronjob_tools.py` enforces a 50,000-character limit and a type check on `prompt` before threat scanning and persistence. Cron jobs run unattended with full tool access; keep these guards in place.

### DO NOT hardcode cross-tool references in schema descriptions
Tool schema descriptions must not mention tools from other toolsets by name (e.g., `browser_navigate` saying "prefer web_search"). Those tools may be unavailable (missing API keys, disabled toolset), causing the model to hallucinate calls to non-existent tools. If a cross-reference is needed, add it dynamically in `get_tool_definitions()` in `model_tools.py` — see the `browser_navigate` / `execute_code` post-processing blocks for the pattern.

### Tests must not write to `~/.spark/`
The `_isolate_spark_home` autouse fixture in `tests/conftest.py` redirects `SPARK_HOME` to a temp dir. Never hardcode `~/.spark/` paths in tests.

**Profile tests**: When testing profile features, also mock `Path.home()` so that
`_get_profiles_root()` and `_get_default_spark_home()` resolve within the temp dir.
Use the pattern from `tests/spark_cli/test_profiles.py`:
```python
@pytest.fixture
def profile_env(tmp_path, monkeypatch):
    home = tmp_path / ".spark"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("SPARK_HOME", str(home))
    return home
```

---

## Testing

```bash
source venv/bin/activate
python -m pytest tests/ -q                      # Full suite (~3000 tests, ~3 min)
python -m pytest tests/tools/ -q                # Tool-level tests
python -m pytest tests/gateway/ -q              # Gateway tests
python -m pytest tests/ -m "not slow" -q        # Skip slow tests (network/sleep-heavy)
python -m pytest tests/ -m "not integration" -q # Skip tests requiring real API keys
python -m pytest tests/ --cov=src -q            # Run with coverage report
```

### Test markers

| Marker | Purpose |
|--------|---------|
| `integration` | Requires real external services (API keys, Modal, etc.) — skipped by default |
| `slow` | Takes >1 second; use `-m "not slow"` to skip during rapid iteration |
| `network` | Hits real network endpoints; skip on offline / CI without credentials |
| `serial` | Cannot run in parallel (shared global state); xdist respects this |

### Before pushing

Verify locally with `ruff check src/`, `mypy src/agent/ src/spark_cli/`, and `python -m pytest tests/ -q` (or narrower subsets while iterating). Per-test timeout is 30 s (`pytest-timeout` in `pyproject.toml`).

Always run the full suite before pushing changes.
