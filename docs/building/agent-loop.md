---
sidebar_position: 3
title: "Agent Loop Internals"
description: "Detailed walkthrough of AIAgent execution, API modes, tools, callbacks, and fallback behavior"
---

# Agent Loop Internals

`AIAgent` in `run_agent.py` is the engine everything else builds on — roughly 10,700 lines that take a user message and run it all the way through to a final response, handling providers, tools, compression, retries, and subagents along the way.

## What `AIAgent` Does

- Assembles the system prompt and tool schemas via `prompt_builder.py`
- Picks the right provider and API mode
- Makes cancellable HTTP calls in a background thread
- Executes tool calls sequentially or in parallel
- Stores conversation history in OpenAI message format
- Compresses context, retries on failure, and switches to fallback models
- Tracks turn budgets across parent and child agents
- Flushes persistent memory before context is lost

## Two Ways to Call It

```python
# Simple: returns the final response string
response = agent.chat("Fix the bug in main.py")

# Full control: returns a dict with messages, metadata, and usage stats
result = agent.run_conversation(
    user_message="Fix the bug in main.py",
    system_message=None,           # auto-built from config if omitted
    conversation_history=None,      # loaded from session DB if omitted
    task_id="task_abc123"
)
```

`chat()` is a thin wrapper around `run_conversation()` that pulls out `result["final_response"]`.

## Picking an API Mode

Three execution modes are available. The agent resolves the right one automatically:

| Mode | What it's for | Client |
|------|--------------|--------|
| `chat_completions` | OpenAI-compatible endpoints (OpenRouter, custom, most providers) | `openai.OpenAI` |
| `codex_responses` | OpenAI Codex / Responses API | `openai.OpenAI` with Responses format |
| `anthropic_messages` | Native Anthropic Messages API | `anthropic.Anthropic` via adapter |

All three converge on the same internal message format — OpenAI-style `role`/`content`/`tool_calls` dicts — before and after API calls.

**Resolution order (highest wins):**
1. Explicit `api_mode` constructor argument
2. Provider-specific detection (`anthropic` provider → `anthropic_messages`)
3. Base URL heuristics (`api.anthropic.com` → `anthropic_messages`)
4. Default: `chat_completions`

## What Happens Each Turn

```text
run_conversation()
  1. Generate task_id if not provided
  2. Append user message to conversation history
  3. Build or reuse cached system prompt (prompt_builder.py)
  4. Check if preflight compression is needed (>50% context)
  5. Build API messages from conversation history
     - chat_completions: OpenAI format as-is
     - codex_responses: convert to Responses API input items
     - anthropic_messages: convert via anthropic_adapter.py
  6. Inject ephemeral prompt layers (budget warnings, context pressure)
  7. Apply prompt caching markers if on Anthropic
  8. Make interruptible API call (_api_call_with_interrupt)
  9. Parse response:
     - If tool_calls: execute them, append results, loop back to step 5
     - If text response: persist session, flush memory if needed, return
```

### Message Format

All messages use OpenAI-compatible format internally:

```python
{"role": "system", "content": "..."}
{"role": "user", "content": "..."}
{"role": "assistant", "content": "...", "tool_calls": [...]}
{"role": "tool", "tool_call_id": "...", "content": "..."}
```

Reasoning content (from models with extended thinking) is stored in `assistant_msg["reasoning"]` and displayed via the `reasoning_callback`.

### Message Alternation

The agent enforces strict role alternation. Break these rules and providers reject the request:

- After system: `User → Assistant → User → Assistant → ...`
- During tool calling: `Assistant (with tool_calls) → Tool → Tool → ... → Assistant`
- Never two assistant messages in a row
- Never two user messages in a row
- Only `tool` role can have consecutive entries (parallel results)

## Interruptible API Calls

API requests run in a background thread while the main thread watches for cancellation:

```text
  Main thread                  API thread
  wait on:               HTTP POST
  - response ready           to provider
  - interrupt event
  - timeout
```

On interrupt (user sends a new message, `/stop`, or signal), the API thread is abandoned. No partial response enters the conversation history. The agent processes the new input or shuts down cleanly.

## How Tool Calls Execute

### Single vs. Parallel

- **One tool call** → runs directly in the main thread
- **Multiple tool calls** → run concurrently via `ThreadPoolExecutor`
  - Interactive tools (e.g., `clarify`) always force sequential execution
  - Results are reinserted in the original call order, regardless of completion order

### Per-Tool Execution Flow

```text
for each tool_call in response.tool_calls:
    1. Resolve handler from tools/registry.py
    2. Fire pre_tool_call plugin hook
    3. Check if dangerous command (tools/approval.py)
       - If dangerous: invoke approval_callback, wait for user
    4. Execute handler with args + task_id
    5. Fire post_tool_call plugin hook
    6. Append {"role": "tool", "content": result} to history
```

### Tools That Bypass the Registry

Some tools need direct access to agent state, so `run_agent.py` intercepts them before `handle_function_call()`:

| Tool | Why it's intercepted |
|------|-----------------------|
| `todo` | Reads/writes agent-local task state |
| `memory` | Writes to persistent memory files with character limits |
| `session_search` | Queries session history via the agent's session DB |
| `delegate_task` | Spawns subagents with isolated context |

### Subagent Lifecycle

`delegate_task` creates child `AIAgent` instances with isolated message history, their own session IDs, and the toolsets allowed by `delegation.default_toolsets` or the call arguments. The parent blocks until each child finishes, but the child lifecycle is still emitted in real time for surfaces that can display it.

The canonical lifecycle payloads live in `agent/subagents.py` and use the `spark.subagent.lifecycle.v1` schema. Events include `created`, `started`, `thinking`, `tool_started`, `tool_output`, `tool_completed`, `status`, `completed`, `failed`, and `interrupted`. Web dashboard callbacks persist these as `subagent_runs` and `subagent_events`, publish `chat.subagent.*` SSE topics, and keep the full child transcript separate from the parent prompt history. CLI and gateway continue to receive concise progress through `tool_progress_callback`.

The parent conversation receives only the structured delegation result returned by `delegate_task`. Child transcripts, tool previews, and sidebar state are UI/session metadata, so they do not mutate the parent system prompt, invalidate prompt caching, or add hidden context after a conversation starts.

## Callbacks — Wiring Into Real-Time Progress

Set these on your `AIAgent` instance to get live updates in CLI, gateway, and ACP integrations:

| Callback | Fires when | Used by |
|----------|-----------|---------|
| `tool_progress_callback` | Before/after each tool execution | CLI spinner, gateway progress |
| `thinking_callback` | Model starts/stops thinking | CLI "thinking..." indicator |
| `reasoning_callback` | Model returns reasoning content | CLI reasoning display, gateway blocks |
| `clarify_callback` | `clarify` tool is called | CLI input prompt, gateway interactive message |
| `step_callback` | Each complete agent turn | Gateway step tracking, ACP progress |
| `stream_delta_callback` | Each streaming token | CLI streaming display |
| `tool_gen_callback` | Tool call parsed from stream | CLI tool preview in spinner |
| `status_callback` | State changes (thinking, executing, etc.) | ACP status updates |
| `subagent_event_callback` | Subagent lifecycle events | Web dashboard subagent sidebar |

ACP v1 continues to expose delegation through normal tool-call progress. Structured subagent sidebar notifications are intentionally dashboard-only until the ACP client protocol has a dedicated UI contract for child transcripts.

## Iteration Budgets and Fallbacks

### Turn Budget

The agent tracks turns via `IterationBudget`:

- Default limit: 90 turns (configurable via `agent.max_turns`)
- Each agent — including subagents — gets its own independent budget
- Subagents are capped at `delegation.max_iterations` (default: 50)
- At 100% budget, the agent stops and returns a summary of work done

### Fallback on Failure

When the primary model returns 429, 5xx, or 401/403:

1. Check `fallback_providers` list in config
2. Try each fallback in order
3. On success, continue the conversation with the new provider
4. On 401/403, attempt credential refresh before failing over

Auxiliary tasks (vision, compression, web extraction, session search) each have their own fallback chain via the `auxiliary.*` config section.

## Context Management and Session Persistence

### When Compression Fires

- **Preflight** — before the API call, if the conversation exceeds 50% of the model's context window
- **Gateway auto-compression** — between turns, if the conversation exceeds 85% (catches sessions that grew overnight)

### What Compression Does

1. Flushes memory to disk first
2. Summarizes middle conversation turns into a compact structured block
3. Preserves the last N messages intact (`compression.protect_last_n`, default: 20)
4. Keeps tool call/result pairs together — never splits them
5. Generates a new session lineage ID (compression creates a child session)
6. Keeps subagent run records discoverable from both the original session ID and the latest compressed descendant

### After Every Turn

- Messages are saved to the SQLite session store (`spark_state.py`)
- Memory changes are flushed to `MEMORY.md` / `USER.md`
- The session can be resumed later via `/resume` or `spark chat --resume`

## Key Source Files

| File | Purpose |
|------|---------|
| `run_agent.py` | `AIAgent` class — the complete agent loop (~10,700 lines) |
| `agent/prompt_builder.py` | System prompt assembly from memory, skills, context files, personality |
| `agent/context_engine.py` | `ContextEngine` ABC — pluggable context management |
| `agent/context_compressor.py` | Default engine — lossy summarization algorithm |
| `agent/prompt_caching.py` | Anthropic prompt caching markers and cache metrics |
| `agent/auxiliary_client.py` | Auxiliary LLM for side tasks (vision, summarization) |
| `model_tools.py` | Tool schema collection, `handle_function_call()` dispatch |

## Related Docs

- [Provider Runtime Resolution](./provider-runtime.md)
- [Prompt Assembly](./prompt-assembly.md)
- [Context Compression & Prompt Caching](./context-compression-and-caching.md)
- [Tools Runtime](./tools-runtime.md)
- [Architecture Overview](./architecture.md)
