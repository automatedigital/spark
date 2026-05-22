# Context Compression and Caching

Long conversations eat context fast. Spark handles this with two independent compression layers and Anthropic prompt caching that cuts input token costs by ~75% on multi-turn sessions.

Source files: `agent/context_engine.py` (ABC), `agent/context_compressor.py` (default engine),
`agent/prompt_caching.py`, `gateway/run.py` (session hygiene), `run_agent.py` (search for `_compress_context`)


## Swappable Context Engine

Context management is built on the `ContextEngine` ABC in `agent/context_engine.py`. The built-in `ContextCompressor` is the default, but you can replace it entirely with a plugin:

```yaml
context:
  engine: "compressor"    # default - built-in lossy summarization
  engine: "lcm"           # example - plugin providing lossless context
```

The engine owns four responsibilities:
- Deciding when compaction fires (`should_compress()`)
- Performing compaction (`compress()`)
- Exposing optional agent-callable tools (e.g., `lcm_grep`)
- Tracking token usage from API responses

**Resolution order when loading:**
1. Check `plugins/context_engine/<name>/` directory
2. Check general plugin system (`register_context_engine()`)
3. Fall back to built-in `ContextCompressor`

Plugin engines are never auto-activated. The user must explicitly set `context.engine`. To build your own, see [Context Engine Plugins](context-engine-plugin.md).

Configure via `spark plugins` → Provider Plugins → Context Engine, or edit `config.yaml` directly.


## Two Compression Layers

Two separate systems fire independently at different thresholds:

```
  Incoming message
       │
       ▼
  Gateway Session Hygiene   ← fires at 85% of context
  (pre-agent, rough estimate)   Safety net for large sessions
       │
       ▼
  Agent ContextCompressor   ← fires at 50% of context (default)
  (in-loop, real tokens)        Normal context management
```

### Gateway Session Hygiene (85% threshold)

Lives in `gateway/run.py` (search `Session hygiene: auto-compress`). This is a safety net that runs **before** the agent processes a message. It catches sessions that grew too large between turns — overnight accumulation in Telegram or Discord, for example.

- **Threshold:** Fixed at 85% of model context length
- **Token source:** Prefers actual API-reported tokens from last turn; falls back to `estimate_messages_tokens_rough`
- **Fires only:** when `len(history) >= 4` and compression is enabled
- **Purpose:** Catch sessions the agent's own compressor missed

The 85% threshold is intentionally higher than the agent compressor's 50%. Setting both at 50% caused premature compression on every turn in long gateway sessions.

### Agent ContextCompressor (50% threshold, configurable)

Lives in `agent/context_compressor.py`. This is the primary system — it runs inside the tool loop with accurate, API-reported token counts.


## Configuration

```yaml
compression:
  enabled: true              # Enable/disable compression (default: true)
  threshold: 0.50            # Fraction of context window (default: 0.50 = 50%)
  target_ratio: 0.20         # How much of threshold to keep as tail (default: 0.20)
  protect_last_n: 20         # Minimum protected tail messages (default: 20)

# Summarization model configured under auxiliary:
auxiliary:
  compression:
    model: null              # Override model for summaries (default: auto-detect)
    provider: auto           # Provider: "auto", "openrouter", "codex", "main", etc.
    base_url: null           # Custom OpenAI-compatible endpoint
```

### Parameter Reference

| Parameter | Default | Range | Description |
|-----------|---------|-------|-------------|
| `threshold` | `0.50` | 0.0–1.0 | Fires when prompt tokens >= `threshold × context_length` |
| `target_ratio` | `0.20` | 0.10–0.80 | Tail protection budget: `threshold_tokens × target_ratio` |
| `protect_last_n` | `20` | ≥1 | Minimum recent messages always preserved |
| `protect_first_n` | `3` | hardcoded | System prompt + first exchange always preserved |

### Computed Values (200K context model at defaults)

```
context_length       = 200,000
threshold_tokens     = 200,000 × 0.50 = 100,000
tail_token_budget    = 100,000 × 0.20 = 20,000
max_summary_tokens   = min(200,000 × 0.05, 12,000) = 10,000
```


## How Compression Works — 4 Phases

### Phase 1 — Prune Old Tool Results (no LLM call needed)

Old tool results longer than 200 chars, outside the protected tail, get replaced with:

```
[Old tool output cleared to save context space]
```

This cheap pre-pass removes the bulk of the tokens from verbose tool outputs — file contents, terminal output, search results.

### Phase 2 — Determine Boundaries

```
  Message list
  ┌────────────────────────────────────────────────────┐
  │ [0..2]  ← protect_first_n (system + first exchange)│
  │ [3..N]  ← middle turns → SUMMARIZED                │
  │ [N..end]← tail (by token budget OR protect_last_n) │
  └────────────────────────────────────────────────────┘
```

Tail protection is **token-budget based**: it walks backward from the end, accumulating tokens until the budget runs out. Falls back to a fixed `protect_last_n` count if the budget would protect fewer messages.

Boundaries are aligned to avoid splitting tool_call/tool_result pairs. `_align_boundary_backward()` walks past consecutive tool results to find the parent assistant message.

### Phase 3 — Generate Structured Summary

:::warning Summary model context length
The summary model's context window must be **at least as large** as the main agent model's. The entire middle section is sent in a single call. If the summary model's context is smaller, `_generate_summary()` catches the error, logs a warning, and returns `None`. The compressor then drops the middle turns **without a summary** — silently losing context. This is the most common cause of degraded compaction quality.
:::

The auxiliary LLM summarizes the middle turns using a structured template:

```
## Goal
[What the user is trying to accomplish]

## Constraints & Preferences
[User preferences, coding style, constraints, important decisions]

## Progress
### Done
[Completed work - specific file paths, commands run, results]
### In Progress
[Work currently underway]
### Blocked
[Any blockers or issues encountered]

## Key Decisions
[Important technical decisions and why]

## Relevant Files
[Files read, modified, or created - with brief note on each]

## Next Steps
[What needs to happen next]

## Critical Context
[Specific values, error messages, configuration details]
```

Summary token budget:
- Formula: `content_tokens × 0.20` (the `_SUMMARY_RATIO` constant)
- Minimum: 2,000 tokens
- Maximum: `min(context_length × 0.05, 12,000)` tokens

### Phase 4 — Reassemble

The final message list is:
1. Head messages (system prompt gets a note appended on the first compaction)
2. Summary message (role chosen to avoid consecutive same-role violations)
3. Tail messages (unmodified)

`_sanitize_tool_pairs()` cleans up orphaned pairs: tool results referencing removed calls are removed; tool calls whose results were removed get a stub result injected.

### Re-compression Across Multiple Rounds

On subsequent compressions, the previous summary is passed to the LLM with instructions to **update** it rather than start from scratch. Items move from "In Progress" to "Done", new progress is added, obsolete information is removed. The `_previous_summary` field stores this across compactions.


## Before/After Example

### Before (45 messages, ~95K tokens)

```
[0] system:    "You are a helpful assistant..." (system prompt)
[1] user:      "Help me set up a FastAPI project"
[2] assistant: <tool_call> terminal: mkdir project </tool_call>
[3] tool:      "directory created"
[4] assistant: <tool_call> write_file: main.py </tool_call>
[5] tool:      "file written (2.3KB)"
    ... 30 more turns of file editing, testing, debugging ...
[38] assistant: <tool_call> terminal: pytest </tool_call>
[39] tool:      "8 passed, 2 failed\n..."  (5KB output)
[40] user:      "Fix the failing tests"
[41] assistant: <tool_call> read_file: tests/test_api.py </tool_call>
[42] tool:      "import pytest\n..."  (3KB)
[43] assistant: "I see the issue with the test fixtures..."
[44] user:      "Great, also add error handling"
```

### After (25 messages, ~45K tokens)

```
[0] system:    "You are a helpful assistant...
               [Note: Some earlier conversation turns have been compacted...]"
[1] user:      "Help me set up a FastAPI project"
[2] assistant: "[CONTEXT COMPACTION] Earlier turns were compacted...

               ## Goal
               Set up a FastAPI project with tests and error handling

               ## Progress
               ### Done
               - Created project structure: main.py, tests/, requirements.txt
               - Implemented 5 API endpoints in main.py
               - Wrote 10 test cases in tests/test_api.py
               - 8/10 tests passing

               ### In Progress
               - Fixing 2 failing tests (test_create_user, test_delete_user)

               ## Relevant Files
               - main.py - FastAPI app with 5 endpoints
               - tests/test_api.py - 10 test cases
               - requirements.txt - fastapi, pytest, httpx

               ## Next Steps
               - Fix failing test fixtures
               - Add error handling"
[3] user:      "Fix the failing tests"
[4] assistant: <tool_call> read_file: tests/test_api.py </tool_call>
[5] tool:      "import pytest\n..."
[6] assistant: "I see the issue with the test fixtures..."
[7] user:      "Great, also add error handling"
```


## Prompt Caching (Anthropic)

Source: `agent/prompt_caching.py`

Reduces input token costs by ~75% on multi-turn conversations by caching the conversation prefix with Anthropic's `cache_control` breakpoints.

### Strategy: system_and_3

Anthropic allows 4 `cache_control` breakpoints per request. Spark uses all four:

```
Breakpoint 1: System prompt             ← stable across all turns
Breakpoint 2: 3rd-to-last non-system message  ┐
Breakpoint 3: 2nd-to-last non-system message  ├ Rolling window
Breakpoint 4: Last non-system message         ┘
```

### How the Markers Are Applied

`apply_anthropic_cache_control()` deep-copies messages and injects `cache_control` markers:

```python
# Standard marker
marker = {"type": "ephemeral"}
# 1-hour TTL marker
marker = {"type": "ephemeral", "ttl": "1h"}
```

Where the marker lands depends on content type:

| Content Type | Where Marker Goes |
|-------------|-------------------|
| String content | Converted to `[{"type": "text", "text": ..., "cache_control": ...}]` |
| List content | Added to the last element's dict |
| None/empty | Added as `msg["cache_control"]` |
| Tool messages | Added as `msg["cache_control"]` (native Anthropic only) |

### Design Rules That Protect Cache Hits

1. **Keep the system prompt stable.** It sits at breakpoint 1 and caches across all turns. Compression appends a note only once — on first compaction.
2. **Order matters.** Cache hits require prefix matching. Inserting or removing messages in the middle invalidates everything after.
3. **After compression,** the cache is invalidated for the compressed region. The system prompt cache survives. The rolling 3-message window re-establishes caching within 1–2 turns.
4. **TTL:** Default is `5m`. Use `1h` for sessions where the user takes breaks between turns.

### Enabling It

Caching activates automatically when:
- The model is a Claude model (detected by model name)
- The provider supports `cache_control` (native Anthropic API or OpenRouter)

```yaml
# config.yaml
model:
  cache_ttl: "5m"   # "5m" or "1h"
```

The CLI shows status at startup:

```
✓ Prompt caching: ENABLED (Claude via OpenRouter, 5m TTL)
```


## Context Pressure Warnings

The agent emits a warning at 85% of the compression threshold (not 85% of context):

```
⚠ Context is 85% to compaction threshold (42,500/50,000 tokens)
```

After compression, if usage drops below 85% of the threshold, the warning clears. If compression fails to reduce below that level, the warning persists — but compression won't re-trigger until the threshold is exceeded again.
