---
sidebar_position: 7
title: "Sessions"
description: "Session persistence, resume, search, management, and per-platform session tracking"
---

# Sessions

Every conversation Spark has is automatically saved. You can pick up where you left off, search across your entire history, and manage everything from the command line.

## What Gets Saved

Sessions are stored in two places:

| Store | Path | Contains |
|-------|------|----------|
| SQLite database | `~/.spark/state.db` | Session metadata + full message history with FTS5 full-text search |
| JSONL transcripts | `~/.spark/sessions/` | Raw conversation transcripts including tool calls (gateway) |

Each session record includes: session ID, title, source platform, model name, system prompt snapshot, full message history (with tool calls and results), token counts, timestamps, and a parent session ID for compression lineages.

## Every Platform, One Store

Sessions from every platform feed the same database:

| Source | Description |
|--------|-------------|
| `cli` | Interactive CLI (`spark` or `spark chat`) |
| `telegram` | Telegram messenger |
| `discord` | Discord server/DM |
| `slack` | Slack workspace |
| `whatsapp` | WhatsApp messenger |
| `signal` | Signal messenger |
| `matrix` | Matrix rooms and DMs |
| `mattermost` | Mattermost channels |
| `email` | Email (IMAP/SMTP) |
| `sms` | SMS via Twilio |
| `dingtalk` | DingTalk messenger |
| `feishu` | Feishu/Lark messenger |
| `wecom` | WeCom (WeChat Work) |
| `weixin` | Weixin (personal WeChat) |
| `bluebubbles` | Apple iMessage via BlueBubbles macOS server |
| `qqbot` | QQ Bot (Tencent QQ) via Official API v2 |
| `homeassistant` | Home Assistant conversation |
| `webhook` | Incoming webhooks |
| `api-server` | API server requests |
| `acp` | ACP editor integration |
| `cron` | Scheduled cron jobs |
| `batch` | Batch processing runs |

## Resuming a Conversation

### Jump Back In

```bash
# Pick up your most recent CLI session
spark --continue
spark -c

# Same thing with the chat subcommand
spark chat --continue
spark chat -c
```

### Resume by Name

```bash
# Resume a session you named
spark -c "my project"

# If there are multiple sessions in a lineage (my project, my project #2, etc.)
# this picks the most recent one automatically
spark -c "my project"   # -> resumes "my project #3"
```

### Resume by ID

```bash
# Exact session ID
spark --resume 20250305_091523_a1b2c3d4
spark -r 20250305_091523_a1b2c3d4

# Or by title
spark --resume "refactoring auth"
```

Session IDs appear when you exit a CLI session and in `spark sessions list`.

### The Recap Panel

When you resume, Spark shows a compact summary of the previous conversation before dropping you back at the prompt:

<img className="docs-terminal-figure" src="/img/docs/session-recap.svg" alt="Stylized preview of the Previous Conversation recap panel shown when resuming a Spark session." />
<p className="docs-figure-caption">Resume mode shows a compact recap panel with recent user and assistant turns before returning you to the live prompt.</p>

The recap shows the last 10 exchanges. It truncates long messages, collapses tool calls to a count, and hides system messages and tool results. Older messages show as `... N earlier messages ...`.

Prefer a minimal one-liner instead? Set this in `~/.spark/config.yaml`:

```yaml
display:
  resume_display: minimal   # default: full
```

:::tip
Session IDs follow the format `YYYYMMDD_HHMMSS_<8-char-hex>`, e.g. `20250305_091523_a1b2c3d4`. You can use either an ID or a title with both `-c` and `-r`.
:::

## Naming Sessions

Named sessions are easier to find and resume. You have two ways to name them.

### Auto-Titling

Spark generates a short descriptive title (3-7 words) after your first exchange. It runs in a background thread using a fast auxiliary model — zero latency impact. Auto-titling is skipped if you've already set a title manually.

### Set a Title Yourself

Inside any chat session:

```text
/title my research project
```

Or rename from the command line:

```bash
spark sessions rename 20250305_091523_a1b2c3d4 "refactoring auth module"
```

### Title Rules

- Unique across all sessions
- Max 100 characters
- Control characters, zero-width chars, and RTL overrides are stripped automatically
- Emoji, CJK, and accented characters are fine

### Lineage on Compression

When context compression creates a continuation session, the title carries forward with a number:

```
"my project" -> "my project #2" -> "my project #3"
```

`spark -c "my project"` always picks the latest in the chain.

## Managing Sessions

### List

```bash
spark sessions list                         # Last 20 sessions
spark sessions list --source telegram       # Filter by platform
spark sessions list --limit 50             # Show more
```

Output with titles:

```
Title                  Preview                                  Last Active   ID

refactoring auth       Help me refactor the auth module please   2h ago        20250305_091523_a
my project #3          Can you check the test failures?          yesterday     20250304_143022_e
-                      What's the weather in Las Vegas?          3d ago        20250303_101500_f
```

### Export

```bash
# All sessions
spark sessions export backup.jsonl

# One platform only
spark sessions export telegram-history.jsonl --source telegram

# Single session
spark sessions export session.jsonl --session-id 20250305_091523_a1b2c3d4
```

Each line in the output file is a complete JSON object with full session metadata and messages.

### Delete

```bash
spark sessions delete 20250305_091523_a1b2c3d4       # Prompts for confirmation
spark sessions delete 20250305_091523_a1b2c3d4 --yes  # Skip confirmation
```

### Rename

```bash
spark sessions rename 20250305_091523_a1b2c3d4 "debugging auth flow"

# Quotes are optional for multi-word titles in the CLI
spark sessions rename 20250305_091523_a1b2c3d4 debugging auth flow
```

### Prune Old Sessions

```bash
spark sessions prune                                    # Sessions older than 90 days
spark sessions prune --older-than 30                    # Custom threshold
spark sessions prune --source telegram --older-than 60  # One platform only
spark sessions prune --older-than 30 --yes              # Skip confirmation
```

:::info
Pruning only removes **ended** sessions. Active sessions are never deleted.
:::

### Stats

```bash
spark sessions stats
```

```
Total sessions: 142
Total messages: 3847
  cli: 89 sessions
  telegram: 38 sessions
  discord: 15 sessions
Database size: 12.4 MB
```

For token usage, cost estimates, tool breakdown, and activity patterns, use [`spark insights`](cli/commands-reference.md#spark-insights).

## Search Across All Sessions

The agent has a built-in `session_search` tool that runs full-text search across your entire conversation history using SQLite's FTS5 engine.

**How it works:**

1. FTS5 ranks matching messages by relevance
2. Groups results by session, takes the top N unique sessions (default 3)
3. Loads each session's conversation, truncates to ~100K chars centered on the matches
4. A fast summarization model produces focused summaries
5. Returns per-session summaries with metadata and context

**FTS5 query syntax:**

| Pattern | Example |
|---------|---------|
| Keywords | `docker deployment` |
| Phrase | `"exact phrase"` |
| Boolean | `docker OR kubernetes`, `python NOT java` |
| Prefix | `deploy*` |

The agent uses session search automatically when you reference something from a past conversation — so you don't have to repeat yourself.

## Group and Multi-User Sessions

### Per-User Isolation in Group Chats

By default, `group_sessions_per_user: true` in `config.yaml` gives each person their own private session inside a shared channel or group. Alice and Bob can both talk to Spark in the same Discord channel without sharing history.

To switch to a single shared "room brain":

```yaml
group_sessions_per_user: false
```

That creates one session per room — shared context, shared token costs, shared interrupt state.

### Session Key Format

| Chat Type | Key Format |
|-----------|--------------------|
| DM (any platform) | `agent:main:<platform>:dm:<chat_id>` |
| Group chat | `agent:main:<platform>:group:<chat_id>:<user_id>` |
| Group thread | `agent:main:<platform>:group:<chat_id>:<thread_id>` |
| Channel | `agent:main:<platform>:channel:<chat_id>:<user_id>` |

### Auto-Reset Policies

Gateway sessions reset automatically based on configurable policy:

| Policy | Behavior |
|--------|----------|
| `idle` | Reset after N minutes of inactivity |
| `daily` | Reset at a specific hour each day |
| `both` | Whichever comes first |
| `none` | Never auto-reset |

Before an auto-reset, the agent saves memories and skills from the session. Sessions with active background processes are never auto-reset.

## Storage Details

The SQLite database runs in WAL mode for concurrent readers, which suits the gateway's multi-platform architecture.

Key tables in `state.db`:

- **sessions** — metadata (id, source, user_id, model, title, timestamps, token counts)
- **messages** — full history (role, content, tool_calls, tool_name, token_count)
- **messages_fts** — FTS5 virtual table for full-text search

### Cleanup

```bash
# Export first, then prune
spark sessions export backup.jsonl
spark sessions prune --older-than 30 --yes
```

:::tip
The database grows slowly — typically 10-15 MB for hundreds of sessions. Pruning is mainly useful when you want to clean out old conversations that are no longer relevant for search recall.
:::
