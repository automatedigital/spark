---
sidebar_position: 14
title: "WeCom (Enterprise WeChat)"
description: "Connect Spark Agent to WeCom via the AI Bot WebSocket gateway"
---

# WeCom (Enterprise WeChat)

Connect Spark to [WeCom](https://work.weixin.qq.com/), Tencent's enterprise messaging platform. Spark uses WeCom's AI Bot WebSocket gateway for real-time bidirectional communication — no public endpoint or webhook required.

## Prerequisites

- A WeCom organization account
- An AI Bot created in the WeCom Admin Console
- The Bot ID and Secret from the bot's credentials page
- Python packages: `aiohttp` and `httpx`

## Setup

### 1. Create an AI Bot

1. Log in to the [WeCom Admin Console](https://work.weixin.qq.com/wework_admin/frame)
2. Navigate to **Applications** -> **Create Application** -> **AI Bot**
3. Configure the bot name and description
4. Copy the **Bot ID** and **Secret** from the credentials page

### 2. Configure Spark

Run the interactive setup:

```bash
spark gateway setup
```

Select **WeCom** and enter your Bot ID and Secret.

Or set environment variables directly in `~/.spark/.env`:

```bash
WECOM_BOT_ID=your-bot-id
WECOM_SECRET=your-secret

# Optional: restrict access
WECOM_ALLOWED_USERS=user_id_1,user_id_2

# Optional: home channel for cron/notifications
WECOM_HOME_CHANNEL=chat_id
```

### 3. Start the Gateway

```bash
spark gateway
```

## What You Get

- **WebSocket transport** — persistent connection, no public endpoint needed
- **DM and group messaging** — configurable access policies
- **Per-group sender allowlists** — fine-grained control over who can interact in each group
- **Media support** — images, files, voice, and video upload and download
- **AES-encrypted media** — automatic decryption for inbound attachments
- **Quote context** — preserves reply threading
- **Markdown rendering** — rich text responses
- **Reply-mode streaming** — correlates responses to inbound message context
- **Auto-reconnect** — exponential backoff on connection drops

## Configuration Options

Set these in `config.yaml` under `platforms.wecom.extra`:

| Key | Default | Description |
|-----|---------|-------------|
| `bot_id` | - | WeCom AI Bot ID (required) |
| `secret` | - | WeCom AI Bot Secret (required) |
| `websocket_url` | `wss://openws.work.weixin.qq.com` | WebSocket gateway URL |
| `dm_policy` | `open` | DM access: `open`, `allowlist`, `disabled`, `pairing` |
| `group_policy` | `open` | Group access: `open`, `allowlist`, `disabled` |
| `allow_from` | `[]` | User IDs allowed for DMs (when dm_policy=allowlist) |
| `group_allow_from` | `[]` | Group IDs allowed (when group_policy=allowlist) |
| `groups` | `{}` | Per-group configuration (see below) |

## Access Policies

### DM Policy

| Value | Behavior |
|-------|----------|
| `open` | Anyone can DM the bot (default) |
| `allowlist` | Only user IDs in `allow_from` can DM |
| `disabled` | All DMs are ignored |
| `pairing` | Pairing mode (for initial setup) |

```bash
WECOM_DM_POLICY=allowlist
```

### Group Policy

| Value | Behavior |
|-------|----------|
| `open` | Bot responds in all groups (default) |
| `allowlist` | Bot only responds in groups listed in `group_allow_from` |
| `disabled` | All group messages are ignored |

```bash
WECOM_GROUP_POLICY=allowlist
```

### Per-Group Sender Allowlists

Restrict which users can interact with the bot within specific groups:

```yaml
platforms:
  wecom:
    enabled: true
    extra:
      bot_id: "your-bot-id"
      secret: "your-secret"
      group_policy: "allowlist"
      group_allow_from:
        - "group_id_1"
        - "group_id_2"
      groups:
        group_id_1:
          allow_from:
            - "user_alice"
            - "user_bob"
        group_id_2:
          allow_from:
            - "user_charlie"
        "*":
          allow_from:
            - "user_admin"
```

**How it works:**

1. `group_policy` and `group_allow_from` determine whether a group is allowed at all
2. If the group passes, `groups.<group_id>.allow_from` (if present) further restricts which senders can interact
3. A wildcard `"*"` group entry is the default for groups not explicitly listed
4. Allowlist entries support `*` to allow all users; entries are case-insensitive
5. Entries can optionally use the `wecom:user:` or `wecom:group:` prefix — the prefix is stripped automatically

If no `allow_from` is configured for a group, all users in that group are allowed (assuming the group passes the top-level policy check).

## Media Support

### Inbound (receiving)

| Type | How it's handled |
|------|-----------------|
| **Images** | Downloaded and cached locally. Supports URL-based and base64-encoded images. |
| **Files** | Downloaded and cached. Original filename is preserved. |
| **Voice** | Text transcription is extracted if available. |
| **Mixed messages** | WeCom mixed-type messages (text + images) are parsed and all components extracted. |

**Quoted messages:** Media from quoted messages is also extracted, giving the agent context about what the user is replying to.

### AES-Encrypted Media

WeCom encrypts some inbound media attachments with AES-256-CBC. The adapter handles this transparently — when an inbound media item includes an `aeskey` field, the adapter downloads and decrypts it automatically.

Requires the `cryptography` Python package (`pip install cryptography`). No configuration needed.

### Outbound (sending)

| Method | What it sends | Size limit |
|--------|--------------|------------|
| `send` | Markdown text messages | 4000 chars |
| `send_image` / `send_image_file` | Native image messages | 10 MB |
| `send_document` | File attachments | 20 MB |
| `send_voice` | Voice messages (AMR format only for native voice) | 2 MB |
| `send_video` | Video messages | 10 MB |

**Chunked upload:** Files upload in 512 KB chunks via a three-step protocol (init → chunks → finish). The adapter handles this automatically.

**Automatic downgrade:** When media exceeds the native type's size limit but stays under the 20 MB absolute limit, it's automatically sent as a generic file attachment:

- Images > 10 MB → sent as file
- Videos > 10 MB → sent as file
- Voice > 2 MB → sent as file
- Non-AMR audio → sent as file (WeCom only supports AMR for native voice)

Files over 20 MB are rejected with an informational message sent to the chat.

## Reply-Mode Stream Responses

When the bot receives a message via the WeCom callback, the adapter stores the inbound request ID. If a response arrives while that request context is still active, the adapter uses WeCom's reply-mode (`aibot_respond_msg`) with streaming to correlate the response directly to the inbound message. This gives a more natural conversation feel in the WeCom client.

If the context has expired, the adapter falls back to proactive message sending via `aibot_send_msg`. Reply-mode also works for media.

## Connection and Reconnection

The adapter maintains a persistent WebSocket connection to `wss://openws.work.weixin.qq.com`.

### Connection Lifecycle

1. **Connect:** Opens a WebSocket connection and sends an `aibot_subscribe` authentication frame
2. **Heartbeat:** Sends application-level ping frames every 30 seconds
3. **Listen:** Continuously reads inbound frames and dispatches message callbacks

### Reconnection Behavior

| Attempt | Delay |
|---------|-------|
| 1st retry | 2 seconds |
| 2nd retry | 5 seconds |
| 3rd retry | 10 seconds |
| 4th retry | 30 seconds |
| 5th+ retry | 60 seconds |

After each successful reconnection, the backoff counter resets. All pending request futures are failed on disconnect so callers don't hang indefinitely.

### Deduplication

Inbound messages are deduplicated using message IDs with a 5-minute window and a maximum cache of 1000 entries. This prevents double-processing during reconnection or network hiccups.

## All Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `WECOM_BOT_ID` | ✓ | - | WeCom AI Bot ID |
| `WECOM_SECRET` | ✓ | - | WeCom AI Bot Secret |
| `WECOM_ALLOWED_USERS` | - | _(empty)_ | Comma-separated user IDs for the gateway-level allowlist |
| `WECOM_HOME_CHANNEL` | - | - | Chat ID for cron/notification output |
| `WECOM_WEBSOCKET_URL` | - | `wss://openws.work.weixin.qq.com` | WebSocket gateway URL |
| `WECOM_DM_POLICY` | - | `open` | DM access policy |
| `WECOM_GROUP_POLICY` | - | `open` | Group access policy |

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `WECOM_BOT_ID and WECOM_SECRET are required` | Set both env vars or run the setup wizard |
| `WeCom startup failed: aiohttp not installed` | `pip install aiohttp` |
| `WeCom startup failed: httpx not installed` | `pip install httpx` |
| `invalid secret (errcode=40013)` | Verify the secret matches your bot's credentials |
| `Timed out waiting for subscribe acknowledgement` | Check network connectivity to `openws.work.weixin.qq.com` |
| Bot doesn't respond in groups | Check `group_policy` and ensure the group ID is in `group_allow_from` |
| Bot ignores certain users in a group | Check per-group `allow_from` lists in the `groups` config section |
| Media decryption fails | `pip install cryptography` |
| `cryptography is required for WeCom media decryption` | `pip install cryptography` |
| Voice messages sent as files | WeCom only supports AMR for native voice — other formats auto-downgrade to file |
| `File too large` error | WeCom has a 20 MB absolute limit. Compress or split the file. |
| Images sent as files | Images > 10 MB exceed the native image limit and auto-downgrade to file attachments |
| `Timeout sending message to WeCom` | The WebSocket may have disconnected. Check logs for reconnection messages. |
| `WeCom websocket closed during authentication` | Network issue or incorrect credentials. Verify bot_id and secret. |
