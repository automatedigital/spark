---
sidebar_position: 11
title: "ACP Editor Integration"
description: "Use Spark Agent inside ACP-compatible editors such as VS Code, Zed, and JetBrains"
---

# ACP Editor Integration

Run Spark as a coding agent inside your editor — not just in a terminal. When you start Spark in ACP mode, ACP-compatible editors like VS Code, Zed, and JetBrains connect to it over stdio and render everything natively:

- Chat messages and streaming responses
- Tool activity and progress
- File diffs and patches
- Terminal command output
- Approval prompts for dangerous commands
- Thinking tokens and reasoning chunks

This is the right mode when you want Spark to feel like a built-in editor assistant rather than an external bot.

## What Tools Are Available in ACP Mode

Spark runs a curated `spark-acp` toolset tuned for editor workflows:

- **File tools:** `read_file`, `write_file`, `patch`, `search_files`
- **Terminal tools:** `terminal`, `process`
- **Web/browser tools**
- **Memory, todo, session search**
- **Skills**
- **`execute_code` and `delegate_task`**
- **Vision**

Tools that don't fit editor UX — messaging delivery, cron management — are intentionally excluded.

## Installation

Install Spark, then add the ACP extra:

```bash
pip install -e '.[acp]'
```

This pulls in the `agent-client-protocol` dependency and enables three entry points:

```bash
spark acp
spark-acp
python -m acp_adapter
```

## Starting the ACP Server

Any of these commands starts Spark in ACP mode:

```bash
spark acp
```

```bash
spark-acp
```

```bash
python -m acp_adapter
```

Spark logs to stderr, keeping stdout free for ACP JSON-RPC traffic.

## Editor Setup

### VS Code

Install an ACP client extension and point it at the repo's registry directory:

```json
{
  "acpClient.agents": [
    {
      "name": "spark-agent",
      "registryDir": "/path/to/spark-agent/acp_adapter/registry"
    }
  ]
}
```

### Zed

```json
{
  "agent_servers": {
    "spark-agent": {
      "type": "custom",
      "command": "spark",
      "args": ["acp"],
    },
  },
}
```

### JetBrains

Use an ACP-compatible plugin and point it at:

```text
/path/to/spark-agent/acp_adapter/registry
```

## Registry Manifest

The ACP registry manifest lives at:

```text
acp_adapter/registry/agent.json
```

It advertises a command-based agent with the launch command `spark acp`.

## Configuration & Credentials

ACP mode shares Spark's standard config — no separate setup needed:

| File | Purpose |
|------|---------|
| `~/.spark/.env` | API keys and secrets |
| `~/.spark/config.yaml` | Model, toolset, and behavior config |
| `~/.spark/skills/` | Skills |
| `~/.spark/state.db` | Session history |

Provider resolution uses Spark's normal runtime resolver, so ACP inherits your currently configured provider and credentials automatically.

## Session Behavior

The ACP adapter maintains an in-memory session manager per server process. Each session tracks:

- Session ID
- Working directory
- Selected model
- Conversation history
- Cancel event

The underlying `AIAgent` still uses Spark's normal persistence paths. ACP `list/load/resume/fork` operations are scoped to the currently running server process.

## Working Directory

ACP sessions bind the editor's working directory to the Spark task ID. File and terminal tools run relative to the editor workspace — not the server's process working directory.

## Approvals

Dangerous terminal commands route back to the editor as approval prompts. Options are simple:

- Allow once
- Allow always
- Deny

On timeout or error, the approval bridge denies the request.

## Troubleshooting

### Agent doesn't appear in the editor

Check all three:

- The editor is pointing at the correct `acp_adapter/registry/` path
- Spark is installed and on your PATH
- The ACP extra is installed: `pip install -e '.[acp]'`

### ACP starts but immediately errors

Run these diagnostics:

```bash
spark doctor
spark status
spark acp
```

### Missing credentials

ACP mode has no login flow of its own. Configure credentials with:

```bash
spark model
```

Or by editing `~/.spark/.env` directly.

## See also

- [ACP Internals](../../building/editor-extension-internals.md)
- [Provider Runtime Resolution](../../building/provider-runtime.md)
- [Tools Runtime](../../building/tools-runtime.md)
