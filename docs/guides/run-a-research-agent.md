---
sidebar_position: 22
title: "Run a Research Agent"
description: "Long-running research: batch jobs, cron, and memory."
---

# Run a Research Agent That Works While You Sleep

Combine [batch processing](../automate/batch.md), [cron](../automate/cron.md), and [memory](../memory/index.md) and Spark keeps making progress across sessions — even when you're not at the keyboard.

---

## The three-piece pattern

| Piece | What it gives you |
|-------|------------------|
| **Batch** | Run many prompts in parallel — good for evals, dataset generation, and bulk research sweeps |
| **Cron** | Schedule recurring prompts — daily digests, monitors, summaries — delivered to a channel |
| **Memory** | `MEMORY.md` and memory providers let later runs pick up where earlier ones left off |

Each piece is useful alone. Combined, they produce a research loop that persists beyond any single session.

---

## Cron requires a running gateway

Cron ticks go nowhere without an active [gateway](../chat-platforms/index.md). Start it before scheduling jobs:

```bash
spark gateway start
```

Or install it as a persistent service so it survives reboots. Either way, the gateway must be running when the scheduled time arrives, or the tick fires into nothing.

---

## Batch: many prompts at once

Use the batch runner for your version of Spark. Point it at a file of prompts, capture outputs into your profile's data directory. Each prompt runs in its own isolated agent context, so failures in one don't affect others.

---

## Make every scheduled prompt self-contained

Cron jobs start with a **fresh agent context** — no memory of previous conversations. Everything the agent needs must live in the prompt itself: goals, file paths, URLs, constraints, output format.

A vague cron prompt produces vague (or failed) output. A good one reads like a complete brief.

See [Automate with cron](automate-with-cron.md) for examples of well-constructed scheduled prompts.

---

## See also

- [Delegation](../tools/delegation.md)
- [Optimize costs](optimize-costs.md)
