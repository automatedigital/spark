---
sidebar_position: 2
title: "ACP Internals"
description: "How the ACP adapter works: lifecycle, sessions, event bridge, approvals, and tool rendering"
---

# ACP Internals

The ACP adapter bridges Spark's synchronous `AIAgent` to an async JSON-RPC stdio server so editors can drive it over the Agent Communication Protocol.

Key implementation files:

- `acp_adapter/entry.py`
- `acp_adapter/server.py`
- `acp_adapter/session.py`
- `acp_adapter/events.py`
- `acp_adapter/permissions.py`
- `acp_adapter/tools.py`
- `acp_adapter/auth.py`
- `acp_adapter/registry/agent.json`

## Boot sequence

```text
spark acp / spark-acp / python -m acp_adapter
  -> acp_adapter.entry.main()
  -> load ~/.spark/.env
  -> configure stderr logging
  -> construct SparkACPAgent
  -> acp.run_agent(agent)
```

Stdout carries the ACP JSON-RPC transport exclusively. Human-readable logs go to stderr.

## Major components

### `SparkACPAgent`

Defined in `acp_adapter/server.py`. Implements the ACP agent protocol and handles:

- Initialize and authenticate
- `new`, `load`, `resume`, `fork`, `list`, `cancel` session methods
- Prompt execution
- Session model switching
- Wiring sync `AIAgent` callbacks into ACP async notifications

### `SessionManager`

Defined in `acp_adapter/session.py`. Tracks live ACP sessions.

Each session stores:

| Field | Description |
|-------|-------------|
| `session_id` | Unique session identifier |
| `agent` | The `AIAgent` instance |
| `cwd` | Working directory bound to this session |
| `model` | Active model for this session |
| `history` | Conversation message history |
| `cancel_event` | Asyncio event for cancellation |

The manager is thread-safe and supports create, get, remove, fork, list, cleanup, and cwd updates.

### Event bridge

Defined in `acp_adapter/events.py`. Converts `AIAgent` callbacks into ACP `session_update` events.

Bridged callbacks:

- `tool_progress_callback`
- `thinking_callback`
- `step_callback`
- `message_callback`

Because `AIAgent` runs in a worker thread while ACP I/O lives on the main event loop, the bridge uses:

```python
asyncio.run_coroutine_threadsafe(...)
```

### Permission bridge

Defined in `acp_adapter/permissions.py`. Translates dangerous terminal approval prompts into ACP permission requests.

| ACP response | Spark action |
|-------------|-------------|
| `allow_once` | `once` |
| `allow_always` | `always` |
| reject options | `deny` |

Timeouts and bridge failures deny by default — safe fallback.

### Tool rendering helpers

Defined in `acp_adapter/tools.py`. Maps Spark tools to ACP tool kinds and builds editor-facing content.

| Tool | ACP rendering |
|------|--------------|
| `patch`, `write_file` | File diffs |
| `terminal` | Shell command text |
| `read_file`, `search_files` | Text previews |
| Large results | Truncated text blocks (UI safety) |

## Session lifecycle

```text
new_session(cwd)
  -> create SessionState
  -> create AIAgent(platform="acp", enabled_toolsets=["spark-acp"])
  -> bind task_id/session_id to cwd override

prompt(..., session_id)
  -> extract text from ACP content blocks
  -> reset cancel event
  -> install callbacks + approval bridge
  -> run AIAgent in ThreadPoolExecutor
  -> update session history
  -> emit final agent message chunk
```

### Cancellation

`cancel(session_id)`:

- Sets the session cancel event
- Calls `agent.interrupt()` when available
- Causes the prompt response to return `stop_reason="cancelled"`

### Forking

`fork_session()` deep-copies message history into a new live session, preserving the full conversation state while giving the fork its own `session_id` and `cwd`.

## Provider and auth

ACP does not maintain its own auth store. It reuses Spark's runtime resolver:

- `acp_adapter/auth.py`
- `spark_cli/runtime_provider.py`

ACP advertises and uses whatever provider and credentials Spark is currently configured with.

## Working directory binding

Every ACP session carries an editor `cwd`. The session manager binds that path to the ACP session ID via task-scoped terminal and file overrides, so file and terminal tools operate relative to the editor's workspace — not wherever the Spark process started.

## Duplicate same-name tool calls

The event bridge tracks tool IDs as a FIFO queue per tool name, not as a single ID per name. This handles:

- Parallel calls to the same tool
- Repeated calls to the same tool within one agent step

Without FIFO queues, completion events would attach to the wrong tool invocation.

## Approval callback restoration

ACP temporarily installs an approval callback on the terminal tool during prompt execution, then restores the previous callback when the prompt finishes. This prevents session-specific approval handlers from leaking into global state.

## Current limitations

- ACP sessions are process-local from the ACP server's perspective
- Non-text prompt blocks are currently ignored for request text extraction
- Editor-specific UX varies by ACP client implementation

## Related files

- `tests/acp/` — ACP test suite
- `toolsets.py` — `spark-acp` toolset definition
- `spark_cli/main.py` — `spark acp` CLI subcommand
- `pyproject.toml` — `[acp]` optional dependency + `spark-acp` script
