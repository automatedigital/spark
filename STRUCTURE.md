# Spark Agent — Repository Structure

Quick orientation for new contributors. See `AGENTS.md` for the detailed developer guide.

## Top-Level Directories

| Directory | What lives here |
|-----------|----------------|
| `src/` | All Python source packages (see below) |
| `tests/` | Pytest suite: ~3000 tests across unit, integration, and e2e. Run with `pytest tests/` |
| `docs/` | Full documentation: guides, developer guide, reference, integration specs |
| `scripts/` | `install.sh` (one-liner installer), release scripts, utilities |
| `docker/` | Docker Compose and Dockerfile configs |
| `assets/` | Brand assets (banner, icons) |
| `skills/` | Built-in skill library, ~26 categories. Users install custom skills to `~/.spark/skills/` |
| `environments/` | RL training environments (Atropos) and terminal backends (Docker, SSH, Modal, Daytona) |

## Python Packages (`src/`)

| Package | What lives here |
|---------|----------------|
| `src/core/` | Agent runtime: `run_agent.py` (AIAgent loop), `cli.py` (prompt_toolkit TUI), `spark_state.py` (SQLite sessions), `model_tools.py` (tool dispatch) |
| `src/agent/` | Agent internals: prompt building, context compression, memory management, model metadata, display/spinner |
| `src/spark_cli/` | CLI entry point (`main.py`) and all `spark` subcommands; also contains the React/Vite web dashboard (`web/`) and FastAPI server |
| `src/tools/` | Tool implementations — one file per tool, registered via `tools/registry.py`. 40+ tools: terminal, file, web, vision, browser, code execution, MCP, delegation |
| `src/gateway/` | Messaging platform gateway: Telegram, Discord, Slack, WhatsApp, Signal, Matrix, and more. Entry via `gateway/run.py` |
| `src/plugins/` | Pluggable memory backends: Honcho, Mem0, Supermemory, RetainDB, Hindsight, etc. |
| `src/cron/` | Natural-language cron scheduler — `spark cron` subcommand, job definitions, scheduler loop |
| `src/acp_adapter/` | Agent Client Protocol server for editor integrations (VS Code, Zed, JetBrains) |

## Key Config Files

| File | Purpose |
|------|---------|
| `pyproject.toml` | Python package definition, dependencies, entry points, ruff/mypy config |
| `package.json` | Node dependencies (browser automation tools) |
| `.env.example` | Template for `~/.spark/.env` — API keys and secrets |
| `docs/cli-config.yaml.example` | Full config reference for `~/.spark/config.yaml` |
| `AGENTS.md` | Developer guide for AI coding assistants — read this first |

## User Data (not in repo)

All user state lives in `~/.spark/` (overridable via `SPARK_HOME`):

```
~/.spark/
├── config.yaml       # Runtime configuration
├── .env              # API keys (never committed)
├── SOUL.md           # Persistent agent identity/preferences
├── memories/         # Long-term memory entries (full-text searchable)
├── sessions/         # Conversation history (SQLite)
├── skills/           # User-installed skills
├── cache/vision/     # Temporary vision tool image downloads
├── logs/             # Agent, error, and gateway logs
└── profiles/         # Named profiles for multi-instance setups
```
