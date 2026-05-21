---
sidebar_position: 20
title: "Deploy on a VPS"
description: "Run Spark on a small Linux VPS and reach it from Telegram (or another gateway)."
---

# Deploy on a VPS

A $5/month Linux VPS is all you need to keep Spark running 24/7. Spark runs as a long-lived process; the gateway handles messages to and from Telegram, Discord, and other platforms.

## Setup Steps

1. **SSH in.** Install Python 3.11+, git, and any build dependencies your install method needs.

2. **Install Spark.** Clone the repo or use your usual install method, create a venv, and run `pip install -e ".[dev]"`. See the [Installation guide](../getting-started/installation.md).

3. **Configure credentials.** Add your provider keys and `TELEGRAM_BOT_TOKEN` (or your platform's token) to `~/.spark/.env`. Set up `config.yaml` using the [Configuration docs](../configuration.md).

4. **Keep the gateway alive across reboots.** The cleanest option is the built-in service installer:
   ```bash
   spark gateway install              # systemd/launchd user service
   sudo spark gateway install --system  # Linux: boot-time system service
   ```
   For a quick test without installing a service:
   ```bash
   spark gateway start   # or use tmux/screen
   ```

5. **Firewall.** Allow outbound HTTPS. Only open inbound ports if you're exposing the [API server](../integrations/api-server.md) — in that case, bind to localhost and put a reverse proxy in front.

## Use a Dedicated Profile

Create an isolated [profile](../cli/profiles.md) for the server bot so production keys and sessions stay separate from any local dev work:

```bash
spark profile create mybot
```

Run all gateway operations under that profile.

## See Also

- [Messaging overview](../chat-platforms/index.md)
- [Switch profiles](switch-profiles.md)
