---
sidebar_position: 7
title: "Email"
description: "Set up Spark Agent as an email assistant via IMAP/SMTP"
---

# Email

Send an email, get a reply. Spark polls a dedicated inbox via IMAP, processes your message through the full agent pipeline, and replies in-thread via SMTP. No special client, no bot API, no third-party service — just standard email protocols. Works with Gmail, Outlook, Yahoo, Fastmail, or any provider that supports IMAP/SMTP.

:::info No External Dependencies
The Email adapter uses Python's built-in `imaplib`, `smtplib`, and `email` modules. Nothing extra to install.
:::

---

## What You Need Before Starting

- **A dedicated email account** — don't use your personal inbox. The agent stores credentials in `.env` and has full IMAP access.
- **IMAP enabled** on that account.
- **An app password** if using Gmail, Outlook, or any provider with 2FA.

### Gmail

1. Enable 2-Factor Authentication on your Google Account.
2. Go to [App Passwords](https://myaccount.google.com/apppasswords).
3. Create a new App Password (select "Mail" or "Other").
4. Copy the 16-character password — use this instead of your real password.

### Outlook / Microsoft 365

1. Go to [Security Settings](https://account.microsoft.com/security).
2. Enable 2FA if not already active.
3. Create an App Password under "Additional security options".
4. Use `outlook.office365.com` for IMAP and `smtp.office365.com` for SMTP.

### Other Providers

Check your provider's docs for IMAP/SMTP hosts and ports. Most use:
- IMAP: port 993, SSL
- SMTP: port 587, STARTTLS

---

## Configure Spark

The fastest path:

```bash
spark gateway setup
```

Select **Email** and follow the prompts for address, password, IMAP/SMTP hosts, and allowed senders.

### Manual Setup

Add to `~/.spark/.env`:

```bash
# Required
EMAIL_ADDRESS=spark@gmail.com
EMAIL_PASSWORD=abcd efgh ijkl mnop    # App password — not your real password
EMAIL_IMAP_HOST=imap.gmail.com
EMAIL_SMTP_HOST=smtp.gmail.com

# Recommended: restrict who can use the agent
EMAIL_ALLOWED_USERS=your@email.com,colleague@work.com

# Optional tuning
EMAIL_IMAP_PORT=993                   # Default: 993
EMAIL_SMTP_PORT=587                   # Default: 587
EMAIL_POLL_INTERVAL=15                # Seconds between inbox checks (default: 15)
EMAIL_HOME_ADDRESS=your@email.com     # Default recipient for cron output
```

---

## Start the Gateway

```bash
spark gateway              # Run in foreground
spark gateway install      # Install as a user service
sudo spark gateway install --system   # Linux only: start at boot
```

On startup, the adapter:
1. Tests IMAP and SMTP connectivity
2. Marks all existing inbox messages as "seen" — only new emails get processed
3. Starts polling for new messages

---

## How Emails Are Handled

### Receiving

Every `UNSEEN` message gets picked up at the poll interval (default: 15 seconds). For each one:

| Condition | What happens |
|-----------|-------------|
| Subject line | Added as context: `[Subject: Deploy to production]` |
| Reply emails (`Re:` prefix) | Subject prefix skipped — thread context is already established |
| Images (JPEG, PNG, GIF, WebP) | Cached locally; available to the vision tool |
| Documents (PDF, ZIP, etc.) | Cached locally; available for file access |
| HTML-only emails | Tags stripped for plain text extraction |
| Self-messages | Filtered out to prevent reply loops |
| Automated senders | Silently ignored (`noreply@`, `mailer-daemon@`, `bounce@`, `no-reply@`, and emails with `Auto-Submitted`, `Precedence: bulk`, or `List-Unsubscribe` headers) |

### Sending Replies

Replies use standard email threading headers:
- **In-Reply-To** and **References** keep messages in the same thread
- **Subject** preserved with a single `Re:` prefix (no `Re: Re:`)
- **Message-ID** generated with the agent's domain
- Sent as plain text (UTF-8)

### File Attachments

To attach a file in a reply, include `MEDIA:/path/to/file` in the response. The file is attached to the outgoing email.

### Skip Incoming Attachments

To ignore all attachment content (for security or bandwidth reasons):

```yaml
platforms:
  email:
    skip_attachments: true
```

The email body is still processed normally.

---

## Access Control

| Configuration | Result |
|--------------|--------|
| `EMAIL_ALLOWED_USERS` set | Only emails from those addresses are processed |
| No allowlist | Unknown senders receive a pairing code |
| `EMAIL_ALLOW_ALL_USERS=true` | Any sender is accepted — use with care |

:::warning
**Always set `EMAIL_ALLOWED_USERS`.** Without it, anyone who learns the agent's address can send commands. The agent has terminal access by default.
:::

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `EMAIL_ADDRESS` | Yes | - | Agent's email address |
| `EMAIL_PASSWORD` | Yes | - | Email password or app password |
| `EMAIL_IMAP_HOST` | Yes | - | IMAP server (e.g., `imap.gmail.com`) |
| `EMAIL_SMTP_HOST` | Yes | - | SMTP server (e.g., `smtp.gmail.com`) |
| `EMAIL_IMAP_PORT` | No | `993` | IMAP server port |
| `EMAIL_SMTP_PORT` | No | `587` | SMTP server port |
| `EMAIL_POLL_INTERVAL` | No | `15` | Seconds between inbox checks |
| `EMAIL_ALLOWED_USERS` | No | - | Comma-separated allowed sender addresses |
| `EMAIL_HOME_ADDRESS` | No | - | Default delivery target for cron jobs |
| `EMAIL_ALLOW_ALL_USERS` | No | `false` | Allow all senders |

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| **"IMAP connection failed"** | Verify `EMAIL_IMAP_HOST` and port. For Gmail, enable IMAP in Settings -> Forwarding and POP/IMAP. |
| **"SMTP connection failed"** | Verify `EMAIL_SMTP_HOST` and port. Confirm the app password is correct. |
| **Messages not received** | Check `EMAIL_ALLOWED_USERS` includes the sender. Check spam — some providers flag automated replies. |
| **"Authentication failed"** | For Gmail, you must use an App Password. Enable 2FA first, then generate one. |
| **Duplicate replies** | Make sure only one gateway instance is running: `spark gateway status`. |
| **Slow response** | Default poll interval is 15 seconds. Use `EMAIL_POLL_INTERVAL=5` to check more often (more IMAP connections). |
| **Replies not threading** | The adapter sets In-Reply-To headers correctly. Some web-based email clients don't thread automated messages well. |

---

## Security Checklist

- Use a **dedicated email account** — not your personal inbox
- Use **App Passwords** instead of your main password
- Set `EMAIL_ALLOWED_USERS` to limit who can interact with the agent
- Protect `~/.spark/.env`: `chmod 600 ~/.spark/.env`
- IMAP uses SSL (port 993) and SMTP uses STARTTLS (port 587) — connections are encrypted by default
