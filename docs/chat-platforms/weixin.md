---
sidebar_position: 15
title: "Weixin (WeChat)"
description: "Connect Spark Agent to personal WeChat accounts via the iLink Bot API"
---

# Weixin (WeChat)

Connect Spark to your personal [WeChat](https://weixin.qq.com/) account via Tencent's **iLink Bot API**. No public endpoint, webhook, or WebSocket needed — the adapter uses long-polling.

:::info
This adapter is for **personal WeChat accounts**. For enterprise/corporate WeChat, see the [WeCom adapter](./wecom.md) instead.
:::

## Prerequisites

Install the required packages:

```bash
pip install aiohttp cryptography
# Optional: for terminal QR code display
pip install qrcode
```

## Connect Your Account

### Step 1: Run the Setup Wizard

```bash
spark gateway setup
```

Select **Weixin** when prompted. The wizard:

1. Requests a QR code from the iLink Bot API
2. Displays the QR code in your terminal (or prints a URL)
3. Waits for you to scan with the WeChat mobile app
4. Prompts you to confirm the login on your phone
5. Saves credentials automatically to `~/.spark/weixin/accounts/`

Once confirmed, you'll see:

```
,account_id=your-account-id
```

The wizard saves `account_id`, `token`, and `base_url` — no manual configuration needed.

### Step 2: Set Your Account ID

After the initial QR login, add at minimum your account ID to `~/.spark/.env`:

```bash
WEIXIN_ACCOUNT_ID=your-account-id

# Optional: override the token (normally auto-saved from QR login)
# WEIXIN_TOKEN=your-bot-token

# Optional: restrict access
WEIXIN_DM_POLICY=open
WEIXIN_ALLOWED_USERS=user_id_1,user_id_2

# Optional: restore legacy multiline splitting behavior
# WEIXIN_SPLIT_MULTILINE_MESSAGES=true

# Optional: home channel for cron/notifications
WEIXIN_HOME_CHANNEL=chat_id
WEIXIN_HOME_CHANNEL_NAME=Home
```

### Step 3: Start the Gateway

```bash
spark gateway
```

The adapter restores saved credentials, connects to the iLink API, and begins long-polling for messages.

## What You Get

- **Long-poll transport** — no public endpoint, webhook, or WebSocket needed
- **QR code login** — scan-to-connect setup via `spark gateway setup`
- **DM and group messaging** — configurable access policies
- **Media support** — images, video, files, and voice messages
- **AES-128-ECB encrypted CDN** — automatic encryption/decryption for all media transfers
- **Context token persistence** — disk-backed reply continuity across restarts
- **Markdown formatting** — headers, tables, and code blocks reformatted for WeChat readability
- **Smart message chunking** — single bubble when under the limit; only oversized payloads split at logical boundaries
- **Typing indicators** — shows "typing..." status while the agent processes
- **SSRF protection** — outbound media URLs are validated before download
- **Message deduplication** — 5-minute sliding window prevents double-processing
- **Automatic retry with backoff** — recovers from transient API errors

## Configuration Options

Set these in `config.yaml` under `platforms.weixin.extra`:

| Key | Default | Description |
|-----|---------|-------------|
| `account_id` | - | iLink Bot account ID (required) |
| `token` | - | iLink Bot token (required, auto-saved from QR login) |
| `base_url` | `https://ilinkai.weixin.qq.com` | iLink API base URL |
| `cdn_base_url` | `https://novac2c.cdn.weixin.qq.com/c2c` | CDN base URL for media transfer |
| `dm_policy` | `open` | DM access: `open`, `allowlist`, `disabled`, `pairing` |
| `group_policy` | `disabled` | Group access: `open`, `allowlist`, `disabled` |
| `allow_from` | `[]` | User IDs allowed for DMs (when dm_policy=allowlist) |
| `group_allow_from` | `[]` | Group IDs allowed (when group_policy=allowlist) |
| `split_multiline_messages` | `false` | When `true`, split multi-line replies into multiple chat messages (legacy behavior). When `false`, keep multi-line replies as one message unless they exceed the length limit. |

## Access Policies

### DM Policy

| Value | Behavior |
|-------|----------|
| `open` | Anyone can DM the bot (default) |
| `allowlist` | Only user IDs in `allow_from` can DM |
| `disabled` | All DMs are ignored |
| `pairing` | Pairing mode (for initial setup) |

```bash
WEIXIN_DM_POLICY=allowlist
WEIXIN_ALLOWED_USERS=user_id_1,user_id_2
```

### Group Policy

| Value | Behavior |
|-------|----------|
| `open` | Bot responds in all groups |
| `allowlist` | Bot only responds in groups listed in `group_allow_from` |
| `disabled` | All group messages are ignored (default) |

```bash
WEIXIN_GROUP_POLICY=allowlist
WEIXIN_GROUP_ALLOWED_USERS=group_id_1,group_id_2
```

:::note
Group policy defaults to `disabled` for Weixin (unlike WeCom where it defaults to `open`). Personal WeChat accounts are often in many groups — this prevents the bot from responding everywhere unexpectedly.
:::

## Media Support

### Inbound (receiving)

| Type | How it's handled |
|------|-----------------| 
| **Images** | Downloaded, AES-decrypted, and cached as JPEG |
| **Video** | Downloaded, AES-decrypted, and cached as MP4 |
| **Files** | Downloaded, AES-decrypted, and cached with original filename preserved |
| **Voice** | Text transcription extracted if available; otherwise audio (SILK format) is downloaded and cached |

**Quoted messages:** Media from quoted messages is also extracted so the agent has context about what the user is replying to.

### AES-128-ECB Encrypted CDN

WeChat media transfers through an encrypted CDN. The adapter handles this transparently in both directions:

- **Inbound:** Downloads encrypted media from the CDN using `encrypted_query_param` URLs, then decrypts with AES-128-ECB using the per-file key from the message payload
- **Outbound:** Encrypts files locally with a random AES-128-ECB key, uploads to the CDN, and includes the encrypted reference in the outbound message

Keys may arrive as raw base64 or hex-encoded — the adapter handles both formats. Requires the `cryptography` package. No configuration needed.

### Outbound (sending)

| Method | What it sends |
|--------|--------------|
| `send` | Text messages with Markdown formatting |
| `send_image` / `send_image_file` | Native image messages (via CDN upload) |
| `send_document` | File attachments (via CDN upload) |
| `send_video` | Video messages (via CDN upload) |

## Markdown Formatting

WeChat's personal chat doesn't natively render Markdown. The adapter reformats content for better readability:

- **Headers** (`# Title`) → `Title` (level 1) or `**Title**` (level 2+)
- **Tables** → reformatted as labeled key-value lists (e.g., `- Column: Value`)
- **Code fences** → preserved as-is (WeChat renders these adequately)
- **Excessive blank lines** → collapsed to double newlines

## Message Chunking

Messages stay as a single chat message whenever they fit within the 4000-character limit. Only oversized payloads split:

- Messages under the limit stay intact even with multiple paragraphs or line breaks
- Oversized messages split at logical boundaries (paragraphs, blank lines, code fences)
- Code fences are kept intact whenever possible — never split mid-block unless the fence itself exceeds the limit
- A 0.3s inter-chunk delay prevents WeChat rate-limit drops when sending multiple chunks

## Typing Indicators

1. When a message arrives, the adapter fetches a `typing_ticket` via the `getconfig` API
2. Tickets are cached for 10 minutes per user
3. `send_typing` sends a typing-start signal; `stop_typing` sends a typing-stop signal
4. The gateway triggers typing indicators automatically while the agent processes a message

## Long-Poll Connection Details

### How It Works

1. **Connect:** Validates credentials and starts the poll loop
2. **Poll:** Calls `getupdates` with a 35-second timeout — the server holds the request until messages arrive or the timeout expires
3. **Dispatch:** Inbound messages are dispatched concurrently via `asyncio.create_task`
4. **Sync buffer:** A persistent sync cursor (`get_updates_buf`) is saved to disk so the adapter resumes from the correct position after restarts

### Retry Behavior

| Condition | Behavior |
|-----------|----------|
| Transient error (1st–2nd) | Retry after 2 seconds |
| Repeated errors (3+) | Back off for 30 seconds, then reset counter |
| Session expired (`errcode=-14`) | Pause for 10 minutes (re-login may be needed) |
| Timeout | Immediately re-poll (normal long-poll behavior) |

### Token Lock

Only one Weixin gateway instance can use a given token at a time. The adapter acquires a scoped lock on startup and releases it on shutdown. If another gateway is already using the same token, startup fails with an informative error message.

## All Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `WEIXIN_ACCOUNT_ID` | ✓ | - | iLink Bot account ID (from QR login) |
| `WEIXIN_TOKEN` | ✓ | - | iLink Bot token (auto-saved from QR login) |
| `WEIXIN_BASE_URL` | - | `https://ilinkai.weixin.qq.com` | iLink API base URL |
| `WEIXIN_CDN_BASE_URL` | - | `https://novac2c.cdn.weixin.qq.com/c2c` | CDN base URL for media transfer |
| `WEIXIN_DM_POLICY` | - | `open` | DM access policy: `open`, `allowlist`, `disabled`, `pairing` |
| `WEIXIN_GROUP_POLICY` | - | `disabled` | Group access policy: `open`, `allowlist`, `disabled` |
| `WEIXIN_ALLOWED_USERS` | - | _(empty)_ | Comma-separated user IDs for DM allowlist |
| `WEIXIN_GROUP_ALLOWED_USERS` | - | _(empty)_ | Comma-separated group IDs for group allowlist |
| `WEIXIN_HOME_CHANNEL` | - | - | Chat ID for cron/notification output |
| `WEIXIN_HOME_CHANNEL_NAME` | - | `Home` | Display name for the home channel |
| `WEIXIN_ALLOW_ALL_USERS` | - | - | Gateway-level flag to allow all users (used by setup wizard) |

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `Weixin startup failed: aiohttp and cryptography are required` | `pip install aiohttp cryptography` |
| `Weixin startup failed: WEIXIN_TOKEN is required` | Run `spark gateway setup` to complete QR login, or set `WEIXIN_TOKEN` manually |
| `Weixin startup failed: WEIXIN_ACCOUNT_ID is required` | Set `WEIXIN_ACCOUNT_ID` in your `.env` or run `spark gateway setup` |
| `Another local Spark gateway is already using this Weixin token` | Stop the other gateway instance — only one poller per token is allowed |
| Session expired (`errcode=-14`) | Your login session expired. Re-run `spark gateway setup` to scan a new QR code |
| QR code expired during setup | The QR auto-refreshes up to 3 times. If it keeps expiring, check your network |
| Bot doesn't respond to DMs | Check `WEIXIN_DM_POLICY` — if set to `allowlist`, the sender must be in `WEIXIN_ALLOWED_USERS` |
| Bot ignores group messages | Group policy defaults to `disabled`. Set `WEIXIN_GROUP_POLICY=open` or `allowlist` |
| Media download/upload fails | Ensure `cryptography` is installed. Check network access to `novac2c.cdn.weixin.qq.com` |
| `Blocked unsafe URL (SSRF protection)` | The outbound media URL points to a private/internal address. Only public URLs are allowed |
| Voice messages show as text | If WeChat provides a transcription, the adapter uses the text. This is expected behavior |
| Messages appear duplicated | Check if multiple gateway instances are running — the adapter deduplicates by message ID |
| `iLink POST ... HTTP 4xx/5xx` | API error from the iLink service. Check your token validity and network connectivity |
| Terminal QR code doesn't render | `pip install qrcode`. Alternatively, open the URL printed above the QR |
