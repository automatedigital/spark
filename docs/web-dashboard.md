# Web UI — Realtime API

The Spark Web UI (`spark web`) runs a FastAPI backend with a React SPA frontend. Everything updates in realtime over **Server-Sent Events (SSE)** — chat tokens, tool calls, session changes, and approval requests all flow through a single event bus.

## Connecting to the Event Stream

```
GET /api/events
```

**Query parameters:**

| Param | Default | Description |
|-------|---------|-------------|
| `topics` | `sessions,chat` | Comma-separated topic prefixes. An event matches if its `topic` equals or starts with any prefix — so `chat` matches `chat.token`, `chat.tool_start`, etc. |

Each event is a single JSON object on a `data:` line:

```json
{
  "topic": "sessions.changed",
  "session_id": "20260101_abc",
  "ts": 1710000000.0,
  "data": { "action": "updated", "session_id": "...", "session": { ... } }
}
```

The server sends an SSE `ping` event every 30 seconds to keep connections alive.

## Event Reference

| Topic | When it fires | Key fields |
|-------|--------------|------------|
| `sessions.changed` | Session created, updated (e.g. kanban move), or deleted | `data.action`: `created` \| `updated` \| `deleted` |
| `chat.token` | Streamed assistant text | `data.t` — the token string |
| `chat.tool_start` | Tool invocation begins | `id`, `name`, `args` |
| `chat.tool_end` | Tool invocation completes | `id`, `name`, `args`, `result` |
| `chat.reasoning` | Reasoning text | `data.text` |
| `chat.status` | Status line update | `data.kind`, `data.message` |
| `chat.approval_requested` | Dangerous command needs user approval | `data.approval` |
| `chat.approval_resolved` | Approval decision recorded | — |
| `chat.interrupted` | User stopped the run | — |
| `chat.turn_done` | Agent finished the current turn | — |
| `chat.model_changed` | Model switched for this session | — |

## Conversation Routes

All session-specific routes are under `/api/conversations/{session_id}/` unless noted.

| Method | Path | Body | What it does |
|--------|------|------|--------------|
| `POST` | `/api/conversations` | `{ message, model? }` | Start a new web session. Returns `session_id`. |
| `POST` | `/{id}/messages` | `{ message }` | Send the next message (agent must still be in memory). |
| `POST` | `/{id}/interrupt` | `{ message? }` | Stop or interrupt a running turn. |
| `POST` | `/{id}/model` | `{ model }` | Switch model for the next turn. Returns 409 if a turn is currently running. |
| `POST` | `/{id}/fork` | `{ from_message_index? }` | Copy SQLite messages into a new session. |
| `POST` | `/{id}/retry` | `{ message_index, message? }` | Re-run from a specific user message. `message_index` is the index of a user row in agent history. Optional `message` lets you edit it before retrying. |
| `POST` | `/{id}/approval` | `{ choice, resolve_all? }` | Respond to a pending approval. `choice`: `once` \| `session` \| `always` \| `deny`. |

## Picking a Model

```
GET /api/conversations/models
```

Returns a curated list of available models:

```json
{
  "models": [
    { "id": "anthropic/claude-sonnet-4-6", "hint": "..." },
    ...
  ]
}
```

## Legacy Token Stream

```
GET /api/conversations/{id}/stream
```

Still works for backwards compatibility. Streams token events the same way as the SSE bus. New integrations should prefer `/api/events` with `topics=chat`.
