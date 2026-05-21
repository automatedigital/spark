---
sidebar_position: 5
title: "Scheduled Tasks (Cron)"
description: "Schedule automated tasks with natural language, manage them with one cron tool, and attach one or more skills"
---

# Scheduled Tasks (Cron)

Spark can run tasks on a schedule — daily digests, server health checks, feed summaries, whatever you need. Schedule them in plain English or with cron expressions. Manage them without ever touching a config file.

:::warning
Cron sessions cannot create more cron jobs. Spark disables cron management tools inside cron executions to prevent runaway scheduling loops.
:::

## Creating a Scheduled Task

### In Chat

```bash
/cron add 30m "Remind me to check the build"
/cron add "every 2h" "Check server status"
/cron add "every 1h" "Summarize new feed items" --skill blogwatcher
/cron add "every 1h" "Use both skills and combine the result" --skill blogwatcher --skill find-nearby
```

### From the CLI

```bash
spark cron create "every 2h" "Check server status"
spark cron create "every 1h" "Summarize new feed items" --skill blogwatcher
spark cron create "every 1h" "Use both skills and combine the result" \
  --skill blogwatcher \
  --skill find-nearby \
  --name "Skill combo"
```

### By Asking Naturally

```text
Every morning at 9am, check Hacker News for AI news and send me a summary on Telegram.
```

Spark translates this into a cron job automatically using the `cronjob` tool.

## Attaching Skills to a Job

Skills give a cron job reusable context without stuffing everything into the prompt.

### Single skill

```python
cronjob(
    action="create",
    skill="blogwatcher",
    prompt="Check the configured feeds and summarize anything new.",
    schedule="0 9 * * *",
    name="Morning feeds",
)
```

### Multiple skills

Skills load in order. The prompt runs on top of all of them.

```python
cronjob(
    action="create",
    skills=["blogwatcher", "find-nearby"],
    prompt="Look for new local events and interesting nearby places, then combine them into one short brief.",
    schedule="every 6h",
    name="Local brief",
)
```

## Schedule Formats

### One-shot (runs once)

```text
30m                     -> In 30 minutes
2h                      -> In 2 hours
1d                      -> In 1 day
2026-03-15T09:00:00     -> On March 15, 2026 at 9:00 AM
```

### Recurring intervals

```text
every 30m    -> Every 30 minutes
every 2h     -> Every 2 hours
every 1d     -> Every day
```

### Cron expressions

```text
0 9 * * *       -> Daily at 9:00 AM
0 9 * * 1-5     -> Weekdays at 9:00 AM
0 */6 * * *     -> Every 6 hours
30 8 1 * *      -> First of the month at 8:30 AM
0 0 * * 0       -> Every Sunday at midnight
```

### Repeat behavior

| Schedule type | Default | Behavior |
|--------------|---------|----------|
| One-shot (`30m`, timestamp) | 1 | Runs once |
| Interval (`every 2h`) | forever | Runs until removed |
| Cron expression | forever | Runs until removed |

Override the repeat count:

```python
cronjob(action="create", prompt="...", schedule="every 2h", repeat=5)
```

## Editing Jobs

No need to delete and recreate just to change something.

### In Chat

```bash
/cron edit <job_id> --schedule "every 4h"
/cron edit <job_id> --prompt "Use the revised task"
/cron edit <job_id> --skill blogwatcher --skill find-nearby
/cron edit <job_id> --remove-skill blogwatcher
/cron edit <job_id> --clear-skills
```

### From the CLI

```bash
spark cron edit <job_id> --schedule "every 4h"
spark cron edit <job_id> --prompt "Use the revised task"
spark cron edit <job_id> --skill blogwatcher --skill find-nearby
spark cron edit <job_id> --add-skill find-nearby        # append, don't replace
spark cron edit <job_id> --remove-skill blogwatcher
spark cron edit <job_id> --clear-skills
```

Skill flag behavior:

- `--skill` (repeated) replaces the entire attached skill list
- `--add-skill` appends without replacing
- `--remove-skill` removes one specific skill
- `--clear-skills` removes all attached skills

## Managing the Job Lifecycle

### In Chat

```bash
/cron list
/cron pause <job_id>
/cron resume <job_id>
/cron run <job_id>
/cron remove <job_id>
```

### From the CLI

```bash
spark cron list
spark cron pause <job_id>     # Stop scheduling; keep the job
spark cron resume <job_id>    # Re-enable + compute next run time
spark cron run <job_id>       # Trigger on the next scheduler tick
spark cron remove <job_id>    # Delete permanently
spark cron status
spark cron tick
```

### Programmatically

```python
cronjob(action="create", ...)
cronjob(action="list")
cronjob(action="update", job_id="...")
cronjob(action="pause", job_id="...")
cronjob(action="resume", job_id="...")
cronjob(action="run", job_id="...")
cronjob(action="remove", job_id="...")
```

Pass `skills=[]` to `update` to remove all attached skills.

## Where Output Goes

Specify a delivery target when creating a job:

| Target | Description |
|--------|-------------|
| `"origin"` | Back to where the job was created (default on messaging platforms) |
| `"local"` | Save to `~/.spark/cron/output/` only (default on CLI) |
| `"telegram"` | Telegram home channel (`TELEGRAM_HOME_CHANNEL`) |
| `"telegram:123456"` | Specific Telegram chat by ID |
| `"telegram:-100123:17585"` | Specific Telegram topic (`chat_id:thread_id`) |
| `"discord"` | Discord home channel (`DISCORD_HOME_CHANNEL`) |
| `"discord:#engineering"` | Specific Discord channel by name |
| `"slack"` | Slack home channel |
| `"whatsapp"` | WhatsApp home |
| `"signal"` | Signal |
| `"matrix"` | Matrix home room |
| `"mattermost"` | Mattermost home channel |
| `"email"` | Email |
| `"sms"` | SMS via Twilio |
| `"homeassistant"` | Home Assistant |
| `"dingtalk"` | DingTalk |
| `"feishu"` | Feishu/Lark |
| `"wecom"` | WeCom |
| `"weixin"` | Weixin (WeChat) |
| `"bluebubbles"` | BlueBubbles (iMessage) |
| `"qqbot"` | QQ Bot (Tencent QQ) |

The agent's final response is delivered automatically — you don't need to call `send_message` in the prompt for the same target.

### Response Wrapping

By default, delivered output is wrapped with a header so the recipient knows it's from a scheduled task:

```
Cronjob Response: Morning feeds
-------------

<agent output here>

Note: The agent cannot see this message, and therefore cannot respond to it.
```

To deliver raw output without the wrapper:

```yaml
# ~/.spark/config.yaml
cron:
  wrap_response: false
```

### Silent Suppression

If the agent's final response starts with `[SILENT]`, delivery is suppressed. Output is still saved locally to `~/.spark/cron/output/`, but no message is sent.

Useful for monitoring jobs that should only alert on problems:

```text
Check if nginx is running. If everything is healthy, respond with only [SILENT].
Otherwise, report the issue.
```

Failed jobs always deliver regardless of `[SILENT]` — only successful runs can be silenced.

## How the Scheduler Works

Cron execution is handled by the **gateway daemon**. The gateway ticks every 60 seconds and runs any due jobs in isolated agent sessions.

```bash
spark gateway install                        # Install as a user service
sudo spark gateway install --system          # Linux: boot-time system service
spark gateway                                # Or run in the foreground
```

On each tick, Spark:

1. Loads jobs from `~/.spark/cron/jobs.json`
2. Checks `next_run_at` against the current time
3. Starts a fresh `AIAgent` session for each due job
4. Injects any attached skills
5. Runs the prompt to completion
6. Delivers the final response
7. Updates run metadata and the next scheduled time

A file lock at `~/.spark/cron/.tick.lock` prevents overlapping ticks from double-running jobs.

## Script Timeout

Pre-run scripts have a default 120-second timeout. Increase it if your scripts need more time (e.g., for randomized delays):

```yaml
# ~/.spark/config.yaml
cron:
  script_timeout_seconds: 300   # 5 minutes
```

Or set the `SPARK_CRON_SCRIPT_TIMEOUT` environment variable. Resolution order: env var → `config.yaml` → 120s default.

## Provider Recovery

Cron jobs inherit your fallback providers and credential pool rotation. If the primary API key is rate-limited, the cron agent can fall back to an alternate provider or rotate to the next credential in your pool.

See: [credential pool strategies](../configuration.md#credential-pool-strategies).

## Writing Self-Contained Prompts

:::warning Important
Each cron job runs in a completely fresh agent session with no memory of previous sessions. Your prompt must contain everything the agent needs.
:::

**BAD:**
```text
Check on that server issue
```

**GOOD:**
```text
SSH into server 192.168.1.100 as user 'deploy', check if nginx is running with
'systemctl status nginx', and verify https://example.com returns HTTP 200.
```

## Storage

| What | Path |
|------|------|
| Job definitions | `~/.spark/cron/jobs.json` |
| Job output | `~/.spark/cron/output/{job_id}/{timestamp}.md` |

Job files use atomic writes — an interrupted write never leaves a partially written file.

## Security

Prompts are scanned for prompt-injection and credential-exfiltration patterns at creation and update time. Prompts with invisible Unicode tricks, SSH backdoor attempts, or obvious secret-exfiltration payloads are rejected.
