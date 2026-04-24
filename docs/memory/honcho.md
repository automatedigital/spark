---
sidebar_position: 99
title: "Honcho Memory"
description: "AI-native persistent memory via Honcho - dialectic reasoning, multi-agent user modeling, and deep personalization"
---

# Honcho Memory

Built-in memory remembers facts. [Honcho](https://github.com/plastic-labs/honcho) understands you.

Honcho is an AI-native memory backend that builds a model of who you are — your preferences, communication style, goals, and patterns — by reasoning about your conversations after they happen. It runs alongside Spark's built-in memory and deepens over time without you doing anything.

:::info Honcho is a Memory Provider Plugin
Honcho plugs into the [Memory Providers](./memory-providers.md) system. Everything below is available through the standard memory provider interface.
:::

## Built-in Memory vs. Honcho

| Capability | Built-in Memory | Honcho |
|-----------|----------------|--------|
| Cross-session persistence | File-based MEMORY.md/USER.md | Server-side with API |
| User profile | Agent curates manually | Automatic dialectic reasoning |
| Multi-agent isolation | — | Per-peer profile separation |
| Observation modes | — | Unified or directional |
| Derived insights | — | Server-side conclusions from patterns |
| History search | FTS5 session search | Semantic search over conclusions |

**Dialectic reasoning** — after each conversation Honcho analyzes the exchange and derives "conclusions": what you prefer, how you work, what you care about. These accumulate and give the agent a deepening understanding that goes beyond what you've explicitly stated.

**Multi-agent profiles** — when multiple Spark instances talk to you (e.g., a coding assistant and a writing assistant), Honcho maintains separate "peer" profiles. Each peer sees only its own observations. No cross-contamination.

## Enable Honcho in Two Steps

```bash
spark memory setup    # select "honcho" from the provider list
```

Or manually:

```yaml
# ~/.spark/config.yaml
memory:
  provider: honcho
```

```bash
echo "HONCHO_API_KEY=your-key" >> ~/.spark/.env
```

Get an API key at [honcho.dev](https://honcho.dev).

## Configuration

```yaml
# ~/.spark/config.yaml
honcho:
  observation: directional    # "unified" or "directional"
  peer_name: ""               # auto-detected from platform, or set manually
```

| Option | Values | When to use |
|--------|--------|-------------|
| `unified` | All observations in one pool | Single-agent setups, simpler |
| `directional` | Tagged by direction (user→agent, agent→user) | Richer analysis, multi-agent |

## Tools Honcho Adds

When Honcho is your active memory provider, four new tools become available to the agent:

| Tool | What it does |
|------|-------------|
| `honcho_conclude` | Trigger server-side dialectic reasoning on recent conversations |
| `honcho_context` | Pull relevant context from Honcho for the current conversation |
| `honcho_profile` | View or update your Honcho profile |
| `honcho_search` | Semantic search across all stored conclusions and observations |

## CLI Commands

```bash
spark honcho status          # Check connection and show current config
spark honcho peer            # Update peer names for multi-agent setups
```

## Already Used `spark honcho` Before?

If you previously set up via `spark honcho setup`, nothing is lost:

1. Your existing config (`honcho.json` or `~/.honcho/config.json`) is preserved
2. All server-side data — memories, conclusions, user profiles — is intact
3. Just set `memory.provider: honcho` in `config.yaml` to reactivate

No re-login or re-setup required. Run `spark memory setup`, select "honcho", and the wizard detects your existing config automatically.

## Full Reference

See [Memory Providers — Honcho](./memory-providers.md#honcho) for the complete configuration reference.
