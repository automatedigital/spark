---
sidebar_position: 8
title: "Mattermost"
description: "Set up Spark Agent as a Mattermost bot"
---

# Mattermost

Add Spark to your self-hosted Mattermost instance. Chat with your AI assistant via direct messages or team channels — no external library required beyond what Spark already ships with.

Spark connects via Mattermost's REST API (v4) and WebSocket for real-time events. It handles text, file attachments, images, and slash commands. The adapter uses `aiohttp`, which is already a Spark dependency.

## How Spark Behaves Once Connected

| Context | Behavior |
|---------|----------|
| **DMs** | Spark responds to every message. No `@mention` needed. Each DM has its own session. |
| **Public/private channels** | Spark responds when you `@mention` it. It ignores messages without a mention. |
| **Threads** | Set `MATTERMOST_REPLY_MODE=thread` to have Spark reply in a thread under your message. Thread context stays isolated from the parent channel. |
| **Shared channels** | By default, each user in a shared channel gets their own isolated session. Two people don't share a transcript unless you explicitly disable this. |

:::tip
Set `MATTERMOST_REPLY_MODE=thread` to keep channels clean when there's a lot of back-and-forth.
:::

## Session Isolation

By default, each DM, thread, and user in a shared channel gets their own session. Control this in `config.yaml`:

```yaml
group_sessions_per_user: true
```

Set it to `false` only if you want one shared conversation for the entire channel:

```yaml
group_sessions_per_user: false
```

Shared sessions are useful for collaborative channels, but come with tradeoffs:

- Users share context growth and token costs
- One person's long tool-heavy task bloats everyone else's context
- One in-flight run can interrupt another person's follow-up

## Step 1: Enable Bot Accounts

Bot accounts must be enabled on your Mattermost server before you can create one.

1. Log in to Mattermost as a **System Admin**
2. Go to **System Console** -> **Integrations** -> **Bot Accounts**
3. Set **Enable Bot Account Creation** to **true**
4. Click **Save**

:::info
If you don't have System Admin access, ask your Mattermost administrator to enable bot accounts and create one for you.
:::

## Step 2: Create the Bot Account

1. Click the **** menu (top-left) -> **Integrations** -> **Bot Accounts**
2. Click **Add Bot Account**
3. Fill in the details:
   - **Username**: e.g., `spark`
   - **Display Name**: e.g., `Spark Agent`
   - **Role**: `Member` is sufficient
4. Click **Create Bot Account**
5. Copy the **bot token** that appears — you only see it once

:::warning[Token shown only once]
If you lose the token, you'll need to regenerate it from the bot account settings. Never share your token publicly or commit it to Git.
:::

:::tip
You can also use a **personal access token** instead of a bot account. Go to **Profile** -> **Security** -> **Personal Access Tokens** -> **Create Token**. This makes Spark post as your own user rather than a separate bot.
:::

## Step 3: Add the Bot to Channels

The bot needs to be a member of any channel where you want it to respond:

1. Open the target channel
2. Click the channel name -> **Add Members**
3. Search for your bot username and add it

For DMs, just open a direct message with the bot — it responds immediately.

## Step 4: Find Your User ID

Spark uses your Mattermost User ID (not your username) to control who can interact with the bot.

1. Click your **avatar** (top-left) -> **Profile**
2. Your User ID appears in the profile dialog — click it to copy

Your User ID is a 26-character alphanumeric string like `3uo8dkh1p7g1mfk49ear5fzs5c`.

:::warning
Your User ID is **not** your username. The username appears after `@`. The User ID is the long alphanumeric string Mattermost uses internally.
:::

You can also get it via the API:

```bash
curl -H "Authorization: Bearer YOUR_TOKEN" \
  https://your-mattermost-server/api/v4/users/me | jq .id
```

:::tip
To get a **Channel ID**: click the channel name -> **View Info**. You'll need this if you want to set a home channel manually.
:::

## Step 5: Configure Spark

### Option A: Interactive Setup (Recommended)

```bash
spark gateway setup
```

Select **Mattermost** when prompted, then paste your server URL, bot token, and user ID.

### Option B: Manual Configuration

```bash
# Required
MATTERMOST_URL=https://mm.example.com
MATTERMOST_TOKEN=***
MATTERMOST_ALLOWED_USERS=3uo8dkh1p7g1mfk49ear5fzs5c

# Multiple allowed users (comma-separated)
# MATTERMOST_ALLOWED_USERS=3uo8dkh1p7g1mfk49ear5fzs5c,8fk2jd9s0a7bncm1xqw4tp6r3e

# Optional: reply mode (thread or off, default: off)
# MATTERMOST_REPLY_MODE=thread

# Optional: respond without @mention (default: true = require mention)
# MATTERMOST_REQUIRE_MENTION=false

# Optional: channels where bot responds without @mention (comma-separated channel IDs)
# MATTERMOST_FREE_RESPONSE_CHANNELS=channel_id_1,channel_id_2
```

Optional in `~/.spark/config.yaml`:

```yaml
group_sessions_per_user: true
```

### Start the Gateway

```bash
spark gateway
```

The bot connects within seconds. Send it a DM or mention it in a channel to test.

:::tip
Run `spark gateway` as a systemd service for persistent operation. See the deployment docs for details.
:::

## Set a Home Channel

Designate a home channel for proactive messages — cron output, reminders, notifications.

### Using a Slash Command

Type `/sethome` in any channel where the bot is present.

### Manual Configuration

```bash
MATTERMOST_HOME_CHANNEL=abc123def456ghi789jkl012mn
```

Replace the ID with the actual channel ID (click channel name -> View Info -> copy the ID).

## Reply Mode

| Mode | Behavior |
|------|----------|
| `off` (default) | Spark posts flat messages in the channel |
| `thread` | Spark replies in a thread under your original message — keeps channels clean during long exchanges |

```bash
MATTERMOST_REPLY_MODE=thread
```

## Mention Behavior

| Variable | Default | Description |
|----------|---------|-------------|
| `MATTERMOST_REQUIRE_MENTION` | `true` | Set to `false` to respond to all channel messages (DMs always work) |
| `MATTERMOST_FREE_RESPONSE_CHANNELS` | _(none)_ | Channel IDs where the bot responds without `@mention`, even when `require_mention` is true |

To find a channel ID: open the channel, click the channel name, and look for the ID in the URL or channel details.

When you `@mention` the bot, the mention is automatically stripped from the message before processing.

## Troubleshooting

### Bot is not responding

**Cause:** The bot isn't a member of the channel, or your User ID isn't in `MATTERMOST_ALLOWED_USERS`.

**Fix:** Add the bot to the channel (channel name -> Add Members). Verify your User ID is in `MATTERMOST_ALLOWED_USERS`. Restart the gateway.

### 403 Forbidden errors

**Cause:** The bot token is invalid, or the bot doesn't have permission to post in the channel.

**Fix:** Check that `MATTERMOST_TOKEN` in your `.env` is correct. Make sure the bot account hasn't been deactivated. Verify the bot has been added to the channel.

### WebSocket disconnects / reconnection loops

**Cause:** Network instability, Mattermost server restarts, or firewall/proxy issues with WebSocket connections.

**Fix:** The adapter automatically reconnects with exponential backoff (2s → 60s). Check your server's WebSocket configuration — reverse proxies need WebSocket upgrade headers.

For nginx:

```nginx
location /api/v4/websocket {
    proxy_pass http://mattermost-backend;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 600s;
}
```

### "Failed to authenticate" on startup

**Cause:** Wrong token or server URL.

**Fix:** Verify `MATTERMOST_URL` includes `https://` with no trailing slash. Test your token:

```bash
curl -H "Authorization: Bearer YOUR_TOKEN" \
  https://your-server/api/v4/users/me
```

A valid token returns your bot's user info. An error means the token needs to be regenerated.

### Bot is offline

**Cause:** The gateway isn't running or failed to connect.

**Fix:** Check that `spark gateway` is running. Look at terminal output for errors. Common causes: wrong URL, expired token, Mattermost server unreachable.

### "User not allowed" / Bot ignores you

**Cause:** Your User ID isn't in `MATTERMOST_ALLOWED_USERS`.

**Fix:** Add your 26-character User ID (not your `@username`) to `MATTERMOST_ALLOWED_USERS` in `~/.spark/.env` and restart the gateway.

## Security

:::warning
Always set `MATTERMOST_ALLOWED_USERS`. Without it, the gateway denies all users by default. Only add User IDs of people you trust — authorized users get full access to the agent's capabilities, including tool use and system access.
:::

## Notes

- **Self-hosted friendly:** Works with any self-hosted Mattermost instance. No cloud account or subscription required.
- **No extra dependencies:** The adapter uses `aiohttp` for HTTP and WebSocket, already included with Spark.
- **Team Edition compatible:** Works with both Mattermost Team Edition (free) and Enterprise Edition.
