---
title: Fallback Providers
description: Configure automatic failover to backup LLM providers when your primary model is unavailable.
sidebar_label: Fallback Providers
sidebar_position: 8
---

# Fallback Providers

Spark keeps your sessions alive even when providers go down. There are three independent layers of resilience, each handling a different failure scenario:

1. **[Credential pools](./credential-pools.md)** — rotate across multiple API keys for the *same* provider (tried first)
2. **Primary model fallback** — switch to a *different* provider:model when your main model fails
3. **Auxiliary task fallback** — independent provider resolution for side tasks like vision, compression, and web extraction

Credential pools handle same-provider rotation. This page covers layers 2 and 3.

## Primary Model Fallback

When your main LLM hits rate limits, server errors, or auth failures, Spark can automatically switch to a backup provider:model mid-session — without losing your conversation history or context.

### Set It Up

Add a `fallback_model` section to `~/.spark/config.yaml`:

```yaml
fallback_model:
  provider: openrouter
  model: anthropic/claude-sonnet-4
```

Both `provider` and `model` are required. If either is missing, fallback is disabled.

### Supported Providers

| Provider | Value | Requirements |
|----------|-------|-------------|
| AI Gateway | `ai-gateway` | `AI_GATEWAY_API_KEY` |
| OpenRouter | `openrouter` | `OPENROUTER_API_KEY` |
| OpenAI Codex | `openai-codex` | `spark model` (ChatGPT OAuth) |
| GitHub Copilot | `copilot` | `COPILOT_GITHUB_TOKEN`, `GH_TOKEN`, or `GITHUB_TOKEN` |
| GitHub Copilot ACP | `copilot-acp` | External process (editor integration) |
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY` or Claude Code credentials |
| z.ai / GLM | `zai` | `GLM_API_KEY` |
| Kimi / Moonshot | `kimi-coding` | `KIMI_API_KEY` |
| MiniMax | `minimax` | `MINIMAX_API_KEY` |
| MiniMax (China) | `minimax-cn` | `MINIMAX_CN_API_KEY` |
| DeepSeek | `deepseek` | `DEEPSEEK_API_KEY` |
| OpenCode Zen | `opencode-zen` | `OPENCODE_ZEN_API_KEY` |
| OpenCode Go | `opencode-go` | `OPENCODE_GO_API_KEY` |
| Kilo Code | `kilocode` | `KILOCODE_API_KEY` |
| Xiaomi MiMo | `xiaomi` | `XIAOMI_API_KEY` |
| Arcee AI | `arcee` | `ARCEEAI_API_KEY` |
| Alibaba / DashScope | `alibaba` | `DASHSCOPE_API_KEY` |
| Hugging Face | `huggingface` | `HF_TOKEN` |
| Custom endpoint | `custom` | `base_url` + `api_key_env` (see below) |

### Use a Custom Endpoint as Fallback

```yaml
fallback_model:
  provider: custom
  model: my-local-model
  base_url: http://localhost:8000/v1
  api_key_env: MY_LOCAL_KEY          # env var name containing the API key
```

### What Triggers the Fallback

Spark activates the fallback when the primary model fails with:

- **Rate limits** (HTTP 429) — after exhausting retry attempts
- **Server errors** (HTTP 500, 502, 503) — after exhausting retry attempts
- **Auth failures** (HTTP 401, 403) — immediately, no retries
- **Not found** (HTTP 404) — immediately
- **Invalid responses** — malformed or empty API responses after repeated attempts

When triggered, Spark resolves credentials for the fallback provider, builds a new API client, and swaps the model in-place. Your conversation history, tool calls, and context are fully preserved. The agent picks up exactly where it left off.

:::info One-Shot
Fallback activates **at most once** per session. If the fallback provider also fails, normal error handling takes over. This prevents cascading failover loops.
:::

### Ready-to-Use Examples

**OpenRouter as fallback for Anthropic native:**
```yaml
model:
  provider: anthropic
  default: claude-sonnet-4-6

fallback_model:
  provider: openrouter
  model: anthropic/claude-sonnet-4
```

**Anthropic as fallback for OpenRouter:**
```yaml
model:
  provider: openrouter
  default: anthropic/claude-opus-4

fallback_model:
  provider: anthropic
  model: claude-sonnet-4-6
```

**Local model as fallback for cloud:**
```yaml
fallback_model:
  provider: custom
  model: llama-3.1-70b
  base_url: http://localhost:8000/v1
  api_key_env: LOCAL_API_KEY
```

**Codex OAuth as fallback:**
```yaml
fallback_model:
  provider: openai-codex
  model: gpt-5.3-codex
```

### Where Fallback Works

| Context | Fallback supported? |
|---------|-------------------|
| CLI sessions | Yes |
| Messaging gateway (Telegram, Discord, etc.) | Yes |
| Subagent delegation | No — subagents don't inherit fallback config |
| Cron jobs | No — run with a fixed provider |
| Auxiliary tasks (vision, compression) | No — use their own provider chain (see below) |

:::tip
There are no environment variables for `fallback_model` — it's configured exclusively through `config.yaml`. This is intentional: fallback configuration is a deliberate choice, not something a stale shell export should override.
:::

---

## Auxiliary Task Fallback

Spark uses separate lightweight models for background work like vision analysis, context compression, and web extraction. Each task has its own provider resolution chain — a built-in fallback system that's always on.

### Tasks with Independent Provider Resolution

| Task | What it handles | Config key |
|------|----------------|-----------|
| Vision | Image analysis, browser screenshots | `auxiliary.vision` |
| Web Extract | Web page summarization | `auxiliary.web_extract` |
| Compression | Context compression summaries | `auxiliary.compression` |
| Session Search | Past session summarization | `auxiliary.session_search` |
| Skills Hub | Skill search and discovery | `auxiliary.skills_hub` |
| MCP | MCP helper operations | `auxiliary.mcp` |
| Memory Flush | Memory consolidation | `auxiliary.flush_memories` |

### How Auto-Detection Works

When a task's provider is set to `"auto"` (the default), Spark tries providers in order until one works:

**Text tasks (compression, web extract, etc.):**

```text
OpenRouter -> Codex OAuth -> Custom endpoint ->
API-key providers (z.ai, Kimi, MiniMax, Xiaomi MiMo, Hugging Face, Anthropic) -> give up
```

**Vision tasks:**

```text
Main provider (if vision-capable) -> OpenRouter ->
Codex OAuth -> Anthropic -> Custom endpoint -> give up
```

If the resolved provider fails at call time and it isn't OpenRouter and has no explicit `base_url`, Spark tries OpenRouter as a last-resort fallback.

### Configure Each Task Independently

```yaml
auxiliary:
  vision:
    provider: "auto"              # auto | openrouter | codex | main | anthropic
    model: ""                     # e.g. "openai/gpt-4o"
    base_url: ""                  # direct endpoint (overrides provider)
    api_key: ""                   # API key for base_url

  web_extract:
    provider: "auto"
    model: ""

  compression:
    provider: "auto"
    model: ""

  session_search:
    provider: "auto"
    model: ""

  skills_hub:
    provider: "auto"
    model: ""

  mcp:
    provider: "auto"
    model: ""

  flush_memories:
    provider: "auto"
    model: ""
```

All tasks share the same `provider / model / base_url` pattern. For context compression specifically:

```yaml
auxiliary:
  compression:
    provider: main                                    # Same options as other auxiliary tasks
    model: google/gemini-3-flash-preview
    base_url: null                                    # Custom OpenAI-compatible endpoint
```

### Provider Options for Auxiliary Tasks

These options apply to `auxiliary:`, `compression:`, and `fallback_model:` — `"main"` is **not** valid for your top-level `model.provider`. For custom endpoints at the top level, use `provider: custom` (see [AI Providers](../integrations/providers.md)).

| Provider | Description | Requirements |
|----------|-------------|-------------|
| `"auto"` | Try providers in order until one works (default) | At least one provider configured |
| `"openrouter"` | Force OpenRouter | `OPENROUTER_API_KEY` |
| `"codex"` | Force Codex OAuth | `spark model` -> Codex |
| `"main"` | Use whatever provider the main agent uses (auxiliary only) | Active main provider |
| `"anthropic"` | Force Anthropic native | `ANTHROPIC_API_KEY` or Claude Code credentials |

### Point a Task at a Direct Endpoint

Setting `base_url` on any auxiliary task bypasses provider resolution entirely:

```yaml
auxiliary:
  vision:
    base_url: "http://localhost:1234/v1"
    api_key: "local-key"
    model: "qwen2.5-vl"
```

`base_url` takes precedence over `provider`. Spark uses the configured `api_key` for auth, falling back to `OPENAI_API_KEY` if not set. It does **not** reuse `OPENROUTER_API_KEY` for custom endpoints.

---

## Context Compression Fallback

Context compression uses `auxiliary.compression` to control which model handles summarization:

```yaml
auxiliary:
  compression:
    provider: "auto"                              # auto | openrouter | codex | main
    model: "google/gemini-3-flash-preview"
```

:::info Legacy migration
Older configs using `compression.summary_model` / `compression.summary_provider` / `compression.summary_base_url` are automatically migrated to `auxiliary.compression.*` on first load (config version 17).
:::

If no compression provider is available, Spark drops middle conversation turns without a summary rather than failing your session entirely.

---

## Delegation Provider Override

Subagents from `delegate_task` don't use the primary fallback model, but you can route them to a specific provider:model for cost control:

```yaml
delegation:
  provider: "openrouter"                      # override provider for all subagents
  model: "google/gemini-3-flash-preview"      # override model
  # base_url: "http://localhost:1234/v1"      # or use a direct endpoint
  # api_key: "local-key"
```

See [Subagent Delegation](../tools/delegation.md) for full configuration details.

---

## Cron Job Providers

Cron jobs run with whatever provider is configured at execution time and don't support a fallback model. Override the provider per job:

```python
cronjob(
    action="create",
    schedule="every 2h",
    prompt="Check server status",
    provider="openrouter",
    model="google/gemini-3-flash-preview"
)
```

See [Scheduled Tasks (Cron)](../automate/cron.md) for full configuration details.

---

## Summary

| Feature | How fallback works | Where to configure |
|---------|-------------------|--------------------|
| Main agent model | One-shot failover via `fallback_model` | `fallback_model:` (top-level) |
| Vision | Auto-detection chain + internal OpenRouter retry | `auxiliary.vision` |
| Web extraction | Auto-detection chain + internal OpenRouter retry | `auxiliary.web_extract` |
| Context compression | Auto-detection chain; degrades to no-summary if unavailable | `auxiliary.compression` |
| Session search | Auto-detection chain | `auxiliary.session_search` |
| Skills hub | Auto-detection chain | `auxiliary.skills_hub` |
| MCP helpers | Auto-detection chain | `auxiliary.mcp` |
| Memory flush | Auto-detection chain | `auxiliary.flush_memories` |
| Delegation | Provider override only — no automatic fallback | `delegation.provider` / `delegation.model` |
| Cron jobs | Per-job provider override only — no automatic fallback | Per-job `provider` / `model` |
