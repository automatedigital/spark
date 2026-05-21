---
sidebar_position: 8
title: "MCP Config Reference"
description: "Reference for Spark Agent MCP configuration keys, filtering semantics, and utility-tool policy"
---

# MCP Config Reference

Quick reference for every MCP configuration key Spark supports. For conceptual background and setup walkthroughs, see:

- [MCP (Model Context Protocol)](../tools/mcp.md)
- [Use MCP with Spark](../guides/use-mcp.md)

## Config Shape

```yaml
mcp_servers:
  <server_name>:
    command: "..."      # stdio servers
    args: []
    env: {}

    # OR
    url: "..."          # HTTP servers
    headers: {}

    enabled: true
    timeout: 120
    connect_timeout: 60
    tools:
      include: []
      exclude: []
      resources: true
      prompts: true
```

## Server Keys

| Key | Type | Applies to | What it does |
|---|---|---|---|
| `command` | string | stdio | Executable to launch |
| `args` | list | stdio | Arguments for the subprocess |
| `env` | mapping | stdio | Environment variables passed to the subprocess |
| `url` | string | HTTP | Remote MCP endpoint |
| `headers` | mapping | HTTP | Request headers for the remote server |
| `enabled` | bool | both | Set to `false` to skip this server entirely |
| `timeout` | number | both | Tool call timeout in seconds |
| `connect_timeout` | number | both | Initial connection timeout in seconds |
| `tools` | mapping | both | Filtering and utility-tool policy |
| `auth` | string | HTTP | Authentication method. Set to `oauth` for OAuth 2.1 with PKCE |
| `sampling` | mapping | both | Server-initiated LLM request policy (see MCP guide) |

## `tools` Policy Keys

| Key | Type | What it does |
|---|---|---|
| `include` | string or list | Allow only these server-native MCP tools |
| `exclude` | string or list | Block these server-native MCP tools |
| `resources` | bool-like | Enable/disable `list_resources` and `read_resource` |
| `prompts` | bool-like | Enable/disable `list_prompts` and `get_prompt` |

## Filtering Rules

### `include` — Allow list

Only the tools you name are registered. Everything else on the server is ignored.

```yaml
tools:
  include: [create_issue, list_issues]
```

### `exclude` — Block list

Every tool on the server is registered *except* the ones you name.

```yaml
tools:
  exclude: [delete_customer]
```

### Precedence

When both are set, `include` wins.

```yaml
tools:
  include: [create_issue]
  exclude: [create_issue, delete_issue]
```

Result: `create_issue` is registered. `delete_issue` is ignored because `include` takes precedence.

## Utility Tools

Spark can register these utility wrappers alongside server-native tools:

**Resources:**
- `list_resources`
- `read_resource`

**Prompts:**
- `list_prompts`
- `get_prompt`

Disable them when you don't need them:

```yaml
tools:
  resources: false
  prompts: false
```

Even when `resources: true` or `prompts: true`, Spark only registers these utilities if the MCP server actually exposes the capability. If a server doesn't support prompts, no prompt utilities appear — that's normal.

## Disabling a Server

```yaml
mcp_servers:
  legacy:
    url: "https://mcp.legacy.internal"
    enabled: false
```

With `enabled: false`, Spark skips the server entirely — no connection attempt, no tool discovery, no registration. The config stays in place for later use.

## Empty Filter Results

If filtering removes all server-native tools and no utility tools are registered, Spark does not create an empty MCP toolset for that server.

## Example Configs

### Safe GitHub allow list

```yaml
mcp_servers:
  github:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "***"
    tools:
      include: [list_issues, create_issue, update_issue, search_code]
      resources: false
      prompts: false
```

### Stripe block list

```yaml
mcp_servers:
  stripe:
    url: "https://mcp.stripe.com"
    headers:
      Authorization: "Bearer ***"
    tools:
      exclude: [delete_customer, refund_payment]
```

### Resource-only docs server

```yaml
mcp_servers:
  docs:
    url: "https://mcp.docs.example.com"
    tools:
      include: []
      resources: true
      prompts: false
```

## Reload Config Without Restarting

After changing MCP config, reload without restarting your session:

```text
/reload-mcp
```

## Tool Naming

Server-native MCP tools are registered as:

```text
mcp_<server>_<tool>
```

Examples:
- `mcp_github_create_issue`
- `mcp_filesystem_read_file`
- `mcp_my_api_query_data`

Utility tools follow the same pattern:
- `mcp_<server>_list_resources`
- `mcp_<server>_read_resource`
- `mcp_<server>_list_prompts`
- `mcp_<server>_get_prompt`

### Name Sanitization

Hyphens (`-`) and dots (`.`) in server names and tool names are replaced with underscores. This keeps tool names valid for LLM function-calling APIs.

A server named `my-api` exposing a tool called `list-items.v2` becomes:

```text
mcp_my_api_list_items_v2
```

When writing `include` / `exclude` filters, use the **original** MCP tool name (with hyphens/dots) — not the sanitized version.

## OAuth 2.1 Authentication

For HTTP servers that require OAuth, add `auth: oauth`:

```yaml
mcp_servers:
  protected_api:
    url: "https://mcp.example.com/mcp"
    auth: oauth
```

What happens:
- Spark runs the MCP SDK's OAuth 2.1 PKCE flow: metadata discovery, dynamic client registration, token exchange, and refresh
- On first connect, a browser window opens for authorization
- Tokens persist to `~/.spark/mcp-tokens/<server>.json` and reuse across sessions
- Token refresh is automatic; you only re-authorize if refresh fails
- Only works with HTTP/StreamableHTTP transport (`url`-based servers)
