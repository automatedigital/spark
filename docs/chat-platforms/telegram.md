---
sidebar_position: 1
title: "Telegram"
description: "Set up Spark Agent as a Telegram bot"
---

# Telegram Setup

Connect Spark to Telegram and you get a full-featured AI assistant on every device you own. Send voice memos that auto-transcribe, receive scheduled task results, use the agent in group chats, and switch models with a tap. The integration runs on [python-telegram-bot](https://python-telegram-bot.org/) and supports text, voice, images, and files.

## Before You Start

You need two things: a bot token from BotFather, and your numeric Telegram user ID.

## Step 1: Create a Bot via BotFather

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot`
3. Pick a display name (e.g., "Spark Agent") — anything works
4. Pick a username — must be unique and end in `bot` (e.g., `my_spark_bot`)
5. BotFather hands you a token that looks like:

```
123456789:ABCdefGHIjklMNOpqrSTUvwxYZ
```

:::warning
Keep your bot token secret. Anyone with it controls your bot. If it leaks, revoke it immediately via `/revoke` in BotFather.
:::

## Step 2: Find Your User ID

Spark identifies you by numeric user ID, not username. Message [@userinfobot](https://t.me/userinfobot) — it replies instantly with your ID. Save that number.

## Step 3: Optional — Polish Your Bot

These BotFather commands improve the experience. None are required, but they help users understand your bot:

| Command | What it does |
|---------|---------|
| `/setdescription` | "What can this bot do?" text shown before first message |
| `/setabouttext` | Short text on the bot's profile page |
| `/setuserpic` | Upload an avatar |
| `/setcommands` | Define the `/` command menu |
| `/setprivacy` | Control group message visibility |

:::tip
A minimal `/setcommands` starter set:

```
help - Show help information
new - Start a new conversation
sethome - Set this chat as the home channel
```
:::

## Step 4: Configure Spark

### Interactive Setup (Recommended)

```bash
spark gateway setup
```

Select **Telegram**. The wizard asks for your bot token and allowed user IDs, then writes everything for you.

### Manual Setup

Add to `~/.spark/.env`:

```bash
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrSTUvwxYZ
TELEGRAM_ALLOWED_USERS=123456789    # Comma-separated for multiple users
```

Then start the gateway:

```bash
spark gateway
```

The bot comes online in seconds. Send it a message to confirm.

## Step 5: Fix Group Chat Visibility (Critical)

Telegram bots have **privacy mode on by default**. In privacy mode, your bot only sees:

- Messages starting with `/`
- Direct replies to the bot's own messages
- Service messages (joins, leaves, pins)
- Messages in channels where the bot is admin

**To let the bot see all group messages**, disable privacy mode:

1. Message **@BotFather** -> `/mybots` -> select your bot
2. **Bot Settings -> Group Privacy -> Turn off**

:::warning
After changing privacy mode, **remove and re-add the bot to every group**. Telegram caches the privacy state at join time.
:::

:::tip
Alternatively, promote the bot to **group admin**. Admins always receive all messages regardless of privacy mode — no need to touch the privacy setting.
:::

## Webhook Mode

By default, Spark uses **long polling** — the gateway makes outbound requests to Telegram to fetch updates. Works anywhere, always on.

**Webhook mode** flips the direction: Telegram pushes updates to your HTTPS URL. This is better for cloud platforms (Fly.io, Railway, Render) that can sleep between inbound requests but can't use outbound polling to wake up.

| | Polling (default) | Webhook |
|---|---|---|
| Direction | Gateway → Telegram | Telegram → Gateway |
| Best for | Local, always-on servers | Cloud platforms with auto-wake |
| Setup | Nothing extra | Set `TELEGRAM_WEBHOOK_URL` |

### Configure Webhook

```bash
TELEGRAM_WEBHOOK_URL=https://my-app.fly.dev/telegram
# TELEGRAM_WEBHOOK_PORT=8443        # optional, default 8443
# TELEGRAM_WEBHOOK_SECRET=mysecret  # optional, strongly recommended
```

| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_WEBHOOK_URL` | Yes | Public HTTPS URL where Telegram delivers updates |
| `TELEGRAM_WEBHOOK_PORT` | No | Local port the webhook server listens on (default: `8443`) |
| `TELEGRAM_WEBHOOK_SECRET` | No | Verifies updates actually come from Telegram — use it in production |

### Cloud Deployment Example (Fly.io)

```bash
fly secrets set TELEGRAM_WEBHOOK_URL=https://my-app.fly.dev/telegram
fly secrets set TELEGRAM_WEBHOOK_SECRET=$(openssl rand -hex 32)
```

In `fly.toml`:

```toml
[[services]]
  internal_port = 8443
  protocol = "tcp"

  [[services.ports]]
    handlers = ["tls", "http"]
    port = 443
```

```bash
fly deploy
```

The gateway log should show: `[telegram] Connected to Telegram (webhook mode)`.

:::warning
Telegram requires a valid TLS certificate. Self-signed certs are rejected. Use a reverse proxy (nginx, Caddy) or a platform that handles TLS termination.
:::

## Home Channel

Use `/sethome` in any Telegram chat (DM or group) to designate it as the home channel. Scheduled tasks and cron jobs deliver results here.

Or set it manually:

```bash
TELEGRAM_HOME_CHANNEL=-1001234567890
TELEGRAM_HOME_CHANNEL_NAME="My Notes"
```

:::tip
Group IDs are negative numbers. Your personal DM chat ID matches your user ID.
:::

## Voice Messages

### Incoming Voice → Text

Send a voice memo and Spark transcribes it automatically using your configured STT provider:

- `local` — uses `faster-whisper` on the machine running Spark, no API key needed
- `groq` — uses Groq Whisper, requires `GROQ_API_KEY`
- `openai` — uses OpenAI Whisper, requires `VOICE_TOOLS_OPENAI_KEY`

### Text → Outgoing Voice

When the agent generates audio via TTS, it arrives as a native Telegram **voice bubble** (round, inline-playable).

- **OpenAI and ElevenLabs** produce Opus natively — no extra setup
- **Edge TTS** (the free default) outputs MP3 and needs **ffmpeg** to convert to Opus:

```bash
# Ubuntu/Debian
sudo apt install ffmpeg

# macOS
brew install ffmpeg
```

Without ffmpeg, Edge TTS audio is still sent — just as a rectangular audio file instead of a voice bubble.

## Group Chat

Spark works in group chats. A few things to know:

- Privacy mode controls what messages the bot can see (see [Step 5](#step-5-fix-group-chat-visibility-critical))
- `TELEGRAM_ALLOWED_USERS` still applies — only authorized users can trigger the bot
- Set `telegram.require_mention: true` to prevent the bot from responding to ordinary group chatter

With `telegram.require_mention: true`, the bot responds to:
- Slash commands
- Replies to the bot's own messages
- `@botusername` mentions
- Custom regex wake words in `telegram.mention_patterns`

### Example Group Config

Add to `~/.spark/config.yaml`:

```yaml
telegram:
  require_mention: true
  mention_patterns:
    - "^\\s*chompy\\b"
```

This accepts all direct triggers plus messages starting with `chompy`, even without `@mention`. Patterns use Python regex, match case-insensitively, and work on both text and captions.

## Private Chat Topics (Bot API 9.4)

Telegram Bot API 9.4 lets bots create forum-style topics in 1-on-1 DM chats. Use this to run multiple isolated workspaces in your existing DM with Spark:

- **Topic "Website"** — your production web service
- **Topic "Research"** — literature review and paper exploration
- **Topic "General"** — quick questions and miscellaneous tasks

Each topic gets its own session, history, and context window.

### Configure DM Topics

Add to `~/.spark/config.yaml`:

```yaml
platforms:
  telegram:
    extra:
      dm_topics:
      - chat_id: 123456789        # Your Telegram user ID
        topics:
        - name: General
          icon_color: 7322096
        - name: Website
          icon_color: 9367192
        - name: Research
          icon_color: 16766590
          skill: arxiv              # Auto-load a skill in this topic
```

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Topic display name |
| `icon_color` | No | Telegram icon color code (integer) |
| `icon_custom_emoji_id` | No | Custom emoji ID for the topic icon |
| `skill` | No | Skill to auto-load on new sessions in this topic |
| `thread_id` | No | Auto-populated after topic creation — don't set manually |

On gateway startup, Spark calls `createForumTopic` for each topic that doesn't have a `thread_id` yet. The `thread_id` is saved back to `config.yaml` automatically.

## Group Forum Topic Skill Binding

Supergroups with Topics mode can bind specific skills to specific topics — so the bot has context for each workstream:

- **Engineering** topic → auto-loads the `software-development` skill
- **Research** topic → auto-loads the `arxiv` skill
- **General** topic → no skill, general-purpose

```yaml
platforms:
  telegram:
    extra:
      group_topics:
      - chat_id: -1001234567890       # Supergroup ID
        topics:
        - name: Engineering
          thread_id: 5
          skill: software-development
        - name: Research
          thread_id: 12
          skill: arxiv
        - name: General
          thread_id: 1
```

| Field | Required | Description |
|-------|----------|-------------|
| `chat_id` | Yes | Supergroup ID (negative, starts with `-100`) |
| `name` | No | Label for your own reference |
| `thread_id` | Yes | Visible in `t.me/c/<group_id>/<thread_id>` URLs |
| `skill` | No | Skill to auto-load when a new session starts |

## Interactive Model Picker

Send `/model` with no arguments and Spark shows a paginated inline keyboard:

1. **Provider selection** — buttons for each provider with model counts
2. **Model selection** — paginated list with **Prev/Next** navigation and a **Back** button

Everything happens by editing the same message — no chat clutter. Or skip the picker with `/model <name>` directly.

## DNS Fallback (Restricted Networks)

If `api.telegram.org` is unreachable on your network, Spark automatically queries Google DNS and Cloudflare DNS over HTTPS to find alternative IPs. A hardcoded seed IP (`149.154.167.220`) is used as a last resort.

To specify fallback IPs manually:

```bash
TELEGRAM_FALLBACK_IPS=149.154.167.220,149.154.167.221
```

## Proxy Support

The Telegram adapter reads standard proxy environment variables automatically:

```bash
export HTTPS_PROXY=http://proxy.example.com:8080
spark gateway
```

Or in `~/.spark/.env`:

```bash
HTTPS_PROXY=http://proxy.example.com:8080
```

Checked in order: `HTTPS_PROXY`, `HTTP_PROXY`, `ALL_PROXY`, then lowercase variants.

## Emoji Reactions

The bot can react to messages as visual feedback:

-  when it starts processing
-  when it delivers the response
-  if an error occurs

Disabled by default. Enable in `config.yaml`:

```yaml
telegram:
  reactions: true
```

Or via env var:

```bash
TELEGRAM_REACTIONS=true
```

## Command Approval for Risky Commands

When the agent wants to run a potentially dangerous command, it pauses and asks:

> ⚠️ This command is potentially dangerous (recursive delete). Reply "yes" to approve.

Reply `yes` or `y` to approve, `no` or `n` to deny. You can also use `/approve` and `/deny` commands.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Bot not responding at all | Verify `TELEGRAM_BOT_TOKEN` is correct. Check `spark gateway` logs. |
| Bot responds with "unauthorized" | Your user ID is not in `TELEGRAM_ALLOWED_USERS`. Re-check with @userinfobot. |
| Bot ignores group messages | Privacy mode is likely on. Disable it (Step 5) or make the bot a group admin. **Remove and re-add the bot after changing privacy.** |
| Voice messages not transcribed | Install `faster-whisper` for local, or set `GROQ_API_KEY` / `VOICE_TOOLS_OPENAI_KEY`. |
| Voice replies are files, not bubbles | Install `ffmpeg` for Edge TTS Opus conversion. |
| Bot token revoked | Generate a new token via `/revoke` then `/token` in BotFather. Update `.env`. |
| Webhook not receiving updates | Verify `TELEGRAM_WEBHOOK_URL` is publicly reachable. Ensure SSL/TLS is active — Telegram only sends to HTTPS. Check firewall rules. |

## Security

:::warning
Always set `TELEGRAM_ALLOWED_USERS`. Without it, the gateway denies all users by default, but the allowlist is the explicit, auditable safeguard.
:::

Never share your bot token. Revoke it immediately via BotFather's `/revoke` command if it's ever compromised.

Use [DM pairing](/docs/chat-platforms/telegram#dm-pairing-alternative-to-allowlists) for a code-based alternative to managing user IDs manually.
