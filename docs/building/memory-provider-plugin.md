---
sidebar_position: 8
title: "Memory Provider Plugins"
description: "How to build a memory provider plugin for Spark Agent"
---

# Building a Memory Provider Plugin

Memory provider plugins give Spark persistent, cross-session knowledge that goes beyond the built-in `MEMORY.md` and `USER.md`. With a plugin, you connect any external backend — a vector store, a hosted service, your own database — and Spark will use it automatically every session.

:::tip
Memory providers are one of two **provider plugin** types. The other is [Context Engine Plugins](/docs/building/context-engine-plugin), which replace the built-in context compressor. Both follow the same pattern: single-select, config-driven, managed via `spark plugins`.
:::

## What You're Building

A plugin is a directory under `plugins/memory/<name>/` with three files:

```
plugins/memory/my-provider/
 __init__.py      # MemoryProvider implementation + register() entry point
 plugin.yaml      # Metadata (name, description, hooks)
 README.md        # Setup instructions, config reference, tools
```

Add a `cli.py` if you want custom `spark my-provider` subcommands (details below).

## Implement MemoryProvider

Subclass the `MemoryProvider` ABC from `agent/memory_provider.py`:

```python
from agent.memory_provider import MemoryProvider

class MyMemoryProvider(MemoryProvider):
    @property
    def name(self) -> str:
        return "my-provider"

    def is_available(self) -> bool:
        """Check if this provider can activate. NO network calls."""
        return bool(os.environ.get("MY_API_KEY"))

    def initialize(self, session_id: str, **kwargs) -> None:
        """Called once at agent startup.

        kwargs always includes:
          spark_home (str): Active SPARK_HOME path. Use for storage.
        """
        self._api_key = os.environ.get("MY_API_KEY", "")
        self._session_id = session_id

    # ... implement remaining methods
```

## Method Reference

### Required Methods

| Method | When called | Notes |
|--------|-------------|-------|
| `name` (property) | Always | Unique identifier |
| `is_available()` | Before activation | No network calls — check env vars only |
| `initialize(session_id, **kwargs)` | Agent startup | `kwargs` includes `spark_home` |
| `get_tool_schemas()` | After init | Returns tools to inject into the model |
| `handle_tool_call(name, args)` | When agent uses your tools | Must return a string |

### Config Methods

| Method | Purpose | Required? |
|--------|---------|-----------|
| `get_config_schema()` | Declare fields for `spark memory setup` | Yes |
| `save_config(values, spark_home)` | Write non-secret config to disk | Yes (unless env-var-only) |

### Optional Lifecycle Hooks

| Method | When fired | What to use it for |
|--------|-----------|-------------------|
| `system_prompt_block()` | System prompt assembly | Inject static provider context |
| `prefetch(query)` | Before each API call | Return recalled memories |
| `queue_prefetch(query)` | After each turn | Pre-warm for the next turn |
| `sync_turn(user, assistant)` | After each completed turn | Persist conversation to your backend |
| `on_session_end(messages)` | Conversation ends | Final extraction or data flush |
| `on_pre_compress(messages)` | Before context compression | Save insights before they're discarded |
| `on_memory_write(action, target, content)` | Built-in memory writes | Mirror writes to your backend |
| `shutdown()` | Process exit | Clean up open connections |

## Declare Your Config Schema

`get_config_schema()` drives the `spark memory setup` wizard — every field you declare here becomes a setup prompt:

```python
def get_config_schema(self):
    return [
        {
            "key": "api_key",
            "description": "My Provider API key",
            "secret": True,           # -> written to .env
            "required": True,
            "env_var": "MY_API_KEY",   # explicit env var name
            "url": "https://my-provider.com/keys",  # where to get it
        },
        {
            "key": "region",
            "description": "Server region",
            "default": "us-east",
            "choices": ["us-east", "eu-west", "ap-south"],
        },
        {
            "key": "project",
            "description": "Project identifier",
            "default": "spark",
        },
    ]
```

Fields with `secret: True` and `env_var` go to `.env`. Non-secret fields are passed to `save_config()`.

:::tip Keep the schema minimal
Every field in `get_config_schema()` gets prompted during `spark memory setup`. Only include fields the user **must** set (API key, required credentials). Put optional settings in a config file at `$SPARK_HOME/myprovider.json` instead. See the Supermemory provider for an example — it only prompts for the API key.
:::

## Save Non-Secret Config

```python
def save_config(self, values: dict, spark_home: str) -> None:
    import json
    from pathlib import Path
    config_path = Path(spark_home) / "my-provider.json"
    config_path.write_text(json.dumps(values, indent=2))
```

For env-var-only providers, the default no-op is fine.

## Register the Plugin

```python
def register(ctx) -> None:
    """Called by the memory plugin discovery system."""
    ctx.register_memory_provider(MyMemoryProvider())
```

## Write plugin.yaml

```yaml
name: my-provider
version: 1.0.0
description: "Short description of what this provider does."
hooks:
  - on_session_end    # list hooks you implement
```

## Keep sync_turn Non-Blocking

`sync_turn()` is called after every conversation turn. If your backend is slow (API calls, LLM processing), run the work in a daemon thread — never block the main loop:

```python
def sync_turn(self, user_content, assistant_content):
    def _sync():
        try:
            self._api.ingest(user_content, assistant_content)
        except Exception as e:
            logger.warning("Sync failed: %s", e)

    if self._sync_thread and self._sync_thread.is_alive():
        self._sync_thread.join(timeout=5.0)
    self._sync_thread = threading.Thread(target=_sync, daemon=True)
    self._sync_thread.start()
```

## Use spark_home for All Storage

Never hardcode `~/.spark`. Always use the `spark_home` kwarg from `initialize()`:

```python
# CORRECT - profile-scoped
from spark_constants import get_spark_home
data_dir = get_spark_home() / "my-provider"

# WRONG - shared across all profiles, breaks isolation
data_dir = Path("~/.spark/my-provider").expanduser()
```

## Test Your Plugin

Use `MemoryManager` directly — see `tests/agent/test_memory_plugin_e2e.py` for the full E2E pattern:

```python
from agent.memory_manager import MemoryManager

mgr = MemoryManager()
mgr.add_provider(my_provider)
mgr.initialize_all(session_id="test-1", platform="cli")

# Test tool routing
result = mgr.handle_tool_call("my_tool", {"action": "add", "content": "test"})

# Test lifecycle
mgr.sync_all("user msg", "assistant msg")
mgr.on_session_end([])
mgr.shutdown_all()
```

## Add CLI Subcommands (Optional)

You can expose `spark my-provider <subcommand>` without touching any core files. Add a `cli.py` to your plugin directory:

```python
# plugins/memory/my-provider/cli.py

def my_command(args):
    sub = getattr(args, "my_command", None)
    if sub == "status":
        print("Provider is active and connected.")
    elif sub == "config":
        print("Showing config...")
    else:
        print("Usage: spark my-provider <status|config>")

def register_cli(subparser) -> None:
    """Build the spark my-provider argparse tree.

    Called by discover_plugin_cli_commands() at argparse setup time.
    """
    subs = subparser.add_subparsers(dest="my_command")
    subs.add_parser("status", help="Show provider status")
    subs.add_parser("config", help="Show provider config")
    subparser.set_defaults(func=my_command)
```

How it works:
1. `discover_plugin_cli_commands()` finds `cli.py` at startup.
2. `register_cli(subparser)` builds the argparse tree.
3. Your commands appear under `spark <provider-name> <subcommand>`.

Your commands only appear when your provider is the active `memory.provider` in config — they won't clutter `spark --help` for users who haven't configured your plugin.

See `plugins/memory/honcho/cli.py` for a full example with 13 subcommands, cross-profile management (`--target-profile`), and config read/write.

### Directory layout with CLI

```
plugins/memory/my-provider/
 __init__.py      # MemoryProvider implementation + register()
 plugin.yaml      # Metadata
 cli.py           # register_cli(subparser) - CLI commands
 README.md        # Setup instructions
```

## One Provider at a Time

Only **one** external memory provider can be active at once. If you try to register a second, `MemoryManager` rejects it with a warning. This prevents tool schema bloat and conflicting backends.
