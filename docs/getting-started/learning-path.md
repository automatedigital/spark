---
sidebar_position: 3
title: 'Learning Path'
description: 'Not sure where to start? Find the right path based on your experience level and goals.'
---

# Learning Path

Spark does a lot: CLI assistant, Telegram/Discord bot, scheduled automation, RL training, Python library, and more. This page cuts straight to what you need based on your goal.

:::tip Haven't installed yet?
Start with [Installation](installation.md) then [Quickstart](quickstart.md). Everything below assumes Spark is installed and working.
:::

## Pick your path by goal

### I want a coding assistant in my terminal

Chat with Spark, drop in files and directories, ask it to write, review, and run code — all from the command line.

1. [Installation](installation.md)
2. [Quickstart](quickstart.md)
3. [CLI Usage](../cli/index.md)
4. [Code Execution](../tools/code-execution.md)
5. [Context Files](../tools/context-files.md)
6. [Tips & Tricks](../guides/tips-and-tricks.md)

:::tip
Drag files and directories directly into the conversation. Spark reads, edits, and runs code across your whole project.
:::

### I want to run a Telegram or Discord bot

Deploy Spark as a bot on your messaging platform.

1. [Installation](installation.md)
2. [Configuration](../configuration.md)
3. [Messaging Overview](../chat-platforms/index.md)
4. [Telegram Setup](../chat-platforms/telegram.md)
5. [Discord Setup](../chat-platforms/discord.md)
6. [Voice Mode](../voice/voice-mode.md)
7. [Enabling Voice Mode](../guides/enable-voice-mode.md)

Real-world examples: [Daily Briefing Bot](../guides/daily-briefing-bot.md) · [Team Telegram Assistant](../guides/team-telegram-assistant.md)

### I want to automate recurring tasks

Schedule jobs, run batch workflows, chain agent actions.

1. [Quickstart](quickstart.md)
2. [Cron Scheduling](../automate/cron.md)
3. [Batch Processing](../automate/batch.md)
4. [Delegation](../tools/delegation.md)
5. [Hooks](../tools/hooks.md)

:::tip
Set up cron jobs by asking Spark in chat. Daily summaries, periodic checks, automated reports — no cron syntax required.
:::

### I want to build my own tools or skills

Extend Spark with custom tools and reusable skill packages.

1. [Tools Overview](../tools/index.md)
2. [Skills Overview](../skills/index.md)
3. [MCP (Model Context Protocol)](../tools/mcp.md)
4. [Architecture](../building/architecture.md)
5. [Adding Tools](../building/adding-tools.md)
6. [Creating Skills](../building/creating-skills.md)

:::tip
**Tools** are individual functions Spark can call. **Skills** are bundles of tools, prompts, and config packaged together. Build a tool first, then graduate to a skill when you want to share or reuse it.
:::

### I want to train models with RL

Use Spark's built-in reinforcement learning pipeline to fine-tune model behavior.

1. [Quickstart](quickstart.md)
2. [Configuration](../configuration.md)
3. [RL Training](../automate/model-training.md)
4. [Provider Routing](../providers/routing.md)
5. [Architecture](../building/architecture.md)

:::tip
RL training is much easier once you understand how Spark handles conversations and tool calls. If you're new, go through the Beginner path first.
:::

### I want to embed Spark in a Python app

Use Spark as a library inside your own code.

1. [Installation](installation.md)
2. [Quickstart](quickstart.md)
3. [Python Library Guide](../guides/use-python-library.md)
4. [Architecture](../building/architecture.md)
5. [Tools](../tools/index.md)
6. [Sessions](../sessions.md)

## By experience level

| Level | Goal | Read these | Time |
|---|---|---|---|
| **Beginner** | Get running, have basic conversations, use built-in tools | [Installation](installation.md) → [Quickstart](quickstart.md) → [CLI Usage](../cli/index.md) → [Configuration](../configuration.md) | ~1 hour |
| **Intermediate** | Bots, memory, scheduled tasks, skills | [Sessions](../sessions.md) → [Messaging](../chat-platforms/index.md) → [Tools](../tools/index.md) → [Skills](../skills/index.md) → [Memory](../memory/index.md) → [Cron](../automate/cron.md) | ~2–3 hours |
| **Advanced** | Custom tools, skill packages, RL training | [Architecture](../building/architecture.md) → [Adding Tools](../building/adding-tools.md) → [Creating Skills](../building/creating-skills.md) → [RL Training](../automate/model-training.md) | ~4–6 hours |

## What Spark can do — at a glance

| Feature | What it gives you | Docs |
|---|---|---|
| **Tools** | Built-in tools the agent calls (file I/O, search, shell, etc.) | [Tools](../tools/index.md) |
| **Skills** | Installable packages that add new capabilities | [Skills](../skills/index.md) |
| **Memory** | Notes that persist across sessions | [Memory](../memory/index.md) |
| **Context Files** | Feed files and directories into conversations | [Context Files](../tools/context-files.md) |
| **MCP** | Connect to external tool servers | [MCP](../tools/mcp.md) |
| **Cron** | Schedule recurring agent tasks | [Cron](../automate/cron.md) |
| **Delegation** | Spawn sub-agents for parallel work | [Delegation](../tools/delegation.md) |
| **Code Execution** | Run code in sandboxed environments | [Code Execution](../tools/code-execution.md) |
| **Browser** | Web browsing and scraping | [Browser](../tools/browser.md) |
| **Hooks** | Event-driven callbacks and middleware | [Hooks](../tools/hooks.md) |
| **Batch Processing** | Process multiple inputs in bulk | [Batch Processing](../automate/batch.md) |
| **RL Training** | Fine-tune models with reinforcement learning | [RL Training](../automate/model-training.md) |
| **Provider Routing** | Route requests across multiple LLM providers | [Provider Routing](../providers/routing.md) |

## What to read next

- **Just finished installing?** → [Quickstart](quickstart.md)
- **Done with the Quickstart?** → [CLI Usage](../cli/index.md) and [Configuration](../configuration.md)
- **Comfortable with the basics?** → [Tools](../tools/index.md), [Skills](../skills/index.md), [Memory](../memory/index.md)
- **Setting up for a team?** → [Sessions](../sessions.md)
- **Ready to build?** → [Developer Guide](../building/architecture.md) and [Adding Tools](../building/adding-tools.md)
- **Want real examples?** → [Guides](../guides/tips-and-tricks.md)
