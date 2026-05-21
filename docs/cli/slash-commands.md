---
sidebar_position: 2
title: "Slash Commands Reference"
description: "Complete reference for interactive CLI and messaging slash commands"
---

# Slash Commands Reference

Spark has two slash-command surfaces, both driven by a central `COMMAND_REGISTRY` in `spark_cli/commands.py`:

- **Interactive CLI slash commands** — dispatched by `cli.py`, with autocomplete from the registry
- **Messaging slash commands** — dispatched by `gateway/run.py`, with help text and platform menus generated from the registry

Installed skills are also exposed as dynamic slash commands on both surfaces. That includes bundled skills like `/plan`, which opens plan mode and saves markdown plans under `.spark/plans/` relative to the active workspace/backend working directory.

## CLI Slash Commands

Type `/` in the CLI to open the autocomplete menu. Built-in commands are case-insensitive.

### Session

| Command | Description |
|---------|-------------|
| `/new` (alias: `/reset`) | Start a new session — fresh session ID and history |
| `/clear` | Clear screen and start a new session |
| `/history` | Show conversation history |
| `/save` | Save the current conversation |
| `/retry` | Resend the last message to the agent |
| `/undo` | Remove the last user/assistant exchange |
| `/title` | Set a title for the current session (usage: `/title My Session Name`) |
| `/compress [focus topic]` | Manually compress conversation context — flushes memories and summarizes. Optional focus topic narrows what the summary preserves. |
| `/rollback` | List or restore filesystem checkpoints (usage: `/rollback [number]`) |
| `/snapshot [create\|restore <id>\|prune]` (alias: `/snap`) | Create or restore state snapshots of Spark config/state. `create [label]` saves a snapshot, `restore <id>` reverts to it, `prune [N]` removes old snapshots, or list all with no args. |
| `/stop` | Kill all running background processes |
| `/queue <prompt>` (alias: `/q`) | Queue a prompt for the next turn — doesn't interrupt the current agent response. **Note:** `/q` is claimed by both `/queue` and `/quit`; the last registration wins, so `/q` resolves to `/quit` in practice. Use `/queue` explicitly. |
| `/resume [name]` | Resume a previously-named session |
| `/status` | Show session info |
| `/background <prompt>` (alias: `/bg`) | Run a prompt in a separate background session. Your current session stays free while the agent works independently. Results appear as a panel when the task finishes. See [CLI Background Sessions](index.md#background-sessions). |
| `/btw <question>` | Ask a quick side question using session context — no tools, not persisted. Useful for quick clarifications without affecting conversation history. |
| `/plan [request]` | Load the bundled `plan` skill to write a markdown plan instead of executing work. Plans are saved under `.spark/plans/` relative to the active workspace/backend working directory. |
| `/branch [name]` (alias: `/fork`) | Branch the current session to explore a different path |

### Configuration

| Command | Description |
|---------|-------------|
| `/config` | Show current configuration |
| `/model [model-name]` | Show or change the current model. Supports: `/model claude-sonnet-4`, `/model provider:model` (switch providers), `/model custom:model` (custom endpoint), `/model custom:name:model` (named custom provider), `/model custom` (auto-detect from endpoint). Use `--global` to persist to config.yaml. |
| `/provider` | Show available providers and the current provider |
| `/personality` | Set a predefined personality |
| `/verbose` | Cycle tool progress display: off → new → all → verbose. Can be [enabled for messaging](#notes) via config. |
| `/fast [normal\|fast\|status]` | Toggle fast mode — OpenAI Priority Processing / Anthropic Fast Mode. Options: `normal`, `fast`, `status`, `on`, `off`. |
| `/reasoning` | Manage reasoning effort and display (usage: `/reasoning [level\|show\|hide]`) |
| `/skin` | Show or change the display skin/theme |
| `/statusbar` (alias: `/sb`) | Toggle the context/model status bar on or off |
| `/voice [on\|off\|tts\|status]` | Toggle CLI voice mode and spoken playback. Recording uses `voice.record_key` (default: `Ctrl+B`). |
| `/yolo` | Toggle YOLO mode — skip all dangerous command approval prompts |

### Tools & Skills

| Command | Description |
|---------|-------------|
| `/tools [list\|disable\|enable] [name...]` | Manage tools: list available tools, or disable/enable specific tools for the current session. Disabling a tool removes it from the agent's toolset and triggers a session reset. |
| `/toolsets` | List available toolsets |
| `/browser [connect\|disconnect\|status]` | Manage local Chrome CDP connection. `connect` attaches browser tools to a running Chrome instance (default: `ws://localhost:9222`). `disconnect` detaches. `status` shows current connection. Auto-launches Chrome if no debugger is detected. |
| `/skills` | Search, install, inspect, or manage skills from online registries |
| `/dream [now\|schedule\|unschedule\|status\|review]` | Offline reflection pass over recent sessions and memory. See [Dream](#dream). |
| `/goal [<objective>\|status\|pause\|resume\|done\|clear\|history]` | Set or manage a durable objective Spark pursues across every session. Backed by the Kanban board — manageable in the Dashboard in real time. See [Goal tracking](#goal-tracking). |
| `/cron` | Manage scheduled tasks (list, add/create, edit, pause, resume, run, remove) |
| `/reload-mcp` (alias: `/reload_mcp`) | Reload MCP servers from config.yaml |
| `/reload` | Reload `.env` variables into the running session — picks up new API keys without restarting |
| `/plugins` | List installed plugins and their status |

### Info

| Command | Description |
|---------|-------------|
| `/help` | Show the help message |
| `/usage` | Show token usage, cost breakdown, and session duration |
| `/insights` | Show usage insights and analytics (last 30 days) |
| `/platforms` (alias: `/gateway`) | Show gateway/messaging platform status |
| `/paste` | Check clipboard for an image and attach it |
| `/image <path>` | Attach a local image file for your next prompt |
| `/debug` | Upload debug report (system info + logs) and get shareable links. Also available in messaging. |
| `/profile` | Show active profile name and home directory |

### Exit

| Command | Description |
|---------|-------------|
| `/quit` | Exit the CLI (also: `/exit`). See note on `/q` under `/queue` above. |

### Dynamic CLI Slash Commands

| Command | Description |
|---------|-------------|
| `/<skill-name>` | Load any installed skill as an on-demand command. Example: `/gif-search`, `/github-pr-workflow`, `/excalidraw`. |
| `/skills ...` | Search, browse, inspect, install, audit, publish, and configure skills from registries and the official optional-skills catalog. |

### Quick Commands

Map short aliases to longer prompts. Configure them in `~/.spark/config.yaml`:

```yaml
quick_commands:
  review: "Review my latest git diff and suggest improvements"
  deploy: "Run the deployment script at scripts/deploy.sh and verify the output"
  morning: "Check my calendar, unread emails, and summarize today's priorities"
```

Then type `/review`, `/deploy`, or `/morning` in the CLI. Quick commands resolve at dispatch time and don't appear in the built-in autocomplete/help tables.

### Alias Resolution

Commands support prefix matching: `/h` resolves to `/help`, `/mod` resolves to `/model`. When a prefix is ambiguous (matches multiple commands), the first match in registry order wins. Full command names and registered aliases always take priority over prefix matches.

## Messaging Slash Commands

These commands work inside Telegram, Discord, Slack, WhatsApp, Signal, Email, and Home Assistant chats:

| Command | Description |
|---------|-------------|
| `/new` | Start a new conversation |
| `/reset` | Reset conversation history |
| `/status` | Show session info |
| `/stop` | Kill all running background processes and interrupt the running agent |
| `/model [provider:model]` | Show or change the model. Supports provider switches (`/model zai:glm-5`), custom endpoints (`/model custom:model`), named custom providers (`/model custom:local:qwen`), and auto-detect (`/model custom`). Use `--global` to persist to config.yaml. |
| `/provider` | Show provider availability and auth status |
| `/personality [name]` | Set a personality overlay for the session |
| `/fast [normal\|fast\|status]` | Toggle fast mode — OpenAI Priority Processing / Anthropic Fast Mode |
| `/retry` | Retry the last message |
| `/undo` | Remove the last exchange |
| `/sethome` (alias: `/set-home`) | Mark the current chat as the platform home channel for deliveries |
| `/compress [focus topic]` | Manually compress conversation context. Optional focus topic narrows what the summary preserves. |
| `/title [name]` | Set or show the session title |
| `/resume [name]` | Resume a previously named session |
| `/usage` | Show token usage, estimated cost breakdown (input/output), context window state, and session duration |
| `/insights [days]` | Show usage analytics |
| `/reasoning [level\|show\|hide]` | Change reasoning effort or toggle reasoning display. Levels: `none`, `minimal`, `low`, `medium`, `high`, `xhigh`; unset defaults to `medium`. |
| `/voice [on\|off\|tts\|join\|channel\|leave\|status]` | Control spoken replies in chat. `join`/`channel`/`leave` manage Discord voice-channel mode. |
| `/rollback [number]` | List or restore filesystem checkpoints |
| `/snapshot [create\|restore <id>\|prune]` (alias: `/snap`) | Create or restore state snapshots of Spark config/state |
| `/background <prompt>` | Run a prompt in a separate background session. Results are delivered back to the same chat when the task finishes. See [Messaging Background Sessions](../chat-platforms/index.md#background-sessions). |
| `/plan [request]` | Load the bundled `plan` skill to write a markdown plan instead of executing work. Plans are saved under `.spark/plans/` relative to the active workspace/backend working directory. |
| `/reload-mcp` (alias: `/reload_mcp`) | Reload MCP servers from config |
| `/reload` | Reload `.env` variables into the running session |
| `/yolo` | Toggle YOLO mode — skip all dangerous command approval prompts |
| `/commands [page]` | Browse all commands and skills (paginated) |
| `/approve [session\|always]` | Approve and execute a pending dangerous command. `session` approves for this session only; `always` adds to the permanent allowlist. |
| `/deny` | Reject a pending dangerous command |
| `/update` | Update Spark Agent to the latest version |
| `/restart` | Gracefully restart the gateway after draining active runs. Sends a confirmation to the requester's chat/thread when back online. |
| `/debug` | Upload debug report (system info + logs) and get shareable links |
| `/help` | Show messaging help |
| `/<skill-name>` | Invoke any installed skill by name |

## Dream

`/dream` runs an offline reflective consolidation pass over recent session transcripts and the holographic memory store. A single LLM synthesis call extracts durable insights, merges semantically-duplicate facts, and writes a human-readable journal entry to the llm-wiki under `dreams/`.

| Subcommand | What it does |
|-----------|--------------|
| `/dream` or `/dream now` | Run a pass immediately (prompts on first run) |
| `/dream schedule` | Enable daily automatic runs (fires at 03:00 local by default) |
| `/dream unschedule` | Disable the daily schedule |
| `/dream status` | Show last run time, total runs, schedule state, and wiki path |
| `/dream review` | List facts flagged as potentially stale — confirm removal with `/memory` |

## Goal tracking

`/goal` sets a **durable, verifiable objective** that Spark actively pursues across every session until you mark it done or clear it. The active goal is injected into the agent's system prompt at the start of every conversation, so the model always knows what you're working toward.

Goals are backed by the **Kanban board** (`goals` board in `kanban.db`). This means goal state is shared with the Dashboard — drag a card to a new column and the CLI picks it up immediately, and vice versa.

### Setting a goal

```
/goal Ship the payment service refactor
```

With an optional stopping condition (the test Spark uses to know when it's done):

```
/goal Ship the payment service refactor -- all CI green and deployed to staging
```

The `--` separator works; so do `when:` and `done when:` as alternatives.

### Subcommands

| Subcommand | What it does |
|-----------|--------------|
| `/goal` or `/goal status` | Show the active goal, task ID, and Dashboard link |
| `/goal pause` | Pause the goal — Spark acknowledges it but stops actively pursuing it |
| `/goal resume` | Resume a paused goal |
| `/goal done` | Mark the active goal complete and move it to the done column |
| `/goal clear` | Archive the active goal without marking it done |
| `/goal history` | Show recent completed and cleared goals |

### Dashboard integration

Open the Dashboard → **Tasks** page and click the **🎯 Goals** button (top-right of the board header) to switch to the goals board. From there you can:

- **Drag cards** between columns to change goal state (todo → blocked = pause, blocked → todo = resume, any → done = complete)
- **Edit the title** (objective) or **body** (stopping condition) inline in the task detail panel
- **View the full event log** — every state change from both the CLI and the Dashboard is recorded

The board slug is `goals` if you prefer to type it manually in the Board input field.

### How the agent uses the goal

The active goal is prepended to the system prompt as:

```
## Active Goal
**Objective:** Ship the payment service refactor
**Done when:** all CI green and deployed to staging
**Board task:** t_abc123 (goals board)

Keep this goal in mind across every reply. When the user's request is
unrelated, complete it as asked and note any progress or blockers toward
the goal. Do not declare the goal complete unless the stopping condition
is explicitly met.
```

When you set or change a goal mid-session, the system prompt is invalidated and rebuilt on the next turn — no restart needed.

### Tips

- **One active goal at a time.** Setting a new goal archives the previous one automatically.
- **Paused goals stay visible** in the Dashboard (blocked column) so you can track them without losing context.
- **Stopping conditions** are the key to good goals. Vague objectives like "improve performance" are hard to complete; specific ones like "p95 latency below 200ms on the checkout endpoint" give Spark a clear finish line.
- **Break big goals into Kanban tasks.** Use `/kanban` or the Dashboard to create child tasks under a goal and dispatch workers to tackle them in parallel.

## Notes

- `/skin`, `/tools`, `/toolsets`, `/browser`, `/config`, `/cron`, `/skills`, `/platforms`, `/paste`, `/image`, `/statusbar`, and `/plugins` are **CLI-only** commands.
- `/verbose` is **CLI-only by default**, but can be enabled for messaging platforms by setting `display.tool_progress_command: true` in `config.yaml`. When enabled, it cycles the `display.tool_progress` mode and saves to config.
- `/sethome`, `/update`, `/restart`, `/approve`, `/deny`, and `/commands` are **messaging-only** commands.
- `/status`, `/background`, `/voice`, `/reload-mcp`, `/rollback`, `/snapshot`, `/debug`, `/fast`, and `/yolo` work in **both** the CLI and the messaging gateway.
- `/voice join`, `/voice channel`, and `/voice leave` are only meaningful on Discord.
