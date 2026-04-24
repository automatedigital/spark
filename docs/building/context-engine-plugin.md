---
sidebar_position: 9
title: "Context Engine Plugins"
description: "How to build a context engine plugin that replaces the built-in ContextCompressor"
---

# Building a Context Engine Plugin

Want to replace lossy summarization with something smarter? Context engine plugins let you swap out the built-in `ContextCompressor` entirely — for example, with a Lossless Context Management (LCM) engine that builds a knowledge DAG instead of discarding turns.

## What You're Replacing

The agent's context management is defined by the `ContextEngine` ABC in `agent/context_engine.py`. The built-in `ContextCompressor` is the default. Your plugin implements the same interface and gets selected by name:

```yaml
# config.yaml
context:
  engine: "compressor"    # default built-in
  engine: "lcm"           # activates your plugin
```

Only one engine is active at a time. Plugin engines are **never auto-activated** — the user must opt in by setting `context.engine`.

## Directory Layout

Put your engine here:

```
plugins/context_engine/lcm/
├── __init__.py      # exports your ContextEngine subclass
├── plugin.yaml      # metadata (name, description, version)
└── ...              # any other modules your engine needs
```

## Implementing the Interface

Your class must subclass `ContextEngine` and implement four required members:

```python
from agent.context_engine import ContextEngine

class LCMEngine(ContextEngine):

    @property
    def name(self) -> str:
        """Short identifier, e.g. 'lcm'. Must match config.yaml value."""
        return "lcm"

    def update_from_response(self, usage: dict) -> None:
        """Called after every LLM call with the usage dict.

        Update self.last_prompt_tokens, self.last_completion_tokens,
        self.last_total_tokens from the response.
        """

    def should_compress(self, prompt_tokens: int = None) -> bool:
        """Return True if compaction should fire this turn."""

    def compress(self, messages: list, current_tokens: int = None) -> list:
        """Compact the message list and return a new (possibly shorter) list.

        The returned list must be a valid OpenAI-format message sequence.
        """
```

### Class Attributes the Agent Reads Directly

Maintain these on your class — they're used for display and logging:

```python
last_prompt_tokens: int = 0
last_completion_tokens: int = 0
last_total_tokens: int = 0
threshold_tokens: int = 0        # when compression triggers
context_length: int = 0          # model's full context window
compression_count: int = 0       # how many times compress() has run
```

### Optional Methods to Override

The ABC has sensible defaults for these. Override only what you need:

| Method | Default | Override when |
|--------|---------|--------------|
| `on_session_start(session_id, **kwargs)` | No-op | You load persisted state (DAG, DB, etc.) |
| `on_session_end(session_id, messages)` | No-op | You flush state or close connections |
| `on_session_reset()` | Resets token counters | You have per-session state to clear |
| `update_model(model, context_length, ...)` | Updates context_length + threshold | You recalculate budgets on model switch |
| `get_tool_schemas()` | Returns `[]` | Your engine exposes agent-callable tools |
| `handle_tool_call(name, args, **kwargs)` | Returns error JSON | You implement those tool handlers |
| `should_compress_preflight(messages)` | Returns `False` | You can do a cheap pre-API-call estimate |
| `get_status()` | Standard token/threshold dict | You have custom metrics to surface |

## Giving the Agent New Tools

Your engine can expose tools the agent calls directly during a session. Return schemas from `get_tool_schemas()` and handle calls in `handle_tool_call()`:

```python
def get_tool_schemas(self):
    return [{
        "name": "lcm_grep",
        "description": "Search the context knowledge graph",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"}
            },
            "required": ["query"],
        },
    }]

def handle_tool_call(self, name, args, **kwargs):
    if name == "lcm_grep":
        results = self._search_dag(args["query"])
        return json.dumps({"results": results})
    return json.dumps({"error": f"Unknown tool: {name}"})
```

Engine tools are injected into the agent's tool list at startup and dispatched automatically — no registry registration needed.

## Registering Your Engine

### Recommended: drop it in the directory

Place your engine at `plugins/context_engine/<name>/`. Export a `ContextEngine` subclass from `__init__.py`. Discovery is automatic.

### Alternative: register from a general plugin

```python
def register(ctx):
    engine = LCMEngine(context_length=200000)
    ctx.register_context_engine(engine)
```

Only one engine can be registered. A second plugin attempting to register is rejected with a warning.

## Engine Lifecycle

```
1. Engine instantiated (plugin load or directory discovery)
2. on_session_start()       — conversation begins
3. update_from_response()   — called after each API call
4. should_compress()        — checked each turn
5. compress()               — called when should_compress() returns True
6. on_session_end()         — session boundary (CLI exit, /reset, gateway expiry)
```

`on_session_reset()` fires on `/new` or `/reset` — clears per-session state without a full shutdown.

## Configuration

Users select your engine via `spark plugins` → Provider Plugins → Context Engine, or by editing `config.yaml`:

```yaml
context:
  engine: "lcm"   # must match your engine's name property
```

The built-in `compression` config block (`compression.threshold`, `compression.protect_last_n`, etc.) belongs to the built-in `ContextCompressor`. Define your own config format if needed and read it from `config.yaml` during initialization.

## Testing Your Engine

```python
from agent.context_engine import ContextEngine

def test_engine_satisfies_abc():
    engine = YourEngine(context_length=200000)
    assert isinstance(engine, ContextEngine)
    assert engine.name == "your-name"

def test_compress_returns_valid_messages():
    engine = YourEngine(context_length=200000)
    msgs = [{"role": "user", "content": "hello"}]
    result = engine.compress(msgs)
    assert isinstance(result, list)
    assert all("role" in m for m in result)
```

See `tests/agent/test_context_engine.py` for the full ABC contract test suite.

## See also

- [Context Compression and Caching](/docs/building/context-compression-and-caching) — how the built-in compressor works
- [Memory Provider Plugins](/docs/building/memory-provider-plugin) — analogous single-select plugin system for memory
- [Plugins](/docs/automate/plugins) — general plugin system overview
