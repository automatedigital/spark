---
sidebar_position: 11
title: "Cron Internals"
description: "How Spark stores, schedules, edits, pauses, skill-loads, and delivers cron jobs"
---

# Cron Internals

The cron subsystem handles everything from one-shot delays to recurring cron-expression jobs — with skill injection, script-backed data collection, and cross-platform delivery to wherever you need results.

## Key files

| File | Purpose |
|------|---------|
| `cron/jobs.py` | Job model, storage, atomic read/write to `jobs.json` |
| `cron/scheduler.py` | Scheduler loop — due-job detection, execution, repeat tracking |
| `tools/cronjob_tools.py` | Model-facing `cronjob` tool registration and handler |
| `gateway/run.py` | Gateway integration — cron ticking in the long-running loop |
| `spark_cli/cron.py` | CLI `spark cron` subcommands |

## Schedule formats

| Format | Example | Behavior |
|--------|---------|----------|
| **Relative delay** | `30m`, `2h`, `1d` | One-shot, fires after the specified duration |
| **Interval** | `every 2h`, `every 30m` | Recurring, fires at regular intervals |
| **Cron expression** | `0 9 * * *` | Standard 5-field cron syntax (minute, hour, day, month, weekday) |
| **ISO timestamp** | `2025-01-15T09:00:00` | One-shot, fires at the exact time |

The model interacts with a single `cronjob` tool using action-style operations: `create`, `list`, `update`, `pause`, `resume`, `run`, `remove`.

## Job storage

Jobs live in `~/.spark/cron/jobs.json`. Writes are atomic — Spark writes to a temp file first, then renames it. Each job record looks like this:

```json
{
  "id": "a1b2c3d4e5f6",
  "name": "Daily briefing",
  "prompt": "Summarize today's AI news and funding rounds",
  "schedule": {
    "kind": "cron",
    "expr": "0 9 * * *",
    "display": "0 9 * * *"
  },
  "skills": ["ai-funding-daily-report"],
  "deliver": "telegram:-1001234567890",
  "repeat": {
    "times": null,
    "completed": 42
  },
  "state": "scheduled",
  "enabled": true,
  "next_run_at": "2025-01-16T09:00:00Z",
  "last_run_at": "2025-01-15T09:00:00Z",
  "last_status": "ok",
  "created_at": "2025-01-01T00:00:00Z",
  "model": null,
  "provider": null,
  "script": null
}
```

### Job lifecycle states

| State | Meaning |
|-------|---------|
| `scheduled` | Active — will fire at next scheduled time |
| `paused` | Suspended — won't fire until resumed |
| `completed` | Repeat count exhausted, or one-shot that has already fired |
| `running` | Currently executing (transient) |

### Backward compatibility

Older jobs may have a single `skill` field instead of a `skills` array. The scheduler normalizes this at load time — `skill` is promoted to `skills: [skill]` automatically.

## How the scheduler runs

### Tick cycle

The scheduler fires on a periodic tick (default: every 60 seconds):

```text
tick()
  1. Acquire scheduler lock (prevents overlapping ticks)
  2. Load all jobs from jobs.json
  3. Filter to due jobs (next_run <= now AND state == "scheduled")
  4. For each due job:
     a. Set state to "running"
     b. Create a fresh AIAgent session (no conversation history)
     c. Load attached skills in order (injected as user messages)
     d. Run the job prompt through the agent
     e. Deliver the response to the configured target
     f. Update run_count, compute next_run
     g. If repeat count exhausted -> state = "completed"
     h. Otherwise -> state = "scheduled"
  5. Write updated jobs back to jobs.json
  6. Release scheduler lock
```

### Gateway vs. CLI mode

In **gateway mode**, the scheduler tick runs inside the gateway's main event loop. The gateway calls `scheduler.tick()` on its periodic maintenance cycle, alongside message handling.

In **CLI mode**, cron jobs only fire during active CLI sessions or when you run `spark cron` commands directly.

### Fresh session isolation

Each cron job runs in a completely fresh agent session:

- No conversation history from previous runs
- No memory of previous cron executions (unless you explicitly persist data to memory or files)
- Prompts must be self-contained — cron jobs cannot ask clarifying questions
- The `cronjob` toolset is disabled (recursion guard — see below)

## Skill-backed jobs

Attach one or more skills to a cron job via the `skills` field. At execution time:

1. Skills load in the specified order
2. Each skill's `SKILL.md` content injects as context
3. The job's prompt appends as the task instruction
4. The agent processes the combined skill context + prompt

This lets you build reusable, tested workflows without copying full instructions into every cron prompt. For example:

```
Create a daily funding report -> attach "ai-funding-daily-report" skill
```

## Script-backed jobs

Attach a Python script via the `script` field. The script runs before each agent turn, and its stdout injects into the prompt as context. This is ideal for data collection and change-detection workflows:

```python
# ~/.spark/scripts/check_competitors.py
import requests, json
# Fetch competitor release notes, diff against last run
# Print summary to stdout - agent analyzes and reports
```

Script timeout defaults to 120 seconds. `_get_script_timeout()` resolves the limit through a four-layer chain:

1. **Module-level override** — `_SCRIPT_TIMEOUT` (for tests/monkeypatching). Only used when it differs from the default.
2. **Environment variable** — `SPARK_CRON_SCRIPT_TIMEOUT`
3. **Config** — `cron.script_timeout_seconds` in `config.yaml` (read via `load_config()`)
4. **Default** — 120 seconds

## Provider recovery

`run_job()` passes your configured fallback providers and credential pool into the `AIAgent` instance:

- **Fallback providers** — reads `fallback_providers` (list) or `fallback_model` (legacy dict) from `config.yaml`. Passed as `fallback_model=` to `AIAgent.__init__`, which normalizes both formats into a fallback chain.
- **Credential pool** — loads via `load_pool(provider)` from `agent.credential_pool`. Only passed when the pool has credentials. Enables same-provider key rotation on 429/rate-limit errors.

Without this, cron agents would fail hard on rate limits with no recovery path.

## Delivery targets

| Target | Syntax | Example |
|--------|--------|---------|
| Origin chat | `origin` | Deliver to the chat where the job was created |
| Local file | `local` | Save to `~/.spark/cron/output/` |
| Telegram | `telegram` or `telegram:<chat_id>` | `telegram:-1001234567890` |
| Discord | `discord` or `discord:#channel` | `discord:#engineering` |
| Slack | `slack` | Deliver to Slack home channel |
| WhatsApp | `whatsapp` | Deliver to WhatsApp home |
| Signal | `signal` | Deliver to Signal |
| Matrix | `matrix` | Deliver to Matrix home room |
| Mattermost | `mattermost` | Deliver to Mattermost home |
| Email | `email` | Deliver via email |
| SMS | `sms` | Deliver via SMS |
| Home Assistant | `homeassistant` | Deliver to HA conversation |
| DingTalk | `dingtalk` | Deliver to DingTalk |
| Feishu | `feishu` | Deliver to Feishu |
| WeCom | `wecom` | Deliver to WeCom |
| Weixin | `weixin` | Deliver to Weixin (WeChat) |
| BlueBubbles | `bluebubbles` | Deliver to iMessage via BlueBubbles |
| QQ Bot | `qqbot` | Deliver to QQ (Tencent) via Official API v2 |

For Telegram topics, use `telegram:<chat_id>:<thread_id>` (e.g., `telegram:-1001234567890:17585`).

### Response wrapping

By default (`cron.wrap_response: true`), cron deliveries include:
- A header identifying the cron job name and task
- A footer noting the agent cannot see the delivered message in conversation

Use the `[SILENT]` prefix in a cron response to suppress delivery entirely — useful for jobs that only need to write files or perform side effects.

### Session isolation

Cron deliveries are NOT mirrored into gateway session conversation history. They exist only in the cron job's own session. This prevents message alternation violations in the target chat.

## Recursion guard

Cron-run sessions have the `cronjob` toolset disabled. This prevents:
- A scheduled job from creating new cron jobs
- Recursive scheduling that could blow up token usage
- Accidental mutation of the job schedule from within a job

## Locking

The scheduler uses file-based locking to prevent overlapping ticks from executing the same due-job batch twice. This matters in gateway mode, where maintenance cycles can overlap if a previous tick takes longer than the tick interval.

## CLI reference

```bash
spark cron list                    # Show all jobs
spark cron create                  # Interactive job creation (alias: add)
spark cron edit <job_id>           # Edit job configuration
spark cron pause <job_id>          # Pause a running job
spark cron resume <job_id>         # Resume a paused job
spark cron run <job_id>            # Trigger immediate execution
spark cron remove <job_id>         # Delete a job
```

## Related docs

- [Cron Feature Guide](/docs/automate/cron)
- [Gateway Internals](./gateway-internals.md)
- [Agent Loop Internals](./agent-loop.md)
