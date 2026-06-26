---
sidebar_position: 7
title: "Subagent Delegation"
description: "Spawn isolated child agents for parallel workstreams with delegate_task"
---

# Subagent Delegation

Some tasks are too big for one conversation. Delegation lets Spark spawn child agents with their own isolated context, restricted toolsets, and separate terminal sessions. Each child runs independently — only its final summary enters the parent's context.

## The Golden Rule: Subagents Know Nothing

:::warning Critical
A subagent starts with a **completely blank slate**. It has no access to the parent's conversation, prior tool calls, or anything discussed before delegation. Its only knowledge comes from the `goal` and `context` fields you provide.
:::

Give it everything it needs upfront:

```python
# BAD — subagent has no idea what "the error" is
delegate_task(goal="Fix the error")

# GOOD — full context included
delegate_task(
    goal="Fix the TypeError in api/handlers.py",
    context="""The file api/handlers.py has a TypeError on line 47:
    'NoneType' object has no attribute 'get'.
    parse_body() returns None when Content-Type is missing.
    Project is at /home/user/myproject, uses Python 3.11."""
)
```

## Running a Single Task

```python
delegate_task(
    goal="Debug why tests fail",
    context="Error: assertion in test_foo.py line 42",
    toolsets=["terminal", "file"]
)
```

## Running Tasks in Parallel

Send up to 3 tasks simultaneously:

```python
delegate_task(tasks=[
    {"goal": "Research topic A", "toolsets": ["web"]},
    {"goal": "Research topic B", "toolsets": ["web"]},
    {"goal": "Fix the build",    "toolsets": ["terminal", "file"]}
])
```

All three run concurrently. Results return sorted by task index regardless of which finished first.

## Inspecting Subagents In The Dashboard

In the web dashboard, delegated children appear in the right-hand chat sidebar under the `Subagents` tab. Each row shows the generated child name, current status, elapsed time, and the delegated task preview. Click a row to open the child thread in the same sidebar.

The child thread is read-only in v1. It shows the task card, reasoning summaries, tool calls, bounded tool output previews, completion summary, and failures or interruptions. The parent chat remains the source of truth for the final answer; intermediate child transcript content is visible for inspection but does not get injected into the parent's prompt history.

While a child is running, the detail header includes a stop control. Stopping the parent turn still interrupts all active children.

## Worked Examples

### Research Three Topics at Once

```python
delegate_task(tasks=[
    {
        "goal": "Research the current state of WebAssembly in 2025",
        "context": "Focus on: browser support, non-browser runtimes, language support",
        "toolsets": ["web"]
    },
    {
        "goal": "Research RISC-V adoption in 2025",
        "context": "Focus on: server chips, embedded systems, software ecosystem",
        "toolsets": ["web"]
    },
    {
        "goal": "Research quantum computing progress in 2025",
        "context": "Focus on: error correction, practical applications, key players",
        "toolsets": ["web"]
    }
])
```

### Security Review with Auto-Fix

```python
delegate_task(
    goal="Review the authentication module for security issues and fix any found",
    context="""Project at /home/user/webapp.
    Auth files: src/auth/login.py, src/auth/jwt.py, src/auth/middleware.py.
    Stack: Flask, PyJWT, bcrypt.
    Focus on: SQL injection, JWT validation, password handling, session management.
    Fix issues found and run pytest tests/auth/.""",
    toolsets=["terminal", "file"]
)
```

### Large-Scale Refactoring

```python
delegate_task(
    goal="Replace print() with proper logging across all Python files in src/",
    context="""Project at /home/user/myproject.
    Use: logger = logging.getLogger(__name__)
    Map print levels:
      print(f"Error: ...") -> logger.error(...)
      print(f"Warning: ...") -> logger.warning(...)
      print(f"Debug: ...") -> logger.debug(...)
      Others -> logger.info(...)
    Skip test files and CLI output.
    Run pytest after to verify nothing broke.""",
    toolsets=["terminal", "file"]
)
```

## Picking Toolsets

Give each subagent only what it needs:

| Task Type | Toolsets |
|-----------|----------|
| Code work, debugging, file edits | `["terminal", "file"]` |
| Research, docs lookup | `["web"]` |
| Full-stack tasks | `["terminal", "file", "web"]` (default) |
| Read-only code review | `["file"]` |
| System administration | `["terminal"]` |

Some toolsets are **always blocked** for subagents regardless of config:

| Blocked Toolset | Why |
|-----------------|-----|
| `delegation` | Prevents infinite recursive spawning |
| `clarify` | Subagents cannot prompt the user |
| `memory` | No writes to shared persistent memory |
| `code_execution` | Children should reason step-by-step |
| `send_message` | No cross-platform side effects |

## Controlling Iterations

Each subagent defaults to 50 turns. Reduce it for simple tasks:

```python
delegate_task(
    goal="Check if /etc/nginx/nginx.conf exists and print its first 10 lines",
    context="Remote server setup",
    max_iterations=10
)
```

## Using a Cheaper Model for Subagents

Route simple subagent tasks to a faster, cheaper model:

```yaml
# In ~/.spark/config.yaml
delegation:
  model: "google/gemini-flash-2.0"
  provider: "openrouter"
```

Or point subagents at a local model:

```yaml
delegation:
  model: "qwen2.5-coder"
  base_url: "http://localhost:1234/v1"
  api_key: "local-key"
```

If omitted, subagents use the same model as the parent.

## How Parallel Execution Works

- Up to 3 tasks run concurrently via `ThreadPoolExecutor`
- CLI mode: a tree-view shows each subagent's tool calls live
- Web dashboard: the `Subagents` right-sidebar tab shows live rows and child transcripts
- Gateway mode: progress is batched and relayed to the parent's callback
- Interrupting the parent interrupts all active children
- Results return in input order

Single-task delegation runs without thread pool overhead.

## Depth Limit

Delegation is limited to **depth 2**. The parent (depth 0) spawns children (depth 1). Children cannot delegate further — no grandchildren.

## Key Properties at a Glance

- Each subagent gets its **own terminal session** (separate from the parent)
- **No nested delegation** — depth limit of 2
- Only the final summary enters the parent's context — token usage stays controlled
- Subagents inherit the parent's **API key, provider config, and credential pool** (key rotation on rate limits works)

## `delegate_task` vs `execute_code`

| Factor | `delegate_task` | `execute_code` |
|--------|----------------|----------------|
| Reasoning | Full LLM loop | Python script only |
| Context | Fresh isolated conversation | No conversation |
| Tool access | All non-blocked tools | 7 tools via RPC |
| Parallelism | Up to 3 concurrent | Single script |
| Best for | Complex tasks needing judgment | Mechanical pipelines |
| Token cost | Higher | Lower (only stdout returned) |

**Rule of thumb:** `delegate_task` when the subtask needs reasoning or multi-step problem solving. `execute_code` when you need to mechanically process data.

## Full Configuration

```yaml
# In ~/.spark/config.yaml
delegation:
  max_iterations: 50
  default_toolsets: ["terminal", "file", "web"]
  model: "google/gemini-3-flash-preview"
  provider: "openrouter"
```

:::tip
The agent decides when to delegate based on task complexity. You don't need to ask — it will do so when it makes sense.
:::
