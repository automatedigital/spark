---
sidebar_position: 11
title: "Feishu / Lark"
description: "Set up Spark Agent as a Feishu or Lark bot"
---

# Feishu / Lark

Connect Spark to Feishu or Lark. You get a fully capable bot in direct messages and group chats, with rich media support, interactive approval cards, per-chat burst protection, and a choice of WebSocket or webhook connection modes.

## Quick Overview

| Feature | Detail |
|---------|--------|
| **DMs** | Spark responds to every message |
| **Group chats** | Spark responds only when `@mentioned` |
| **Connection options** | WebSocket (recommended) or webhook |
| **Media** | Images, audio, video, and documents in both directions |
| **Session isolation** | Each user gets their own history in shared groups by default |

---

## Step 1: Create Your App

### Recommended: One Command

```bash
spark gateway setup
```

Select **Feishu / Lark** and scan the QR code with your mobile app. Spark creates the bot application automatically with the right permissions.

### Alternative: Manual Setup

1. Open the developer console:
   - Feishu: [https://open.feishu.cn/](https://open.feishu.cn/)
   - Lark: [https://open.larksuite.com/](https://open.larksuite.com/)
2. Create a new app and enable the **Bot** capability.
3. Go to **Credentials & Basic Info** and copy your **App ID** and **App Secret**.
4. Run `spark gateway setup`, select **Feishu / Lark**, and enter the credentials.

:::warning
Keep the App Secret private. Anyone with it can impersonate your app.
:::

---

## Step 2: Pick a Connection Mode

### WebSocket Mode (recommended)

Spark opens an outbound connection to Feishu — no public URL needed. Works on laptops, workstations, and private servers behind NAT or firewalls.

```bash
FEISHU_CONNECTION_MODE=websocket
```

Requires: `pip install lark-oapi websockets`

The Lark SDK manages the connection lifecycle, heartbeats, and automatic reconnection.

### Webhook Mode

Feishu pushes events to your server over HTTP. Use this only when Spark already runs behind a reachable endpoint.

```bash
FEISHU_CONNECTION_MODE=webhook
```

Requires: `pip install aiohttp`

Spark serves the webhook at:

```
/feishu/webhook
```

Customize the bind address and path if needed:

```bash
FEISHU_WEBHOOK_HOST=127.0.0.1   # default
FEISHU_WEBHOOK_PORT=8765         # default
FEISHU_WEBHOOK_PATH=/feishu/webhook  # default
```

When Feishu sends a URL verification challenge (`type: url_verification`), the webhook responds automatically.

---

## Step 3: Configure Spark

**Interactive setup:**

```bash
spark gateway setup
```

**Manual setup** — add to `~/.spark/.env`:

```bash
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=secret_xxx
FEISHU_DOMAIN=feishu          # feishu (China) or lark (international)
FEISHU_CONNECTION_MODE=websocket

# Strongly recommended
FEISHU_ALLOWED_USERS=ou_xxx,ou_yyy
FEISHU_HOME_CHANNEL=oc_xxx
```

---

## Step 4: Start the Gateway

```bash
spark gateway
```

Send the bot a message to confirm it's live.

Use `/set-home` in any chat to designate it as the home channel for cron output and notifications.

---

## Security

### User Allowlist

Restrict who can use the bot by listing Feishu Open IDs:

```bash
FEISHU_ALLOWED_USERS=ou_xxx,ou_yyy
```

Without this, anyone who can reach the bot may interact with it.

### Group Message Policy

Control how the bot behaves in group chats:

```bash
FEISHU_GROUP_POLICY=allowlist   # default
```

| Value | Behavior |
|-------|----------|
| `open` | Responds to `@mentions` from any user in any group |
| `allowlist` | Responds only to `@mentions` from users in `FEISHU_ALLOWED_USERS` |
| `disabled` | Ignores all group messages |

### Webhook Signature Verification

When using webhook mode, enable payload verification with your app's encrypt key:

```bash
FEISHU_ENCRYPT_KEY=your-encrypt-key
```

Every request is verified using:
```
SHA256(timestamp + nonce + encrypt_key + body)
```

Requests with invalid or missing signatures are rejected with HTTP 401.

### Verification Token

An additional check on the `token` field inside webhook payloads:

```bash
FEISHU_VERIFICATION_TOKEN=your-verification-token
```

Payloads with mismatched tokens are rejected with HTTP 401. Both `FEISHU_ENCRYPT_KEY` and `FEISHU_VERIFICATION_TOKEN` can be used together for defense in depth.

:::tip
In WebSocket mode, signature verification is handled by the SDK automatically. `FEISHU_ENCRYPT_KEY` is optional there.
:::

---

## Per-Group Access Control

Fine-grained rules per group chat in `~/.spark/config.yaml`:

```yaml
platforms:
  feishu:
    extra:
      default_group_policy: "open"
      admins:
        - "ou_admin_open_id"
      group_rules:
        "oc_group_chat_id_1":
          policy: "allowlist"
          allowlist:
            - "ou_user_open_id_1"
            - "ou_user_open_id_2"
        "oc_group_chat_id_2":
          policy: "admin_only"
        "oc_group_chat_id_3":
          policy: "blacklist"
          blacklist:
            - "ou_blocked_user"
```

| Policy | Who can use the bot in this group |
|--------|----------------------------------|
| `open` | Anyone in the group |
| `allowlist` | Only users in the group's `allowlist` |
| `blacklist` | Everyone except users in the group's `blacklist` |
| `admin_only` | Only users in the global `admins` list |
| `disabled` | Nobody — bot ignores the group entirely |

Groups not listed in `group_rules` fall back to `default_group_policy`.

---

## Interactive Card Actions (Approval Buttons)

When the agent needs to run a risky command, it sends an interactive card with **Allow Once / Session / Always / Deny** buttons. You click a button; the card action delivers the approval back to the agent.

Button clicks are routed as synthetic `/card` command events:
```
/card button {"key": "value", ...}
```

### Required Feishu App Configuration

Three steps are needed — miss any one and card buttons silently fail with error **200340**:

1. **Subscribe to the card action event:** In **Event Subscriptions**, add `card.action.trigger`.
2. **Enable Interactive Card capability:** In **App Features > Bot**, toggle **Interactive Card** on.
3. **Set the Card Request URL** (webhook mode only): In **App Features > Bot > Message Card Request URL**, set the same URL as your event webhook.

:::warning
Without all three steps, cards display correctly but clicking any button returns error 200340.
:::

---

## Media Support

### Inbound

| Type | Extensions | Processing |
|------|-----------|-----------|
| Images | .jpg, .jpeg, .png, .gif, .webp, .bmp | Downloaded via Feishu API and cached locally |
| Audio | .ogg, .mp3, .wav, .m4a, .aac, .flac, .opus, .webm | Downloaded and cached |
| Video | .mp4, .mov, .avi, .mkv, .webm, .m4v, .3gp | Downloaded and cached as documents |
| Files | .pdf, .doc, .docx, .xls, .xlsx, .ppt, .pptx, and more | Downloaded and cached |

Small text files (.txt, .md) have their content injected directly into the message.

### Outbound

| Method | Sends |
|--------|-------|
| `send` | Text or rich post messages (auto-detected by markdown content) |
| `send_image` / `send_image_file` | Uploads image to Feishu, sends as native image bubble |
| `send_document` | Uploads file via Feishu API, sends as attachment |
| `send_voice` | Uploads audio as file attachment |
| `send_video` | Uploads and sends as native media message |
| `send_animation` | GIFs downgraded to file attachments (no native GIF bubble in Feishu) |

When outbound text contains markdown, it's sent as a Feishu **post** message. If the API rejects the post payload, the adapter falls back to plain text automatically.

---

## Burst Protection

### Text Batching

Multiple messages sent in quick succession are merged before dispatch:

| Setting | Env Var | Default |
|---------|---------|---------|
| Quiet period | `SPARK_FEISHU_TEXT_BATCH_DELAY_SECONDS` | 0.6s |
| Max messages per batch | `SPARK_FEISHU_TEXT_BATCH_MAX_MESSAGES` | 8 |
| Max characters per batch | `SPARK_FEISHU_TEXT_BATCH_MAX_CHARS` | 4000 |

### Media Batching

Multiple media attachments sent together are also merged:

| Setting | Env Var | Default |
|---------|---------|---------|
| Quiet period | `SPARK_FEISHU_MEDIA_BATCH_DELAY_SECONDS` | 0.8s |

Messages within the same chat are always processed one at a time. Different chats run concurrently.

---

## Webhook Rate Limiting

In webhook mode, per-IP rate limiting protects against abuse:

- **Window:** 60-second sliding window
- **Limit:** 120 requests per window per (app_id, path, IP) triple
- **Over-limit response:** HTTP 429
- **Body size limit:** 1 MB
- **Body read timeout:** 30 seconds
- **Content-Type enforcement:** Only `application/json` accepted

---

## WebSocket Tuning

```yaml
platforms:
  feishu:
    extra:
      ws_reconnect_interval: 120   # Seconds between reconnect attempts
      ws_ping_interval: 30         # WebSocket keepalive ping interval
```

---

## All Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `FEISHU_APP_ID` | — | Feishu/Lark App ID (required) |
| `FEISHU_APP_SECRET` | — | Feishu/Lark App Secret (required) |
| `FEISHU_DOMAIN` | `feishu` | `feishu` (China) or `lark` (international) |
| `FEISHU_CONNECTION_MODE` | `websocket` | `websocket` or `webhook` |
| `FEISHU_ALLOWED_USERS` | _(empty)_ | Comma-separated open_id list |
| `FEISHU_HOME_CHANNEL` | — | Chat ID for cron/notification output |
| `FEISHU_ENCRYPT_KEY` | _(empty)_ | Webhook signature verification key |
| `FEISHU_VERIFICATION_TOKEN` | _(empty)_ | Webhook payload auth token |
| `FEISHU_GROUP_POLICY` | `allowlist` | Group message policy |
| `FEISHU_BOT_OPEN_ID` | _(empty)_ | Bot's open_id for @mention detection |
| `FEISHU_BOT_USER_ID` | _(empty)_ | Bot's user_id for @mention detection |
| `FEISHU_BOT_NAME` | _(empty)_ | Bot's display name for @mention detection |
| `FEISHU_WEBHOOK_HOST` | `127.0.0.1` | Webhook server bind address |
| `FEISHU_WEBHOOK_PORT` | `8765` | Webhook server port |
| `FEISHU_WEBHOOK_PATH` | `/feishu/webhook` | Webhook endpoint path |
| `SPARK_FEISHU_DEDUP_CACHE_SIZE` | `2048` | Max deduplicated message IDs to track |
| `SPARK_FEISHU_TEXT_BATCH_DELAY_SECONDS` | `0.6` | Text burst debounce quiet period |
| `SPARK_FEISHU_TEXT_BATCH_MAX_MESSAGES` | `8` | Max messages merged per text batch |
| `SPARK_FEISHU_TEXT_BATCH_MAX_CHARS` | `4000` | Max characters merged per text batch |
| `SPARK_FEISHU_MEDIA_BATCH_DELAY_SECONDS` | `0.8` | Media burst debounce quiet period |

WebSocket and per-group ACL settings go in `config.yaml` under `platforms.feishu.extra`.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `lark-oapi not installed` | `pip install lark-oapi` |
| `websockets not installed; websocket mode unavailable` | `pip install websockets` |
| `aiohttp not installed; webhook mode unavailable` | `pip install aiohttp` |
| `FEISHU_APP_ID or FEISHU_APP_SECRET not set` | Set both env vars or run `spark gateway setup` |
| Another gateway already using this app_id | Only one Spark instance can use a given app_id. Stop the other one first. |
| Bot doesn't respond in groups | Confirm bot is @mentioned; check `FEISHU_GROUP_POLICY`; verify sender is in `FEISHU_ALLOWED_USERS` |
| `Webhook rejected: invalid verification token` | `FEISHU_VERIFICATION_TOKEN` must match the token in Event Subscriptions |
| `Webhook rejected: invalid signature` | `FEISHU_ENCRYPT_KEY` must match the encrypt key in your app config |
| Post messages show as plain text | Normal fallback when Feishu rejects the post payload — check logs for details |
| Images/files not received | Grant `im:message` and `im:resource` permission scopes |
| Bot identity not auto-detected | Grant `admin:app.info:readonly` scope, or set `FEISHU_BOT_OPEN_ID` / `FEISHU_BOT_NAME` manually |
| Error 200340 on approval buttons | Enable Interactive Card capability and set Card Request URL — see [Interactive Card Actions](#interactive-card-actions-approval-buttons) |
| `Webhook rate limit exceeded` | More than 120 req/min from same IP — usually a misconfiguration or loop |
