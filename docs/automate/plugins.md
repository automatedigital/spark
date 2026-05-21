---
sidebar_position: 11
sidebar_label: "Plugins"
title: "Plugins"
description: "Extend Spark with custom tools, hooks, and integrations via the plugin system"
---

# Plugins

Add custom tools, lifecycle hooks, and integrations to Spark without touching core code. Drop a directory into `~/.spark/plugins/` and your additions appear alongside built-in tools the next time Spark starts.

**-> [Build a Spark Plugin](../guides/build-a-plugin.md)** - step-by-step guide with a complete working example.

## How plugins are structured

A plugin is a directory with a manifest and Python code:

```
~/.spark/plugins/my-plugin/
  plugin.yaml      # manifest
  __init__.py      # register() - wires schemas to handlers
  schemas.py       # tool schemas (what the LLM sees)
  tools.py         # tool handlers (what runs when called)
```

Start Spark and your tools are immediately available to the model.

## Minimal working example

Here's a complete plugin that adds a `hello_world` tool and logs every tool call via a hook.

**`~/.spark/plugins/hello-world/plugin.yaml`**

```yaml
name: hello-world
version: "1.0"
description: A minimal example plugin
```

**`~/.spark/plugins/hello-world/__init__.py`**

```python
"""Minimal Spark plugin - registers a tool and a hook."""


def register(ctx):
    # --- Tool: hello_world ---
    schema = {
        "name": "hello_world",
        "description": "Returns a friendly greeting for the given name.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name to greet",
                }
            },
            "required": ["name"],
        },
    }

    def handle_hello(params):
        name = params.get("name", "World")
        return f"Hello, {name}!   (from the hello-world plugin)"

    ctx.register_tool("hello_world", schema, handle_hello)

    # --- Hook: log every tool call ---
    def on_tool_call(tool_name, params, result):
        print(f"[hello-world] tool called: {tool_name}")

    ctx.register_hook("post_tool_call", on_tool_call)
```

Drop both files into `~/.spark/plugins/hello-world/`, restart Spark, and the model can call `hello_world` immediately. The hook prints a log line after every tool invocation.

Project-local plugins under `./.spark/plugins/` are disabled by default. Enable them only for trusted repositories by setting `SPARK_ENABLE_PROJECT_PLUGINS=true` before starting Spark.

## What plugins can do

| Capability | How |
|-----------|-----|
| Add tools | `ctx.register_tool(name, schema, handler)` |
| Add hooks | `ctx.register_hook("post_tool_call", callback)` |
| Add CLI commands | `ctx.register_cli_command(name, help, setup_fn, handler_fn)` — adds `spark <plugin> <subcommand>` |
| Inject messages | `ctx.inject_message(content, role="user")` — see [Injecting Messages](#injecting-messages) |
| Ship data files | `Path(__file__).parent / "data" / "file.yaml"` |
| Bundle skills | Copy `skill.md` to `~/.spark/skills/` at load time |
| Gate on env vars | `requires_env: [API_KEY]` in plugin.yaml — prompted during `spark plugins install` |
| Distribute via pip | `[project.entry-points."spark_agent.plugins"]` |

## Where plugins are discovered

| Source | Path | Use case |
|--------|------|----------|
| User | `~/.spark/plugins/` | Personal plugins |
| Project | `.spark/plugins/` | Project-specific plugins (requires `SPARK_ENABLE_PROJECT_PLUGINS=true`) |
| pip | `spark_agent.plugins` entry_points | Distributed packages |

## Available lifecycle hooks

Register callbacks for these events. See the **[Event Hooks page](../tools/hooks.md#plugin-hooks)** for full signatures and examples.

| Hook | Fires when |
|------|-----------|
| [`pre_tool_call`](../tools/hooks.md#pre_tool_call) | Before any tool executes |
| [`post_tool_call`](../tools/hooks.md#post_tool_call) | After any tool returns |
| [`pre_llm_call`](../tools/hooks.md#pre_llm_call) | Once per turn, before the LLM loop — can return `{"context": "..."}` to [inject context into the user message](../tools/hooks.md#pre_llm_call) |
| [`post_llm_call`](../tools/hooks.md#post_llm_call) | Once per turn, after the LLM loop (successful turns only) |
| [`on_session_start`](../tools/hooks.md#on_session_start) | New session created (first turn only) |
| [`on_session_end`](../tools/hooks.md#on_session_end) | End of every `run_conversation` call + CLI exit handler |

## Plugin types

| Type | What it does | Selection | Location |
|------|-------------|-----------|----------|
| **General plugins** | Add tools, hooks, CLI commands | Multi-select (enable/disable any combination) | `~/.spark/plugins/` |
| **Memory providers** | Replace or augment built-in memory | Single-select (one active at a time) | `plugins/memory/` |
| **Context engines** | Replace the built-in context compressor | Single-select (one active at a time) | `plugins/context_engine/` |

Memory providers and context engines are **provider plugins** — only one of each type can be active at a time. General plugins stack freely.

## Managing plugins

```bash
spark plugins                  # unified interactive UI
spark plugins list             # table view with enabled/disabled status
spark plugins install user/repo  # install from Git
spark plugins update my-plugin   # pull latest
spark plugins remove my-plugin   # uninstall
spark plugins enable my-plugin   # re-enable a disabled plugin
spark plugins disable my-plugin  # disable without removing
```

### Interactive UI

Running `spark plugins` opens a composite interactive screen:

```
Plugins
   navigate  SPACE toggle  ENTER configure/confirm  ESC done

  General Plugins
 -> [] my-tool-plugin - Custom search tool
    [ ] webhook-notifier - Event hooks

  Provider Plugins
      Memory Provider           honcho
      Context Engine            compressor
```

- **General Plugins** — toggle with SPACE
- **Provider Plugins** — press ENTER to open a radio picker and choose one active provider

Provider selections are saved to `config.yaml`:

```yaml
memory:
  provider: "honcho"      # empty string = built-in only

context:
  engine: "compressor"    # default built-in compressor
```

### Disabling plugins without removing them

Disabled plugins stay installed but are skipped at load time. The disabled list lives in `config.yaml`:

```yaml
plugins:
  disabled:
    - my-noisy-plugin
```

In a running session, `/plugins` shows which plugins are currently loaded.

## Injecting messages

Plugins can push messages into the active conversation using `ctx.inject_message()`:

```python
ctx.inject_message("New data arrived from the webhook", role="user")
```

**Signature:** `ctx.inject_message(content: str, role: str = "user") -> bool`

Behavior depends on agent state:

- **Agent is idle** (waiting for input) — the message queues as the next input and starts a new turn
- **Agent is mid-turn** (actively running) — the message interrupts the current operation, the same as a user pressing Enter with a new message
- **Non-`"user"` roles** — content is prefixed with `[role]` (e.g. `[system] ...`)
- Returns `True` if queued successfully, `False` if no CLI reference is available (e.g. in gateway mode)

This is how plugins like remote viewers, messaging bridges, and webhook receivers feed external events into the conversation.

:::note
`inject_message` only works in CLI mode. In gateway mode, there is no CLI reference and the method returns `False`.
:::

See the **[full guide](../guides/build-a-plugin.md)** for handler contracts, schema format, hook behavior, error handling, and common mistakes.
