---
sidebar_position: 6
title: "Signal"
description: "Set up Spark Agent as a Signal messenger bot via signal-cli daemon"
---

# Run Spark on Signal

Signal gives you end-to-end encryption, an open-source protocol, and minimal metadata collection. If you're running agent workflows where privacy matters, Signal is the right platform.

Spark talks to Signal through [signal-cli](https://github.com/AsamK/signal-cli) — a Java-based daemon you run locally. The adapter connects via SSE (Server-Sent Events) for incoming messages and JSON-RPC for sending. No new Python packages required; it uses `httpx`, which Spark already depends on.

---

## What You Need Before Starting

- **signal-cli** installed and on your PATH
- **Java 17+** (required by signal-cli)
- **A phone number** with Signal active (you'll link it as a secondary device)

### Install signal-cli

```bash
# macOS
brew install signal-cli

# Linux (download directly from GitHub releases)
VERSION=$(curl -Ls -o /dev/null -w %{url_effective} \
  https://github.com/AsamK/signal-cli/releases/latest | sed 's/^.*\/v//')
curl -L -O "https://github.com/AsamK/signal-cli/releases/download/v${VERSION}/signal-cli-${VERSION}.tar.gz"
sudo tar xf "signal-cli-${VERSION}.tar.gz" -C /opt
sudo ln -sf "/opt/signal-cli-${VERSION}/bin/signal-cli" /usr/local/bin/
```

:::caution
signal-cli is **not** in apt or snap. The Linux install above pulls directly from [GitHub releases](https://github.com/AsamK/signal-cli/releases).
:::

---

## Step 1: Link Your Phone Number

Signal-cli acts as a linked secondary device — just like Signal Desktop. Your phone stays the primary.

```bash
signal-cli link -n "SparkAgent"
```

Then on your phone:
1. Open Signal
2. Go to **Settings -> Linked Devices**
3. Tap **Link New Device**
4. Scan the QR code or paste the URI

---

## Step 2: Start the signal-cli Daemon

```bash
# Use your Signal number in E.164 format
signal-cli --account +1234567890 daemon --http 127.0.0.1:8080
```

Keep this running in the background via `systemd`, `tmux`, or a service manager.

Confirm it's alive:

```bash
curl http://127.0.0.1:8080/api/v1/check
# Expected: {"versions":{"signal-cli":...}}
```

---

## Step 3: Connect Spark

Run the interactive wizard:

```bash
spark gateway setup
```

Pick **Signal** from the menu. It will check for signal-cli, test connectivity, prompt for your account number, and configure access policies.

### Skip the wizard — configure manually

Add to `~/.spark/.env`:

```bash
# Required
SIGNAL_HTTP_URL=http://127.0.0.1:8080
SIGNAL_ACCOUNT=+1234567890

# Recommended: restrict who can message the bot
SIGNAL_ALLOWED_USERS=+1234567890,+0987654321    # E.164 numbers or UUIDs

# Optional
SIGNAL_GROUP_ALLOWED_USERS=groupId1,groupId2     # Omit to disable groups; * for all
SIGNAL_HOME_CHANNEL=+1234567890                  # Default target for cron jobs
```

Start the gateway:

```bash
spark gateway              # Foreground
spark gateway install      # Install as a user service
sudo spark gateway install --system   # Linux only: boot-time system service
```

---

## Controlling Who Can Message the Bot

### Direct messages

| Configuration | What happens |
|---------------|--------------|
| `SIGNAL_ALLOWED_USERS` set | Only listed numbers/UUIDs can message |
| No allowlist set | Unknown senders get a pairing code — approve with `spark pairing approve signal CODE` |
| `SIGNAL_ALLOW_ALL_USERS=true` | Anyone can message (use carefully) |

### Groups

| `SIGNAL_GROUP_ALLOWED_USERS` value | Behavior |
|------------------------------------|----------|
| Not set (default) | Groups ignored — bot only responds to DMs |
| Specific group IDs | Only those groups are monitored |
| `*` | Bot responds in every group it belongs to |

---

## What the Bot Can Do

### Send and receive media

**Incoming (user to agent):**
- Images: PNG, JPEG, GIF, WebP (format auto-detected)
- Audio: MP3, OGG, WAV, M4A — voice messages transcribed if Whisper is configured
- Documents: PDF, ZIP, and other file types

**Outgoing (agent to user):**
- Images via `send_image_file`
- Audio/voice via `send_voice`
- Video via `send_video`
- Documents via `send_document`

All attachments go through Signal's standard attachment API. Size limit: **100 MB** in both directions.

### Typing indicators

The bot sends typing indicators while it's working, refreshing every 8 seconds.

### Talk to yourself (Note to Self)

Running signal-cli linked to your own number? You can interact with Spark through Signal's "Note to Self" — just message yourself. The adapter detects `syncMessage.sentMessage` envelopes addressed to the bot's own account and treats them as inbound messages. Echo protection prevents loops. Nothing to configure — works automatically as long as `SIGNAL_ACCOUNT` matches your number.

### Phone number privacy in logs

All phone numbers are automatically redacted in logs: `+15551234567` becomes `+155****4567`.

### Automatic reconnection

If the SSE connection drops, the adapter reconnects with exponential backoff (2s up to 60s). If no activity is detected for 120 seconds, it pings signal-cli to verify the connection is still live.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| "Cannot reach signal-cli" during setup | Confirm the daemon is running: `signal-cli --account +YOUR_NUMBER daemon --http 127.0.0.1:8080` |
| Messages not received | Check that the sender's number is in `SIGNAL_ALLOWED_USERS` with the `+` prefix (E.164) |
| "signal-cli not found on PATH" | Install signal-cli or add it to your PATH |
| Connection keeps dropping | Check signal-cli logs and confirm Java 17+ is installed |
| Group messages ignored | Set `SIGNAL_GROUP_ALLOWED_USERS` to specific group IDs or `*` |
| Bot responds to no one | Set `SIGNAL_ALLOWED_USERS`, enable DM pairing, or set `SIGNAL_ALLOW_ALL_USERS=true` |
| Duplicate messages | Make sure only one signal-cli instance is running for your number |

---

## Security Notes

:::warning
Always configure access controls. The bot has terminal access. Without `SIGNAL_ALLOWED_USERS` or DM pairing enabled, the gateway denies all incoming messages by default.
:::

- Use an allowlist or DM pairing — don't leave the bot open
- Keep groups disabled unless you specifically need them, and allowlist only groups you trust
- Signal's end-to-end encryption protects message content in transit
- The signal-cli session at `~/.local/share/signal-cli/` contains account credentials — protect it like a password

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SIGNAL_HTTP_URL` | Yes | — | signal-cli HTTP endpoint |
| `SIGNAL_ACCOUNT` | Yes | — | Bot phone number (E.164) |
| `SIGNAL_ALLOWED_USERS` | No | — | Comma-separated phone numbers or UUIDs |
| `SIGNAL_GROUP_ALLOWED_USERS` | No | — | Group IDs to monitor, or `*` for all (omit to disable) |
| `SIGNAL_ALLOW_ALL_USERS` | No | `false` | Skip the allowlist — allow everyone |
| `SIGNAL_HOME_CHANNEL` | No | — | Default delivery target for cron jobs |
