---
sidebar_position: 1
title: "Quickstart"
description: "Get Spark up and running in a few minutes."
---

# Quickstart

Five minutes to your first conversation. Here's the shortest path.

## Step 1 — Install

```bash
curl -fsSL https://raw.githubusercontent.com/automatedigital/spark/main/scripts/install.sh | bash
source ~/.bashrc   # or ~/.zshrc
```

> On Windows? Use [WSL2](https://learn.microsoft.com/en-us/windows/wsl/install). Native Windows isn't supported. See [Installation](./installation.md) for more detail.

## Step 2 — Connect an AI provider

```bash
spark model    # pick a provider and model
spark doctor   # confirm keys and dependencies are good
```

## Step 3 — Start chatting

```bash
spark
```

You're in. Try asking it to write a script, or explore with:

- `/tools` — see what's available
- `/help` — browse commands
- `/model` — switch models mid-session

**Handy shortcuts:**
- `Alt+Enter` or `Ctrl+J` — new line (multiline input)
- Type a message while it's running — interrupts the current response
- `Ctrl+C` — stops immediately
- `spark --continue` (or `spark -c`) — resume where you left off next time

## Step 4 — Go further

Pick what sounds useful and follow the link:

| Goal | How to get there |
|------|----------------|
| Run terminal commands in a sandbox | `spark config set terminal.backend docker` (or `ssh`) — [Configuration](../configuration.md) |
| Connect to Telegram, Discord, etc. | `spark gateway setup` — [Messaging](../chat-platforms/index.md) |
| Talk to Spark with your voice | `pip install "spark-agent[voice]"` then `/voice on` — [Voice](../voice/voice-mode.md) |
| Schedule recurring tasks | Ask Spark in chat to set one up — [Cron](../automate/cron.md) |
| Add new skills | `spark skills search …` or `/skills` — [Skills](../skills/index.md) |
| Use Spark inside your code editor | `pip install -e '.[acp]'` then `spark acp` — [ACP](../integrations/acp.md) |
| Connect to external tool servers (MCP) | Add `mcp_servers:` to your config — [MCP](../tools/mcp.md) |

## Essential commands

| Command | What it does |
|---------|---------|
| `spark` | Open the chat interface |
| `spark setup` | Walk through full configuration |
| `spark tools` | Manage which toolsets are active |
| `spark gateway` | Set up messaging platform connections |
| `spark update` | Update to the latest version |

**Keep going:** [CLI overview](../cli/index.md) · [Configuration](../configuration.md) · [Learning path](./learning-path.md)
