---
title: Credential Pools
description: Pool multiple API keys or OAuth tokens per provider for automatic rotation and rate limit recovery.
sidebar_label: Credential Pools
sidebar_position: 9
---

# Credential Pools

Hit a rate limit? Spark rotates to your next healthy key automatically — no interruptions, no manual intervention. Credential pools let you register multiple API keys or OAuth tokens for the same provider and Spark handles the switching.

This is different from [fallback providers](./fallback-providers.md), which switch to a *different* provider. Credential pools rotate within the same provider. Pools are tried first — if every key is exhausted, *then* the fallback provider activates.

## How Rotation Works

```
Your request
  -> Pick key from pool (round_robin / least_used / fill_first / random)
  -> Send to provider
  -> 429 rate limit?
      -> Retry same key once (might be transient)
      -> Second 429 -> rotate to next pool key
      -> All keys exhausted -> fallback_model (different provider)
  -> 402 billing error?
      -> Immediately rotate to next pool key (24h cooldown)
  -> 401 auth expired?
      -> Try refreshing the token (OAuth)
      -> Refresh failed -> rotate to next pool key
  -> Success -> continue normally
```

## Add Your First Extra Key

If you already have an API key in `.env`, Spark treats it as a 1-key pool automatically. To get rotation benefits, add more:

```bash
# Add a second OpenRouter key
spark auth add openrouter --api-key sk-or-v1-your-second-key

# Add a second Anthropic key
spark auth add anthropic --type api-key --api-key sk-ant-api03-your-second-key

# Add an Anthropic OAuth credential (Claude Code subscription)
spark auth add anthropic --type oauth
# Opens browser for OAuth login
```

Check your pools:

```bash
spark auth list
```

Output:
```
openrouter (2 credentials):
  #1  OPENROUTER_API_KEY   api_key env:OPENROUTER_API_KEY <-
  #2  backup-key           api_key manual

anthropic (3 credentials):
  #1  spark_pkce          oauth   spark_pkce <-
  #2  claude_code          oauth   claude_code
  #3  ANTHROPIC_API_KEY    api_key env:ANTHROPIC_API_KEY
```

The `<-` marks the currently active credential.

## Manage Pools Interactively

Run `spark auth` with no arguments for a guided menu:

```bash
spark auth
```

```
What would you like to do?
  1. Add a credential
  2. Remove a credential
  3. Reset cooldowns for a provider
  4. Set rotation strategy for a provider
  5. Exit
```

For providers that support both API keys and OAuth (Anthropic, Spark Portal, Codex), the add flow asks which type you want:

```
anthropic supports both API keys and OAuth login.
  1. API key (paste a key from the provider dashboard)
  2. OAuth login (authenticate via browser)
Type [1/2]:
```

## CLI Reference

| Command | What it does |
|---------|-------------|
| `spark auth` | Interactive pool management wizard |
| `spark auth list` | Show all pools and credentials |
| `spark auth list <provider>` | Show one provider's pool |
| `spark auth add <provider>` | Add a credential interactively |
| `spark auth add <provider> --type api-key --api-key <key>` | Add an API key non-interactively |
| `spark auth add <provider> --type oauth` | Add an OAuth credential via browser |
| `spark auth remove <provider> <index>` | Remove credential by 1-based index |
| `spark auth reset <provider>` | Clear all cooldowns and exhaustion flags |

## Rotation Strategies

Set a strategy via `spark auth` -> "Set rotation strategy", or directly in `config.yaml`:

```yaml
credential_pool_strategies:
  openrouter: round_robin
  anthropic: least_used
```

| Strategy | Behavior |
|----------|----------|
| `fill_first` (default) | Exhaust the first healthy key before moving to the next |
| `round_robin` | Cycle through keys evenly, one at a time |
| `least_used` | Always pick the key with the lowest request count |
| `random` | Random selection among healthy keys |

## Error Recovery

Different errors trigger different behaviors:

| Error | What Spark does | Cooldown |
|-------|----------------|----------|
| **429 Rate Limit** | Retry same key once. Second consecutive 429 rotates to the next key | 1 hour |
| **402 Billing/Quota** | Immediately rotate to the next key | 24 hours |
| **401 Auth Expired** | Try refreshing the OAuth token first. Rotate only if refresh fails | — |
| **All keys exhausted** | Fall through to `fallback_model` if configured | — |

The `has_retried_429` flag resets on every successful API call, so a single transient 429 never triggers rotation.

## Pools for Custom Endpoints

Custom OpenAI-compatible endpoints (Together.ai, RunPod, local servers) get their own pools, keyed by the endpoint name from `custom_providers` in `config.yaml`.

When you set up a custom endpoint via `spark model`, Spark auto-generates a name like "Together.ai" or "Local (localhost:8080)". That name becomes the pool key.

```bash
# After setting up a custom endpoint via spark model:
spark auth list
# Shows:
#   Together.ai (1 credential):
#     #1  config key    api_key config:Together.ai <-

# Add a second key for the same endpoint:
spark auth add Together.ai --api-key sk-together-second-key
```

Custom endpoint pools are stored in `auth.json` under a `custom:` prefix:

```json
{
  "credential_pool": {
    "openrouter": [...],
    "custom:together.ai": [...]
  }
}
```

## Auto-Discovery

Spark seeds pools automatically from multiple sources at startup:

| Source | Example | Auto-seeded? |
|--------|---------|-------------|
| Environment variables | `OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY` | Yes |
| OAuth tokens (auth.json) | Codex device code, Spark Portal device code | Yes |
| Claude Code credentials | `~/.claude/.credentials.json` | Yes (Anthropic) |
| Spark PKCE OAuth | `~/.spark/auth.json` | Yes (Anthropic) |
| Custom endpoint config | `model.api_key` in `config.yaml` | Yes (custom endpoints) |
| Manual entries | Added via `spark auth add` | Persisted in `auth.json` |

Auto-seeded entries update on each pool load — remove an env var and its pool entry is pruned automatically. Manual entries added via `spark auth add` are never auto-pruned.

## Subagent Sharing

When Spark spawns subagents via `delegate_task`, the parent's credential pool is shared automatically:

- **Same provider** — the child gets the parent's full pool, including key rotation
- **Different provider** — the child loads that provider's own pool
- **No pool configured** — the child falls back to the inherited single API key

Subagents get the same rate-limit resilience as the parent with no extra config. Per-task credential leasing prevents concurrent subagents from stepping on each other's keys.

## Thread Safety

The credential pool uses a threading lock for all state mutations (`select()`, `mark_exhausted_and_rotate()`, `try_refresh_current()`, `mark_used()`). Multiple gateway sessions can rotate keys concurrently without conflicts.

## Architecture

For the full data flow diagram, see [`docs/credential-pool-flow.excalidraw`](https://excalidraw.com/#json=2Ycqhqpi6f12E_3ITyiwh,c7u9jSt5BwrmiVzHGbm87g) in the repository.

The pool integrates at the provider resolution layer across four files:

1. **`agent/credential_pool.py`** — Pool manager: storage, selection, rotation, cooldowns
2. **`spark_cli/auth_commands.py`** — CLI commands and interactive wizard
3. **`spark_cli/runtime_provider.py`** — Pool-aware credential resolution
4. **`run_agent.py`** — Error recovery: 429/402/401 -> pool rotation -> fallback

## Storage Format

Pool state lives in `~/.spark/auth.json` under the `credential_pool` key:

```json
{
  "version": 1,
  "credential_pool": {
    "openrouter": [
      {
        "id": "abc123",
        "label": "OPENROUTER_API_KEY",
        "auth_type": "api_key",
        "priority": 0,
        "source": "env:OPENROUTER_API_KEY",
        "access_token": "sk-or-v1-...",
        "last_status": "ok",
        "request_count": 142
      }
    ]
  },
}
```

Rotation strategies live in `config.yaml`, not `auth.json`:

```yaml
credential_pool_strategies:
  openrouter: round_robin
  anthropic: least_used
```
