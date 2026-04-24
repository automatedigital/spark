---
sidebar_position: 6
title: "Session Storage"
description: "SQLite schema, write contention handling, search, and lineage for Spark session storage"
---

# Session Storage

All conversation history lives in a single SQLite database at `~/.spark/state.db`. Every CLI session, gateway session, and platform conversation writes to this file. Here's what's inside and how to work with it.

Source file: `spark_state.py`

## Database Structure

```
~/.spark/state.db (SQLite, WAL mode)
 sessions          - Session metadata, token counts, billing
 messages          - Full message history per session
 messages_fts      - FTS5 virtual table for full-text search
 schema_version    - Single-row table tracking migration state
```

Key design decisions:
- **WAL mode** — concurrent readers plus one writer (handles gateway multi-platform)
- **FTS5 virtual table** — fast full-text search across all messages
- **Session lineage** — `parent_session_id` chains sessions split by context compression
- **Source tagging** — `cli`, `telegram`, `discord`, etc. for platform-specific filtering
- Batch runner and RL trajectories are NOT stored here — they use separate systems

## Schema

### sessions

```sql
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    user_id TEXT,
    model TEXT,
    model_config TEXT,
    system_prompt TEXT,
    parent_session_id TEXT,
    started_at REAL NOT NULL,
    ended_at REAL,
    end_reason TEXT,
    message_count INTEGER DEFAULT 0,
    tool_call_count INTEGER DEFAULT 0,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cache_read_tokens INTEGER DEFAULT 0,
    cache_write_tokens INTEGER DEFAULT 0,
    reasoning_tokens INTEGER DEFAULT 0,
    billing_provider TEXT,
    billing_base_url TEXT,
    billing_mode TEXT,
    estimated_cost_usd REAL,
    actual_cost_usd REAL,
    cost_status TEXT,
    cost_source TEXT,
    pricing_version TEXT,
    title TEXT,
    FOREIGN KEY (parent_session_id) REFERENCES sessions(id)
);
```

### messages

```sql
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,
    content TEXT,
    tool_call_id TEXT,
    tool_calls TEXT,
    tool_name TEXT,
    timestamp REAL NOT NULL,
    token_count INTEGER,
    finish_reason TEXT,
    reasoning TEXT,
    reasoning_details TEXT,
    codex_reasoning_items TEXT
);
```

Notes:
- `tool_calls` is a JSON string (serialized list of tool call objects)
- `reasoning_details` and `codex_reasoning_items` are JSON strings
- `reasoning` stores raw reasoning text from providers that expose it
- Timestamps are Unix epoch floats (`time.time()`)

### FTS5 Full-Text Search

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content,
    content=messages,
    content_rowid=id
);
```

Three triggers keep the FTS5 table in sync automatically — on INSERT, UPDATE, and DELETE of the `messages` table.

## Schema Migrations

Current version: **6**

| Version | Change |
|---------|--------|
| 1 | Initial schema (sessions, messages, FTS5) |
| 2 | Add `finish_reason` to messages |
| 3 | Add `title` to sessions |
| 4 | Add unique index on `title` (NULLs allowed, non-NULL must be unique) |
| 5 | Add billing columns: cache tokens, reasoning tokens, billing provider/URL/mode, cost fields |
| 6 | Add reasoning columns to messages: `reasoning`, `reasoning_details`, `codex_reasoning_items` |

Each migration uses `ALTER TABLE ADD COLUMN` inside a try/except — idempotent, safe to re-run.

## Handling Write Contention

Multiple Spark processes (gateway + CLI sessions + worktree agents) share one `state.db`. `SessionDB` handles contention with:

- **Short SQLite timeout** (1 second) instead of the default 30s
- **Application-level retry** with random jitter (20–150ms, up to 15 retries)
- **`BEGIN IMMEDIATE`** transactions to surface lock contention at transaction start
- **Periodic WAL checkpoints** every 50 writes (PASSIVE mode)

This avoids the convoy effect where SQLite's deterministic internal backoff causes all competing writers to retry in lock-step.

```
_WRITE_MAX_RETRIES = 15
_WRITE_RETRY_MIN_S = 0.020   # 20ms
_WRITE_RETRY_MAX_S = 0.150   # 150ms
_CHECKPOINT_EVERY_N_WRITES = 50
```

## Working with SessionDB

### Initialize

```python
from spark_state import SessionDB

db = SessionDB()                              # Default: ~/.spark/state.db
db = SessionDB(db_path=Path("/tmp/test.db"))  # Custom path for testing
```

### Sessions

```python
# Create
db.create_session(
    session_id="sess_abc123",
    source="cli",
    model="anthropic/claude-sonnet-4.6",
    user_id="user_1",
    parent_session_id=None,  # or previous session ID for lineage
)

# End
db.end_session("sess_abc123", end_reason="user_exit")

# Reopen (clears ended_at and end_reason)
db.reopen_session("sess_abc123")
```

### Messages

```python
# Write
msg_id = db.append_message(
    session_id="sess_abc123",
    role="assistant",
    content="Here's the answer...",
    tool_calls=[{"id": "call_1", "function": {"name": "terminal", "arguments": "{}"}}],
    token_count=150,
    finish_reason="stop",
    reasoning="Let me think about this...",
)

# Read — raw rows
messages = db.get_messages("sess_abc123")

# Read — OpenAI conversation format (for API replay)
conversation = db.get_messages_as_conversation("sess_abc123")
# Returns: [{"role": "user", "content": "..."}, {"role": "assistant", ...}]
```

### Session Titles

```python
# Set (must be unique among non-NULL titles)
db.set_session_title("sess_abc123", "Fix Docker Build")

# Resolve by title (returns most recent in lineage)
session_id = db.resolve_session_by_title("Fix Docker Build")

# Auto-generate next title in lineage
next_title = db.get_next_title_in_lineage("Fix Docker Build")
# Returns: "Fix Docker Build #2"
```

## Full-Text Search

`search_messages()` supports the full FTS5 query syntax, with automatic sanitization of user input.

### Query Syntax

| Syntax | Example | Meaning |
|--------|---------|---------|
| Keywords | `docker deployment` | Both terms (implicit AND) |
| Quoted phrase | `"exact phrase"` | Exact phrase match |
| Boolean OR | `docker OR kubernetes` | Either term |
| Boolean NOT | `python NOT java` | Exclude term |
| Prefix | `deploy*` | Prefix match |

### Filtering

```python
# Search only CLI sessions
results = db.search_messages("error", source_filter=["cli"])

# Exclude gateway sessions
results = db.search_messages("bug", exclude_sources=["telegram", "discord"])

# Search only user messages
results = db.search_messages("help", role_filter=["user"])
```

### Result Format

Each result includes:
- `id`, `session_id`, `role`, `timestamp`
- `snippet` — FTS5-generated snippet with `>>>match<<<` markers
- `context` — 1 message before and after the match (truncated to 200 chars)
- `source`, `model`, `session_started` — from the parent session

## Session Lineage

Context compression can split a long session into a chain of sessions linked by `parent_session_id`. Useful SQL for navigating chains:

```sql
-- All ancestors of a session
WITH RECURSIVE lineage AS (
    SELECT * FROM sessions WHERE id = ?
    UNION ALL
    SELECT s.* FROM sessions s
    JOIN lineage l ON s.id = l.parent_session_id
)
SELECT id, title, started_at, parent_session_id FROM lineage;

-- All descendants of a session
WITH RECURSIVE descendants AS (
    SELECT * FROM sessions WHERE id = ?
    UNION ALL
    SELECT s.* FROM sessions s
    JOIN descendants d ON s.parent_session_id = d.id
)
SELECT id, title, started_at FROM descendants;
```

### Other Useful Queries

```sql
-- Recent sessions with first-message preview
SELECT s.*,
    COALESCE(
        (SELECT SUBSTR(m.content, 1, 63)
         FROM messages m
         WHERE m.session_id = s.id AND m.role = 'user' AND m.content IS NOT NULL
         ORDER BY m.timestamp, m.id LIMIT 1),
        ''
    ) AS preview,
    COALESCE(
        (SELECT MAX(m2.timestamp) FROM messages m2 WHERE m2.session_id = s.id),
        s.started_at
    ) AS last_active
FROM sessions s
ORDER BY s.started_at DESC
LIMIT 20;

-- Token usage and cost by model
SELECT model,
       COUNT(*) as session_count,
       SUM(input_tokens) as total_input,
       SUM(output_tokens) as total_output,
       SUM(estimated_cost_usd) as total_cost
FROM sessions
WHERE model IS NOT NULL
GROUP BY model
ORDER BY total_cost DESC;
```

## Export and Cleanup

```python
# Export one session with messages
data = db.export_session("sess_abc123")

# Export all sessions as a list of dicts
all_data = db.export_all(source="cli")

# Delete old ended sessions
deleted_count = db.prune_sessions(older_than_days=90)
deleted_count = db.prune_sessions(older_than_days=30, source="telegram")

# Clear messages but keep the session record
db.clear_messages("sess_abc123")

# Delete session and all its messages
db.delete_session("sess_abc123")
```

## Database Location

Default: `~/.spark/state.db`

Derived from `spark_constants.get_spark_home()`. Override with the `SPARK_HOME` environment variable.

The WAL file (`state.db-wal`) and shared-memory file (`state.db-shm`) live in the same directory.
