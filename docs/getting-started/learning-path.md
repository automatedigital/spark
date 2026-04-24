---
sidebar_position: 3
title: 'Learning Path'
description: 'Not sure where to start? Find the right path based on your experience level and goals.'
---

# Learning Path

Spark does a lot: CLI assistant, Telegram/Discord bot, scheduled automation, RL training, Python library, and more. This page cuts straight to what you need based on your goal.

:::tip Haven't installed yet?
Start with [Installation](/docs/getting-started/installation) then [Quickstart](/docs/getting-started/quickstart). Everything below assumes Spark is installed and working.
:::

## Pick your path by goal

### I want a coding assistant in my terminal

Chat with Spark, drop in files and directories, ask it to write, review, and run code — all from the command line.

1. [Installation](/docs/getting-started/installation)
2. [Quickstart](/docs/getting-started/quickstart)
3. [CLI Usage](/docs/cli)
4. [Code Execution](/docs/tools/code-execution)
5. [Context Files](/docs/tools/context-files)
6. [Tips & Tricks](/docs/guides/tips-and-tricks)

:::tip
Drag files and directories directly into the conversation. Spark reads, edits, and runs code across your whole project.
:::

### I want to run a Telegram or Discord bot

Deploy Spark as a bot on your messaging platform.

1. [Installation](/docs/getting-started/installation)
2. [Configuration](/docs/configuration)
3. [Messaging Overview](/docs/chat-platforms)
4. [Telegram Setup](/docs/chat-platforms/telegram)
5. [Discord Setup](/docs/chat-platforms/discord)
6. [Voice Mode](/docs/voice/voice-mode)
7. [Enabling Voice Mode](/docs/guides/enable-voice-mode)

Real-world examples: [Daily Briefing Bot](/docs/guides/daily-briefing-bot) · [Team Telegram Assistant](/docs/guides/team-telegram-assistant)

### I want to automate recurring tasks

Schedule jobs, run batch workflows, chain agent actions.

1. [Quickstart](/docs/getting-started/quickstart)
2. [Cron Scheduling](/docs/automate/cron)
3. [Batch Processing](/docs/automate/batch)
4. [Delegation](/docs/tools/delegation)
5. [Hooks](/docs/tools/hooks)

:::tip
Set up cron jobs by asking Spark in chat. Daily summaries, periodic checks, automated reports — no cron syntax required.
:::

### I want to build my own tools or skills

Extend Spark with custom tools and reusable skill packages.

1. [Tools Overview](/docs/tools)
2. [Skills Overview](/docs/skills)
3. [MCP (Model Context Protocol)](/docs/tools/mcp)
4. [Architecture](/docs/building/architecture)
5. [Adding Tools](/docs/building/adding-tools)
6. [Creating Skills](/docs/building/creating-skills)

:::tip
**Tools** are individual functions Spark can call. **Skills** are bundles of tools, prompts, and config packaged together. Build a tool first, then graduate to a skill when you want to share or reuse it.
:::

### I want to train models with RL

Use Spark's built-in reinforcement learning pipeline to fine-tune model behavior.

1. [Quickstart](/docs/getting-started/quickstart)
2. [Configuration](/docs/configuration)
3. [RL Training](/docs/automate/model-training)
4. [Provider Routing](/docs/providers/routing)
5. [Architecture](/docs/building/architecture)

:::tip
RL training is much easier once you understand how Spark handles conversations and tool calls. If you're new, go through the Beginner path first.
:::

### I want to embed Spark in a Python app

Use Spark as a library inside your own code.

1. [Installation](/docs/getting-started/installation)
2. [Quickstart](/docs/getting-started/quickstart)
3. [Python Library Guide](/docs/guides/use-python-library)
4. [Architecture](/docs/building/architecture)
5. [Tools](/docs/tools)
6. [Sessions](/docs/sessions)

## By experience level

| Level | Goal | Read these | Time |
|---|---|---|---|
| **Beginner** | Get running, have basic conversations, use built-in tools | [Installation](/docs/getting-started/installation) → [Quickstart](/docs/getting-started/quickstart) → [CLI Usage](/docs/cli) → [Configuration](/docs/configuration) | ~1 hour |
| **Intermediate** | Bots, memory, scheduled tasks, skills | [Sessions](/docs/sessions) → [Messaging](/docs/chat-platforms) → [Tools](/docs/tools) → [Skills](/docs/skills) → [Memory](/docs/memory) → [Cron](/docs/automate/cron) | ~2–3 hours |
| **Advanced** | Custom tools, skill packages, RL training | [Architecture](/docs/building/architecture) → [Adding Tools](/docs/building/adding-tools) → [Creating Skills](/docs/building/creating-skills) → [RL Training](/docs/automate/model-training) | ~4–6 hours |

## What Spark can do — at a glance

| Feature | What it gives you | Docs |
|---|---|---|
| **Tools** | Built-in tools the agent calls (file I/O, search, shell, etc.) | [Tools](/docs/tools) |
| **Skills** | Installable packages that add new capabilities | [Skills](/docs/skills) |
| **Memory** | Notes that persist across sessions | [Memory](/docs/memory) |
| **Context Files** | Feed files and directories into conversations | [Context Files](/docs/tools/context-files) |
| **MCP** | Connect to external tool servers | [MCP](/docs/tools/mcp) |
| **Cron** | Schedule recurring agent tasks | [Cron](/docs/automate/cron) |
| **Delegation** | Spawn sub-agents for parallel work | [Delegation](/docs/tools/delegation) |
| **Code Execution** | Run code in sandboxed environments | [Code Execution](/docs/tools/code-execution) |
| **Browser** | Web browsing and scraping | [Browser](/docs/tools/browser) |
| **Hooks** | Event-driven callbacks and middleware | [Hooks](/docs/tools/hooks) |
| **Batch Processing** | Process multiple inputs in bulk | [Batch Processing](/docs/automate/batch) |
| **RL Training** | Fine-tune models with reinforcement learning | [RL Training](/docs/automate/model-training) |
| **Provider Routing** | Route requests across multiple LLM providers | [Provider Routing](/docs/providers/routing) |

## What to read next

- **Just finished installing?** → [Quickstart](/docs/getting-started/quickstart)
- **Done with the Quickstart?** → [CLI Usage](/docs/cli) and [Configuration](/docs/configuration)
- **Comfortable with the basics?** → [Tools](/docs/tools), [Skills](/docs/skills), [Memory](/docs/memory)
- **Setting up for a team?** → [Sessions](/docs/sessions)
- **Ready to build?** → [Developer Guide](/docs/building/architecture) and [Adding Tools](/docs/building/adding-tools)
- **Want real examples?** → [Guides](/docs/guides/tips-and-tricks)
