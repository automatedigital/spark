---
sidebar_position: 8
sidebar_label: "SMS (Twilio)"
title: "SMS (Twilio)"
description: "Set up Spark Agent as an SMS chatbot via Twilio"
---

# Run Spark over SMS

Text your Twilio number. Get an AI response back. Same conversational experience as any other Spark platform — no app required, works on every phone.

Spark handles SMS through [Twilio](https://www.twilio.com/). Twilio delivers messages to your server via webhook; Spark processes them and replies through the Twilio API.

:::info Shared Credentials
If you've already set up Twilio for voice calls or one-off SMS using the telephony skill, the gateway reuses the same `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, and `TWILIO_PHONE_NUMBER`.
:::

---

## What You Need

- A [Twilio account](https://www.twilio.com/try-twilio) with a phone number that has SMS capability
- A **publicly accessible server** — Twilio POSTs webhooks to your server when a message arrives
- The `aiohttp` package: `pip install 'spark-agent[sms]'`

---

## Setup

### 1. Get Your Twilio Credentials

1. Open the [Twilio Console](https://console.twilio.com/)
2. Copy your **Account SID** and **Auth Token** from the dashboard
3. Go to **Phone Numbers -> Manage -> Active Numbers** and note your number in E.164 format (e.g. `+15551234567`)

### 2. Configure Spark

Run the wizard:

```bash
spark gateway setup
```

Select **SMS (Twilio)** and enter your credentials.

Or add directly to `~/.spark/.env`:

```bash
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token_here
TWILIO_PHONE_NUMBER=+15551234567

# Restrict to specific numbers (recommended)
SMS_ALLOWED_USERS=+15559876543,+15551112222

# Optional: home channel for cron job delivery
SMS_HOME_CHANNEL=+15559876543
```

### 3. Point Twilio at Your Server

In the [Twilio Console](https://console.twilio.com/):

1. Go to **Phone Numbers -> Manage -> Active Numbers**
2. Click your number
3. Under **Messaging -> A MESSAGE COMES IN**, set:
   - **Webhook**: `https://your-server:8080/webhooks/twilio`
   - **HTTP Method**: `POST`

:::tip Running locally?
Use a tunnel to expose the webhook:

```bash
# cloudflared
cloudflared tunnel --url http://localhost:8080

# ngrok
ngrok http 8080
```

Paste the resulting URL into Twilio Console.
:::

Then set `SMS_WEBHOOK_URL` to **the same URL** you put in Twilio Console — this is required for signature validation:

```bash
SMS_WEBHOOK_URL=https://your-server:8080/webhooks/twilio
```

The port defaults to `8080`. Override it:

```bash
SMS_WEBHOOK_PORT=3000
```

### 4. Start the Gateway

```bash
spark gateway
```

You'll see:

```
[sms] Twilio webhook server listening on 0.0.0.0:8080, from: +1555***4567
```

If you see `Refusing to start: SMS_WEBHOOK_URL is required`, set `SMS_WEBHOOK_URL` to the public URL you configured in Twilio Console.

Text your Twilio number — Spark responds via SMS.

---

## How SMS Works

SMS is plain text. The gateway handles the rough edges automatically:

- **Markdown stripped** — SMS renders it as literal characters, so Spark removes it
- **1600 character limit** — longer responses split across multiple messages at natural boundaries (newlines, then spaces)
- **Echo prevention** — messages from your own Twilio number are ignored
- **Phone number redaction** — numbers are masked in logs for privacy

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `TWILIO_ACCOUNT_SID` | Yes | Account SID (starts with `AC`) |
| `TWILIO_AUTH_TOKEN` | Yes | Auth Token — also used for webhook signature validation |
| `TWILIO_PHONE_NUMBER` | Yes | Your Twilio number (E.164 format) |
| `SMS_WEBHOOK_URL` | Yes | Public URL matching your Twilio Console webhook — required for signature validation |
| `SMS_WEBHOOK_PORT` | No | Listener port (default: `8080`) |
| `SMS_WEBHOOK_HOST` | No | Bind address (default: `0.0.0.0`) |
| `SMS_INSECURE_NO_SIGNATURE` | No | `true` disables signature validation — local dev only, never production |
| `SMS_ALLOWED_USERS` | No | Comma-separated E.164 numbers allowed to chat |
| `SMS_ALLOW_ALL_USERS` | No | `true` to allow anyone (not recommended) |
| `SMS_HOME_CHANNEL` | No | Phone number for cron/notification delivery |
| `SMS_HOME_CHANNEL_NAME` | No | Display name for home channel (default: `Home`) |

---

## Security

### Webhook signature validation

Spark validates every inbound webhook using the `X-Twilio-Signature` header (HMAC-SHA1). This blocks forged requests from anyone who isn't Twilio.

`SMS_WEBHOOK_URL` must match the webhook URL in your Twilio Console exactly. The adapter refuses to start without it.

For local development without a public URL:

```bash
# Local dev only — NOT for production
SMS_INSECURE_NO_SIGNATURE=true
```

### Access control

The gateway denies all users by default. Configure an allowlist:

```bash
# Specific numbers only
SMS_ALLOWED_USERS=+15559876543,+15551112222

# Open to anyone (not recommended for bots with terminal access)
SMS_ALLOW_ALL_USERS=true
```

:::warning
SMS has no built-in encryption. Don't use it for sensitive operations. For privacy-sensitive workflows, use Signal or Telegram instead.
:::

---

## Troubleshooting

### Messages not arriving

1. Confirm your webhook URL is publicly reachable
2. Double-check `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN`
3. Check **Monitor -> Logs -> Messaging** in the Twilio Console
4. Make sure the sender's number is in `SMS_ALLOWED_USERS` (or set `SMS_ALLOW_ALL_USERS=true`)

### Replies not sending

1. Verify `TWILIO_PHONE_NUMBER` is in E.164 format with the `+` prefix
2. Confirm your Twilio number has SMS capability
3. Check gateway logs for Twilio API errors

### Port conflict

If port 8080 is taken:

```bash
SMS_WEBHOOK_PORT=3001
```

Update the webhook URL in Twilio Console to match the new port.
