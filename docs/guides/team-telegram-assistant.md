---
sidebar_position: 4
title: "Tutorial: Team Telegram Assistant"
description: "Step-by-step guide to setting up a Telegram bot that your whole team can use for code help, research, system admin, and more"
---

# Set Up a Team Telegram Assistant

By the end of this tutorial, your team will have a shared AI assistant they can DM directly — code reviews, debugging, shell commands, research, whatever they need — secured so only approved users can interact.

## What You're Building

A Telegram bot that:

- **Any authorized team member** can DM — code reviews, research, shell commands, debugging
- **Runs on your server** with full tool access — terminal, file editing, web search, code execution
- **Gives each person their own session** — separate conversation context per user
- **Blocks unauthorized access by default** — only approved users get responses
- **Handles scheduled tasks** — daily standups, health checks, reminders to a team channel

---

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| Spark Agent on a server or VPS | Not your laptop — the bot needs to stay running. [Installation guide](../getting-started/installation.md) |
| A Telegram account | You'll be the bot owner |
| An LLM provider key | OpenAI, Anthropic, or another supported provider in `~/.spark/.env` |

:::tip
A $5/month VPS is plenty. Spark is lightweight — the LLM API calls happen remotely and that's where the cost is.
:::

---

## Step 1: Create a Telegram Bot

Every Telegram bot starts with **@BotFather**.

1. Open Telegram and find [@BotFather](https://t.me/BotFather).

2. Send `/newbot`. BotFather asks two questions:
   - **Display name** — what users see (e.g., `Team Spark Assistant`)
   - **Username** — must end in `bot` (e.g., `myteam_spark_bot`)

3. Copy the bot token from BotFather's reply:
   ```
   Use this token to access the HTTP API:
   7123456789:AAH1bGciOiJSUzI1NiIsInR5cCI6Ikp...
   ```

4. Set a description (optional but helps teammates know what the bot does):
   ```
   /setdescription
   ```
   Something like: `Team AI assistant powered by Spark Agent. DM me for code help, research, debugging, and more.`

5. Set bot commands (gives users a menu):
   ```
   /setcommands
   ```
   Paste:
   ```
   new - Start a fresh conversation
   model - Show or change the AI model
   status - Show session info
   help - Show available commands
   stop - Stop the current task
   ```

:::warning
Keep your bot token secret. Anyone with it controls the bot. If it leaks, use `/revoke` in BotFather to generate a new one.
:::

---

## Step 2: Configure the Gateway

### Option A: Interactive Setup (Recommended)

```bash
spark gateway setup
```

Arrow-key through the prompts. Pick Telegram, paste your bot token, and enter your user ID.

### Option B: Manual Configuration

Add to `~/.spark/.env`:

```bash
# Telegram bot token from BotFather
TELEGRAM_BOT_TOKEN=7123456789:AAH1bGciOiJSUzI1NiIsInR5cCI6Ikp...

# Your Telegram user ID (numeric)
TELEGRAM_ALLOWED_USERS=123456789
```

### Find Your User ID

Your Telegram user ID is a permanent number, not your `@username`. Get it by messaging [@userinfobot](https://t.me/userinfobot) — it replies instantly with your numeric ID.

:::info
Always use the numeric ID for allowlists. Usernames can change; numeric IDs never do.
:::

---

## Step 3: Start the Gateway

### Quick Test First

Run the gateway in the foreground to confirm everything works:

```bash
spark gateway
```

You should see:

```
[Gateway] Starting Spark Gateway...
[Gateway] Telegram adapter connected
[Gateway] Cron scheduler started (tick every 60s)
```

Open Telegram, find your bot, send a message. If it replies, you're good. Press `Ctrl+C` to stop.

### Install as a Persistent Service

For a deployment that survives reboots:

```bash
spark gateway install
sudo spark gateway install --system   # Linux only: boot-time system service
```

This creates a background service — systemd on Linux, launchd on macOS.

```bash
# Linux — manage the user service
spark gateway start
spark gateway stop
spark gateway status

# Watch live logs
journalctl --user -u spark-gateway -f

# Keep running after SSH logout
sudo loginctl enable-linger $USER

# Linux servers — system service
sudo spark gateway start --system
sudo spark gateway status --system
journalctl -u spark-gateway -f
```

```bash
# macOS
spark gateway start
spark gateway stop
tail -f ~/.spark/logs/gateway.log
```

:::tip macOS PATH
The launchd plist captures your shell PATH at install time. If you install new tools later (Node.js, ffmpeg, etc.), re-run `spark gateway install` to pick them up.
:::

### Verify It's Running

```bash
spark gateway status
```

Then send a test message on Telegram. You should get a response within a few seconds.

---

## Step 4: Set Up Team Access

Two approaches. Pick one.

### Approach A: Static Allowlist

Collect each teammate's numeric Telegram user ID (they can get it from [@userinfobot](https://t.me/userinfobot)) and add them comma-separated:

```bash
# In ~/.spark/.env
TELEGRAM_ALLOWED_USERS=123456789,987654321,555555555
```

Restart after any changes:

```bash
spark gateway stop && spark gateway start
```

### Approach B: DM Pairing (Recommended for Teams)

No need to collect IDs upfront. Here's the flow:

1. **Teammate DMs the bot** — since they're not on the allowlist, the bot replies with a pairing code:
   ```
    Pairing code: XKGH5N7P
   Send this code to the bot owner for approval.
   ```

2. **Teammate sends you the code** (Slack, email, in person — any channel works)

3. **You approve it** on the server:
   ```bash
   spark pairing approve telegram XKGH5N7P
   ```

4. **They're in** — the bot starts responding immediately

**Manage paired users:**

```bash
spark pairing list                          # See all pending and approved users
spark pairing revoke telegram 987654321     # Revoke access
spark pairing clear-pending                 # Clear expired codes
```

:::tip
DM pairing works without restarting the gateway. Approvals take effect immediately.
:::

### Security Notes

- **Never set `GATEWAY_ALLOW_ALL_USERS=true`** on a bot with terminal access — anyone who finds your bot could run commands on your server
- Pairing codes expire after **1 hour** and use cryptographic randomness
- Rate limiting kicks in at 1 request per user per 10 minutes, max 3 pending codes per platform
- After 5 failed approval attempts, the platform enters a 1-hour lockout
- All pairing data is stored with `chmod 0600` permissions

---

## Step 5: Configure the Bot

### Set a Home Channel

A home channel is where scheduled task results and proactive messages get delivered. Without one, cron jobs have nowhere to send output.

**Option 1:** Use `/sethome` in any Telegram group or chat where the bot is a member.

**Option 2:** Set it manually in `~/.spark/.env`:

```bash
TELEGRAM_HOME_CHANNEL=-1001234567890
TELEGRAM_HOME_CHANNEL_NAME="Team Updates"
```

To find a group's chat ID, add [@userinfobot](https://t.me/userinfobot) to the group — it reports the group's ID.

### Control Tool Progress Display

In `~/.spark/config.yaml`:

```yaml
display:
  tool_progress: new    # off | new | all | verbose
```

| Mode | What You See |
|------|-------------|
| `off` | Clean responses only — no tool activity shown |
| `new` | Brief status for each new tool call (recommended for messaging) |
| `all` | Every tool call with details |
| `verbose` | Full tool output including command results |

Users can change this per-session with `/verbose`.

### Give the Bot a Personality

Edit `~/.spark/SOUL.md` to customize how the bot communicates:

```markdown
# Soul
You are a helpful team assistant. Be concise and technical.
Use code blocks for any code. Skip pleasantries - the team
values directness. When debugging, always ask for error logs
before guessing at solutions.
```

For a full walkthrough, see [Use SOUL.md with Spark](define-personality-with-soul.md).

### Add Project Context

Let the bot know your stack by creating an `AGENTS.md`:

```markdown
<!-- ~/.spark/AGENTS.md -->
# Team Context
- We use Python 3.12 with FastAPI and SQLAlchemy
- Frontend is React with TypeScript
- Tests and lint must pass before merge
- Production deploys to AWS ECS
- Always suggest writing tests for new code
```

:::info
Context files are injected into every session's system prompt. Keep them concise — every character counts against your token budget.
:::

---

## Step 6: Schedule Team Tasks

With the gateway running, you can deliver recurring reports straight to your team channel.

### Daily Standup Summary

Message the bot on Telegram:

```
Every weekday at 9am, check the GitHub repository at
github.com/myorg/myproject for:
1. Pull requests opened/merged in the last 24 hours
2. Issues created or closed
3. Any failing checks or broken builds on the main branch
Format as a brief standup-style summary.
```

The agent creates a cron job and delivers results to your chat (or the home channel).

### Server Health Check

```
Every 6 hours, check disk usage with 'df -h', memory with 'free -h',
and Docker container status with 'docker ps'. Report anything unusual -
partitions above 80%, containers that have restarted, or high memory usage.
```

### Manage Scheduled Jobs

```bash
# From the CLI
spark cron list          # View all scheduled jobs
spark cron status        # Check if scheduler is running

# From Telegram chat
/cron list                # View jobs
/cron remove <job_id>     # Remove a job
```

:::warning
Cron prompts run in completely fresh sessions — no memory of previous conversations. Write each prompt with **all** the context the agent needs: file paths, URLs, server addresses, clear instructions.
:::

---

## Production Tips

### Use Docker for Safety

On a shared bot, run agent commands inside a container so they can't touch your host:

```bash
# In ~/.spark/.env
TERMINAL_BACKEND=docker
TERMINAL_DOCKER_IMAGE=nikolaik/python-nodejs:python3.11-nodejs20
```

Or in `~/.spark/config.yaml`:

```yaml
terminal:
  backend: docker
  container_cpu: 1
  container_memory: 5120
  container_persistent: true
```

Even if someone asks the bot to run something destructive, your host is protected.

### Monitor the Gateway

```bash
spark gateway status

# Live logs on Linux
journalctl --user -u spark-gateway -f

# Live logs on macOS
tail -f ~/.spark/logs/gateway.log
```

### Keep Spark Updated

From Telegram, send `/update` — the bot pulls the latest version and restarts. Or from the server:

```bash
spark update
spark gateway stop && spark gateway start
```

### Log Locations

| What | Location |
|------|----------|
| Gateway logs | `journalctl --user -u spark-gateway` (Linux) or `~/.spark/logs/gateway.log` (macOS) |
| Cron job output | `~/.spark/cron/output/{job_id}/{timestamp}.md` |
| Cron job definitions | `~/.spark/cron/jobs.json` |
| Pairing data | `~/.spark/pairing/` |
| Session history | `~/.spark/sessions/` |

---

## What's Next

- **[Messaging Gateway](../chat-platforms/index.md)** — gateway architecture, session management, chat commands
- **[Telegram Setup](../chat-platforms/telegram.md)** — platform details including voice messages and TTS
- **[Scheduled Tasks](../automate/cron.md)** — advanced cron scheduling, delivery options, expressions
- **[Context Files](../tools/context-files.md)** — AGENTS.md, SOUL.md, and .cursorrules
- **[Personality](../personality.md)** — built-in presets and custom persona definitions
- **Add more platforms** — the same gateway can simultaneously run [Discord](../chat-platforms/discord.md), [Slack](../chat-platforms/slack.md), and [WhatsApp](../chat-platforms/whatsapp.md)

---

*Questions or issues? Open an issue on GitHub.*
