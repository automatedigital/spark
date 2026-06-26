---
sidebar_position: 4
title: "Provider Runtime Resolution"
description: "How Spark resolves providers, credentials, API modes, and auxiliary models at runtime"
---

# Provider Runtime Resolution

Spark uses a single shared provider resolver across every execution context — CLI sessions, gateway message handling, cron jobs, ACP editor sessions, and auxiliary model tasks. This page explains how that resolver works and where to look when credentials or endpoints behave unexpectedly.

Primary files:
- `spark_cli/runtime_provider.py` — credential resolution, `_resolve_custom_runtime()`
- `spark_cli/auth.py` — provider registry, `resolve_provider()`
- `spark_cli/model_switch.py` — shared `/model` switch pipeline (CLI + gateway)
- `agent/auxiliary_client.py` — auxiliary model routing

Adding a new first-class inference provider? Read [Adding Providers](./adding-providers.md) alongside this page.

## Resolution Precedence

When Spark resolves a provider, it checks in this order:

1. Explicit CLI/runtime request
2. `config.yaml` model/provider config
3. Environment variables
4. Provider-specific defaults or auto-resolution

Config takes priority over environment variables by design. A stale shell export can't silently override the endpoint you last selected in `spark model`.

## Supported Providers

| Provider | Notes |
|----------|-------|
| AI Gateway (Vercel) | Fetches model list from `/models` endpoint |
| OpenRouter | |
| OpenAI Codex | Uses Responses API (`codex_responses` mode) |
| Copilot / Copilot ACP | |
| Anthropic (native) | Full native Messages API path |
| Google / Gemini | |
| Alibaba / DashScope | |
| DeepSeek | |
| Z.AI | |
| Kimi / Moonshot | |
| MiniMax | |
| MiniMax China | |
| Kilo Code | |
| Hugging Face | |
| OpenCode Zen / OpenCode Go | |
| Custom (`provider: custom`) | Any OpenAI-compatible endpoint |
| Named custom providers | `custom_providers` list in `config.yaml` |

## What Resolution Returns

The resolver produces a record with these fields:

- `provider`
- `api_mode`
- `base_url`
- `api_key`
- `source`
- Provider-specific metadata (expiry/refresh info for refreshable credentials)

## API Key Scoping

When you have multiple provider keys, Spark ensures each key only goes to its own endpoint:

| Key | Sent to |
|-----|---------|
| `OPENROUTER_API_KEY` | `openrouter.ai` endpoints only |
| `AI_GATEWAY_API_KEY` | `ai-gateway.vercel.sh` endpoints only |
| `OPENAI_API_KEY` | Custom endpoints and fallback |

Spark also distinguishes between a real custom endpoint you've configured and the OpenRouter fallback path. That matters when you're running a local model server or a non-OpenRouter OpenAI-compatible API — your saved endpoint keeps working even when `OPENAI_BASE_URL` isn't exported in the current shell.

## Native Anthropic Path

When the resolver selects `anthropic`, Spark routes through the native Anthropic Messages API — not OpenRouter:

- `api_mode = anthropic_messages`
- Translation handled by `agent/anthropic_adapter.py`

Credential preference for native Anthropic:

1. Claude Code credential files with refreshable auth (preferred)
2. Manual `ANTHROPIC_TOKEN` / `CLAUDE_CODE_OAUTH_TOKEN` (explicit override)

Spark preflights an Anthropic credential refresh before each native Messages API call. It also retries once on a 401 after rebuilding the client, as a failsafe.

## OpenAI Codex Path

Codex gets its own execution path:

- `api_mode = codex_responses`
- Dedicated credential resolution and auth store support

## Auxiliary Model Routing

These tasks can use their own provider/model independently of the main conversational model:

- Vision
- Web extraction summarization
- Context compression summaries
- Session search summarization
- Skills hub operations
- MCP helper operations
- Memory flushes

Configure an auxiliary task with `provider: main` and Spark resolves it through the same shared runtime path as normal chat — including support for env-driven endpoints and config-saved custom endpoints. The auxiliary resolver can tell the difference between a real saved custom endpoint and the OpenRouter fallback, so your custom setup works everywhere.

## Fallback Models

You can configure a fallback provider/model pair. If the primary model hits errors, Spark automatically activates the fallback and retries.

### When Fallback Activates

`_try_activate_fallback()` is called from three points in the main retry loop in `run_agent.py`:

| Trigger | Condition |
|---------|-----------|
| Max retries on invalid responses | None choices, missing content |
| Non-retryable client errors | HTTP 401, 403, 404 |
| Max retries on transient errors | HTTP 429, 500, 502, 503 |

### What Happens on Activation

1. Returns immediately if already activated or not configured.
2. Calls `resolve_provider_client()` from `auxiliary_client.py` to build a new client.
3. Determines `api_mode`: `codex_responses` for openai-codex, `anthropic_messages` for anthropic, `chat_completions` for everything else.
4. Swaps in-place: `self.model`, `self.provider`, `self.base_url`, `self.api_mode`, `self.client`, `self._client_kwargs`.
5. For anthropic fallback: builds a native Anthropic client instead of OpenAI-compatible.
6. Re-evaluates prompt caching (enabled for Claude models on OpenRouter).
7. Sets `_fallback_activated = True` — one-shot, won't fire again.
8. Resets retry count to 0 and continues the loop.

### Fallback Config

```yaml
# config.yaml
fallback_model:
  provider: anthropic
  model: claude-haiku-3-5
```

Both `provider` and `model` must be non-empty or fallback is disabled.

### What Doesn't Support Fallback

- **Subagent delegation** (`tools/delegate_tool.py`) — subagents inherit the parent's provider, not the fallback config
- **Cron jobs** (`cron/`) — run with a fixed provider, no fallback
- **Auxiliary tasks** — use their own independent provider auto-detection chain

See `tests/run_agent/test_fallback_model.py` for comprehensive tests covering all supported providers, one-shot semantics, and edge cases.

## Related Docs

- [Agent Loop Internals](./agent-loop.md)
- [ACP Internals](./editor-extension-internals.md)
- [Context Compression & Prompt Caching](./context-compression-and-caching.md)
