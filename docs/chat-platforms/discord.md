---
sidebar_position: 3
title: "Discord"
description: "Set up Spark Agent as a Discord bot"
---

# Discord

Run Spark as a Discord bot. It handles DMs, server channels, threads, voice messages, and slash commands — with full tool use, memory, and reasoning on every message.

## Understand the Behavior First

Before touching any settings, know what to expect out of the box:

| Context | Default behavior |
|---------|-----------------|
| DMs | Responds to every message. No `@mention` required. Each DM has its own session. |
| Server channels | Only responds when `@mentioned`. Ignores everything else. |
| Free-response channels | Add channel IDs to `DISCORD_FREE_RESPONSE_CHANNELS` to drop the mention requirement. |
| Threads | Replies stay in the same thread. Mention rules apply unless the thread (or its parent channel) is free-response. |
| Shared channels, multiple users | Each user gets their own session. Alice and Bob in `#research` don't share a transcript. |
| Messages mentioning other users | Spark stays quiet if a message `@mentions` someone other than the bot. It won't jump into conversations meant for other people. |

:::tip
Want a channel where people can talk to Spark without tagging it? Add it to `DISCORD_FREE_RESPONSE_CHANNELS`.
:::

### How Sessions Work

Each user in a shared channel gets their own conversation history by default:

```yaml
group_sessions_per_user: true   # default
```

Set this to `false` in `~/.spark/config.yaml` only if you want the whole channel to share one conversation:

```yaml
group_sessions_per_user: false
```

Shared sessions have tradeoffs: everyone's context grows together, one person's long tool run bloats everyone's history, and concurrent messages can interrupt each other's in-flight requests.

---

## Setup: 8 Steps

### Step 1: Create a Discord Application

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) and sign in.
2. Click **New Application** (top-right).
3. Name it (e.g., "Spark Agent") and click **Create**.
4. Note the **Application ID** from the General Information page — you'll need it for the invite URL.

### Step 2: Create the Bot User

1. Click **Bot** in the left sidebar.
2. Discord creates a bot user automatically. You can set a custom username, avatar, and banner here.
3. Under **Authorization Flow**: set **Public Bot** to **ON**. Leave **Require OAuth2 Code Grant** off.

:::info[Private Bot Alternative]
If you set Public Bot to **OFF**, you must use the Manual URL method in Step 5 instead of the Installation tab.
:::

### Step 3: Enable Required Intents

:::warning[This is the #1 reason Discord bots don't work]
Without **Message Content Intent**, the bot connects but reads empty messages. It will never respond. Go to Bot -> Privileged Gateway Intents and make sure these are ON.
:::

| Intent | Required? | What it does |
|--------|-----------|-------------|
| Presence Intent | Optional | See user online/offline status |
| **Server Members Intent** | **Yes** | Resolve usernames; identify who is messaging |
| **Message Content Intent** | **Yes** | Read what users actually typed |

Toggle both required intents **ON** and click **Save Changes**.

> For bots in fewer than 100 servers, you can freely toggle intents. Bots in 100+ servers need Discord's verification process — not a concern for personal use.

### Step 4: Get the Bot Token

1. On the **Bot** page, click **Reset Token**.
2. Enter your 2FA code if required.
3. **Copy the token immediately** — it's shown only once.

:::warning[Token shown only once]
Anyone with this token has full control of your bot. Store it in a password manager. Never commit it to Git.
:::

### Step 5: Generate an Invite URL

**Option A — Installation Tab (requires Public Bot = ON):**

1. Click **Installation** in the sidebar.
2. Enable **Guild Install** under Installation Contexts.
3. Select **Discord Provided Link** for Install Link.
4. Under Default Install Settings, add scopes `bot` + `applications.commands` and set permissions.

**Option B — Manual URL:**

```
https://discord.com/oauth2/authorize?client_id=YOUR_APP_ID&scope=bot+applications.commands&permissions=274878286912
```

Replace `YOUR_APP_ID` with the ID from Step 1.

**Permissions:**

| Level | Integer | Includes |
|-------|---------|---------|
| Minimal | `117760` | View Channels, Send Messages, Read History, Attach Files |
| **Recommended** | `274878286912` | All above + Embed Links, Send in Threads, Add Reactions |

### Step 6: Invite the Bot to Your Server

1. Open the invite URL in your browser.
2. Select your server from the dropdown.
3. Click **Continue** -> **Authorize** -> complete CAPTCHA if shown.

You need **Manage Server** permission to invite bots. The bot appears offline until you start the Spark gateway.

### Step 7: Find Your Discord User ID

1. Open Discord -> **Settings** -> **Advanced** -> toggle **Developer Mode** ON.
2. Right-click your username anywhere -> **Copy User ID**.

Your User ID is a long number like `284102345871466496`.

:::tip
Developer Mode also lets you right-click channels and servers to copy their IDs — useful for `DISCORD_HOME_CHANNEL` and `DISCORD_FREE_RESPONSE_CHANNELS`.
:::

### Step 8: Configure and Start Spark

**Option A — Interactive setup:**

```bash
spark gateway setup
```

Select **Discord**, then paste your bot token and User ID when asked.

**Option B — Manual setup:**

Add to `~/.spark/.env`:

```bash
# Required
DISCORD_BOT_TOKEN=your-bot-token
DISCORD_ALLOWED_USERS=284102345871466496

# Multiple users (comma-separated)
# DISCORD_ALLOWED_USERS=284102345871466496,198765432109876543
```

Then start the gateway:

```bash
spark gateway
```

The bot comes online within a few seconds. Send it a DM or `@mention` it to confirm.

---

## Configuration Reference

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DISCORD_BOT_TOKEN` | **Yes** | - | Bot token from the [Discord Developer Portal](https://discord.com/developers/applications) |
| `DISCORD_ALLOWED_USERS` | **Yes** | - | Comma-separated Discord user IDs allowed to use the bot |
| `DISCORD_HOME_CHANNEL` | No | - | Channel ID for cron output, reminders, and notifications |
| `DISCORD_HOME_CHANNEL_NAME` | No | `"Home"` | Display name for the home channel in logs |
| `DISCORD_REQUIRE_MENTION` | No | `true` | Require `@mention` in server channels |
| `DISCORD_FREE_RESPONSE_CHANNELS` | No | - | Channel IDs that skip the mention requirement |
| `DISCORD_IGNORE_NO_MENTION` | No | `true` | Stay silent if a message mentions other users but not the bot |
| `DISCORD_AUTO_THREAD` | No | `true` | Auto-create a thread for each `@mention` in a text channel |
| `DISCORD_ALLOW_BOTS` | No | `"none"` | How to handle messages from other bots: `none`, `mentions`, or `all` |
| `DISCORD_REACTIONS` | No | `true` | Add emoji reactions during processing ( starting,  done,  error) |
| `DISCORD_IGNORED_CHANNELS` | No | - | Channel IDs where the bot never responds, even when `@mentioned` |
| `DISCORD_NO_THREAD_CHANNELS` | No | - | Channel IDs where the bot responds inline instead of creating threads |
| `DISCORD_REPLY_TO_MODE` | No | `"first"` | Reply-reference behavior: `off`, `first`, or `all` |

### Config File (`config.yaml`)

Settings in `config.yaml` act as defaults — env vars take precedence when both are set.

```yaml
discord:
  require_mention: true           # Require @mention in server channels
  free_response_channels: ""      # Comma-separated channel IDs (or YAML list)
  auto_thread: true               # Auto-create threads on @mention
  reactions: true                 # Add emoji reactions during processing
  ignored_channels: []            # Channel IDs where bot never responds
  no_thread_channels: []          # Channel IDs where bot responds without threading

group_sessions_per_user: true     # Isolate sessions per user in shared channels
```

#### Key Settings Explained

**`discord.auto_thread`** — When `true` (default), every `@mention` in a regular text channel spawns a new thread. Keeps the main channel clean. Once inside a thread, the bot responds without needing another `@mention`.

**`discord.reactions`** — Visual feedback via emoji:  when processing starts,  on success,  on error. Disable if you find them distracting or the bot lacks Add Reactions permission.

**`discord.ignored_channels`** — Highest priority. A channel here is silently ignored regardless of all other settings. Child threads of ignored channels are also ignored.

**`discord.free_response_channels`** — Accepts both formats:
```yaml
# String
discord:
  free_response_channels: "1234567890,9876543210"

# List
discord:
  free_response_channels:
    - 1234567890
    - 9876543210
```

**`display.tool_progress`** — Controls in-chat progress messages while tools run:

```yaml
display:
  tool_progress: "all"    # off | new | all | verbose
```

Enable the `/verbose` slash command to switch modes on the fly:
```yaml
display:
  tool_progress_command: true
```

---

## Special Features

### Interactive Model Picker

Type `/model` (no arguments) in any channel to open a dropdown for switching providers and models. Accepts up to 25 providers and 25 models per provider. Times out after 120 seconds. Or type `/model <name>` directly if you know the model name.

### Skills as Native Slash Commands

Every skill you install via `spark skills install` automatically becomes a Discord Application Command — visible in the `/` autocomplete menu alongside built-in commands like `/model`, `/reset`, and `/background`.

- Each skill accepts an optional `args` string parameter
- Discord caps bots at 100 application commands; extra skills are skipped with a log warning
- No extra configuration needed — restart the gateway to register newly installed skills

### Home Channel

Set a home channel for proactive messages (cron output, reminders, notifications):

```bash
# Slash command — type this in any channel where the bot is present
/sethome

# Or set manually in ~/.spark/.env
DISCORD_HOME_CHANNEL=123456789012345678
DISCORD_HOME_CHANNEL_NAME="#bot-updates"
```

### Voice Messages

- **Incoming voice messages** are automatically transcribed using `faster-whisper` (no key required), Groq Whisper (`GROQ_API_KEY`), or OpenAI Whisper (`VOICE_TOOLS_OPENAI_KEY`).
- **TTS responses:** use `/voice tts` to have the bot send spoken audio alongside text.
- **Voice channels:** Spark can join a voice channel, listen, and talk back.

See: [Voice Mode](../voice/voice-mode.md) and [Enable Voice Mode](../guides/enable-voice-mode.md).

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Bot online but never responds | Message Content Intent disabled | Developer Portal -> your app -> Bot -> enable **Message Content Intent** -> Save |
| "Disallowed Intents" on startup | Intents not enabled in portal | Enable all three Privileged Gateway Intents in Bot settings |
| Bot can't see a specific channel | Missing channel permissions | Channel Settings -> Permissions -> add bot role with View Channel + Read Message History |
| 403 Forbidden errors | Bot missing required permissions | Re-invite with the correct permissions URL, or adjust the bot's role in Server Settings -> Roles |
| Bot is offline | Gateway not running or wrong token | Run `spark gateway`; verify `DISCORD_BOT_TOKEN` in `.env` |
| Bot ignores you | Your User ID not in allowlist | Add your ID to `DISCORD_ALLOWED_USERS` and restart the gateway |
| Users sharing context unexpectedly | `group_sessions_per_user` is `false` | Set `group_sessions_per_user: true` in `config.yaml` and restart |

## Security

:::warning
Always set `DISCORD_ALLOWED_USERS`. Without it, the gateway denies all users by default. Only add IDs you trust — authorized users get full access to the agent, including tool use and system access.
:::
