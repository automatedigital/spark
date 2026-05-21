---
sidebar_position: 24
title: "Deploy to a Slack Team"
description: "Wire Spark's gateway to a Slack workspace."
---

# Deploy to a Slack Team

The [Slack messaging doc](../chat-platforms/slack.md) is your source of truth for tokens, scopes, and event configuration. This page gives you the outline.

## Steps

1. **Create a Slack app** in your workspace and add the required bot scopes. See the messaging doc for the full scope list.

2. **Add your credentials** to `~/.spark/.env` for the profile that will run the bot:
   ```bash
   SLACK_BOT_TOKEN=xoxb-...
   ```
   Add any signing secret the same way.

3. **Enable Slack in your config.** Set `slack` (or the equivalent key) in [configuration](../configuration.md) so the gateway activates the Slack adapter.

4. **Start the gateway** for that profile:
   ```bash
   spark gateway start
   ```
   Or install it as a persistent service:
   ```bash
   spark gateway install
   ```

## Multiple Workspaces

Need separate tokens and session data per workspace? Use separate [profiles](../cli/profiles.md) — one per workspace.

## See Also

- [Slash commands reference](../cli/slash-commands.md) (gateway routing)
