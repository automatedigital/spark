---
sidebar_position: 5
title: "WhatsApp"
description: "Set up Spark Agent as a WhatsApp bot via the built-in Baileys bridge"
---

# WhatsApp

Run Spark as a WhatsApp bot using the built-in Baileys bridge. This works by emulating a WhatsApp Web session — **not** through the official WhatsApp Business API. No Meta developer account or Business verification required.

:::warning Unofficial API — Ban Risk
WhatsApp doesn't officially support third-party bots outside the Business API. There's a small risk of account restrictions. To minimize it:
- **Use a dedicated phone number** for the bot — not your personal number
- **Keep usage conversational** — don't send bulk or unsolicited messages
- **Don't automate outbound messaging** to people who haven't messaged first
:::

:::warning WhatsApp Web Protocol Updates
WhatsApp periodically updates their Web protocol, which can temporarily break third-party bridges. When this happens, Spark updates the bridge dependency. If the bot stops working after a WhatsApp update, pull the latest Spark version and re-pair.
:::

## Choose Your Mode

| Mode | How it works | Best for |
|------|-------------|----------|
| **Separate bot number** (recommended) | Dedicate a phone number to the bot. People message that number directly. | Clean UX, multiple users, lower ban risk |
| **Personal self-chat** | Use your own WhatsApp. Message yourself to talk to the agent. | Quick setup, single user, testing |

## Prerequisites

- **Node.js v18+** and **npm** — the WhatsApp bridge runs as a Node.js process
- **A phone with WhatsApp** installed (for scanning the QR code)

The current Baileys-based bridge does **not** require Chromium or Puppeteer.

## Step 1: Pair with WhatsApp

```bash
spark whatsapp
```

The wizard:

1. Asks which mode you want (**bot** or **self-chat**)
2. Installs bridge dependencies if needed
3. Displays a **QR code** in your terminal
4. Waits for you to scan it

**To scan the QR code:**

1. Open WhatsApp on your phone
2. Go to **Settings -> Linked Devices**
3. Tap **Link a Device**
4. Point your camera at the terminal QR code

Once paired, the wizard confirms and exits. Your session is saved automatically.

:::tip
If the QR code looks garbled, ensure your terminal is at least 60 columns wide and supports Unicode. Try a different terminal emulator if needed.
:::

## Step 2: Get a Second Phone Number (Bot Mode)

For bot mode, you need a phone number not already registered with WhatsApp.

| Option | Cost | Notes |
|--------|------|-------|
| **Google Voice** | Free | US only. Get a number at [voice.google.com](https://voice.google.com). Verify WhatsApp via SMS through the Google Voice app. |
| **Prepaid SIM** | $5–15 one-time | Any carrier. Activate, verify WhatsApp, then put the SIM in a drawer. Make a call every 90 days to keep the number active. |
| **VoIP services** | Free–$5/month | TextNow, TextFree, or similar. Some VoIP numbers are blocked by WhatsApp — try a few if the first doesn't work. |

After getting the number:

1. Install WhatsApp on a phone (or use the WhatsApp Business app with dual-SIM)
2. Register the new number with WhatsApp
3. Run `spark whatsapp` and scan the QR code from that WhatsApp account

## Step 3: Configure Spark

```bash
# Required
WHATSAPP_ENABLED=true
WHATSAPP_MODE=bot                          # "bot" or "self-chat"

# Access control — pick ONE of these options:
WHATSAPP_ALLOWED_USERS=15551234567         # Comma-separated phone numbers (with country code, no +)
# WHATSAPP_ALLOWED_USERS=*                 # OR use * to allow everyone
# WHATSAPP_ALLOW_ALL_USERS=true            # OR set this flag instead (same effect as *)
```

:::tip Allow-all shorthand
`WHATSAPP_ALLOWED_USERS=*` allows all senders. This is equivalent to `WHATSAPP_ALLOW_ALL_USERS=true`.
To use the pairing flow instead, remove both variables and rely on the
[DM pairing system](whatsapp.md#dm-pairing).
:::

Optional behavior in `~/.spark/config.yaml`:

```yaml
unauthorized_dm_behavior: pair

whatsapp:
  unauthorized_dm_behavior: ignore
```

- `unauthorized_dm_behavior: pair` is the global default — unknown senders get a pairing code
- `whatsapp.unauthorized_dm_behavior: ignore` makes WhatsApp stay silent for unauthorized DMs, which is usually the better choice for a private number

Start the gateway:

```bash
spark gateway              # Foreground
spark gateway install      # Install as a user service
sudo spark gateway install --system   # Linux only: boot-time system service
```

The gateway starts the WhatsApp bridge automatically using the saved session.

## Session Persistence

The Baileys bridge saves its session under `~/.spark/platforms/whatsapp/session`:

- **Sessions survive restarts** — no re-scanning needed on every start
- The session data includes encryption keys and device credentials
- **Never share or commit this directory** — it grants full access to the WhatsApp account

## Re-pairing

If the session breaks (phone reset, WhatsApp update, manually unlinked), you'll see connection errors in the gateway logs.

```bash
spark whatsapp
```

This generates a fresh QR code. Scan it and the session is re-established. Temporary disconnections (network blips, phone going offline briefly) are handled automatically with reconnection logic.

## Voice Messages

- **Incoming:** Voice messages (`.ogg` opus) are automatically transcribed using the configured STT provider: local `faster-whisper`, Groq Whisper (`GROQ_API_KEY`), or OpenAI Whisper (`VOICE_TOOLS_OPENAI_KEY`)
- **Outgoing:** TTS responses are sent as MP3 audio file attachments

Customize the agent's reply prefix in `config.yaml`:

```yaml
# ~/.spark/config.yaml
whatsapp:
  reply_prefix: ""                          # Empty string disables the header
  # reply_prefix: " *My Bot*\n\n"  # Custom prefix (supports \n for newlines)
```

## Message Formatting and Delivery

WhatsApp supports **streaming (progressive) responses** — the bot edits its message in real-time as the AI generates text, just like Discord and Telegram.

### Chunking

Long responses automatically split at **4,096 characters** per chunk (WhatsApp's practical display limit). The gateway handles splitting and sends chunks sequentially.

### WhatsApp-Compatible Markdown

Standard Markdown in AI responses converts to WhatsApp's native formatting:

| Markdown | WhatsApp | Renders as |
|----------|----------|------------|
| `**bold**` | `*bold*` | **bold** |
| `~~strikethrough~~` | `~strikethrough~` | ~~strikethrough~~ |
| `# Heading` | `*Heading*` | Bold text (no native headings) |
| `[link text](url)` | `link text (url)` | Inline URL |

Code blocks and inline code are preserved as-is — WhatsApp supports triple-backtick formatting natively.

### Tool Progress

When the agent calls tools (web search, file operations, etc.), WhatsApp displays real-time progress indicators showing which tool is running. Enabled by default.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| **QR code not scanning** | Ensure terminal is 60+ columns wide. Try a different terminal. Make sure you're scanning from the correct WhatsApp account (bot number, not personal). |
| **QR code expires** | QR codes refresh every ~20 seconds. If it times out, restart `spark whatsapp`. |
| **Session not persisting** | Check that `~/.spark/platforms/whatsapp/session` exists and is writable. If containerized, mount it as a persistent volume. |
| **Logged out unexpectedly** | WhatsApp unlinks devices after long inactivity. Keep the phone on and connected, then re-pair with `spark whatsapp`. |
| **Bridge crashes or reconnect loops** | Restart the gateway, update Spark, and re-pair if the session was invalidated by a WhatsApp protocol change. |
| **Bot stops working after WhatsApp update** | Update Spark to get the latest bridge version, then re-pair. |
| **macOS: "Node.js not installed" but node works in terminal** | launchd services don't inherit your shell PATH. Run `spark gateway install` to re-snapshot your current PATH into the plist, then `spark gateway start`. See the [Gateway Service docs](./index.md#macos-launchd) for details. |
| **Messages not being received** | Verify `WHATSAPP_ALLOWED_USERS` includes the sender's number (with country code, no `+` or spaces), or set it to `*` to allow everyone. Set `WHATSAPP_DEBUG=true` in `.env` and restart to see raw message events in `bridge.log`. |
| **Bot replies to strangers with a pairing code** | Set `whatsapp.unauthorized_dm_behavior: ignore` in `~/.spark/config.yaml` to silently ignore unauthorized DMs instead. |

## Security

:::warning
Set `WHATSAPP_ALLOWED_USERS` before going live. Use specific phone numbers (with country code, without `+`), `*` to allow everyone, or `WHATSAPP_ALLOW_ALL_USERS=true`. Without any of these, the gateway **denies all incoming messages** as a safety measure.
:::

To keep a private WhatsApp number silent to strangers:

```yaml
whatsapp:
  unauthorized_dm_behavior: ignore
```

Additional steps to protect your setup:

- The `~/.spark/platforms/whatsapp/session` directory contains full session credentials — protect it like a password
- Set file permissions: `chmod 700 ~/.spark/platforms/whatsapp/session`
- Use a **dedicated phone number** for the bot to isolate risk from your personal account
- If you suspect compromise, unlink the device via WhatsApp -> Settings -> Linked Devices
- Phone numbers in logs are partially redacted, but review your log retention policy
