---
sidebar_position: 9
sidebar_label: "Build a Plugin"
title: "Build a Spark Plugin"
description: "Step-by-step guide to building a complete Spark plugin with tools, hooks, data files, and skills"
---

# Build a Spark Plugin

Four files. That's all it takes. By the end of this guide you'll have a working plugin with real tools the model can call, a lifecycle hook, and a bundled skill.

## What you're building

A **calculator** plugin with two tools:
- `calculate` — evaluate math expressions (`2**16`, `sqrt(144)`, `pi * 5**2`)
- `unit_convert` — convert between units (`100 F -> 37.78 C`, `5 km -> 3.11 mi`)

Plus a hook that logs every tool call.

---

## Step 1: Create the plugin directory

```bash
mkdir -p ~/.spark/plugins/calculator
cd ~/.spark/plugins/calculator
```

## Step 2: Write the manifest

Create `plugin.yaml`:

```yaml
name: calculator
version: 1.0.0
description: Math calculator - evaluate expressions and convert units
provides_tools:
  - calculate
  - unit_convert
provides_hooks:
  - post_tool_call
```

This tells Spark what the plugin provides. Optional fields you can add:

```yaml
author: Your Name
requires_env:          # gate loading on env vars; prompted during install
  - SOME_API_KEY       # simple format - plugin disabled if missing
  - name: OTHER_KEY    # rich format - shows description/url during install
    description: "Key for the Other service"
    url: "https://other.com/keys"
    secret: true
```

## Step 3: Write the tool schemas

Create `schemas.py` — this is what the LLM reads to decide when to call your tools:

```python
"""Tool schemas - what the LLM sees."""

CALCULATE = {
    "name": "calculate",
    "description": (
        "Evaluate a mathematical expression and return the result. "
        "Supports arithmetic (+, -, *, /, **), functions (sqrt, sin, cos, "
        "log, abs, round, floor, ceil), and constants (pi, e). "
        "Use this for any math the user asks about."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "Math expression to evaluate (e.g., '2**10', 'sqrt(144)')",
            },
        },
        "required": ["expression"],
    },
}

UNIT_CONVERT = {
    "name": "unit_convert",
    "description": (
        "Convert a value between units. Supports length (m, km, mi, ft, in), "
        "weight (kg, lb, oz, g), temperature (C, F, K), data (B, KB, MB, GB, TB), "
        "and time (s, min, hr, day)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "value": {
                "type": "number",
                "description": "The numeric value to convert",
            },
            "from_unit": {
                "type": "string",
                "description": "Source unit (e.g., 'km', 'lb', 'F', 'GB')",
            },
            "to_unit": {
                "type": "string",
                "description": "Target unit (e.g., 'mi', 'kg', 'C', 'MB')",
            },
        },
        "required": ["value", "from_unit", "to_unit"],
    },
}
```

The `description` field is how the LLM decides when to use your tool. Be specific — name the cases, not just the category.

## Step 4: Write the tool handlers

Create `tools.py` — the code that executes when the LLM calls your tools:

```python
"""Tool handlers - the code that runs when the LLM calls each tool."""

import json
import math

# Safe globals for expression evaluation - no file/network access
_SAFE_MATH = {
    "abs": abs, "round": round, "min": min, "max": max,
    "pow": pow, "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos,
    "tan": math.tan, "log": math.log, "log2": math.log2, "log10": math.log10,
    "floor": math.floor, "ceil": math.ceil,
    "pi": math.pi, "e": math.e,
    "factorial": math.factorial,
}


def calculate(args: dict, **kwargs) -> str:
    """Evaluate a math expression safely."""
    expression = args.get("expression", "").strip()
    if not expression:
        return json.dumps({"error": "No expression provided"})

    try:
        result = eval(expression, {"__builtins__": {}}, _SAFE_MATH)
        return json.dumps({"expression": expression, "result": result})
    except ZeroDivisionError:
        return json.dumps({"expression": expression, "error": "Division by zero"})
    except Exception as e:
        return json.dumps({"expression": expression, "error": f"Invalid: {e}"})


# Conversion tables - values are in base units
_LENGTH = {"m": 1, "km": 1000, "mi": 1609.34, "ft": 0.3048, "in": 0.0254, "cm": 0.01}
_WEIGHT = {"kg": 1, "g": 0.001, "lb": 0.453592, "oz": 0.0283495}
_DATA = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
_TIME = {"s": 1, "ms": 0.001, "min": 60, "hr": 3600, "day": 86400}


def _convert_temp(value, from_u, to_u):
    # Normalize to Celsius
    c = {"F": (value - 32) * 5/9, "K": value - 273.15}.get(from_u, value)
    # Convert to target
    return {"F": c * 9/5 + 32, "K": c + 273.15}.get(to_u, c)


def unit_convert(args: dict, **kwargs) -> str:
    """Convert between units."""
    value = args.get("value")
    from_unit = args.get("from_unit", "").strip()
    to_unit = args.get("to_unit", "").strip()

    if value is None or not from_unit or not to_unit:
        return json.dumps({"error": "Need value, from_unit, and to_unit"})

    try:
        # Temperature
        if from_unit.upper() in {"C","F","K"} and to_unit.upper() in {"C","F","K"}:
            result = _convert_temp(float(value), from_unit.upper(), to_unit.upper())
            return json.dumps({"input": f"{value} {from_unit}", "result": round(result, 4),
                             "output": f"{round(result, 4)} {to_unit}"})

        # Ratio-based conversions
        for table in (_LENGTH, _WEIGHT, _DATA, _TIME):
            lc = {k.lower(): v for k, v in table.items()}
            if from_unit.lower() in lc and to_unit.lower() in lc:
                result = float(value) * lc[from_unit.lower()] / lc[to_unit.lower()]
                return json.dumps({"input": f"{value} {from_unit}",
                                 "result": round(result, 6),
                                 "output": f"{round(result, 6)} {to_unit}"})

        return json.dumps({"error": f"Cannot convert {from_unit} -> {to_unit}"})
    except Exception as e:
        return json.dumps({"error": f"Conversion failed: {e}"})
```

Three rules every handler must follow:
1. **Signature:** `def my_handler(args: dict, **kwargs) -> str`
2. **Always return a JSON string.** Success and errors alike — never a dict, never None.
3. **Never raise.** Catch all exceptions and return error JSON instead.

## Step 5: Write the registration

Create `__init__.py` — this wires schemas to handlers:

```python
"""Calculator plugin - registration."""

import logging

from . import schemas, tools

logger = logging.getLogger(__name__)

_call_log = []

def _on_post_tool_call(tool_name, args, result, task_id, **kwargs):
    """Hook: runs after every tool call (not just ours)."""
    _call_log.append({"tool": tool_name, "session": task_id})
    if len(_call_log) > 100:
        _call_log.pop(0)
    logger.debug("Tool called: %s (session %s)", tool_name, task_id)


def register(ctx):
    """Wire schemas to handlers and register hooks."""
    ctx.register_tool(name="calculate",    toolset="calculator",
                      schema=schemas.CALCULATE,    handler=tools.calculate)
    ctx.register_tool(name="unit_convert", toolset="calculator",
                      schema=schemas.UNIT_CONVERT, handler=tools.unit_convert)

    # Fires for ALL tool calls, not just ours
    ctx.register_hook("post_tool_call", _on_post_tool_call)
```

`register()` is called exactly once at startup. If it crashes, the plugin is disabled but Spark continues normally.

## Step 6: Test it

```bash
spark
```

You should see `calculator: calculate, unit_convert` in the banner's tool list.

Try these prompts:
```
What's 2 to the power of 16?
Convert 100 fahrenheit to celsius
What's the square root of 2 times pi?
How many gigabytes is 1.5 terabytes?
```

Check plugin status:
```
/plugins
```

```
Plugins (1):
   calculator v1.0.0 (2 tools, 1 hooks)
```

## Your plugin's final structure

```
~/.spark/plugins/calculator/
 plugin.yaml      # What the plugin is
 __init__.py      # Wiring: schemas -> handlers, hooks
 schemas.py       # What the LLM reads
 tools.py         # What actually runs
```

---

## What else can plugins do?

### Ship data files

Put files in your plugin directory and read them at import time:

```python
from pathlib import Path

_PLUGIN_DIR = Path(__file__).parent
_DATA_FILE = _PLUGIN_DIR / "data" / "languages.yaml"

with open(_DATA_FILE) as f:
    _DATA = yaml.safe_load(f)
```

### Bundle a skill

Include a `skill.md` file and install it during registration:

```python
import shutil
from pathlib import Path

def _install_skill():
    """Copy our skill to ~/.spark/skills/ on first load."""
    try:
        from spark_cli.config import get_spark_home
        dest = get_spark_home() / "skills" / "my-plugin" / "SKILL.md"
    except Exception:
        dest = Path.home() / ".spark" / "skills" / "my-plugin" / "SKILL.md"

    if dest.exists():
        return  # don't overwrite user edits

    source = Path(__file__).parent / "skill.md"
    if source.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)

def register(ctx):
    ctx.register_tool(...)
    _install_skill()
```

### Gate on environment variables

```yaml
# plugin.yaml - simple format
requires_env:
  - WEATHER_API_KEY
```

If `WEATHER_API_KEY` isn't set, the plugin is disabled with a clear message. During `spark plugins install`, users are prompted interactively for any missing env vars.

Use the rich format for a better install experience:

```yaml
# plugin.yaml - rich format
requires_env:
  - name: WEATHER_API_KEY
    description: "API key for OpenWeather"
    url: "https://openweathermap.org/api"
    secret: true
```

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Environment variable name |
| `description` | No | Shown to user during install |
| `url` | No | Where to get the credential |
| `secret` | No | If `true`, input is hidden |

### Conditional tool availability

```python
ctx.register_tool(
    name="my_tool",
    schema={...},
    handler=my_handler,
    check_fn=lambda: _has_optional_lib(),  # False = tool hidden from model
)
```

### Hook reference

All hooks accept `**kwargs` for forward compatibility. If a callback crashes, it's logged and skipped.

| Hook | Fires when | Signature |
|------|-----------|-----------|
| [`pre_tool_call`](../tools/hooks.md#pre_tool_call) | Before any tool executes | `tool_name, args, task_id` |
| [`post_tool_call`](../tools/hooks.md#post_tool_call) | After any tool returns | `tool_name, args, result, task_id` |
| [`pre_llm_call`](../tools/hooks.md#pre_llm_call) | Before the tool-calling loop | `session_id, user_message, conversation_history, is_first_turn, model, platform` |
| [`post_llm_call`](../tools/hooks.md#post_llm_call) | After the tool-calling loop (successful turns) | `session_id, user_message, assistant_response, conversation_history, model, platform` |
| [`on_session_start`](../tools/hooks.md#on_session_start) | New session created | `session_id, model, platform` |
| [`on_session_end`](../tools/hooks.md#on_session_end) | End of every conversation | `session_id, completed, interrupted, model, platform` |
| [`pre_api_request`](../tools/hooks.md#pre_api_request) | Before each HTTP request to the LLM | `method, url, headers, body` |
| [`post_api_request`](../tools/hooks.md#post_api_request) | After each HTTP response | `method, url, status_code, response` |

### `pre_llm_call` context injection

This is the only hook whose return value matters. Return a dict with a `"context"` key (or a plain string) and Spark injects it into the current turn's user message.

```python
# Inject context
return {"context": "Recalled memories:\n- User prefers dark mode"}

# Plain string works too
return "Recalled memories:\n- User prefers dark mode"

# Observer-only: return None
return None
```

Context is injected at API call time only — the original conversation history is never mutated, and nothing is persisted. This preserves the system prompt for caching.

**Memory recall plugin:**
```python
def recall_context(session_id, user_message, is_first_turn, **kwargs):
    try:
        resp = httpx.post(f"{MEMORY_API}/recall", json={
            "session_id": session_id,
            "query": user_message,
        }, timeout=3)
        memories = resp.json().get("results", [])
        if not memories:
            return None

        text = "Recalled context from previous sessions:\n"
        text += "\n".join(f"- {m['text']}" for m in memories)
        return {"context": text}
    except Exception:
        return None

def register(ctx):
    ctx.register_hook("pre_llm_call", recall_context)
```

**Guardrails plugin:**
```python
POLICY = """You MUST follow these content policies for this session:
- Never generate code that accesses the filesystem outside the working directory
- Always warn before executing destructive operations"""

def inject_guardrails(**kwargs):
    return {"context": POLICY}

def register(ctx):
    ctx.register_hook("pre_llm_call", inject_guardrails)
```

When multiple plugins return context from `pre_llm_call`, their outputs are joined with double newlines in alphabetical order by plugin directory name.

### Register CLI commands

```python
def _my_command(args):
    sub = getattr(args, "my_command", None)
    if sub == "status":
        print("All good!")
    elif sub == "config":
        print("Current config: ...")
    else:
        print("Usage: spark my-plugin <status|config>")

def _setup_argparse(subparser):
    subs = subparser.add_subparsers(dest="my_command")
    subs.add_parser("status", help="Show plugin status")
    subs.add_parser("config", help="Show plugin config")
    subparser.set_defaults(func=_my_command)

def register(ctx):
    ctx.register_tool(...)
    ctx.register_cli_command(
        name="my-plugin",
        help="Manage my plugin",
        setup_fn=_setup_argparse,
        handler_fn=_my_command,
    )
```

After registration, users run `spark my-plugin status`, `spark my-plugin config`, etc.

### Distribute via pip

```toml
# pyproject.toml
[project.entry-points."spark_agent.plugins"]
my-plugin = "my_plugin_package"
```

```bash
pip install spark-plugin-calculator
# Auto-discovered on next spark startup
```

---

## Common mistakes

**Handler returns a dict instead of a JSON string:**
```python
# Wrong
def handler(args, **kwargs):
    return {"result": 42}

# Right
def handler(args, **kwargs):
    return json.dumps({"result": 42})
```

**Missing `**kwargs`:**
```python
# Wrong — will break if Spark passes extra context
def handler(args):
    ...

# Right
def handler(args, **kwargs):
    ...
```

**Handler raises exceptions:**
```python
# Wrong — exception propagates, tool call fails
def handler(args, **kwargs):
    result = 1 / int(args["value"])  # ZeroDivisionError!
    return json.dumps({"result": result})

# Right — catch and return error JSON
def handler(args, **kwargs):
    try:
        result = 1 / int(args.get("value", 0))
        return json.dumps({"result": result})
    except Exception as e:
        return json.dumps({"error": str(e)})
```

**Schema description too vague:**
```python
# Bad — model doesn't know when to use it
"description": "Does stuff"

# Good — model knows exactly when and how
"description": "Evaluate a mathematical expression. Use for arithmetic, trig, logarithms. Supports: +, -, *, /, **, sqrt, sin, cos, log, pi, e."
```

:::tip
This guide covers general plugins (tools, hooks, CLI commands). For specialized types, see:
- [Memory Provider Plugins](../building/memory-provider-plugin.md) — cross-session knowledge backends
- [Context Engine Plugins](../building/context-engine-plugin.md) — alternative context management strategies
:::
