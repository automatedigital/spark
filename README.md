<div align="center">

<img src="assets/spark-header.jpg" alt="Spark Agent Header" width="100%" style="max-width:900px; border-radius: 10px; margin-bottom: 20px;" />


<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/icon_small-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="assets/icon_small-light.png">
  <img alt="Spark" src="assets/icon_small-light.png" width="80">
</picture>

# Spark

**A self-improving AI agent harness for the terminal and beyond**

A modular AI harness that runs in your terminal, connects to any LLM provider, and gets smarter over time. Learns from your sessions, adapts to your workflow, and bridges the terminal with messaging platforms like Telegram, Discord, and Slack.

<img src="https://img.shields.io/badge/version-1.2.6-blue" alt="Version 1.2.6">
<a href="https://img.shields.io/github/commit-activity/m/automatedigital/spark">
  <img src="https://img.shields.io/github/commit-activity/m/automatedigital/spark?label=commits%20this%20month" alt="Commits this month" />
</a>


</div>

---

## Why Spark

- **Works everywhere** — Same agent in the TUI, scheduled jobs, messaging bots, and [ACP-compatible editors](./docs/integrations/acp.md) (VS Code, Zed, JetBrains).
- **Memory by default** — **Holographic** local memory is on by default, together with persistent, curated patterns (`MEMORY.md` / `USER.md`). Optional [memory provider plugins](./docs/memory/providers.md) (Mem0, Honcho, and others) let you swap backends when you need them.
- **Coding-agent TUI** — File-aware context, tools, skills, checkpoints, and a polished terminal UI comparable in spirit to Claude Code or OpenCode-style workflows.
- **Task board + web dashboard** — Durable multi-agent task board (SQLite `kanban.db`), `spark kanban` / `/kanban`, REST + SSE in the bundled dashboard (`spark dashboard`), optional embed alongside the gateway, and an Admin area for bounded gateway/profile/diagnostic/plugin/MCP/backup/update control. Gateway worker dispatch is opt-in via `kanban.dispatch_in_gateway`. Configure under `dashboard.*` and `kanban.*` in `config.yaml`.
- **Simple layout** — One install directory, config and state under `~/.spark/` (or a [profile](./docs/cli/profiles.md)), and a clear split between CLI, gateway, tools, and plugins.
- **Straightforward onboarding** — One-line install; first launch runs interactive setup if you are not configured yet.

Full documentation lives in the **[`docs/`](./docs/)** directory. For a quick map, start with the **[Docs Navigation Guide](./docs/README.md)**.

---

## Quick Install

### macOS / Linux (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/automatedigital/spark/main/scripts/install.sh | bash
```

The script installs dependencies (Python, Node.js, ripgrep, ffmpeg, etc.), clones the project under `~/.spark/spark-agent` by default, creates a virtualenv, wires the global `spark` command, and runs the setup wizard when appropriate.

Useful installer flags:

```bash
curl -fsSL https://raw.githubusercontent.com/automatedigital/spark/main/scripts/install.sh | bash -s -- --help
# Examples:
#   --skip-setup     Skip the interactive setup wizard
#   --no-venv        Do not create a virtual environment
#   --branch NAME    Install from a specific branch
#   --dir PATH       Custom install directory (default: ~/.spark/spark-agent)
```

After install, reload your shell so `spark` is on your `PATH`:

```bash
source ~/.bashrc   # or: source ~/.zshrc
```

### Manual / development install

See **[Installation](./docs/getting-started/installation.md)** in the docs (clone with submodules, venv, `pip install -e .`, shell hook).

---

## Getting Started

### 1. First run

```bash
spark                   # Starts the interactive TUI; runs setup on first launch if needed
```

### 2. Configure your model

```bash
spark model             # Switch provider or model
spark model reasoning   # Show or set reasoning effort
```

Spark expects a model with **at least ~64K tokens** of context for reliable multi-step tool use.
Reasoning effort defaults to **medium**. Set it from the model picker, or directly:

```bash
spark model reasoning high    # none|minimal|low|medium|high|xhigh
```

### 3. Enable toolsets

```bash
spark tools             # Enable/disable toolsets
```

Start with the defaults for the CLI; add web, browser, or MCP toolsets as needed.

### 4. Open the Web UI

```bash
spark dashboard         # Starts the bundled Web UI on dashboard.host:dashboard.port
```

The bundled Web UI is configured by default. It can run standalone with
`spark dashboard`, and the gateway exposes it by default when the gateway is
running (`dashboard.enabled_with_gateway: true`). The default dashboard config
binds to `0.0.0.0:9119` for LAN/VPS access; open it locally at
`http://127.0.0.1:9119` or from another machine at `http://<host-or-ip>:9119`.
Remote API calls require the token in `~/.spark/dashboard.token` or
`SPARK_DASHBOARD_TOKEN`. Use it for status, config, API keys, logs, the task
board, and Admin controls.

### 5. Diagnose any issues

```bash
spark doctor            # Diagnose environment and config issues
spark doctor --fix      # Auto-fix what the doctor can repair safely
```

---

## Configuration

| Location | Purpose |
|----------|---------|
| `~/.spark/config.yaml` | Model, toolsets, terminal, gateway, memory, and other settings |
| `~/.spark/.env` | API keys and secrets (never commit these) |
| `~/.spark/skills/` | Installed skills |
| `~/.spark/logs/` | Rotating logs |
| `~/.spark/kanban.db` | Kanban task board (per [profile](./docs/cli/profiles.md)) |

---

## CLI

| Command | Description |
|---------|-------------|
| `spark` | Interactive TUI (default) |
| `spark setup` | Full interactive wizard (model, terminal backend, tools, messaging, …) |
| `spark setup permissions` | Set agent permission level (locked down / standard / full) |
| `spark model` | Switch provider or model |
| `spark model reasoning [level]` | Show or set reasoning effort (`medium` by default) |
| `spark tools` | Enable/disable toolsets |
| `spark gateway` | Messaging gateway (`--help` for start/stop/status/service) |
| `spark dashboard` | Start the bundled Web UI for status, config, keys, logs, task board, and Admin controls; defaults to `dashboard.host` / `dashboard.port` (`0.0.0.0:9119` in new configs) |
| `spark kanban` | Inspect the board, create tasks, or run dispatcher ticks (`kanban` / `kanban --help`) |
| `spark cron` | Scheduled tasks |
| `spark doctor` | Diagnose configuration and dependencies |
| `spark update` | Update to the latest version |
| `spark sessions browse` | Interactive session search and resume |
| `spark status` | Component status |
| `spark dump` | Compact setup summary for support/debugging |

**Profiles** — Isolated instances (separate config, keys, sessions): use `spark -p <name>` before any subcommand. See [Profiles](./docs/cli/profiles.md).

---

## Inside the TUI

Type **`/`** to see slash commands. Commonly used:

```
/model        Switch AI model for this session
/reasoning    Show or set reasoning effort/display in this session
/sessions     Browse and resume past sessions
/files        Fuzzy file picker — insert @path into your message
/memory       Show stored memories
/dream        Reflect on past sessions and consolidate memory (run once or schedule daily)
/goal         Set a durable objective Spark works toward across every session
/skills       Search and install skills
/kanban       Board summary, task details, or opt-in gateway dispatch
/keys         Show keyboard shortcuts
/clear        Clear screen, start a new session
/undo         Remove last exchange
/retry        Resend last message
/verbose      Cycle tool progress display
```

Full reference: [Slash commands](./docs/cli/slash-commands.md).

---

## Features

| Area | What you get |
|------|----------------|
| **Tools** | Terminal, files, web search, browser automation, vision, MCP, delegation, code execution, and more — grouped into [toolsets](./docs/reference/toolsets-reference.md) you can toggle per platform. |
| **Skills** | Shareable instruction packs ([agentskills.io](https://agentskills.io/specification)-compatible); browse and install from the TUI with `/skills`. |
| **Memory** | **Holographic** local store by default; optional backends (Mem0, Honcho, …) — see [Memory](./docs/memory.md) and [Memory providers](./docs/memory/providers.md). |
| **Dream** | `/dream` — offline reflection pass that mines recent session transcripts + the holographic store via a single LLM synthesis call, adds insights back to memory, merges duplicates, and writes a human-readable summary to the llm-wiki under `dreams/`. Runs on demand or on a daily schedule. |
| **Goal tracking** | `/goal <objective>` — set a durable, verifiable objective that Spark works toward across every session until you mark it done. Goals are backed by the Kanban board (`goals` board), so they're visible and manageable in the Dashboard in real time. Supports stopping conditions (`-- <done when>`), pause/resume, and a full history. |
| **Context** | Auto-loads project files like `AGENTS.md`, `.spark.md`, `SOUL.md`; `@` references for files, folders, and URLs. |
| **Gateway** | Same agent on Telegram, Discord, Slack, WhatsApp, Signal, and [other platforms](./docs/chat-platforms/index.md). |
| **Task board** | Shared board with worker claims, run history, templates, task duplication/retry, conversation-to-task entry points, and tooling for parallel agents (CLI, chat, dashboard API). |
| **Dashboard** | Local web UI + API; can run standalone or with the gateway for LAN access (see `dashboard.token` / `SPARK_DASHBOARD_TOKEN`). Includes an Admin section with allowlisted actions, confirmations, and live output for gateway control, profiles, diagnostics, plugins, MCP, backups, and updates. |
| **Cron** | Schedule natural-language or cron-style jobs; deliver results to chat or email. |
| **Safety** | Three permission levels (locked down / standard / full) set during setup or via `spark setup permissions`. Checkpoints before file edits, approval modes for risky commands, optional security scanning. |

---

## Requirements

- **Git** — the installer clones the repo and sets up the environment.
- **macOS, Linux, or WSL2** — Native Windows is not supported; use WSL2.
- **Python 3.11+** — Installed for you by the official installer (via `uv` on desktop).

---

## Documentation

- **[Docs Navigation Guide](./docs/README.md)** — Best first stop to find the right section quickly.
- **[Getting Started](./docs/getting-started/quickstart.md)** — Install, first run, and core setup path.
- **[Configuration](./docs/configuration.md)** — Main configuration concepts and keys.
- **[Guides](./docs/guides/)** — Task-oriented how-tos for deployment, MCP, automation, profiles, and more.
- **[CLI Slash Commands](./docs/cli/slash-commands.md)** — In-app command reference.
- **[Tools Reference](./docs/reference/tools-reference.md)** — Built-in tools and behavior.
- **[Building on Spark](./docs/building/architecture.md)** — Architecture and internals for contributors.

---

## Repository layout

```
spark-agent/
├── core/           # Agent runtime and conversation loop
├── agent/          # Prompts, compression, display, skills helpers
├── spark_cli/      # CLI entrypoint, config, web dashboard server
├── tools/          # Built-in tools and environments
├── gateway/        # Messaging platform adapters
├── plugins/        # Memory and extension plugins
├── skills/         # Bundled skill library
├── tests/
├── scripts/        # install.sh and utilities
└── docs/           # Markdown documentation
```

Developer-oriented detail: **[AGENTS.md](./AGENTS.md)**.
