---
title: Provider Routing
description: Configure OpenRouter provider preferences to optimize for cost, speed, or quality.
sidebar_label: Provider Routing
sidebar_position: 7
---

# Provider Routing

OpenRouter routes your requests to many underlying providers — Anthropic, Google, AWS Bedrock, Together AI, and more. Provider routing gives you control over which of those providers handles each request and how they're ranked.

Use it to cut costs, reduce latency, enforce data privacy requirements, or lock to a specific provider for consistency.

:::info
Provider routing only applies when using OpenRouter. It has no effect when you connect directly to a provider like the Anthropic API.
:::

## Configure It

Add a `provider_routing` section to `~/.spark/config.yaml`:

```yaml
provider_routing:
  sort: "price"           # How to rank providers
  only: []                # Allow list: only use these providers
  ignore: []              # Block list: never use these providers
  order: []               # Explicit priority order
  require_parameters: false  # Only use providers that support all request parameters
  data_collection: null   # Control data collection ("allow" or "deny")
```

## Options

### `sort` — Pick your ranking

| Value | Ranks by |
|-------|---------|
| `"price"` | Cheapest provider first |
| `"throughput"` | Fastest tokens-per-second first |
| `"latency"` | Lowest time-to-first-token first |

```yaml
provider_routing:
  sort: "price"
```

### `only` — Allow list

Only route to the providers you list. Everything else is excluded.

```yaml
provider_routing:
  only:
    - "Anthropic"
    - "Google"
```

### `ignore` — Block list

Never use the providers you list, even if they're the cheapest or fastest.

```yaml
provider_routing:
  ignore:
    - "Together"
    - "DeepInfra"
```

### `order` — Explicit priority

List providers in preference order. Unlisted providers are used as fallbacks.

```yaml
provider_routing:
  order:
    - "Anthropic"
    - "Google"
    - "AWS Bedrock"
```

### `require_parameters` — Prevent silent drops

When `true`, OpenRouter only routes to providers that support every parameter in your request (`temperature`, `top_p`, `tools`, etc.). Avoids cases where a provider silently ignores parameters.

```yaml
provider_routing:
  require_parameters: true
```

### `data_collection` — Control training data opt-out

Set to `"deny"` to prevent providers from using your prompts for training.

```yaml
provider_routing:
  data_collection: "deny"
```

## Practical Examples

### Cut costs

```yaml
provider_routing:
  sort: "price"
```

### Speed up interactive use

```yaml
provider_routing:
  sort: "latency"
```

### Maximize throughput for long generations

```yaml
provider_routing:
  sort: "throughput"
```

### Lock to a specific provider

```yaml
provider_routing:
  only:
    - "Anthropic"
```

### Block providers for data privacy

```yaml
provider_routing:
  ignore:
    - "Together"
    - "Lepton"
  data_collection: "deny"
```

### Prefer specific providers with fallbacks

```yaml
provider_routing:
  order:
    - "Anthropic"
    - "Google"
  require_parameters: true
```

### Combine multiple options

Options stack — you can sort by price while blocking certain providers and requiring parameter support:

```yaml
provider_routing:
  sort: "price"
  ignore: ["Together"]
  require_parameters: true
  data_collection: "deny"
```

## How It Works

Routing preferences pass to the OpenRouter API via the `extra_body.provider` field on every API call. This works the same in both CLI mode and gateway mode — the same `config.yaml` drives both.

The config keys map to these `AIAgent` parameters:

```
providers_allowed  <- from provider_routing.only
providers_ignored  <- from provider_routing.ignore
providers_order    <- from provider_routing.order
provider_sort      <- from provider_routing.sort
provider_require_parameters <- from provider_routing.require_parameters
provider_data_collection    <- from provider_routing.data_collection
```

## Default Behavior

Without a `provider_routing` section, OpenRouter uses its own default routing logic — generally a balance of cost and availability. You don't need to configure anything to get started.

:::tip Provider Routing vs. Fallback Models
Provider routing controls which sub-providers *within OpenRouter* handle your requests. For automatic failover to an entirely different provider when your primary model fails, see [Fallback Providers](fallback.md).
:::
