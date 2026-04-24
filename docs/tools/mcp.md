---
sidebar_position: 4
title: "MCP (Model Context Protocol)"
description: "Connect Spark Agent to external tool servers via MCP - and control exactly which MCP tools Spark loads"
---

# MCP (Model Context Protocol)

MCP lets Spark connect to external tool servers and use their tools as if they were native — GitHub, databases, file systems, browser stacks, internal APIs, and more.

If a tool already exists as an MCP server somewhere, connecting it to Spark is usually faster than building a native integration.

---

## What MCP Gives You

- Access to external tool ecosystems without writing a native Spark tool
- Local stdio servers and remote HTTP MCP servers in the same config
- Automatic tool discovery and registration at startup
- Utility wrappers for MCP resources and prompts when the server supports them
- Per-server filtering so Spark only sees the MCP tools you actually want

---

## Quick Start

1. Install MCP support (already included in the standard install):

```bash
cd ~/.spark/spark-agent
uv pip install -e ".[mcp]"
```

2. Add an MCP server to `~/.spark/config.yaml`:

```yaml
mcp_servers:
  filesystem:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/projects"]
```

3. Start Spark:

```bash
spark chat
```

4. Ask Spark to use the new capability:

```text
List the files in /home/user/projects and summarize the repo structure.
```

Spark discovers the MCP server's tools at startup and uses them like any other tool.

---

## Two Kinds of MCP Servers

### Stdio servers

Stdio servers run as local subprocesses and communicate over stdin/stdout.

```yaml
mcp_servers:
  github:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "***"
```

Use stdio servers when:
- the server is installed locally
- you want low-latency access to local resources
- the MCP server docs show `command`, `args`, and `env`

### HTTP servers

HTTP MCP servers are remote endpoints Spark connects to directly.

```yaml
mcp_servers:
  remote_api:
    url: "https://mcp.example.com/mcp"
    headers:
      Authorization: "Bearer ***"
```

Use HTTP servers when:
- the MCP server is hosted elsewhere
- your organization exposes internal MCP endpoints
- you don't want Spark spawning a local subprocess for that integration

---

## Basic Configuration Reference

Spark reads MCP config from `~/.spark/config.yaml` under `mcp_servers`.

### Common keys

| Key | Type | Meaning |
|---|---|---|
| `command` | string | Executable for a stdio MCP server |
| `args` | list | Arguments for the stdio server |
| `env` | mapping | Environment variables passed to the stdio server |
| `url` | string | HTTP MCP endpoint |
| `headers` | mapping | HTTP headers for remote servers |
| `timeout` | number | Tool call timeout |
| `connect_timeout` | number | Initial connection timeout |
| `enabled` | bool | If `false`, Spark skips the server entirely |
| `tools` | mapping | Per-server tool filtering and utility policy |

### Minimal stdio example

```yaml
mcp_servers:
  filesystem:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
```

### Minimal HTTP example

```yaml
mcp_servers:
  company_api:
    url: "https://mcp.internal.example.com"
    headers:
      Authorization: "Bearer ***"
```

---

## How Spark Registers MCP Tools

Spark prefixes MCP tools to avoid collisions with built-in names:

```text
mcp_<server_name>_<tool_name>
```

Examples:

| Server | MCP tool | Registered name |
|---|---|---|
| `filesystem` | `read_file` | `mcp_filesystem_read_file` |
| `github` | `create-issue` | `mcp_github_create_issue` |
| `my-api` | `query.data` | `mcp_my_api_query_data` |

In practice you rarely need to use the prefixed name manually — Spark sees the tool and selects it during normal reasoning.

---

## MCP Utility Tools

When the server supports it, Spark also registers utility tools for MCP resources and prompts:

- `list_resources`
- `read_resource`
- `list_prompts`
- `get_prompt`

These follow the same prefix pattern:

- `mcp_github_list_resources`
- `mcp_github_get_prompt`

Spark only registers resource utilities if the MCP session actually supports resource operations — and only prompt utilities if the session supports prompt operations. Servers that expose tools but no resources/prompts won't get those extra wrappers.

---

## Per-Server Filtering

Control exactly which tools each MCP server contributes to Spark.

### Disable a server entirely

```yaml
mcp_servers:
  legacy:
    url: "https://mcp.legacy.internal"
    enabled: false
```

With `enabled: false`, Spark skips the server completely and never attempts a connection.

### Whitelist server tools

```yaml
mcp_servers:
  github:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "***"
    tools:
      include: [create_issue, list_issues]
```

Only the listed tools are registered.

### Blacklist server tools

```yaml
mcp_servers:
  stripe:
    url: "https://mcp.stripe.com"
    tools:
      exclude: [delete_customer]
```

All tools are registered except the excluded ones.

### Precedence rule

If both `include` and `exclude` are present, `include` wins:

```yaml
tools:
  include: [create_issue]
  exclude: [create_issue, delete_issue]
```

### Filter utility tools too

Disable Spark-added utility wrappers separately:

```yaml
mcp_servers:
  docs:
    url: "https://mcp.docs.example.com"
    tools:
      prompts: false
      resources: false
```

- `tools.resources: false` disables `list_resources` and `read_resource`
- `tools.prompts: false` disables `list_prompts` and `get_prompt`

### Full example

```yaml
mcp_servers:
  github:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "***"
    tools:
      include: [create_issue, list_issues, search_code]
      prompts: false

  stripe:
    url: "https://mcp.stripe.com"
    headers:
      Authorization: "Bearer ***"
    tools:
      exclude: [delete_customer]
      resources: false

  legacy:
    url: "https://mcp.legacy.internal"
    enabled: false
```

If filtering removes all callable tools and no supported utilities remain, Spark does not create an empty toolset for that server — the tool list stays clean.

---

## Runtime Behavior

### Discovery

Spark discovers MCP servers at startup and registers their tools into the normal tool registry.

### Dynamic Tool Discovery

MCP servers can notify Spark when their available tools change at runtime via `notifications/tools/list_changed`. When Spark receives this notification, it automatically re-fetches the server's tool list and updates the registry — no manual `/reload-mcp` needed.

This is useful for servers whose capabilities change dynamically (e.g. a server that adds tools when a new database schema loads, or removes tools when a service goes offline).

The refresh is lock-protected so rapid-fire notifications from the same server don't trigger overlapping refreshes. Prompt and resource change notifications (`prompts/list_changed`, `resources/list_changed`) are received but not yet acted on.

### Reloading

Changed your MCP config? Reload without restarting:

```text
/reload-mcp
```

This reloads MCP servers from config and refreshes the available tool list. For runtime tool changes pushed by the server itself, see [Dynamic Tool Discovery](#dynamic-tool-discovery) above.

### Toolsets

Each configured MCP server creates a runtime toolset when it contributes at least one registered tool:

```text
mcp-<server>
```

This makes MCP servers easier to reason about at the toolset level.

---

## Security Model

### Stdio env filtering

For stdio servers, Spark does not pass your full shell environment. Only the explicitly configured `env` keys plus a safe baseline are passed through. This prevents accidental secret leakage.

### Config-level exposure control

The filtering system is also a security control. You can:
- disable dangerous tools you don't want the model to see
- expose only a minimal allowlist for a sensitive server
- disable resource/prompt wrappers when you don't want that surface exposed

---

## Example Use Cases

### GitHub server with a minimal issue-management surface

```yaml
mcp_servers:
  github:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "***"
    tools:
      include: [list_issues, create_issue, update_issue]
      prompts: false
      resources: false
```

```text
Show me open issues labeled bug, then draft a new issue for the flaky MCP reconnection behavior.
```

### Stripe server with dangerous actions removed

```yaml
mcp_servers:
  stripe:
    url: "https://mcp.stripe.com"
    headers:
      Authorization: "Bearer ***"
    tools:
      exclude: [delete_customer, refund_payment]
```

```text
Look up the last 10 failed payments and summarize common failure reasons.
```

### Filesystem server scoped to a single project root

```yaml
mcp_servers:
  project_fs:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/my-project"]
```

```text
Inspect the project root and explain the directory layout.
```

---

## Troubleshooting

### MCP server not connecting

```bash
# Verify MCP deps are installed (already included in standard install)
cd ~/.spark/spark-agent && uv pip install -e ".[mcp]"

node --version
npx --version
```

Verify your config and restart Spark.

### Tools not appearing

Possible causes:
- the server failed to connect
- discovery failed
- your filter config excluded the tools
- the utility capability doesn't exist on that server
- the server is disabled with `enabled: false`

If you're intentionally filtering, this is expected.

### Why didn't resource or prompt utilities appear?

Spark only registers those wrappers when both conditions are true:
1. your config allows them
2. the server session actually supports the capability

This keeps the tool list honest.

---

## MCP Sampling Support

MCP servers can request LLM inference from Spark via the `sampling/createMessage` protocol. This lets an MCP server ask Spark to generate text on its behalf — useful for servers that need LLM capabilities but don't have their own model access.

Sampling is **enabled by default** for all MCP servers (when the MCP SDK supports it). Configure it per-server under the `sampling` key:

```yaml
mcp_servers:
  my_server:
    command: "my-mcp-server"
    sampling:
      enabled: true            # Enable sampling (default: true)
      model: "openai/gpt-4o"  # Override model for sampling requests (optional)
      max_tokens_cap: 4096     # Max tokens per sampling response (default: 4096)
      timeout: 30              # Timeout in seconds per request (default: 30)
      max_rpm: 10              # Rate limit: max requests per minute (default: 10)
      max_tool_rounds: 5       # Max tool-use rounds in sampling loops (default: 5)
      allowed_models: []       # Allowlist of model names the server may request (empty = any)
      log_level: "info"        # Audit log level: debug, info, or warning (default: info)
```

The sampling handler includes a sliding-window rate limiter, per-request timeouts, and tool-loop depth limits to prevent runaway usage. Metrics (request count, errors, tokens used) are tracked per server instance.

To disable sampling for a specific server:

```yaml
mcp_servers:
  untrusted_server:
    url: "https://mcp.example.com"
    sampling:
      enabled: false
```

---

## Running Spark as an MCP Server

Spark can also **be** an MCP server. This lets other MCP-capable agents — Claude Code, Cursor, Codex, or any MCP client — use Spark's messaging capabilities: list conversations, read message history, and send messages across all connected platforms.

### When to use this

- You want Claude Code, Cursor, or another coding agent to send and read Telegram/Discord/Slack messages through Spark
- You want a single MCP server that bridges to all of Spark's connected messaging platforms at once
- You already have a running Spark gateway with connected platforms

### Quick Start

```bash
spark mcp serve
```

This starts a stdio MCP server. The MCP client — not you — manages the process lifecycle.

### MCP Client Configuration

Add Spark to your MCP client config. For Claude Code's `~/.claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "spark": {
      "command": "spark",
      "args": ["mcp", "serve"]
    }
  }
}
```

Or if Spark is installed at a specific path:

```json
{
  "mcpServers": {
    "spark": {
      "command": "/home/user/.spark/spark-agent/venv/bin/spark",
      "args": ["mcp", "serve"]
    }
  }
}
```

### Available Tools

The MCP server exposes 10 tools:

| Tool | Description |
|------|-------------|
| `conversations_list` | List active messaging conversations. Filter by platform or search by name. |
| `conversation_get` | Get detailed info about one conversation by session key. |
| `messages_read` | Read recent message history for a conversation. |
| `attachments_fetch` | Extract non-text attachments (images, media) from a specific message. |
| `events_poll` | Poll for new conversation events since a cursor position. |
| `events_wait` | Long-poll / block until the next event arrives (near-real-time). |
| `messages_send` | Send a message through a platform (e.g. `telegram:123456`, `discord:#general`). |
| `channels_list` | List available messaging targets across all platforms. |
| `permissions_list_open` | List pending approval requests observed during this bridge session. |
| `permissions_respond` | Allow or deny a pending approval request. |

### Event System

The MCP server includes a live event bridge that polls Spark's session database for new messages. This gives MCP clients near-real-time awareness of incoming conversations:

```
# Poll for new events (non-blocking)
events_poll(after_cursor=0)

# Wait for next event (blocks up to timeout)
events_wait(after_cursor=42, timeout_ms=30000)
```

Event types: `message`, `approval_requested`, `approval_resolved`

The event queue is in-memory and starts when the bridge connects. Older messages are available through `messages_read`.

### Options

```bash
spark mcp serve              # Normal mode
spark mcp serve --verbose    # Debug logging on stderr
```

### How It Works

The MCP server reads conversation data directly from Spark's session store (`~/.spark/sessions/sessions.json` and the SQLite database). A background thread polls the database for new messages and maintains an in-memory event queue. For sending messages, it uses the same `send_message` infrastructure as the Spark agent itself.

The gateway does NOT need to be running for read operations (listing conversations, reading history, polling events). It DOES need to be running for send operations, since the platform adapters need active connections.

### Current Limits

- Stdio transport only (no HTTP MCP transport yet)
- Event polling at ~200ms intervals via mtime-optimized DB polling (skips work when files are unchanged)
- No `claude/channel` push notification protocol yet
- Text-only sends (no media/attachment sending through `messages_send`)

---

## Related Docs

- [Use MCP with Spark](/docs/guides/use-mcp)
- [CLI Commands](/docs/cli/commands-reference)
- [Slash Commands](/docs/cli/slash-commands)
- [FAQ](/docs/reference/faq)
