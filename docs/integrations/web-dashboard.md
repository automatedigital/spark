---
sidebar_position: 15
title: "Web Dashboard"
description: "Browser-based dashboard for managing configuration, API keys, sessions, logs, analytics, cron jobs, and skills"
---

# Web Dashboard

Skip the YAML editing. `spark dashboard` opens a browser UI where you manage your entire Spark installation — API keys, config, sessions, logs, cron jobs, skills — without touching a terminal.

Everything runs on your machine. New configs bind the dashboard to `0.0.0.0:9119`
so it can be reached from your LAN or VPS network. Non-loopback API requests are
protected by the dashboard token.

## Get Started in One Command

```bash
spark dashboard
```

Starts the server using `dashboard.host` and `dashboard.port` from
`~/.spark/config.yaml` (`0.0.0.0:9119` by default in new configs). On the Spark
machine, open `http://127.0.0.1:9119`; from another machine, open
`http://<host-or-ip>:9119`. Stop it with `Ctrl-C`.

**Startup options:**

| Flag | Default | What it does |
|------|---------|--------------|
| `--port` | `dashboard.port` (`9119`) | Change the port |
| `--host` | `dashboard.host` (`0.0.0.0`) | Bind address |
| `--no-open` | — | Don't auto-open the browser |

```bash
spark dashboard --port 8080
spark dashboard --host 127.0.0.1 # local-only
spark dashboard --no-open
```

## Install the Dependencies First

The dashboard needs FastAPI and Uvicorn:

```bash
pip install spark-agent[web]
```

Already installed `spark-agent[all]`? You're set. If the frontend hasn't been built yet and `npm` is available, it builds itself on first launch.

---

## What Each Page Does

### Status — Your Installation at a Glance

The home page gives you a live snapshot:

- Agent version and release date
- Gateway running/stopped, PID, connected platforms
- Active session count (last 5 minutes)
- The 20 most recent sessions with model, message count, token usage, and a conversation preview

Refreshes every 5 seconds automatically.

### Config — Edit Settings Without Touching YAML

A form-based editor for `config.yaml`. All 150+ fields are auto-discovered from `DEFAULT_CONFIG` and grouped into tabbed categories:

| Tab | What you configure |
|-----|-------------------|
| **model** | Default model, provider, base URL, reasoning |
| **terminal** | Backend (local/docker/ssh/modal), timeout, shell |
| **display** | Skin, tool progress, spinner, resume display |
| **agent** | Max iterations, gateway timeout, service tier |
| **delegation** | Subagent limits, reasoning effort |
| **memory** | Provider selection, context injection |
| **approvals** | Dangerous command mode (ask/yolo/deny) |

Fields with known valid values render as dropdowns. Booleans are toggles. Everything else is a text input.

**Available actions:** Save, Reset to defaults, Export (JSON), Import (JSON).

:::tip
Config changes take effect on the next agent session or gateway restart. The dashboard writes to the same `config.yaml` that `spark config set` and the gateway use.
:::

### API Keys — Manage Credentials Visually

A clean view of your `.env` file. Keys are grouped by category:

- **LLM Providers** — OpenRouter, Anthropic, OpenAI, DeepSeek, etc.
- **Tool API Keys** — Browserbase, Firecrawl, Tavily, ElevenLabs, etc.
- **Messaging Platforms** — Telegram, Discord, Slack bot tokens, etc.
- **Agent Settings** — non-secret vars like `API_SERVER_ENABLED`

Each key shows its set/unset status, a redacted value preview, a description, a link to the provider's key page, an edit field, and a delete button. Advanced keys are hidden behind a toggle unless you need them.

### Sessions — Search and Inspect Every Conversation

Browse all agent sessions in one place. Each row shows:

- Session title and source platform icon (CLI, Telegram, Discord, Slack, cron)
- Model, message count, tool call count, last-active time
- Live sessions get a pulsing badge

**What you can do:**

- **Search** — full-text search using FTS5, with highlighted snippets
- **Expand** — load the full message history with color-coded roles (user, assistant, system, tool) and Markdown + syntax highlighting
- **Tool calls** — collapsible blocks showing function name and JSON args
- **Delete** — remove a session entirely

### Workspace Projects — Start From a Guided Scaffold

The sidebar can create project workspaces from a multi-step wizard:

- **Details** — project name and type: Blank, Static Website, Web Application, Design Project, Productivity Workspace, or Video Project
- **Starter** — starter stacks filtered by project type
- **Options** — package manager, Git initialization, AI skill preferences, development tools, and integrations
- **Review** — final summary before the workspace directory is created under Spark's workspace home

Implemented starters are scaffolded immediately. Framework starters such as
Astro, Eleventy, Next.js, SvelteKit, Nuxt, Design System and Remotion use
lightweight starter manifests that are ready for dependency installation;
workspace/design/video starters create organized folders and project-local
`AGENTS.md` skill guidance.

### Logs — Live-Tail with Filters

View `agent`, `errors`, and `gateway` log files with:

| Control | Options |
|---------|---------|
| File | `agent`, `errors`, `gateway` |
| Level | ALL, DEBUG, INFO, WARNING, ERROR |
| Component | all, gateway, agent, tools, cli, cron |
| Lines | 50, 100, 200, 500 |
| Auto-refresh | polls every 5 seconds |

Log lines are color-coded by severity: red for errors, yellow for warnings, dim for debug.

### Analytics — Token Usage and Cost Over Time

Select a time window (7, 30, or 90 days) and get:

- **Summary cards** — total tokens (input/output), cache hit %, estimated cost, session count with daily average
- **Daily token chart** — stacked bar chart with hover tooltips
- **Daily breakdown table** — date, sessions, input tokens, output tokens, cache rate, cost
- **Per-model breakdown** — which models you used, how much, and what they cost

### Cron — Create and Manage Scheduled Prompts

Schedule any prompt to run on a recurring basis:

- **Create** — name (optional), prompt, cron expression (e.g. `0 9 * * *`), delivery target (local, Telegram, Discord, Slack, email)
- **Job list** — name, prompt preview, schedule, state badge (enabled/paused/error), delivery target, last run, next run
- **Controls** — Pause/Resume, Trigger now, Delete

### Skills — Toggle Capabilities Per Session

Browse, search, and enable/disable skills loaded from `~/.spark/skills/`:

- **Search** — filter by name, description, or category
- **Category pills** — narrow to MLOps, MCP, GitHub, Productivity, etc.
- **Toggle** — flip a skill on or off; takes effect next session
- **Toolsets** — built-in toolsets with status, setup requirements, and included tools

:::warning Security
The dashboard reads and writes your `.env` file, including all API keys. When
accessing it from another machine, protected API routes require
`Authorization: Bearer <token>`; the SPA prompts for the token stored in
`~/.spark/dashboard.token` (or `SPARK_DASHBOARD_TOKEN`). Keep the dashboard on a
trusted LAN/VPN or bind it to `127.0.0.1` for local-only access.
:::

---

## Pick Up New Keys Without Restarting

After adding API keys in the dashboard (or editing `.env` directly), reload them into your running CLI session:

```
You -> /reload
  Reloaded .env (3 var(s) updated)
```

No restart needed. The new keys are immediately available for your next request.

---

## REST API Reference

The frontend calls these endpoints. You can call them too, for automation:

### Status & Config

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/status` | Agent version, gateway status, active session count |
| `GET` | `/api/config` | Current `config.yaml` as JSON |
| `GET` | `/api/config/defaults` | Default configuration values |
| `GET` | `/api/config/schema` | Field schema with types, descriptions, and select options |
| `PUT` | `/api/config` | Save config. Body: `{"config": {...}}` |

### Environment Variables

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/env` | All known env vars with set/unset status and redacted values |
| `PUT` | `/api/env` | Set a var. Body: `{"key": "VAR_NAME", "value": "secret"}` |
| `DELETE` | `/api/env` | Remove a var. Body: `{"key": "VAR_NAME"}` |

### Sessions

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/sessions` | 20 most recent sessions with metadata |
| `GET` | `/api/sessions/{session_id}` | Single session metadata |
| `GET` | `/api/sessions/{session_id}/messages` | Full message history including tool calls |
| `GET` | `/api/sessions/search` | Full-text search. Query: `?q=your+query` |
| `DELETE` | `/api/sessions/{session_id}` | Delete a session and its history |

### Logs & Analytics

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/logs` | Log lines. Params: `file`, `lines`, `level`, `component` |
| `GET` | `/api/analytics/usage` | Token usage, costs, daily breakdowns. Param: `?days=30` |

### Cron Jobs

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/cron/jobs` | All jobs with state and run history |
| `POST` | `/api/cron/jobs` | Create a job. Body: `{"prompt": "...", "schedule": "0 9 * * *", "name": "...", "deliver": "local"}` |
| `POST` | `/api/cron/jobs/{job_id}/pause` | Pause a job |
| `POST` | `/api/cron/jobs/{job_id}/resume` | Resume a job |
| `POST` | `/api/cron/jobs/{job_id}/trigger` | Run a job immediately |
| `DELETE` | `/api/cron/jobs/{job_id}` | Delete a job |

### Skills & Toolsets

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/skills` | All skills with name, description, category, enabled status |
| `PUT` | `/api/skills/toggle` | Enable or disable a skill. Body: `{"name": "skill-name", "enabled": true}` |
| `GET` | `/api/tools/toolsets` | All toolsets with label, tools, and active/configured status |

---

## CORS

The server allows HTTP origins and requires dashboard-token auth for non-loopback
API requests by default. Common local development origins include:

- `http://localhost:9119` / `http://127.0.0.1:9119`
- `http://localhost:3000` / `http://127.0.0.1:3000`
- `http://localhost:5173` / `http://127.0.0.1:5173` (Vite dev server)

Running on a custom port? That origin is added automatically.

---

## Developing the Frontend

```bash
# Terminal 1: start the backend
spark dashboard --no-open

# Terminal 2: start Vite with HMR
cd web/ && npm install && npm run dev
```

Vite at `http://localhost:5173` proxies `/api` to the FastAPI backend at `http://127.0.0.1:9119`. Stack: React 19, TypeScript, Tailwind v4. Production builds go to `spark_cli/web_dist/`.

When you run `spark update`, the frontend rebuilds automatically if `npm` is available. If not, `spark dashboard` builds it on the next launch.
