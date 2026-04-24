# BlueBubbles (iMessage)

Send and receive iMessages from Spark. [BlueBubbles](https://bluebubbles.app/) is a free, open-source macOS server that bridges your Mac's Messages.app to any device. Once connected, Spark can read and send iMessages, handle media attachments, and react to messages.

```
iMessage -> Messages.app -> BlueBubbles Server -> Webhook -> Spark
Spark -> BlueBubbles REST API -> Messages.app -> iMessage
```

## What You Need

- A **Mac that stays on** with [BlueBubbles Server](https://bluebubbles.app/) installed
- An Apple ID signed into Messages.app on that Mac
- BlueBubbles Server v1.0.0+ (older versions don't support webhooks)
- Network access between your Spark machine and the Mac

## Get Connected in 5 Steps

### 1. Install BlueBubbles Server

Download from [bluebubbles.app](https://bluebubbles.app/). Run the setup wizard — sign in with your Apple ID and pick a connection method (local network, Ngrok, Cloudflare, or Dynamic DNS).

### 2. Grab Your Server URL and Password

In BlueBubbles Server: **Settings -> API**. Note both:
- **Server URL** (e.g., `http://192.168.1.10:1234`)
- **Server Password**

### 3. Configure Spark

Run the guided setup:

```bash
spark gateway setup
```

Select **BlueBubbles (iMessage)**, then enter your server URL and password.

Or write them directly to `~/.spark/.env`:

```bash
BLUEBUBBLES_SERVER_URL=http://192.168.1.10:1234
BLUEBUBBLES_PASSWORD=your-server-password
```

### 4. Decide Who Can Reach the Bot

Pick one approach:

**DM Pairing (recommended):** When someone messages your iMessage, Spark sends them a pairing code. Approve it with:
```bash
spark pairing approve bluebubbles <CODE>
```
List pending codes and approved users with `spark pairing list`.

**Pre-authorize specific contacts** (in `~/.spark/.env`):
```bash
BLUEBUBBLES_ALLOWED_USERS=user@icloud.com,+15551234567
```

**Open access** (in `~/.spark/.env`):
```bash
BLUEBUBBLES_ALLOW_ALL_USERS=true
```

### 5. Start the Gateway

```bash
spark gateway run
```

Spark registers a webhook with BlueBubbles and begins listening for messages. No polling — delivery is instant.

## What Works

### Messaging
- Send and receive iMessages. Markdown is stripped for clean plain-text delivery.

### Rich Media
| Type | Support |
|------|---------|
| Images | Appear natively in iMessage |
| Voice messages | Sent as iMessage voice attachments |
| Videos | Sent as video attachments |
| Documents | Sent as iMessage file attachments |

Inbound attachments are downloaded and cached locally so the agent can process them.

### Private API Features

Some features require the [Private API helper](https://docs.bluebubbles.app/helper-bundle/installation):

| Feature | Private API required? |
|---------|----------------------|
| Tapback reactions (love, like, dislike, etc.) | Yes |
| Typing indicators | Yes |
| Read receipts | Yes |
| Create new chats by phone/email | Yes |
| Basic text and media | No |

### Chat Addressing

Use phone numbers or email addresses directly — Spark resolves them to BlueBubbles chat GUIDs automatically.

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BLUEBUBBLES_SERVER_URL` | Yes | - | BlueBubbles server URL |
| `BLUEBUBBLES_PASSWORD` | Yes | - | Server password |
| `BLUEBUBBLES_WEBHOOK_HOST` | No | `127.0.0.1` | Webhook listener bind address |
| `BLUEBUBBLES_WEBHOOK_PORT` | No | `8645` | Webhook listener port |
| `BLUEBUBBLES_WEBHOOK_PATH` | No | `/bluebubbles-webhook` | Webhook URL path |
| `BLUEBUBBLES_HOME_CHANNEL` | No | - | Phone/email for cron delivery |
| `BLUEBUBBLES_ALLOWED_USERS` | No | - | Comma-separated authorized users |
| `BLUEBUBBLES_ALLOW_ALL_USERS` | No | `false` | Allow all users |
| `BLUEBUBBLES_SEND_READ_RECEIPTS` | No | `true` | Auto-mark messages as read |

## Troubleshooting

**"Cannot reach server"**
- Confirm the Mac is on and BlueBubbles Server is running
- Check network connectivity, firewall rules, and port forwarding

**Messages not arriving**
- Verify the webhook is registered: BlueBubbles Server -> Settings -> API -> Webhooks
- Confirm the webhook URL is reachable from the Mac
- Check logs: `spark logs gateway` (or `spark logs -f` to follow live)

**"Private API helper not connected"**
- Install it: [docs.bluebubbles.app](https://docs.bluebubbles.app/helper-bundle/installation)
- Basic messaging still works without it — only reactions, typing indicators, and read receipts are blocked
