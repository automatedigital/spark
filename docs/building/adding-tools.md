---
sidebar_position: 2
title: "Adding Tools"
description: "How to add a new tool to Spark Agent - schemas, handlers, registration, and toolsets"
---

# Adding Tools

## Skill or Tool — Pick the Right One

Before writing any code, ask yourself which abstraction fits:

| Reach for a **Skill** when... | Reach for a **Tool** when... |
|-------------------------------|-------------------------------|
| Instructions + shell commands are enough | You need custom Python integration |
| You're wrapping a CLI or API the agent calls via `terminal` | Auth flows, API keys, or multi-component config are involved |
| arXiv search, git workflows, Docker management, PDF processing | Browser automation, TTS, vision analysis, streaming data |

Skills are zero-code. If the work can be expressed as prose instructions and shell invocations, [write a skill](creating-skills.md) instead.

## Three Files, One Tool

Every new tool touches exactly three files:

| File | What you do |
|------|-------------|
| `tools/your_tool.py` | Handler, schema, check function, `registry.register()` call |
| `toolsets.py` | Add tool name to `_SPARK_CORE_TOOLS` or a custom toolset |
| `model_tools.py` | Add `"tools.your_tool"` to the `_discover_tools()` list |

## Step 1 — Write the Tool File

Here's the full pattern. Every tool file looks like this:

```python
# tools/weather_tool.py
"""Weather Tool -- look up current weather for a location."""

import json
import os
import logging

logger = logging.getLogger(__name__)


# --- Availability check ---

def check_weather_requirements() -> bool:
    """Return True if the tool's dependencies are available."""
    return bool(os.getenv("WEATHER_API_KEY"))


# --- Handler ---

def weather_tool(location: str, units: str = "metric") -> str:
    """Fetch weather for a location. Returns JSON string."""
    api_key = os.getenv("WEATHER_API_KEY")
    if not api_key:
        return json.dumps({"error": "WEATHER_API_KEY not configured"})
    try:
        # ... call weather API ...
        return json.dumps({"location": location, "temp": 22, "units": units})
    except Exception as e:
        return json.dumps({"error": str(e)})


# --- Schema ---

WEATHER_SCHEMA = {
    "name": "weather",
    "description": "Get current weather for a location.",
    "parameters": {
        "type": "object",
        "properties": {
            "location": {
                "type": "string",
                "description": "City name or coordinates (e.g. 'London' or '51.5,-0.1')"
            },
            "units": {
                "type": "string",
                "enum": ["metric", "imperial"],
                "description": "Temperature units (default: metric)",
                "default": "metric"
            }
        },
        "required": ["location"]
    }
}


# --- Registration ---

from tools.registry import registry

registry.register(
    name="weather",
    toolset="weather",
    schema=WEATHER_SCHEMA,
    handler=lambda args, **kw: weather_tool(
        location=args.get("location", ""),
        units=args.get("units", "metric")),
    check_fn=check_weather_requirements,
    requires_env=["WEATHER_API_KEY"],
)
```

### Non-Negotiable Rules

:::danger Important
- Handlers **must** return a JSON string via `json.dumps()` — never a raw dict
- Errors **must** come back as `{"error": "message"}` — never raise exceptions
- The `check_fn` runs at startup; returning `False` silently excludes the tool
- The `handler` signature is `(args: dict, **kwargs)` where `args` holds the LLM's arguments
:::

## Step 2 — Register It in a Toolset

Open `toolsets.py` and add the tool name where it belongs:

```python
# Available everywhere (CLI + messaging platforms):
_SPARK_CORE_TOOLS = [
    ...
    "weather",  # <-- add here
]

# Or define a standalone toolset:
"weather": {
    "description": "Weather lookup tools",
    "tools": ["weather"],
    "includes": []
},
```

## Step 3 — Add the Discovery Import

Open `model_tools.py` and add the module path inside `_discover_tools()`:

```python
def _discover_tools():
    _modules = [
        ...
        "tools.weather_tool",  # <-- add here
    ]
```

This import triggers `registry.register()` at the bottom of your tool file. That's the whole chain.

## Async Handlers

If your handler needs async code, mark it `is_async=True`. The registry calls `_run_async()` for you — never call `asyncio.run()` yourself:

```python
async def weather_tool_async(location: str) -> str:
    async with aiohttp.ClientSession() as session:
        ...
    return json.dumps(result)

registry.register(
    name="weather",
    toolset="weather",
    schema=WEATHER_SCHEMA,
    handler=lambda args, **kw: weather_tool_async(args.get("location", "")),
    check_fn=check_weather_requirements,
    is_async=True,
)
```

## Using Per-Session State (`task_id`)

Tools that track per-session state receive a `task_id` via `**kwargs`:

```python
def _handle_weather(args, **kw):
    task_id = kw.get("task_id")
    return weather_tool(args.get("location", ""), task_id=task_id)

registry.register(
    name="weather",
    ...
    handler=_handle_weather,
)
```

## Agent-Loop Intercepted Tools

A small set of tools — `todo`, `memory`, `session_search`, `delegate_task` — are intercepted directly by `run_agent.py` before they reach the registry. They need access to per-session agent state that isn't available at the registry level. The registry still holds their schemas; `dispatch()` returns a fallback error if the intercept is bypassed unexpectedly.

## Wiring Up API Keys

If your tool requires an API key, add an entry to `OPTIONAL_ENV_VARS` in `spark_cli/config.py`. This wires the key into the setup wizard and `spark doctor`:

```python
OPTIONAL_ENV_VARS = {
    ...
    "WEATHER_API_KEY": {
        "description": "Weather API key for weather lookup",
        "prompt": "Weather API key",
        "url": "https://weatherapi.com/",
        "tools": ["weather"],
        "password": True,
    },
}
```

## Before You Ship — Checklist

- [ ] Tool file created: handler, schema, check function, registration
- [ ] Tool name added to the right toolset in `toolsets.py`
- [ ] Discovery import added in `model_tools.py`
- [ ] Handler returns JSON strings; errors use `{"error": "..."}`
- [ ] Optional: API key added to `OPTIONAL_ENV_VARS` in `spark_cli/config.py`
- [ ] Optional: Added to `toolset_distributions.py` for batch processing
- [ ] Tested: `spark chat -q "Use the weather tool for London"`
