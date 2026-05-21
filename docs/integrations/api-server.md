---
sidebar_position: 14
title: "API Server"
description: "Expose spark-agent as an OpenAI-compatible API for any frontend"
---

# API Server

Turn Spark into an OpenAI-compatible HTTP backend that any frontend can connect to. Open WebUI, LobeChat, LibreChat, NextChat, ChatBox, the OpenAI Python SDK — anything that speaks the OpenAI format works.

Your agent handles requests with its full toolset: terminal, file operations, web search, memory, skills. When streaming, tool activity appears inline so frontends can show exactly what Spark is doing.

## Quick Start

### 1. Enable the API server

Add to `~/.spark/.env`:

```bash
API_SERVER_ENABLED=true
API_SERVER_KEY=change-me-local-dev
# Only needed if a browser must call Spark directly:
# API_SERVER_CORS_ORIGINS=http://localhost:3000
```

### 2. Start the gateway

```bash
spark gateway
```

You'll see:

```
[API Server] API server listening on http://127.0.0.1:8642
```

### 3. Connect a frontend

Point any OpenAI-compatible client at `http://localhost:8642/v1`:

```bash
curl http://localhost:8642/v1/chat/completions \
  -H "Authorization: Bearer change-me-local-dev" \
  -H "Content-Type: application/json" \
  -d '{"model": "spark-agent", "messages": [{"role": "user", "content": "Hello!"}]}'
```

For step-by-step instructions with Open WebUI, see the [Open WebUI integration guide](../chat-platforms/open-webui.md).

## Endpoints

### POST /v1/chat/completions

Standard OpenAI Chat Completions format. Stateless — the full conversation history goes in the `messages` array on every request.

**Request:**
```json
{
  "model": "spark-agent",
  "messages": [
    {"role": "system", "content": "You are a Python expert."},
    {"role": "user", "content": "Write a fibonacci function"}
  ],
  "stream": false
}
```

**Response:**
```json
{
  "id": "chatcmpl-abc123",
  "object": "chat.completion",
  "created": 1710000000,
  "model": "spark-agent",
  "choices": [{
    "index": 0,
    "message": {"role": "assistant", "content": "Here's a fibonacci function..."},
    "finish_reason": "stop"
  }],
  "usage": {"prompt_tokens": 50, "completion_tokens": 200, "total_tokens": 250}
}
```

**Streaming** (`"stream": true`): Returns Server-Sent Events with token-by-token chunks. When the agent calls tools during a streaming request, brief progress indicators (e.g., `` `pwd` ``, `` `Python docs` ``) are injected inline before the response text.

### POST /v1/responses

OpenAI Responses API format. The server stores full conversation history (including tool calls) and chains turns via `previous_response_id` — clients don't need to manage context themselves.

**Request:**
```json
{
  "model": "spark-agent",
  "input": "What files are in my project?",
  "instructions": "You are a helpful coding assistant.",
  "store": true
}
```

**Response:**
```json
{
  "id": "resp_abc123",
  "object": "response",
  "status": "completed",
  "model": "spark-agent",
  "output": [
    {"type": "function_call", "name": "terminal", "arguments": "{\"command\": \"ls\"}", "call_id": "call_1"},
    {"type": "function_call_output", "call_id": "call_1", "output": "README.md src/ tests/"},
    {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Your project has..."}]}
  ],
  "usage": {"input_tokens": 50, "output_tokens": 200, "total_tokens": 250}
}
```

#### Multi-turn with previous_response_id

Chain turns while preserving full tool call context:

```json
{
  "input": "Now show me the README",
  "previous_response_id": "resp_abc123"
}
```

The server reconstructs the full conversation from the stored chain — all prior tool calls and results are preserved.

#### Named conversations

Use `conversation` instead of tracking response IDs manually:

```json
{"input": "Hello", "conversation": "my-project"}
{"input": "What's in src/?", "conversation": "my-project"}
{"input": "Run the tests", "conversation": "my-project"}
```

The server auto-chains to the latest response in that conversation.

### GET /v1/responses/\{id\}

Retrieve a previously stored response by ID.

### DELETE /v1/responses/\{id\}

Delete a stored response.

### GET /v1/models

Lists Spark as an available model. The advertised name defaults to the [profile](../cli/profiles.md) name, or `spark-agent` for the default profile. Most frontends require this endpoint for model discovery.

### GET /health

Returns `{"status": "ok"}`. Also available at **GET /v1/health** for clients that expect the `/v1/` prefix.

## System Prompt Handling

When a frontend sends a `system` message (Chat Completions) or `instructions` field (Responses API), Spark layers it on top of its core system prompt. Your agent keeps all its tools, memory, and skills — the frontend's prompt adds extra instructions on top.

This lets you customize behavior per-frontend without losing capabilities:

```
Open WebUI system prompt: "Always include type hints in Python examples."
→ Agent still has terminal, file tools, web search, memory, etc.
```

## Authentication

Bearer token auth via the `Authorization` header:

```
Authorization: Bearer your-key
```

Set the key with `API_SERVER_KEY`. If browsers need to call Spark directly, also set `API_SERVER_CORS_ORIGINS` to an explicit allowlist.

:::warning Security
The API server gives full access to Spark's toolset, **including terminal commands**. When binding to a non-loopback address like `0.0.0.0`, `API_SERVER_KEY` is **required**. Keep `API_SERVER_CORS_ORIGINS` narrow to control browser access.

The default bind address (`127.0.0.1`) is local-only. Browser access is disabled by default.
:::

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `API_SERVER_ENABLED` | `false` | Enable the API server |
| `API_SERVER_PORT` | `8642` | HTTP server port |
| `API_SERVER_HOST` | `127.0.0.1` | Bind address |
| `API_SERVER_KEY` | _(none)_ | Bearer token for auth |
| `API_SERVER_CORS_ORIGINS` | _(none)_ | Comma-separated allowed browser origins |
| `API_SERVER_MODEL_NAME` | _(profile name)_ | Model name on `/v1/models` |

### config.yaml

```yaml
# Not yet supported - use environment variables.
# config.yaml support coming in a future release.
```

## Security Headers

All responses include:
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: no-referrer`

## CORS

Browser CORS is disabled by default. To enable it:

```bash
API_SERVER_CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
```

When CORS is enabled:
- Preflight responses include `Access-Control-Max-Age: 600` (10-minute cache)
- SSE streaming responses include CORS headers so browser `EventSource` works
- `Idempotency-Key` is an allowed request header (cached for 5 minutes)

Most documented frontends like Open WebUI connect server-to-server and don't need CORS at all.

## Compatible Frontends

| Frontend | Stars | How to connect |
|----------|-------|----------------|
| [Open WebUI](../chat-platforms/open-webui.md) | 126k | Full guide available |
| LobeChat | 73k | Custom provider endpoint |
| LibreChat | 34k | Custom endpoint in librechat.yaml |
| AnythingLLM | 56k | Generic OpenAI provider |
| NextChat | 87k | BASE_URL env var |
| ChatBox | 39k | API Host setting |
| Jan | 26k | Remote model config |
| HF Chat-UI | 8k | OPENAI_BASE_URL |
| big-AGI | 7k | Custom endpoint |
| OpenAI Python SDK | - | `OpenAI(base_url="http://localhost:8642/v1")` |
| curl | - | Direct HTTP requests |

## Multi-User Setup with Profiles

Give multiple users isolated Spark instances — separate config, memory, and skills — using [profiles](../cli/profiles.md):

```bash
spark profile create alice
spark profile create bob

spark -p alice config set API_SERVER_ENABLED true
spark -p alice config set API_SERVER_PORT 8643
spark -p alice config set API_SERVER_KEY alice-secret

spark -p bob config set API_SERVER_ENABLED true
spark -p bob config set API_SERVER_PORT 8644
spark -p bob config set API_SERVER_KEY bob-secret

spark -p alice gateway &
spark -p bob gateway &
```

Each profile's API server advertises the profile name as the model ID:

- `http://localhost:8643/v1/models` → model `alice`
- `http://localhost:8644/v1/models` → model `bob`

In Open WebUI, add each as a separate connection. See the [Open WebUI guide](../chat-platforms/open-webui.md#multi-user-setup-with-profiles).

## Limitations

- **Response storage** — stored responses persist in SQLite and survive restarts. Max 100 stored responses (LRU eviction).
- **No file upload** — vision/document analysis via uploaded files is not yet supported.
- **Model field is cosmetic** — the `model` field in requests is accepted but the actual LLM used is configured server-side in `config.yaml`.
