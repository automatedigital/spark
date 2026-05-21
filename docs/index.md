---
slug: /
sidebar_position: 0
title: "Spark Agent Documentation"
description: "A friendly, terminal-first AI agent with tools, memory, messaging bots, and skills."
hide_table_of_contents: true
---

# Spark Agent

An AI assistant that lives in your terminal — built by [Automate Digital](https://automatedigital.ai). Chat with it, schedule jobs, connect it to messaging apps, extend it with tools and skills. Everything runs from one place, config stored safely in `~/.spark/`.

**[Install Spark →](getting-started/installation.md)** · [5-minute quickstart](getting-started/quickstart.md) · [GitHub](https://github.com/automatedigital/spark)

## Where do you want to go?

| I want to... | Go here |
|---|---|
| Install or update Spark | [Installation](getting-started/installation.md) · [Updating](getting-started/updating.md) |
| Have my first conversation | [Quickstart](getting-started/quickstart.md) |
| Tweak settings | [Configuration](configuration.md) · [Environment variables](reference/environment-variables.md) |
| Learn the CLI | [CLI overview](cli/index.md) · [Profiles](cli/profiles.md) · [Slash commands](cli/slash-commands.md) |
| Connect Telegram, Discord, Slack | [Messaging platforms](chat-platforms/index.md) |
| Add tools or MCP servers | [Tools](tools/index.md) · [MCP](tools/mcp.md) |
| Work with memory and skills | [Memory](memory/index.md) · [Skills](skills/index.md) |
| Use voice input/output | [Voice mode](voice/voice-mode.md) |
| Deploy on a server, cut costs | [Guides](guides/tips-and-tricks.md) · [Deploy to a VPS](guides/deploy-on-a-vps.md) · [Reduce costs](guides/optimize-costs.md) |
| Understand how it works | [Architecture](building/architecture.md) · [FAQ](reference/faq.md) |

## What Spark can do

**Use tools** — Search the web, run terminal commands, read and write files, browse pages, generate images, execute code, and more.

**Remember things** — Notes persist across conversations using the built-in memory store. Connect external providers like [Honcho](https://github.com/plastic-labs/honcho) or Mem0 when you need more.

**Run as a bot** — Connect Spark to Telegram, Discord, Slack, WhatsApp, and [many other platforms](chat-platforms/index.md).

**Automate tasks** — Schedule recurring jobs with [cron](automate/cron.md), run [batch workflows](automate/batch.md), or trigger actions via [hooks](tools/hooks.md).

**Extend with skills** — Install skill packages from [agentskills.io](https://agentskills.io) or build your own right from the CLI.

For the full command and config reference, see [CLI commands](cli/commands-reference.md) or browse the [example `config.yaml`](./cli-config.yaml.example).
