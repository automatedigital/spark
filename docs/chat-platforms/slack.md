---
sidebar_position: 4
title: "Slack"
description: "Set up Spark Agent as a Slack bot using Socket Mode"
---

# Run Spark on Slack

Spark connects to Slack as a bot using **Socket Mode** — a WebSocket connection that requires no public URL. It works behind firewalls, on your laptop, or on a private server.

:::warning Classic Slack Apps Deprecated
Classic apps using the RTM API were **fully deprecated in March 2025**. If you have an old classic app, create a new one following this guide.
:::

| What | Value |
|------|-------|
| Library | `slack-bolt` + `slack_sdk` (Socket Mode) |
| Connection | WebSocket — no public URL needed |
| Tokens required | Bot Token (`xoxb-`) + App-Level Token (`xapp-`) |
| User identification | Slack Member IDs (e.g. `U01ABC2DEF3`) |

---

## Step 1: Create the Slack App

1. Go to [https://api.slack.com/apps](https://api.slack.com/apps)
2. Click **Create New App** -> **From scratch**
3. Name it (e.g. "Spark Agent") and select your workspace
4. Click **Create App** — you'll land on the Basic Information page

---

## Step 2: Add Bot Token Scopes

Go to **Features -> OAuth & Permissions -> Bot Token Scopes** and add these:

| Scope | Why you need it |
|-------|----------------|
| `chat:write` | Send messages as the bot |
| `app_mentions:read` | Detect @mentions in channels |
| `channels:history` | Read messages in public channels the bot is in |
| `channels:read` | List and get info about public channels |
| `groups:history` | Read messages in private channels the bot's invited to |
| `im:history` | Read DM history |
| `im:read` | View basic DM info |
| `im:write` | Open and manage DMs |
| `users:read` | Look up user info |
| `files:read` | Read and download attachments, voice notes, audio |
| `files:write` | Upload files — images, audio, documents |

:::caution Missing scopes = missing messages
Without `channels:history` and `groups:history`, the bot **will not see channel messages** — DMs only. These are the most commonly skipped scopes.
:::

Optional:

| Scope | Why you need it |
|-------|----------------|
| `groups:read` | List and get info about private channels |

---

## Step 3: Enable Socket Mode

1. Go to **Settings -> Socket Mode**
2. Toggle **Enable Socket Mode** ON
3. Create an App-Level Token:
   - Name it anything (e.g. `spark-socket`)
   - Add the **`connections:write`** scope
   - Click **Generate**
4. Copy the token — it starts with `xapp-`. This is your `SLACK_APP_TOKEN`

:::tip
Regenerate app-level tokens anytime under **Settings -> Basic Information -> App-Level Tokens**.
:::

---

## Step 4: Subscribe to Events

This determines what messages the bot actually receives.

1. Go to **Features -> Event Subscriptions**
2. Toggle **Enable Events** ON
3. Add these bot events:

| Event | Required? | Purpose |
|-------|-----------|---------|
| `message.im` | Yes | Bot receives direct messages |
| `message.channels` | Yes | Bot receives messages in public channels it's in |
| `message.groups` | Recommended | Bot receives messages in private channels |
| `app_mention` | Yes | Prevents Bolt SDK errors on @mentions |

4. Click **Save Changes**

:::danger #1 setup issue
Bot works in DMs but not channels? You almost certainly missed `message.channels` and/or `message.groups`. Without these events, Slack simply never sends channel messages to the bot.
:::

---

## Step 5: Enable the Messages Tab

Without this, users see "Sending messages to this app has been turned off" when trying to DM the bot.

1. Go to **Features -> App Home**
2. Scroll to **Show Tabs**
3. Toggle **Messages Tab** ON
4. Check **"Allow users to send Slash commands and messages from the messages tab"**

:::danger DMs are blocked without this
Even with every scope and event correctly configured, Slack blocks DMs to your bot unless the Messages Tab is enabled. This is a Slack requirement.
:::

---

## Step 6: Install to Your Workspace

1. Go to **Settings -> Install App**
2. Click **Install to Workspace** and approve the permissions
3. Copy the **Bot User OAuth Token** — starts with `xoxb-`. This is your `SLACK_BOT_TOKEN`

:::tip
Any time you change scopes or event subscriptions, you **must reinstall the app** for the changes to take effect.
:::

---

## Step 7: Find Your Member ID

Spark uses Slack Member IDs — not usernames — for its allowlist.

To find a Member ID:
1. Click any user's name or avatar in Slack
2. Click **View full profile**
3. Click the **...** button -> **Copy member ID**

Member IDs look like `U01ABC2DEF3`. At minimum, add your own.

---

## Step 8: Configure Spark

Add to `~/.spark/.env`:

```bash
# Required
SLACK_BOT_TOKEN=xoxb-your-bot-token-here
SLACK_APP_TOKEN=xapp-your-app-token-here
SLACK_ALLOWED_USERS=U01ABC2DEF3              # Comma-separated Member IDs

# Optional
SLACK_HOME_CHANNEL=C01234567890              # Default channel for cron/scheduled messages
SLACK_HOME_CHANNEL_NAME=general              # Human-readable name (optional)
```

Or use the interactive wizard:

```bash
spark gateway setup    # Select Slack when prompted
```

Start the gateway:

```bash
spark gateway              # Foreground
spark gateway install      # Install as a user service
sudo spark gateway install --system   # Linux only: boot-time system service
```

---

## Step 9: Invite the Bot to Channels

The bot won't join channels on its own. Invite it wherever you want it:

```
/invite @Spark Agent
```

---

## How the Bot Responds in Different Contexts

| Context | What to expect |
|---------|----------------|
| **DMs** | Bot responds to every message — no @mention needed |
| **Channels** | Bot only responds when @mentioned. Replies appear in a thread on that message. |
| **Threads** | @mention to start. Once active in a thread, subsequent replies in that thread don't need a mention. |

---

## Configuration Options

### Thread and reply behavior

```yaml
platforms:
  slack:
    # Controls how multi-part responses are threaded
    # "off"   - never thread replies to the original message
    # "first" - first chunk threads to user's message (default)
    # "all"   - all chunks thread to user's message
    reply_to_mode: "first"

    extra:
      # Reply in a thread (default: true).
      # Set false to post direct channel replies instead of threads.
      # Messages inside existing threads always reply in-thread.
      reply_in_thread: true

      # Also broadcast thread replies to the main channel.
      # Only the first chunk of the first reply is broadcast.
      reply_broadcast: false
```

| Key | Default | Description |
|-----|---------|-------------|
| `platforms.slack.reply_to_mode` | `"first"` | Threading mode: `"off"`, `"first"`, or `"all"` |
| `platforms.slack.extra.reply_in_thread` | `true` | `false` posts direct channel replies instead of threads |
| `platforms.slack.extra.reply_broadcast` | `false` | `true` also broadcasts thread replies to the main channel |

### Session isolation

```yaml
# Global setting — applies to Slack and all other platforms
group_sessions_per_user: true
```

With `true` (the default), each user in a channel gets their own isolated conversation. Two people in `#general` have separate histories.

Set to `false` for collaborative mode where everyone in a channel shares one session. Note: one user's `/reset` clears the session for everyone.

### Mention triggers

```yaml
slack:
  # Channels require @mention (default behavior)
  require_mention: true

  # Additional patterns that trigger the bot
  mention_patterns:
    - "hey spark"
    - "spark,"

  # Text prepended to every outgoing message
  reply_prefix: ""
```

:::info
Slack requires @mention to start a conversation in channels. Once the bot is active in a thread, replies in that thread don't need a mention. In DMs, the bot always responds.
:::

### Handling unauthorized users

```yaml
slack:
  # What happens when an unauthorized user DMs the bot
  # "pair"   - prompt them for a pairing code (default)
  # "ignore" - silently drop the message
  unauthorized_dm_behavior: "pair"
```

Set globally for all platforms:

```yaml
unauthorized_dm_behavior: "pair"
```

The `slack:`-level setting takes precedence over the global one.

### Voice transcription

```yaml
# Global setting
stt_enabled: true
```

When `true` (the default), incoming audio messages are transcribed before being processed.

### Full example config

```yaml
# Global gateway settings
group_sessions_per_user: true
unauthorized_dm_behavior: "pair"
stt_enabled: true

# Slack-specific settings
slack:
  require_mention: true
  unauthorized_dm_behavior: "pair"

# Platform config
platforms:
  slack:
    reply_to_mode: "first"
    extra:
      reply_in_thread: true
      reply_broadcast: false
```

---

## Set a Home Channel

`SLACK_HOME_CHANNEL` tells Spark where to deliver scheduled messages, cron results, and proactive notifications.

To find a channel ID:
1. Right-click the channel name
2. Click **View channel details**
3. Scroll down — the Channel ID is at the bottom

```bash
SLACK_HOME_CHANNEL=C01234567890
```

The bot must be invited to that channel first (`/invite @Spark Agent`).

---

## Connect Multiple Workspaces

One gateway instance can serve multiple Slack workspaces simultaneously.

### Pass multiple tokens

```bash
# Comma-separated bot tokens — one per workspace
SLACK_BOT_TOKEN=xoxb-workspace1-token,xoxb-workspace2-token,xoxb-workspace3-token

# A single app-level token still handles Socket Mode
SLACK_APP_TOKEN=xapp-your-app-token
```

Or in `~/.spark/config.yaml`:

```yaml
platforms:
  slack:
    token: "xoxb-workspace1-token,xoxb-workspace2-token"
```

### OAuth token file

Spark also reads from `~/.spark/slack_tokens.json`:

```json
{
  "T01ABC2DEF3": {
    "token": "xoxb-workspace-token-here",
    "team_name": "My Workspace"
  }
}
```

Tokens from this file merge with tokens from `SLACK_BOT_TOKEN`. Duplicates are deduplicated automatically.

### How multi-workspace routing works

- The **first token** is the primary — used for the Socket Mode connection
- Each token is verified via `auth.test` at startup and mapped to its workspace's `WebClient` and `bot_user_id`
- Spark routes each incoming message to the correct workspace client automatically

---

## Voice Messages

- **Incoming:** Voice messages are automatically transcribed using your configured STT provider (local `faster-whisper`, Groq Whisper via `GROQ_API_KEY`, or OpenAI Whisper via `VOICE_TOOLS_OPENAI_KEY`)
- **Outgoing:** TTS responses are sent as audio file attachments

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Bot doesn't respond to DMs | Check that `message.im` is in event subscriptions and the app is reinstalled |
| Bot works in DMs but not channels | Add `message.channels` + `message.groups` to events, reinstall, and `/invite` the bot |
| Bot doesn't respond to @mentions | Check `message.channels` event, invite the bot, confirm `channels:history` scope, reinstall |
| Bot ignores private channels | Add `message.groups` event + `groups:history` scope, reinstall, invite the bot |
| "Sending messages to this app has been turned off" | Enable the Messages Tab in App Home (Step 5) |
| "not_authed" or "invalid_auth" errors | Regenerate your Bot Token and App Token, update `.env` |
| Bot can't post in a channel | Invite it: `/invite @Spark Agent` |
| "missing_scope" error | Add the scope in OAuth & Permissions, then reinstall |
| Socket disconnects frequently | Bolt auto-reconnects; check network stability |
| Changed scopes/events but nothing changed | **Reinstall the app** — required after any scope or event change |

### Channel not working? Check all of these

1. `message.channels` event subscribed (public channels)
2. `message.groups` event subscribed (private channels)
3. `app_mention` event subscribed
4. `channels:history` scope added (public channels)
5. `groups:history` scope added (private channels)
6. App **reinstalled** after adding scopes/events
7. Bot **invited** to the channel (`/invite @Spark Agent`)
8. You are **@mentioning** the bot in your message

---

## Security

:::warning
Set `SLACK_ALLOWED_USERS` with authorized Member IDs. Without it, the gateway denies all messages by default. Never share your bot tokens — treat them like passwords.
:::

- Store tokens in `~/.spark/.env` with permissions `600`
- Rotate tokens periodically in the Slack app settings
- Socket Mode means no public endpoint is exposed — one less attack surface
