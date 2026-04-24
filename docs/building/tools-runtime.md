---
sidebar_position: 9
title: "Tools Runtime"
description: "Runtime behavior of the tool registry, toolsets, dispatch, and terminal environments"
---

# Tools Runtime

Spark tools are self-registering functions, grouped into toolsets, and executed through a central registry and dispatch system. Understanding this pipeline is the key to adding new tools, debugging unexpected availability, and reasoning about execution order.

Primary files:

- `tools/registry.py`
- `model_tools.py`
- `toolsets.py`
- `tools/terminal_tool.py`
- `tools/environments/*`

## How tools register themselves

Every tool module calls `registry.register(...)` at import time. When `model_tools.py` is imported, it runs `_discover_tools()` which imports every tool module — triggering those registration calls.

### `registry.register()` parameters

```python
registry.register(
    name="terminal",               # Unique tool name (used in API schemas)
    toolset="terminal",            # Toolset this tool belongs to
    schema={...},                  # OpenAI function-calling schema (description, parameters)
    handler=handle_terminal,       # The function that executes when the tool is called
    check_fn=check_terminal,       # Optional: returns True/False for availability
    requires_env=["SOME_VAR"],     # Optional: env vars needed (for UI display)
    is_async=False,                # Whether the handler is an async coroutine
    description="Run commands",    # Human-readable description
    emoji="",                    # Emoji for spinner/progress display
)
```

Each call creates a `ToolEntry` stored in the singleton `ToolRegistry._tools` dict, keyed by tool name. If two tools share a name, the later registration wins and a warning is logged.

### Discovery: `_discover_tools()`

`_discover_tools()` imports every tool module in order:

```python
_modules = [
    "tools.web_tools",
    "tools.terminal_tool",
    "tools.file_tools",
    "tools.vision_tools",
    "tools.mixture_of_agents_tool",
    "tools.image_generation_tool",
    "tools.skills_tool",
    "tools.skill_manager_tool",
    "tools.browser_tool",
    "tools.cronjob_tools",
    "tools.rl_training_tool",
    "tools.tts_tool",
    "tools.todo_tool",
    "tools.memory_tool",
    "tools.session_search_tool",
    "tools.clarify_tool",
    "tools.code_execution_tool",
    "tools.delegate_tool",
    "tools.process_registry",
    "tools.send_message_tool",
    # "tools.honcho_tools",  # Removed - Honcho is now a memory provider plugin
    "tools.homeassistant_tool",
]
```

Errors in optional tools are caught and logged — one broken tool doesn't prevent the others from loading.

After core discovery, MCP tools and plugin tools are also discovered:

1. **MCP tools** — `tools.mcp_tool.discover_mcp_tools()` reads MCP server config and registers tools from external servers.
2. **Plugin tools** — `spark_cli.plugins.discover_plugins()` loads user/project/pip plugins that may register additional tools.

**Optional SDK imports** must use `try/except ImportError` at module level. A missing package should only disable its own tool. For example, `web_tools.py` wraps `from firecrawl import Firecrawl` in a try/except and checks `if Firecrawl is None` before instantiating it — giving a clear "install with pip" error at call time rather than a module-level crash.

## Tool availability: `check_fn`

Each tool can declare a `check_fn` — a callable that returns `True` when the tool is available. Typical checks:

- **API key present** — e.g., `lambda: bool(os.environ.get("SERP_API_KEY"))`
- **Service running** — e.g., checking if the Honcho server is configured
- **Binary installed** — e.g., verifying `playwright` is available for browser tools

When `registry.get_definitions()` builds the schema list for the model, it runs each `check_fn()`:

```python
# Simplified from registry.py
if entry.check_fn:
    try:
        available = bool(entry.check_fn())
    except Exception:
        available = False   # Exceptions = unavailable
    if not available:
        continue            # Skip this tool entirely
```

Key behaviors:
- Check results are **cached per-call** — shared `check_fn` references only run once.
- Exceptions in `check_fn()` are treated as "unavailable" — fail-safe by default.
- `is_toolset_available()` checks whether a toolset's `check_fn` passes, used for UI display and toolset resolution.

## Toolset resolution

Toolsets are named bundles of tools. Spark resolves the active set through:

- Explicit enabled/disabled toolset lists
- Platform presets (`spark-cli`, `spark-telegram`, etc.)
- Dynamic MCP toolsets
- Curated special-purpose sets like `spark-acp`

### How `get_tool_definitions()` filters tools

The main entry point is `model_tools.get_tool_definitions(enabled_toolsets, disabled_toolsets, quiet_mode)`:

1. **`enabled_toolsets` provided** — only tools from those toolsets are included. Each toolset name expands via `resolve_toolset()` into individual tool names.
2. **`disabled_toolsets` provided** — start with ALL toolsets, subtract the disabled ones.
3. **Neither provided** — include all known toolsets.
4. **Registry filtering** — the resolved tool name set goes to `registry.get_definitions()`, which applies `check_fn` filtering and returns OpenAI-format schemas.
5. **Dynamic schema patching** — after filtering, `execute_code` and `browser_navigate` schemas are adjusted to only reference tools that actually passed filtering. This prevents the model from hallucinating calls to unavailable tools.

### Legacy toolset names

Old toolset names with `_tools` suffixes (e.g., `web_tools`, `terminal_tools`) map to their modern equivalents via `_LEGACY_TOOLSET_MAP` for backward compatibility.

## Dispatch

When the model returns a `tool_call`, the flow is:

```
Model response with tool_call
    ↓
run_agent.py agent loop
    ↓
model_tools.handle_function_call(name, args, task_id, user_task)
    ↓
[Agent-loop tools?] -> handled directly by agent loop (todo, memory, session_search, delegate_task)
    ↓
[Plugin pre-hook] -> invoke_hook("pre_tool_call", ...)
    ↓
registry.dispatch(name, args, **kwargs)
    ↓
Look up ToolEntry by name
    ↓
[Async handler?] -> bridge via _run_async()
[Sync handler?]  -> call directly
    ↓
Return result string (or JSON error)
    ↓
[Plugin post-hook] -> invoke_hook("post_tool_call", ...)
```

### Error wrapping

Tool execution is protected at two levels:

1. **`registry.dispatch()`** — catches `Exception` from the handler and returns `{"error": "Tool execution failed: ExceptionType: message"}` as JSON. **`KeyboardInterrupt` and `SystemExit` are re-raised** — handlers must never catch these, so Ctrl-C and process exit always work correctly.

2. **`handle_function_call()`** — wraps the entire dispatch in a secondary try/except that returns `{"error": "Error executing tool_name: message"}`.

The model always receives a well-formed JSON string, never an unhandled exception. Tool handlers should only catch `Exception`, not `BaseException`.

### Agent-loop tools

Four tools are intercepted before registry dispatch because they need agent-level state (TodoStore, MemoryStore, etc.):

- `todo` — planning/task tracking
- `memory` — persistent memory writes
- `session_search` — cross-session recall
- `delegate_task` — spawns subagent sessions

Their schemas are still registered for `get_tool_definitions`, but their handlers return a stub error if dispatch somehow reaches them directly.

### Async bridging

When a tool handler is async, `_run_async()` bridges it to the sync dispatch path:

- **CLI path (no running loop)** — uses a persistent event loop to keep cached async clients alive
- **Gateway path (running loop)** — spins up a disposable thread with `asyncio.run()`
- **Worker threads (parallel tools)** — uses per-thread persistent loops stored in thread-local storage

## The dangerous-command approval flow

The terminal tool integrates a dangerous-command approval system defined in `tools/approval.py`:

1. **Pattern detection** — `DANGEROUS_PATTERNS` is a list of `(regex, description)` tuples covering destructive operations:
   - Recursive deletes (`rm -rf`)
   - Filesystem formatting (`mkfs`, `dd`)
   - SQL destructive operations (`DROP TABLE`, `DELETE FROM` without `WHERE`)
   - System config overwrites (`> /etc/`)
   - Service manipulation (`systemctl stop`)
   - Remote code execution (`curl | sh`)
   - Fork bombs, process kills, etc.

2. **Detection** — before executing any terminal command, `detect_dangerous_command(command)` checks against all patterns.

3. **Approval prompt** — when a match is found:
   - **CLI mode** — an interactive prompt asks you to approve, deny, or allow permanently
   - **Gateway mode** — an async approval callback sends the request to the messaging platform
   - **Smart approval** — optionally, an auxiliary LLM can auto-approve low-risk commands that match patterns (e.g., `rm -rf node_modules/` is safe but matches "recursive delete")

4. **Session state** — approvals are tracked per-session. Approve "recursive delete" once and subsequent `rm -rf` commands won't re-prompt.

5. **Permanent allowlist** — "allow permanently" writes the pattern to `config.yaml`'s `command_allowlist`, persisting across sessions.

## Terminal backends

The terminal system supports multiple execution backends:

| Backend | Use case |
|---------|---------|
| `local` | Run commands on the local machine |
| `docker` | Sandboxed Docker containers |
| `ssh` | Remote machines via SSH |
| `singularity` | HPC/singularity containers |
| `modal` | Modal cloud sandboxes |
| `daytona` | Daytona dev environments |

Additional capabilities across all backends:
- Per-task `cwd` overrides
- Background process management
- PTY mode
- Approval callbacks for dangerous commands

## Concurrency

Tool calls may execute sequentially or concurrently depending on the tool mix and any interaction requirements between calls.

## Related docs

- [Toolsets Reference](../reference/toolsets-reference.md)
- [Built-in Tools Reference](../reference/tools-reference.md)
- [Agent Loop Internals](./agent-loop.md)
- [ACP Internals](./editor-extension-internals.md)
