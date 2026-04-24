---
sidebar_position: 0
title: "Providers"
description: "Routing, fallbacks, and API key pools for LLM providers."
---

# Providers

Spark works with multiple OpenAI-compatible backends and gives you fine-grained control over how requests are routed, what happens when a provider fails, and how API keys are managed.

| Topic | What you'll learn |
|-------|------------------|
| [Routing](./routing.md) | Sorting, allow/deny lists, and per-task rules for OpenRouter |
| [Fallback](./fallback.md) | Automatic failover chains when your primary provider errors |
| [Credential pools](./credential-pools.md) | Rotating multiple API keys per provider |

See also: [Configuration](../configuration.md), [Integrations index](../integrations/index.md), [Environment variables](../reference/environment-variables.md).
