---
sidebar_position: 11
title: "Automate Anything with Cron"
description: "Real-world automation patterns using Spark cron - monitoring, reports, pipelines, and multi-skill workflows"
---

# Automate Anything with Cron

Got the basics from the [daily briefing bot tutorial](/docs/guides/daily-briefing-bot)? This guide goes further — five real-world patterns you can steal and adapt.

Full reference: [Scheduled Tasks (Cron)](/docs/automate/cron).

:::info One rule you can't break
Cron jobs run in a fresh agent session every time — no memory of your current chat, no prior context. Your prompt must be **completely self-contained**. Include every URL, repo name, format preference, and instruction directly in the prompt text.
:::

---

## Pattern 1: Website Change Monitor

Get notified only when a page actually changes — no noise on quiet days.

The trick: a Python script runs before each execution. Its stdout becomes context for the agent. The script does the mechanical work (fetching, diffing); the agent decides what's interesting.

Create the monitoring script:

```bash
mkdir -p ~/.spark/scripts
```

```python title="~/.spark/scripts/watch-site.py"
import hashlib, json, os, urllib.request

URL = "https://example.com/pricing"
STATE_FILE = os.path.expanduser("~/.spark/scripts/.watch-site-state.json")

# Fetch current content
req = urllib.request.Request(URL, headers={"User-Agent": "Spark-Monitor/1.0"})
content = urllib.request.urlopen(req, timeout=30).read().decode()
current_hash = hashlib.sha256(content.encode()).hexdigest()

# Load previous state
prev_hash = None
if os.path.exists(STATE_FILE):
    with open(STATE_FILE) as f:
        prev_hash = json.load(f).get("hash")

# Save current state
with open(STATE_FILE, "w") as f:
    json.dump({"hash": current_hash, "url": URL}, f)

# Output for the agent
if prev_hash and prev_hash != current_hash:
    print(f"CHANGE DETECTED on {URL}")
    print(f"Previous hash: {prev_hash}")
    print(f"Current hash: {current_hash}")
    print(f"\nCurrent content (first 2000 chars):\n{content[:2000]}")
else:
    print("NO_CHANGE")
```

Wire up the cron job:

```bash
/cron add "every 1h" "If the script output says CHANGE DETECTED, summarize what changed on the page and why it might matter. If it says NO_CHANGE, respond with just [SILENT]." --script ~/.spark/scripts/watch-site.py --name "Pricing monitor" --deliver telegram
```

:::tip The [SILENT] trick
When the agent's final response contains `[SILENT]`, delivery is suppressed. Use it liberally in monitoring jobs so you only get notified when something real happens.
:::

---

## Pattern 2: Weekly Digest

Pull from multiple sources once a week, compile into a formatted summary.

```bash
/cron add "0 9 * * 1" "Generate a weekly report covering:

1. Search the web for the top 5 AI news stories from the past week
2. Search GitHub for trending repositories in the 'machine-learning' topic
3. Check Hacker News for the most discussed AI/ML posts

Format as a clean summary with sections for each source. Include links.
Keep it under 500 words - highlight only what matters." --name "Weekly AI digest" --deliver telegram
```

From the CLI instead:

```bash
spark cron create "0 9 * * 1" \
  "Generate a weekly report covering the top AI news, trending ML GitHub repos, and most-discussed HN posts. Format with sections, include links, keep under 500 words." \
  --name "Weekly AI digest" \
  --deliver telegram
```

`0 9 * * 1` = 9:00 AM every Monday.

---

## Pattern 3: GitHub Repository Watcher

Track a repository for new issues, PRs, or releases every six hours.

```bash
/cron add "every 6h" "Check the GitHub repository automatedigital/spark for:
- New issues opened in the last 6 hours
- New PRs opened or merged in the last 6 hours
- Any new releases

Use the terminal to run gh commands:
  gh issue list --repo automatedigital/spark --state open --json number,title,author,createdAt --limit 10
  gh pr list --repo automatedigital/spark --state all --json number,title,author,createdAt,mergedAt --limit 10

Filter to only items from the last 6 hours. If nothing new, respond with [SILENT].
Otherwise, provide a concise summary of the activity." --name "Repo watcher" --deliver discord
```

:::warning Include the exact commands
Notice the prompt includes the full `gh` commands. The cron agent has no memory of your setup — spell out everything.
:::

---

## Pattern 4: Data Collection Pipeline

Collect data on a schedule, accumulate a history file, and have the agent analyze trends. The script does the collection; the agent adds the reasoning.

```python title="~/.spark/scripts/collect-prices.py"
import json, os, urllib.request
from datetime import datetime

DATA_DIR = os.path.expanduser("~/.spark/data/prices")
os.makedirs(DATA_DIR, exist_ok=True)

# Fetch current data (example: crypto prices)
url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=usd"
data = json.loads(urllib.request.urlopen(url, timeout=30).read())

# Append to history file
entry = {"timestamp": datetime.now().isoformat(), "prices": data}
history_file = os.path.join(DATA_DIR, "history.jsonl")
with open(history_file, "a") as f:
    f.write(json.dumps(entry) + "\n")

# Load recent history for analysis
lines = open(history_file).readlines()
recent = [json.loads(l) for l in lines[-24:]]  # Last 24 data points

# Output for the agent
print(f"Current: BTC=${data['bitcoin']['usd']}, ETH=${data['ethereum']['usd']}")
print(f"Data points collected: {len(lines)} total, showing last {len(recent)}")
print(f"\nRecent history:")
for r in recent[-6:]:
    print(f"  {r['timestamp']}: BTC=${r['prices']['bitcoin']['usd']}, ETH=${r['prices']['ethereum']['usd']}")
```

```bash
/cron add "every 1h" "Analyze the price data from the script output. Report:
1. Current prices
2. Trend direction over the last 6 data points (up/down/flat)
3. Any notable movements (>5% change)

If prices are flat and nothing notable, respond with [SILENT].
If there's a significant move, explain what happened." \
  --script ~/.spark/scripts/collect-prices.py \
  --name "Price tracker" \
  --deliver telegram
```

---

## Pattern 5: Multi-Skill Workflow

Chain skills together for complex scheduled tasks. Skills load in order before the prompt executes.

```bash
# Use the arxiv skill to find papers, then the obsidian skill to save notes
/cron add "0 8 * * *" "Search arXiv for the 3 most interesting papers on 'language model reasoning' from the past day. For each paper, create an Obsidian note with the title, authors, abstract summary, and key contribution." \
  --skill arxiv \
  --skill obsidian \
  --name "Paper digest"
```

Or via the tool directly:

```python
cronjob(
    action="create",
    skills=["arxiv", "obsidian"],
    prompt="Search arXiv for papers on 'language model reasoning' from the past day. Save the top 3 as Obsidian notes.",
    schedule="0 8 * * *",
    name="Paper digest",
    deliver="local"
)
```

Skills load in the order you specify — `arxiv` first (teaches how to search papers), then `obsidian` (teaches how to write notes).

---

## Managing jobs

```bash
/cron list                          # List all active jobs
/cron run <job_id>                  # Trigger immediately (great for testing)
/cron pause <job_id>                # Pause without deleting
/cron edit <job_id> --schedule "every 4h"
/cron edit <job_id> --prompt "Updated task description"
/cron edit <job_id> --skill arxiv --skill obsidian
/cron edit <job_id> --clear-skills
/cron remove <job_id>               # Delete permanently
```

---

## Delivery targets

| Target | Example | When to use |
|--------|---------|------------|
| `origin` | `--deliver origin` | Same chat that created the job (default) |
| `local` | `--deliver local` | Save to local file only |
| `telegram` | `--deliver telegram` | Your Telegram home channel |
| `discord` | `--deliver discord` | Your Discord home channel |
| `slack` | `--deliver slack` | Your Slack home channel |
| Specific chat | `--deliver telegram:-1001234567890` | A specific Telegram group |
| Threaded | `--deliver telegram:-1001234567890:17585` | A specific Telegram topic thread |

---

## Troubleshooting jobs that aren't working

### Jobs not firing

Work through these checks in order:

**Is the job active?**
```bash
spark cron list
```
Confirm the state shows `[active]`, not `[paused]` or `[completed]`.

**Is the schedule valid?**

| Expression | Meaning |
|-----------|---------|
| `0 9 * * *` | 9:00 AM every day |
| `0 9 * * 1` | 9:00 AM every Monday |
| `every 2h` | Every 2 hours from now |
| `30m` | 30 minutes from now (one-shot) |
| `2025-06-01T09:00:00` | Specific datetime (one-shot) |

One-shot schedules (`30m`, `1d`, ISO timestamps) disappear from the list after firing — that's expected.

**Is the gateway running?** Cron jobs require a running gateway to fire automatically. A plain CLI session won't trigger them. Start it with `spark gateway` or install as a service.

**Is the clock right?** Jobs use local timezone. Verify with `date` and compare `next_run` times in `spark cron list`.

---

### Delivery failures

**Check the target is configured:**

| Target | Requires |
|--------|----------|
| `telegram` | `TELEGRAM_BOT_TOKEN` in `~/.spark/.env` |
| `discord` | `DISCORD_BOT_TOKEN` in `~/.spark/.env` |
| `slack` | `SLACK_BOT_TOKEN` in `~/.spark/.env` |
| `local` | Write access to `~/.spark/cron/output/` |

Other supported platforms: `mattermost`, `homeassistant`, `dingtalk`, `feishu`, `wecom`, `weixin`, `bluebubbles`, `qqbot`, `webhook`, `email`, `sms`, `signal`, `matrix`, `whatsapp`.

**Check `[SILENT]` isn't suppressing everything.** If your prompt says "respond with [SILENT] if nothing changed" but the condition logic is wrong, you'll silence real results too.

**Check bot permissions:**
- Telegram: bot must be admin in the target group/channel
- Discord: bot must have send permission in the target channel
- Slack: bot must be added to the workspace with `chat:write` scope

**Disable response wrapping if needed:**
```yaml
cron:
  wrap_response: false
```

---

### Skill loading failures

**Verify skills are installed:** `spark skills list`

**Check the exact skill name.** Names are case-sensitive and must match the folder name.

**Some skills require interactive tools** that are disabled in cron context (`clarify`, `send_message`, `execute_code`). Check that your skill works in headless mode.

**Multi-skill order matters.** If Skill A depends on context from Skill B, load B first:
```bash
/cron add "0 9 * * *" "..." --skill context-skill --skill target-skill
```

---

### Job errors

**Common patterns:**

- `"No such file or directory"` for scripts — use absolute paths: `~/.spark/scripts/your-script.py`
- `"Skill not found"` — skills don't sync between machines; reinstall with `spark skills install <skill-name>`
- Job delivers nothing — usually a delivery target issue or `[SILENT]` suppression
- Job hangs — the scheduler times out after 600s of inactivity (configurable via `SPARK_CRON_TIMEOUT`). Use scripts for data collection so the agent only handles the reasoning step.

**Lock contention:** Two gateway instances can cause jobs to be skipped. Kill duplicates:
```bash
ps aux | grep spark
```

**Check jobs.json permissions:**
```bash
ls -la ~/.spark/cron/jobs.json
chmod 600 ~/.spark/cron/jobs.json
```

---

### Performance tips

- **Stagger overlapping jobs.** Jobs run sequentially in each tick. `0 9 * * *` and `5 9 * * *` instead of both at `0 9 * * *`.
- **Filter script output.** Scripts that dump megabytes will hit token limits. Emit only what the agent needs to reason about.
- **Add buffer time.** Each job creates a fresh agent session. Build in a few minutes of margin on time-sensitive schedules.

---

## Diagnostic commands

```bash
spark cron list                    # All jobs, states, next_run times
spark cron run <job_id>            # Schedule for next tick (for testing)
spark cron edit <job_id>           # Fix configuration issues
spark logs                         # View recent Spark logs
spark skills list                  # Verify installed skills
```

If you've worked through all of this and the problem persists, open an issue at [github.com/automatedigital/spark](https://github.com/automatedigital/spark) with the job ID, schedule, delivery target, what you expected, and the relevant error from `~/.spark/logs/agent.log`.

---

*For the complete cron reference, see [Scheduled Tasks (Cron)](/docs/automate/cron).*
