---
sidebar_position: 3
title: "Updating & Uninstalling"
description: "How to update Spark Agent to the latest version or uninstall it"
---

# Updating & Uninstalling

## Update Spark

```bash
spark update
```

That's the whole command. It pulls the latest code, updates dependencies, and prompts you about any new config options added since your last update.

:::tip Missed the config prompt?
Run `spark config check` to see missing options, then `spark config migrate` to add them interactively.
:::

### What `spark update` does

| Step | Details |
|---|---|
| Git pull | Pulls the latest code from `main` and updates submodules |
| Dependency install | Runs `uv pip install -e ".[all]"` to pick up changes |
| Config migration | Detects new config options and prompts you to set them |
| Gateway restart | If a gateway service is running (systemd/launchd), restarts it automatically |

Expected output:

```
$ spark update
Updating Spark Agent...
 Pulling latest code...
Already up to date.
 Updating dependencies...
 Dependencies updated
 Checking for new config options...
 Config is up to date
 Restarting gateway service...
 Gateway restarted
 Spark Agent updated successfully!
```

### Validate after updating

A quick check after every update is worth the habit:

```bash
git status --short      # look for unexpected dirty state
spark doctor            # checks config, deps, and service health
spark --version         # confirm the version bumped
spark gateway status    # if you run the gateway
```

:::warning Dirty working tree?
If `git status --short` shows unexpected changes, inspect them before continuing. This usually means local modifications were reapplied on top of new code, or a dependency step refreshed lockfiles.
:::

### Check your current version

```bash
spark version
```

Or check for updates without applying them:

```bash
spark update --check
```

Compare against the [GitHub releases page](https://github.com/automatedigital/spark/releases).

### Update from a messaging platform

Send `/update` in Telegram, Discord, Slack, or WhatsApp. Spark pulls the latest code, updates dependencies, and restarts the gateway. The bot goes offline briefly (5–15 seconds) then resumes.

### Manual update

If you installed manually rather than via the quick installer:

```bash
cd /path/to/spark-agent
export VIRTUAL_ENV="$(pwd)/venv"

git pull origin main
git submodule update --init --recursive

uv pip install -e ".[all]"
uv pip install -e "./tinker-atropos"

spark config check
spark config migrate   # add any missing options interactively
```

## Roll back to a previous version

If an update breaks something:

```bash
cd /path/to/spark-agent

git log --oneline -10              # find a good commit
git checkout <commit-hash>
git submodule update --init --recursive
uv pip install -e ".[all]"

spark gateway restart              # if you run the gateway
```

To roll back to a specific release tag:

```bash
git checkout v0.6.0
git submodule update --init --recursive
uv pip install -e ".[all]"
```

:::warning Config compatibility after rollback
Rolling back may cause config issues if new options were added. Run `spark config check` and remove any unrecognized keys from `config.yaml` if you get errors.
:::

## Uninstall Spark

```bash
spark uninstall
```

The uninstaller asks whether to keep your `~/.spark/` files so you can reinstall later without losing config and sessions.

### Manual uninstall

```bash
rm -f ~/.local/bin/spark
rm -rf /path/to/spark-agent
rm -rf ~/.spark            # optional — keep if you plan to reinstall
```

:::info Running the gateway as a service?
Stop and disable it first:
```bash
spark gateway stop
# Linux: systemctl --user disable spark-gateway
# macOS: launchctl remove ai.spark.gateway
```
:::
