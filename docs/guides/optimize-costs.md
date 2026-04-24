---
sidebar_position: 25
title: "Optimize Costs"
description: "Reduce spend: caching, routing, batch, and model choice."
---

# Cut Your Spark Costs

A few targeted changes make a big difference. Start with prompt caching — it's the highest-leverage lever and requires no extra setup if you're not already breaking it.

---

## The five levers

### 1. Protect the prompt cache

Most providers cache the system prompt prefix. A cache hit costs a fraction of a cache miss. Spark preserves this automatically — but you can break it by accident.

What breaks the cache mid-session:
- Switching models
- Modifying toolsets
- Rebuilding the system prompt

Leave these alone during a session. See [context compression](/docs/building/context-compression-and-caching) for the full picture.

### 2. Route to cheaper models for easy work

Not every task needs your most capable model. [Provider routing](/docs/providers/routing) and [fallbacks](/docs/providers/fallback) let you send simple steps to cheaper models automatically.

### 3. Batch instead of one-off runs

[Batch processing](/docs/automate/batch) amortizes setup cost across many prompts. Tune your parallelism against your rate limits — running too many workers simultaneously just triggers retries, which costs more.

### 4. Rotate credential pools to avoid retry waste

A key that hits its rate limit triggers retries. [Rotating keys](/docs/providers/credential-pools) spreads load and avoids the hard failures that silently inflate your token usage.

### 5. Point auxiliary tasks at smaller models

Vision analysis and summarization rarely need your frontier model. Point these at smaller, cheaper options in `~/.spark/config.yaml`.

---

## Two habits worth building

**Keep prompts short.** Put stable instructions in `AGENTS.md` or `SOUL.md` files once, not repeated every turn. The agent loads them automatically — you don't pay to resend them as messages.

**Delegate strategically.** Spawning subagents via `delegate_task` adds inference overhead. Use it when parallel execution actually saves wall-clock time. Skip it for tasks that are naturally sequential.

---

## See also

- [Configuration](/docs/configuration)
- [Environment variables](/docs/reference/environment-variables)
