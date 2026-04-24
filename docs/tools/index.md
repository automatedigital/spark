---
sidebar_position: 1
title: "Tools & Toolsets"
description: "Overview of Spark Agent's tools - what's available, how toolsets work, and terminal backends"
---

# Tools & Toolsets

Tools are functions that extend what the agent can do. They're organized into **toolsets** — logical groups you can enable or disable per platform.

---

## What's Available

Spark ships with a broad built-in registry: web search, browser automation, terminal execution, file editing, memory, delegation, RL training, messaging delivery, Home Assistant, and more.

:::note
**Honcho cross-session memory** is available as a memory provider plugin (`plugins/memory/honcho/`), not as a built-in toolset. See [Plugins](../automate/plugins.md) for installation.
:::

| Category | Example tools | What you can do |
|----------|--------------|-----------------|
| **Web** | `web_search`, `web_extract` | Search the web and extract page content |
| **Terminal & Files** | `terminal`, `process`, `read_file`, `patch` | Run commands and manipulate files |
| **Browser** | `browser_navigate`, `browser_snapshot`, `browser_vision` | Automate a browser with text and vision support |
| **Media** | `vision_analyze`, `image_generate`, `text_to_speech` | Analyze images, generate images, and synthesize speech |
| **Agent orchestration** | `todo`, `clarify`, `execute_code`, `delegate_task` | Plan tasks, ask clarifying questions, run code, spawn subagents |
| **Memory & recall** | `memory`, `session_search` | Persist facts and search conversation history |
| **Automation & delivery** | `cronjob`, `send_message` | Schedule tasks and send outbound messages |
| **Integrations** | `ha_*`, MCP server tools, `rl_*` | Home Assistant, MCP, RL training, and more |

For the authoritative code-derived registry, see [Built-in Tools Reference](/docs/reference/tools-reference) and [Toolsets Reference](/docs/reference/toolsets-reference).

---

## Working with Toolsets

```bash
# Start with specific toolsets
spark chat --toolsets "web,terminal"

# See all available tools
spark tools

# Configure tools per platform (interactive)
spark tools
```

Common toolsets: `web`, `terminal`, `file`, `browser`, `vision`, `image_gen`, `moa`, `skills`, `tts`, `todo`, `memory`, `session_search`, `cronjob`, `code_execution`, `delegation`, `clarify`, `homeassistant`, and `rl`.

See [Toolsets Reference](/docs/reference/toolsets-reference) for the full set, including platform presets like `spark-cli` and `spark-telegram`, and dynamic MCP toolsets like `mcp-<server>`.

---

## Terminal Backends

The terminal tool can execute commands in several environments:

| Backend | Description | Use Case |
|---------|-------------|----------|
| `local` | Run on your machine (default) | Development, trusted tasks |
| `docker` | Isolated containers | Security, reproducibility |
| `ssh` | Remote server | Sandboxing, keeping the agent away from its own code |
| `singularity` | HPC containers | Cluster computing, rootless |
| `modal` | Cloud execution | Serverless, scale |
| `daytona` | Cloud sandbox workspace | Persistent remote dev environments |

### Configuration

```yaml
# In ~/.spark/config.yaml
terminal:
  backend: local    # or: docker, ssh, singularity, modal, daytona
  cwd: "."          # Working directory
  timeout: 180      # Command timeout in seconds
```

### Docker Backend

```yaml
terminal:
  backend: docker
  docker_image: python:3.11-slim
```

### SSH Backend

Recommended for security — the agent can't modify its own code when running on a remote server:

```yaml
terminal:
  backend: ssh
```

```bash
# Set credentials in ~/.spark/.env
TERMINAL_SSH_HOST=my-server.example.com
TERMINAL_SSH_USER=myuser
TERMINAL_SSH_KEY=~/.ssh/id_rsa
```

### Singularity/Apptainer

```bash
# Pre-build a SIF for parallel workers
apptainer build ~/python.sif docker://python:3.11-slim

# Configure
spark config set terminal.backend singularity
spark config set terminal.singularity_image ~/python.sif
```

### Modal (Serverless Cloud)

```bash
uv pip install modal
modal setup
spark config set terminal.backend modal
```

### Container Resources

Configure CPU, memory, disk, and persistence for any container backend:

```yaml
terminal:
  backend: docker  # or singularity, modal, daytona
  container_cpu: 1              # CPU cores (default: 1)
  container_memory: 5120        # Memory in MB (default: 5 GB)
  container_disk: 51200         # Disk in MB (default: 50 GB)
  container_persistent: true    # Persist filesystem across sessions (default: true)
```

When `container_persistent: true`, installed packages, files, and config survive across sessions.

### Container Security

All container backends run with hardening applied:

- Read-only root filesystem (Docker)
- All Linux capabilities dropped
- No privilege escalation
- PID limits (256 processes)
- Full namespace isolation
- Persistent workspace via volumes, not the writable root layer

Docker can optionally receive an explicit env allowlist via `terminal.docker_forward_env`, but forwarded variables are visible to commands inside the container and should be treated as exposed to that session.

---

## Background Process Management

Start a command in the background, then manage it with the `process` tool:

```python
terminal(command="pytest -v tests/", background=true)
# Returns: {"session_id": "proc_abc123", "pid": 12345}

# Manage with the process tool:
process(action="list")                              # Show all running processes
process(action="poll", session_id="proc_abc123")   # Check status
process(action="wait", session_id="proc_abc123")   # Block until done
process(action="log", session_id="proc_abc123")    # Full output
process(action="kill", session_id="proc_abc123")   # Terminate
process(action="write", session_id="proc_abc123", data="y")  # Send input
```

PTY mode (`pty=true`) enables interactive CLI tools like Codex and Claude Code.

---

## Sudo Support

If a command needs sudo, you'll be prompted for your password (cached for the session). Or set `SUDO_PASSWORD` in `~/.spark/.env` to avoid the prompt entirely.

:::warning
On messaging platforms, if sudo fails, the output includes a tip to add `SUDO_PASSWORD` to `~/.spark/.env`.
:::
