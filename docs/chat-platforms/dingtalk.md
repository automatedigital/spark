---
sidebar_position: 10
title: "DingTalk"
description: "Set up Spark Agent as a DingTalk chatbot"
---

# DingTalk

Chat with Spark directly inside DingTalk — via direct messages or group chats. The bot connects through DingTalk's **Stream Mode**: a long-lived WebSocket initiated from your machine, so you need no public URL, no webhook server, and it works fine behind NAT or a firewall.

## Before You Start: Install the Dependencies

```bash
pip install dingtalk-stream httpx
```

- `dingtalk-stream` — DingTalk's official SDK for WebSocket-based real-time messaging
- `httpx` — async HTTP client used to send replies via session webhooks

## How the Bot Behaves

| Context | What happens |
|---------|-------------|
| **DMs (1:1)** | Spark replies to every message. No `@mention` needed. Each DM has its own session. |
| **Group chats** | Spark only replies when you `@mention` it. Other messages are ignored. |
| **Groups with multiple users** | Each user gets their own session history by default. Alice and Bob in the same group don't share a transcript. |

### Changing Group Session Behavior

The default keeps sessions isolated per user inside groups:

```yaml
group_sessions_per_user: true
```

If you want a single shared conversation for the whole group, set this in `~/.spark/config.yaml`:

```yaml
group_sessions_per_user: false
```

Only do this deliberately — shared sessions mean everyone's messages pile into one context.

## Step 1: Create a DingTalk App

1. Go to the [DingTalk Developer Console](https://open-dev.dingtalk.com/) and log in as an admin.
2. Click **Application Development** -> **Custom Apps** -> **Create App via H5 Micro-App** (or **Robot**, depending on your console version).
3. Name your app (e.g., `Spark Agent`) and click **Create**.
4. Go to **Credentials & Basic Info** and copy your **Client ID** (AppKey) and **Client Secret** (AppSecret).

:::warning[Credentials shown only once]
The Client Secret is displayed once at creation. If you lose it, you'll need to regenerate it. Never commit these credentials to Git.
:::

## Step 2: Enable the Robot Capability

1. In your app settings, go to **Add Capability** -> **Robot**.
2. Enable the robot capability.
3. Under **Message Reception Mode**, select **Stream Mode**.

:::tip
Stream Mode requires no public URL. DingTalk's servers connect *to you* over WebSocket — it works on any machine, even behind a firewall.
:::

## Step 3: Find Your DingTalk User ID

Spark uses your User ID to control who can talk to the bot. DingTalk User IDs are alphanumeric strings assigned by your organization.

Two ways to find yours:
- Ask your org admin — User IDs live in the DingTalk admin console under **Contacts -> Members**.
- Start the gateway, send the bot a message, then check the logs for the `sender_id` field.

## Step 4: Configure Spark

**Option A — Interactive setup (recommended):**

```bash
spark gateway setup
```

Select **DingTalk** and paste your Client ID, Client Secret, and allowed User IDs when prompted.

**Option B — Manual setup:**

Add to `~/.spark/.env`:

```bash
# Required
DINGTALK_CLIENT_ID=your-app-key
DINGTALK_CLIENT_SECRET=your-app-secret

# Restrict who can use the bot (recommended)
DINGTALK_ALLOWED_USERS=user-id-1

# Multiple users (comma-separated)
# DINGTALK_ALLOWED_USERS=user-id-1,user-id-2
```

And to `~/.spark/config.yaml` if needed:

```yaml
group_sessions_per_user: true
```

## Step 5: Start the Gateway

```bash
spark gateway
```

The bot connects to DingTalk's Stream Mode within seconds. Send it a DM or `@mention` it in a group to test.

:::tip
Run `spark gateway` as a background process or systemd service for always-on operation. See the deployment docs for details.
:::

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Bot doesn't respond | Robot capability not enabled, or your User ID isn't in `DINGTALK_ALLOWED_USERS` | Enable Robot in app settings, confirm Stream Mode is selected, check `DINGTALK_ALLOWED_USERS`, restart gateway |
| `dingtalk-stream not installed` | Package missing | `pip install dingtalk-stream httpx` |
| `DINGTALK_CLIENT_ID and DINGTALK_CLIENT_SECRET required` | Credentials not set | Verify both are in `~/.spark/.env`; Client ID = AppKey, Client Secret = AppSecret |
| Stream disconnects repeatedly | Network instability or invalid credentials | Adapter auto-reconnects (2s → 5s → 10s → 30s → 60s backoff). Verify credentials and check that outbound WebSocket connections are allowed. |
| Bot offline | Gateway not running or failed to connect | Run `spark gateway` and check terminal output for errors |
| `No session_webhook available` | Webhook expired between receiving and replying | Normal DingTalk limitation — send a new message to refresh the session webhook |

## Security

:::warning
Always set `DINGTALK_ALLOWED_USERS`. Without it, the gateway denies everyone by default. Only add User IDs you trust — authorized users get full access to the agent, including tool use.
:::

## Notes

| Topic | Details |
|-------|---------|
| **Stream Mode** | No public IP or webhook endpoint needed. Works behind NAT and firewalls. |
| **Markdown replies** | Responses use DingTalk's markdown format for rich text rendering. |
| **Deduplication** | Messages are deduplicated with a 5-minute window to prevent double-processing. |
| **Auto-reconnection** | Connection drops are handled automatically with exponential backoff. |
| **Message length** | Responses are capped at 20,000 characters. Longer responses are truncated. |
