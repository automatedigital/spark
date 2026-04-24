---
sidebar_position: 6
title: "Use MCP with Spark"
description: "A practical guide to connecting MCP servers to Spark Agent, filtering their tools, and using them safely in real workflows"
---

# Use MCP with Spark

MCP lets you connect external systems — databases, APIs, filesystems, internal tools — to Spark without touching Spark's core code. This guide gets you from zero to working integration, safely.

## When to Use MCP

**Reach for MCP when:**
- A tool already exists as an MCP server and you don't want to build a native Spark tool
- You want Spark to operate against a local or remote system through a clean RPC layer
- You need fine-grained per-server exposure control
- You're connecting Spark to internal APIs or company systems

**Skip MCP when:**
- A built-in Spark tool already does the job well
- The server exposes a large, dangerous tool surface you're not prepared to filter
- You only need one narrow integration and a native tool would be simpler and safer

## The Right Mental Model

Think of MCP as an adapter layer:

- Spark stays the agent
- MCP servers contribute tools
- Spark discovers those tools at startup or on `/reload-mcp`
- The model calls them like any other tool
- You control how much of each server is visible

That last point matters. Good MCP usage isn't "connect everything" — it's "connect the right thing, with the smallest useful surface."

## Step 1: Install MCP Support

If you installed Spark with the standard install script, MCP support is already included (the installer runs `uv pip install -e ".[all]"`).

If you installed without extras:

```bash
cd ~/.spark/spark-agent
uv pip install -e ".[mcp]"
```

For npm-based servers, make sure Node.js and `npx` are available. For Python-based servers, `uvx` is a good default.

## Step 2: Add One Server First

Start with a single, safe server. Filesystem access scoped to one project directory is ideal:

```yaml
mcp_servers:
  project_fs:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/my-project"]
```

Start Spark and test it:

```bash
spark chat
```

```text
Inspect this project and summarize the repo layout.
```

## Step 3: Verify MCP Loaded

A few ways to check:

- Ask Spark directly: `Tell me which MCP-backed tools are available right now.`
- Use `/reload-mcp` after config changes and watch the output
- Check logs if the server failed to connect

## Step 4: Filter Immediately

Don't wait until a problem appears. If a server exposes many tools, lock it down as soon as you add it.

### Allowlist Only What You Need

```yaml
mcp_servers:
  github:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "***"
    tools:
      include: [list_issues, create_issue, search_code]
```

Start with the smallest useful set and expand when needed.

### Block Dangerous Actions

```yaml
mcp_servers:
  stripe:
    url: "https://mcp.stripe.com"
    headers:
      Authorization: "Bearer ***"
    tools:
      exclude: [delete_customer, refund_payment]
```

### Disable Utility Wrappers

```yaml
mcp_servers:
  docs:
    url: "https://mcp.docs.example.com"
    tools:
      prompts: false
      resources: false
```

## What Filtering Controls

Two categories of MCP-exposed functionality:

**Server-native tools** — filtered with `tools.include` or `tools.exclude`

**Spark-added utility wrappers** — filtered with `tools.resources` and `tools.prompts`

The utility wrappers you might see:

| Wrapper | Category |
|---------|----------|
| `list_resources` | resources |
| `read_resource` | resources |
| `list_prompts` | prompts |
| `get_prompt` | prompts |

These only appear if your config allows them **and** the MCP server actually supports those capabilities. Spark won't fabricate wrappers for a server that doesn't support them.

## Common Patterns

### Local Project Assistant

Use MCP for a repo-scoped filesystem or git server when you want Spark to reason over a bounded workspace:

```yaml
mcp_servers:
  fs:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/project"]

  git:
    command: "uvx"
    args: ["mcp-server-git", "--repository", "/home/user/project"]
```

```text
Review the project structure and identify where configuration lives.
```

```text
Check the local git state and summarize what changed recently.
```

### GitHub Triage Assistant

```yaml
mcp_servers:
  github:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "***"
    tools:
      include: [list_issues, create_issue, update_issue, search_code]
      prompts: false
      resources: false
```

```text
List open issues about MCP, cluster them by theme, and draft a high-quality issue for the most common bug.
```

```text
Search the repo for uses of _discover_and_register_server and explain how MCP tools are registered.
```

### Internal API Assistant

```yaml
mcp_servers:
  internal_api:
    url: "https://mcp.internal.example.com"
    headers:
      Authorization: "Bearer ***"
    tools:
      include: [list_customers, get_customer, list_invoices]
      resources: false
      prompts: false
```

```text
Look up customer ACME Corp and summarize recent invoice activity.
```

For anything customer-facing or financial, a tight allowlist beats a blocklist. You can always expand it.

### Documentation / Knowledge Servers

Some MCP servers expose prompts or resources as shared knowledge assets rather than direct actions:

```yaml
mcp_servers:
  docs:
    url: "https://mcp.docs.example.com"
    tools:
      prompts: true
      resources: true
```

```text
List available MCP resources from the docs server, then read the onboarding guide and summarize it.
```

```text
List prompts exposed by the docs server and tell me which ones would help with incident response.
```

## End-to-End Tutorial

### Phase 1: Tight Allowlist to Start

```yaml
mcp_servers:
  github:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "***"
    tools:
      include: [list_issues, create_issue, search_code]
      prompts: false
      resources: false
```

Start Spark and test:

```text
Search the codebase for references to MCP and summarize the main integration points.
```

### Phase 2: Expand Only When You Need To

If you need issue updates too:

```yaml
tools:
  include: [list_issues, create_issue, update_issue, search_code]
```

Reload without restarting:

```text
/reload-mcp
```

### Phase 3: Add a Second Server

```yaml
mcp_servers:
  github:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "***"
    tools:
      include: [list_issues, create_issue, update_issue, search_code]
      prompts: false
      resources: false

  filesystem:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/project"]
```

Now Spark can combine both:

```text
Inspect the local project files, then create a GitHub issue summarizing the bug you find.
```

That's where MCP gets powerful: multi-system workflows without touching Spark core.

## Safe Usage Rules

**Allowlists for dangerous systems.** For anything financial, customer-facing, or destructive, use `tools.include` and start with the smallest set possible.

**Disable unused utilities.** If you don't want the model browsing server-provided resources or prompts, turn them off:

```yaml
tools:
  resources: false
  prompts: false
```

**Keep servers scoped narrowly.**
- Filesystem server rooted to one project dir, not your whole home directory
- Git server pointed at one repo
- Internal API server with read-heavy exposure by default

**Reload after config changes:**

```text
/reload-mcp
```

Do this after changing include/exclude lists, enabled flags, resources/prompts toggles, or auth headers.

## Troubleshooting

| Symptom | Check |
|---------|-------|
| Server connects but expected tools are missing | `tools.include` filter, `tools.exclude` filter, `resources: false` / `prompts: false`, or server doesn't actually support those capabilities |
| Server is configured but nothing loads | `enabled: false` left in config, command/runtime not on PATH, HTTP endpoint unreachable, auth env or headers wrong |
| Fewer tools than the MCP server advertises | Expected — Spark respects your per-server policy. That's a feature. |
| I want to disable a server without deleting the config | Add `enabled: false` to that server's config block |

## Good First MCP Servers

**Start here:**
- filesystem
- git
- GitHub
- fetch / documentation servers
- one narrow internal API

**Avoid until you're comfortable:**
- Large business systems with many destructive actions
- Anything you don't understand well enough to constrain

## Related Docs

- [MCP (Model Context Protocol)](/docs/tools/mcp)
- [FAQ](/docs/reference/faq)
- [Slash Commands](/docs/cli/slash-commands)
