---
sidebar_position: 21
title: "Switch Profiles"
description: "Isolate work vs personal agents with Spark profiles."
---

# Switch Profiles

[Profiles](/docs/cli/profiles) give each agent its own `SPARK_HOME` — completely isolated config, `.env`, memories, sessions, skills, and gateway. Work and personal never bleed into each other.

## Create a Profile

```bash
spark profile create work --clone    # copy config/env/SOUL from current profile
spark profile create personal        # start blank; run personal setup
```

## Set a Default Profile

```bash
spark profile use work
spark chat                           # now uses the work profile
```

## Use a Profile for One Command

```bash
spark -p personal chat -q "Hello"
coder chat                           # if a `coder` alias exists
```

## Profiles and Gateways

Each profile stores its own bot tokens in `~/.spark/profiles/<name>/.env`. Run `spark gateway start` separately for each profile, or use per-profile `gateway install` services.

## See Also

- [Profile commands reference](/docs/cli/profiles#profile-commands-reference)
- [FAQ — profiles](/docs/reference/faq#profiles)
