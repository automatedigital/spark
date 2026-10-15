<div align="center">

<img src="assets/spark-header.jpg" alt="Spark Agent Header" width="100%" style="max-width:900px; border-radius: 10px; margin-bottom: 20px;" />


<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/icon_small-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="assets/icon_small-light.png">
  <img alt="Spark" src="assets/icon_small-light.png" width="80">
</picture>

# Spark

**An AI agent workbench for chat, code, and automation**

A modular Python agent with a shared web and desktop workbench, terminal UI, and messaging gateway. Organize project conversations, inspect delegated work, use tools and skills, and keep durable tasks and memory across sessions. Provider support depends on the configured runtime and credentials.

<a href="https://github.com/automatedigital/spark/releases"><img src="https://img.shields.io/github/v/release/automatedigital/spark" alt="Latest Spark release"></a>
<a href="https://img.shields.io/github/commit-activity/m/automatedigital/spark">
  <img src="https://img.shields.io/github/commit-activity/m/automatedigital/spark?label=commits%20this%20month" alt="Commits this month" />
</a>


</div>

---

## Why Spark

- **Works everywhere** — Same agent in the TUI, scheduled jobs, messaging bots, and [ACP-compatible editors](./docs/integrations/acp.md) (VS Code, Zed, JetBrains).
- **Memory by default** — **Holographic** local memory is on by default and **updates itself at the end of every session** (auto-extraction), alongside persistent, curated patterns (`MEMORY.md` / `USER.md`). Run `/dream` for a deeper reflection pass and `/learnings` to review what it proposes. Optional [memory provider plugins](./docs/memory/providers.md) (Mem0, Honcho, and others) let you swap backends when you need them.
- **Coding-agent TUI** — File-aware context, tools, skills, checkpoints, and a polished terminal UI comparable in spirit to Claude Code or OpenCode-style workflows.
- **Task board + web dashboard** — Durable multi-agent task board (SQLite `kanban.db`), `spark kanban` / `/kanban`, REST + SSE in the bundled dashboard (`spark dashboard`), optional embed alongside the gateway, and an Admin area for bounded gateway/profile/diagnostic/plugin/MCP/backup/update control. Gateway worker dispatch is opt-in via `kanban.dispatch_in_gateway`. Configure under `dashboard.*` and `kanban.*` in `config.yaml`.
- **Project chat workbench** — Project-grouped conversations, pins and Inbox, recoverable drafts and attachments, conversation search, file/terminal/preview panels, and parent-linked subagent detail in the shared React UI.
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

### macOS Desktop App

A native **Spark.app** bundles the Web UI and Python backend in one drag-to-install package — no separate `spark dashboard` step.

**[Download Spark Desktop](https://github.com/automatedigital/spark/releases)** — choose the macOS artifact and read its release-specific requirements.

The repository also contains a Windows desktop beta build workflow. Platform artifacts and validation vary by release; a source build is not a claim that an installed package has passed QA.

**Install:**

1. Download **Spark.dmg** and open it.
2. Drag **Spark.app** to Applications.
3. Open **Spark.app** and follow the release's signing/install instructions.

For an unsigned development build, use **right-click → Open**; macOS may also
require **System Settings → Privacy & Security → Open Anyway**.

Fully silent installs require Apple notarization (`scripts/notarize_mac.sh` for maintainers with a Developer ID).

The desktop app uses the same `~/.spark/` config and state as the CLI.

### Manual / development install

See **[Installation](./docs/getting-started/installation.md)** in the docs (clone with submodules, venv, `pip install -e .`, shell hook).

Contributors should start with [Development](#development) below.

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

### 5. Update safely

Update from the terminal or use **Admin → Update** in the Web UI:

```bash
spark update
```

Spark updates the code and Python dependencies, rebuilds the current Web UI,
and verifies that every content-hashed JavaScript and CSS file referenced by
`index.html` exists before restarting the gateway. A complete production Web UI
bundle also ships with each update so existing VPS installations receive a
coherent dashboard during the upgrade. If a compatible Node.js runtime is not
available, Spark installs a checksum-verified managed Node.js 22 runtime under
your Spark home and uses it for the build.

An update that cannot produce a valid Web UI fails explicitly and does not
report success or restart Spark with an incomplete dashboard. Fix the reported
Node.js/npm or network error, then rerun `spark update`.

If a VPS was left on a blank dashboard by an older Spark version, SSH into the
server and run:

```bash
spark update
spark gateway restart
```

Then reload the dashboard. If the browser retained the old page, perform a hard
refresh once.

### 6. Diagnose any issues

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
/learnings    Review recent dreams and confirm/keep memory changes Spark proposes
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
| **Memory** | **Always-on by default**: at the end of each session Spark updates both the **Holographic** local store (auto-extraction) and curated `MEMORY.md`/`USER.md` — no action needed. This is the "gets smarter over time" behavior. Optional backends (Mem0, Honcho, …) — see [Memory](./docs/memory/index.md) and [Memory providers](./docs/memory/providers.md). |
| **Dream** | `/dream` — a heavier, **explicitly-invoked** reflection pass (never auto-fires at session end) that mines recent session transcripts + the holographic store via a single LLM synthesis call, proposes consolidated insights and a `MEMORY.md` cleanup, merges duplicates, and writes a human-readable summary to the llm-wiki under `dreams/`. Runs on demand or on a daily schedule. |
| **Learnings** | `/learnings` — review surface for what Spark has learned: see recent dreams and confirm/keep the memory changes Dream proposes (stale-fact removals are confirmed here, never applied silently). |
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
- **macOS, Linux, or WSL2** for the documented CLI/source installation. The separate native Windows desktop path is a beta workflow; consult its release notes for support and validation.
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
spark/
├── src/
│   ├── core/       # Runtime, session/task persistence, CLI orchestration
│   ├── agent/      # Prompts, compression, memory and model internals
│   ├── spark_cli/  # Commands, FastAPI, React web UI and Tauri shell
│   ├── tools/      # Built-in tools and lazy schema manifest
│   ├── gateway/    # Messaging platform adapters
│   └── plugins/    # Memory and extension plugins
├── skills/         # Bundled skill library
├── tests/
├── scripts/        # install.sh and utilities
└── docs/           # Markdown documentation
```

The complete ownership/build/state map is in [STRUCTURE.md](STRUCTURE.md).

## Development

Read [AGENTS.md](AGENTS.md) for development rules, [CONTEXT.md](CONTEXT.md) for
domain language, and [accepted architecture decisions](docs/adr/) before changing
runtime or persistence. [CLAUDE.md](CLAUDE.md) is a compact entry point to the same
rules. Issues are tracked in [GitHub Issues](https://github.com/automatedigital/spark/issues)
using the [repository tracker conventions](docs/agents/issue-tracker.md).

```bash
source .venv/bin/activate
pip install -e ".[dev,web]"
python -m pytest tests/ -m "not slow and not integration" -q
ruff check src/
mypy src/agent/ src/spark_cli/
python scripts/generate_tool_manifest.py --check

# React/Vite frontend: Node.js 22 and its own npm lockfile
(cd src/spark_cli/web && npm ci)
(cd src/spark_cli/web && npm run dev)
(cd src/spark_cli/web && npm run lint && npm test && npm run build)
```

Keep `.venv` active for servers and browser tests. Use an isolated `SPARK_HOME`
for manual testing. The existing browser suites cover concurrent chats, recovery,
drafts and sidebar scale; prerequisite details and exact flows are in
[AGENTS.md](AGENTS.md) and `.github/workflows/web-quality.yml`. Make changes in
`web/src/`; regenerate the tracked `web_dist/` bundle through the build workflow.
Verify installed desktop packages separately from the web build.
Vite proxies `/api` to `127.0.0.1:9119` by default; start the isolated dashboard
backend separately, or set `SPARK_API_TARGET` to its address.

## Upgrade roadmap

[PLAN.md](PLAN.md) tracks the approved app update based on pinned reviews of
[Hermes Agent](https://github.com/nousresearch/hermes-agent) for agent features and
[T3 Code](https://github.com/pingdotgg/t3code) for sidebar and orchestration-v2
patterns. It defines a five-day core slice, agent-sized packets, dependencies,
acceptance tests and separately estimated extensions.

Implemented foundations include atomic child lifecycle events, idempotent control
receipts, durable sidebar pin/order/settlement and fenced task workers with
profile-local transcripts. Async delegation and local Git worktree isolation are
opt-in (`delegation.async_enabled` and `delegation.worktree_isolation`, both false
by default). Async workers are process-local; lost work becomes uncertain and
stored results are delivered on the next explicit parent turn. The child
inspector adds capability-gated controls, paged history, result copy and worktree
references while preserving parent drafts and scroll position through switching
and reconnects. Verified task links open their actual board; an explicit action
opens an owned worktree as a project. Gateway approval ownership, final performance
and package acceptance remain in progress in the plan.
See the [rollout runbook](docs/development/app-upgrade-rollout.md) for backup,
isolated enablement and rollback boundaries.
