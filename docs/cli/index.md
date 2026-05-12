---
sidebar_position: 1
title: "CLI Interface"
description: "Master the Spark Agent terminal interface - commands, keybindings, personalities, and more"
---

# CLI Interface

Spark's CLI is a full terminal user interface — not a web app. You get multiline editing, slash-command autocomplete, conversation history, interrupt-and-redirect, and streaming tool output. Built for people who live in the terminal.

## Launch options

```bash
spark                                        # interactive session (default)
spark chat -q "Hello"                        # one-shot, non-interactive
spark chat --model "anthropic/claude-sonnet-4"
spark chat --provider nous                   # force a specific provider
spark chat --toolsets "web,terminal,skills"  # specific toolsets
spark -s spark-agent-dev,github-auth         # preload skills
spark --continue                             # resume last session (-c)
spark --resume <session_id>                  # resume a specific session (-r)
spark -w                                     # isolated git worktree
spark chat --verbose                         # debug output
```

## Reading the interface

The welcome banner shows your model, terminal backend, working directory, available tools, and installed skills.

### Status bar

A persistent bar sits above the input area and updates in real time:

```
 Spark claude-sonnet-4-20250514 | 12.4K/200K | [######----] 6% | $0.06 | 15m
```

| Element | What it shows |
|---------|-------------|
| Model name | Current model (truncated past 26 chars) |
| Token count | Context tokens used / max window |
| Context bar | Visual fill with color-coded thresholds |
| Cost | Estimated session cost (`n/a` for unknown/free models) |
| Duration | Elapsed session time |

The bar adapts to terminal width: full layout at 76+ columns, compact at 52–75, minimal (model + duration only) below 52.

**Context color thresholds:**

| Color | When | What it means |
|-------|-----------|---------|
| Green | < 50% | Plenty of room |
| Yellow | 50–80% | Getting full |
| Orange | 80–95% | Approaching limit |
| Red | ≥ 95% | Near overflow — run `/compress` |

Run `/usage` for a full breakdown including per-category costs.

### Resuming a session

When you resume (`spark -c` or `spark --resume <id>`), a "Previous Conversation" panel appears between the banner and input, showing a compact recap of history. See [Sessions — Conversation Recap on Resume](sessions.md#conversation-recap-on-resume) for config options.

## Keybindings

| Key | Action |
|-----|--------|
| `Enter` | Send message |
| `Alt+Enter` or `Ctrl+J` | Insert new line (multiline input) |
| `Alt+V` | Paste image from clipboard |
| `Ctrl+V` | Paste text and opportunistically attach clipboard images |
| `Ctrl+B` | Start/stop voice recording (when voice mode is on) |
| `Ctrl+C` | Interrupt agent (double-press within 2s to force exit) |
| `Ctrl+D` | Exit |
| `Ctrl+Z` | Suspend to background (Unix only — run `fg` to resume) |
| `Tab` | Accept autocomplete suggestion or slash command |

## Slash commands

Type `/` to open the autocomplete dropdown. Commands are case-insensitive — `/HELP` and `/help` are the same.

Common examples:

| Command | What it does |
|---------|-------------|
| `/help` | Show command help |
| `/model` | Show or change the current model |
| `/tools` | List currently active tools |
| `/skills browse` | Browse the skills hub |
| `/background <prompt>` | Run a prompt in a separate background session |
| `/skin` | Show or switch the active CLI skin |
| `/voice on` | Enable voice mode (press `Ctrl+B` to record) |
| `/voice tts` | Toggle spoken playback for Spark replies |
| `/reasoning high` | Increase reasoning effort |
| `/title My Session` | Name the current session |

Full reference: [Slash Commands Reference](../cli/slash-commands.md) · [Voice Mode](../voice/voice-mode.md)

## Model and Reasoning

Use `spark model` outside the chat UI to choose the default provider/model. The first menu lets you pick simple one-model mode, multi-model routing, or reasoning effort.

Reasoning effort controls the default thinking depth sent to models that support reasoning controls. It defaults to `medium` when unset.

```bash
spark model reasoning              # show current effort
spark model reasoning low          # lower-cost default
spark model reasoning high         # deeper default
spark model reasoning none         # disable reasoning controls
```

Valid levels are `none`, `minimal`, `low`, `medium`, `high`, and `xhigh`. In an active TUI session, `/reasoning <level>` changes the same setting and `/reasoning show` or `/reasoning hide` controls whether reasoning text is displayed.

## Multiline input

Two ways to write multiline messages:

1. **`Alt+Enter` or `Ctrl+J`** — inserts a newline
2. **Backslash continuation** — end a line with `\` to continue:

```
> Write a function that:\
  1. Takes a list of numbers\
  2. Returns the sum
```

Pasting multiline text works too.

## Interrupting the agent

You don't have to wait. While the agent is running:

- **Type a message and press `Enter`** — interrupts and processes your new input immediately
- **`Ctrl+C`** — interrupt (press twice within 2s to force exit)

Running terminal commands get killed immediately (SIGTERM, then SIGKILL after 1s). Multiple messages typed during an interrupt are combined into one prompt.

### Queue mode vs. interrupt mode

Control what happens when you press Enter while the agent is busy:

| Mode | Behavior |
|------|----------|
| `"interrupt"` (default) | Your message interrupts the current operation immediately |
| `"queue"` | Your message waits and sends as the next turn after the agent finishes |

```yaml
# ~/.spark/config.yaml
display:
  busy_input_mode: "queue"   # or "interrupt" (default)
```

Queue mode is useful when you want to prepare follow-up messages without canceling in-flight work.

### Suspend to background

Press `Ctrl+Z` to suspend Spark like any Unix process. Your shell prints:

```
Spark Agent has been suspended. Run `fg` to bring Spark Agent back.
```

Type `fg` to resume exactly where you left off.

## Quick commands

Define shell commands that run instantly without going through the LLM:

```yaml
# ~/.spark/config.yaml
quick_commands:
  status:
    type: exec
    command: systemctl status spark-agent
  gpu:
    type: exec
    command: nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader
```

Then type `/status` or `/gpu` in any chat — CLI or messaging platform. See [Configuration](/docs/configuration#quick-commands) for more examples.

## Personalities

Change the agent's tone without changing its capabilities:

```
/personality pirate
/personality kawaii
/personality concise
```

Built-in options: `helpful`, `concise`, `technical`, `creative`, `teacher`, `kawaii`, `catgirl`, `pirate`, `shakespeare`, `surfer`, `noir`, `uwu`, `philosopher`, `hype`.

Define your own in `~/.spark/config.yaml`:

```yaml
personalities:
  helpful: "You are a helpful, friendly AI assistant."
  kawaii: "You are a kawaii assistant! Use cute expressions..."
  pirate: "Arrr! Ye be talkin' to Captain Spark..."
```

## Preloading skills at launch

If you already know which skills you need, pass them at startup:

```bash
spark -s spark-agent-dev,github-auth
spark chat -s github-pr-workflow -s github-auth
```

Spark loads each skill into the session prompt before the first turn. Works in both interactive and one-shot mode.

## Skill slash commands

Every skill in `~/.spark/skills/` automatically becomes a slash command:

```
/gif-search funny cats
/axolotl help me fine-tune Llama 3 on my dataset
/github-pr-workflow create a PR for the auth refactor
/excalidraw         # loads the skill and lets it ask what you need
```

## Tool progress display

What you see while the agent works:

**Thinking animation:**
```
  - (think) pondering... (1.2s)
  - (think) contemplating... (2.4s)
  done got it! (3.1s)
```

**Tool execution feed:**
```
  | TERM terminal `ls -la` (0.3s)
  | SEARCH web_search (1.2s)
  | * web_extract (2.1s)
```

Cycle through display modes with `/verbose`: `off → new → all → verbose`.

Control how much of each tool's arguments show in preview lines:

```yaml
# ~/.spark/config.yaml
display:
  tool_preview_length: 80   # truncate at 80 chars (0 = no limit, default)
```

## Sessions

### Resume a previous session

When you exit, Spark prints a resume command:

```
Resume this session with:
  spark --resume 20260225_143052_a1b2c3
```

All resume options:

```bash
spark --continue                          # most recent CLI session
spark -c                                  # short form
spark -c "my project"                     # most recent session with that title
spark --resume 20260225_143052_a1b2c3     # by ID
spark --resume "refactoring auth"         # by title
spark -r 20260225_143052_a1b2c3           # short form
```

Resuming restores the full conversation — all messages, tool calls, and responses — exactly as you left it.

Name sessions with `/title My Session Name` in chat, or `spark sessions rename <id> <title>` from the shell. Browse past sessions with `spark sessions list`.

### Session storage

CLI sessions live in `~/.spark/state.db` (SQLite). The database stores:

- Session metadata (ID, title, timestamps, token counts)
- Full message history
- Session lineage across compressions and resumes
- Full-text search indexes

### Context compression

Long conversations are summarized automatically as you approach context limits:

```yaml
# ~/.spark/config.yaml
compression:
  enabled: true
  threshold: 0.50    # trigger at 50% of context window

auxiliary:
  compression:
    model: "google/gemini-3-flash-preview"   # model used for summarization
```

When compression triggers, the middle of the conversation is summarized. The first 3 and last 4 turns are always kept intact.

## Background sessions

Run a prompt in a separate session while keeping the CLI free:

```
/background Analyze the logs in /var/log and summarize any errors from today
```

Spark confirms immediately and returns your prompt:

```
BG Background task #1 started: "Analyze the logs in /var/log and summarize..."
   Task ID: bg_143022_a1b2c3
```

Background sessions are fully isolated — they have no knowledge of your current session's history. They inherit your model, provider, toolsets, and reasoning settings. You can run several in parallel.

When a task finishes, the result appears as a panel:

```
+- Spark (background #1) ----------------------------------+
| Found 3 errors in syslog from today:                         |
| 1. OOM killer invoked at 03:22 - killed process nginx        |
| 2. Disk I/O error on /dev/sda1 at 07:15                      |
| 3. Failed SSH login attempts from 192.168.1.50 at 14:30      |
+--------------------------------------------------------------+
```

Good use cases: long research tasks, file analysis across a repo, parallel investigations into different questions.

## Quiet mode

By default the CLI suppresses verbose tool logging and shows clean animated feedback. For debug output:

```bash
spark chat --verbose
```
