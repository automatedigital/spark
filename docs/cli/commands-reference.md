---
sidebar_position: 1
title: "CLI Commands Reference"
description: "Authoritative reference for Spark terminal commands and command families"
---

# CLI Commands Reference

These are the commands you run in your shell. For commands you type inside a running chat session, see [Slash Commands Reference](./slash-commands.md).

## The `spark` entrypoint

```bash
spark [global-options] <command> [subcommand/options]
```

### Global options

These apply to any command:

| Option | What it does |
|--------|-------------|
| `--version`, `-V` | Print version and exit |
| `--profile <name>`, `-p <name>` | Use a specific profile for this run, ignoring the sticky default |
| `--resume <session>`, `-r <session>` | Jump back into a session by ID or title |
| `--continue [name]`, `-c [name]` | Resume the most recent session (optionally matching a title) |
| `--worktree`, `-w` | Start in an isolated git worktree for parallel-agent work |
| `--yolo` | Skip approval prompts for dangerous commands |
| `--pass-session-id` | Inject the session ID into the agent's system prompt |

## Command index

| Command | What you get |
|---------|-------------|
| `spark chat` | Interactive TUI or one-shot queries |
| `spark model` | Pick your provider and model interactively |
| `spark gateway` | Run and manage the messaging gateway |
| `spark setup` | Wizard-style configuration for any part of Spark |
| `spark whatsapp` | Pair and configure the WhatsApp bridge |
| `spark auth` | Manage API keys and OAuth credentials |
| `spark status` | Agent, auth, and platform health at a glance |
| `spark cron` | Schedule and manage automated jobs |
| `spark webhook` | Subscribe to external events and trigger the agent |
| `spark doctor` | Diagnose and fix config or dependency issues |
| `spark dump` | Copy-pasteable support summary |
| `spark debug` | Upload logs and system info for support |
| `spark backup` | Zip up your entire Spark home |
| `spark import` | Restore from a backup zip |
| `spark logs` | View and tail log files |
| `spark config` | Read and edit configuration |
| `spark pairing` | Manage messaging pairing codes |
| `spark skills` | Browse, install, and manage skills |
| `spark honcho` | Manage Honcho cross-session memory |
| `spark memory` | Configure external memory providers |
| `spark acp` | Run Spark as an ACP server for editor integration |
| `spark mcp` | Configure MCP servers or expose Spark as an MCP server |
| `spark plugins` | Install, enable, and disable plugins |
| `spark tools` | Configure which tools are active per platform |
| `spark sessions` | Browse, export, rename, and prune sessions |
| `spark insights` | Token, cost, and activity analytics |
| `spark claw` | Migrate from OpenClaw |
| `spark dashboard` | Browser-based config and monitoring UI |
| `spark profile` | Create and switch between isolated Spark instances |
| `spark completion` | Shell tab-completion scripts |
| `spark version` | Print version info |
| `spark update` | Pull latest code and reinstall |
| `spark uninstall` | Remove Spark from the system |

---

## `spark chat`

```bash
spark chat [options]
```

Your main entry point. Run `spark` with no arguments to open the interactive TUI. Add `-q` to send a single query and exit.

| Option | What it does |
|--------|-------------|
| `-q`, `--query "..."` | One-shot query, non-interactive |
| `-m`, `--model <model>` | Override the model for this run |
| `-t`, `--toolsets <csv>` | Enable a specific set of toolsets |
| `--provider <provider>` | Force a provider: `auto`, `openrouter`, `nous`, `openai-codex`, `copilot-acp`, `copilot`, `anthropic`, `gemini`, `huggingface`, `zai`, `kimi-coding`, `minimax`, `minimax-cn`, `kilocode`, `xiaomi`, `arcee` |
| `-s`, `--skills <name>` | Preload skills for the session (repeat or comma-separate) |
| `-v`, `--verbose` | Verbose output |
| `-Q`, `--quiet` | Suppress banner, spinner, and tool previews — useful for scripting |
| `--image <path>` | Attach a local image to a single query |
| `--resume <session>` / `--continue [name]` | Resume a previous session |
| `--worktree` | Create an isolated git worktree for this run |
| `--checkpoints` | Save filesystem checkpoints before destructive file changes |
| `--yolo` | Skip all approval prompts |
| `--pass-session-id` | Inject the session ID into the system prompt |
| `--source <tag>` | Tag this session's source (default: `cli`; use `tool` for integrations that shouldn't appear in user session lists) |
| `--max-turns <N>` | Cap tool-calling iterations per turn (default: 90, or `agent.max_turns` in config) |

**Examples:**

```bash
spark
spark chat -q "Summarize the latest PRs"
spark chat --provider openrouter --model anthropic/claude-sonnet-4.6
spark chat --toolsets web,terminal,skills
spark chat --quiet -q "Return only JSON"
spark chat --worktree -q "Review this repo and open a PR"
```

---

## `spark model`

```bash
spark model
```

Opens an interactive picker for provider and model selection. Use this to:

- Switch default providers
- Log into OAuth-backed providers
- Pick from a provider's model list
- Configure a custom or self-hosted endpoint
- Save the new default to config

### Switch mid-session with `/model`

You don't need to restart to change models. Inside any session:

```
/model                              # Show current model + available options
/model claude-sonnet-4              # Switch model (auto-detects provider)
/model zai:glm-5                    # Switch provider and model
/model custom:qwen-2.5              # Use model on your custom endpoint
/model custom                       # Auto-detect model from custom endpoint
/model custom:local:qwen-2.5        # Use a named custom provider
/model openrouter:anthropic/claude-sonnet-4  # Switch back to cloud
```

Provider and base URL changes persist to `config.yaml` automatically. Switching away from a custom endpoint clears the stale base URL so it doesn't leak into other providers.

---

## `spark gateway`

```bash
spark gateway <subcommand>
```

| Subcommand | What it does |
|------------|-------------|
| `run` | Run the gateway in the foreground — recommended for WSL and Termux |
| `start` | Start the installed systemd/launchd background service |
| `stop` | Stop the service (or foreground process) |
| `restart` | Restart the service |
| `status` | Show service status |
| `install` | Install as a systemd (Linux) or launchd (macOS) service |
| `uninstall` | Remove the installed service |
| `setup` | Interactive messaging-platform setup |

:::tip WSL users
Use `spark gateway run` instead of `spark gateway start` — WSL's systemd support is unreliable. Wrap it in tmux for persistence: `tmux new -s spark 'spark gateway run'`. See [WSL FAQ](/docs/reference/faq#wsl-gateway-keeps-disconnecting-or-spark-gateway-start-fails) for details.
:::

---

## `spark setup`

```bash
spark setup [model|tts|terminal|gateway|tools|agent] [--non-interactive] [--reset]
```

Run the full wizard or jump directly to a section:

| Section | What it configures |
|---------|-------------|
| `model` | Provider and model |
| `terminal` | Terminal backend and sandbox |
| `gateway` | Messaging platform connections |
| `tools` | Enable/disable tools per platform |
| `agent` | Agent behavior settings |

| Option | What it does |
|--------|-------------|
| `--non-interactive` | Use defaults and env values without prompting |
| `--reset` | Reset config to defaults before running setup |

---

## `spark whatsapp`

```bash
spark whatsapp
```

Runs the WhatsApp pairing flow, including mode selection and QR-code pairing.

---

## `spark auth`

Manage API keys and OAuth credentials. Supports credential pools for key rotation.

```bash
spark auth                                              # Interactive wizard
spark auth list                                         # Show all pools
spark auth list openrouter                              # Show a specific provider
spark auth add openrouter --api-key sk-or-v1-xxx        # Add an API key
spark auth add anthropic --type oauth                   # Add OAuth credential
spark auth remove openrouter 2                          # Remove by index
spark auth reset openrouter                             # Clear cooldowns
```

Subcommands: `add`, `list`, `remove`, `reset`. No subcommand opens the interactive wizard.

See [Credential Pools](/docs/providers/credential-pools) for the full reference.

:::caution
`spark login` has been removed. Use `spark auth` to manage OAuth credentials, `spark model` to select a provider, or `spark setup` for full interactive setup.
:::

---

## `spark status`

```bash
spark status [--all] [--deep]
```

| Option | What it does |
|--------|-------------|
| `--all` | Show all details in a shareable redacted format |
| `--deep` | Run deeper checks (takes longer) |

---

## `spark cron`

```bash
spark cron <list|create|edit|pause|resume|run|remove|status|tick>
```

| Subcommand | What it does |
|------------|-------------|
| `list` | Show scheduled jobs |
| `create` / `add` | Create a job from a prompt; attach skills with repeated `--skill` |
| `edit` | Update schedule, prompt, name, delivery, repeat count, or skills. Supports `--clear-skills`, `--add-skill`, `--remove-skill` |
| `pause` | Pause a job without deleting it |
| `resume` | Resume a paused job and compute its next future run |
| `run` | Trigger a job on the next scheduler tick |
| `remove` | Delete a scheduled job |
| `status` | Check whether the cron scheduler is running |
| `tick` | Run due jobs once and exit |

---

## `spark webhook`

```bash
spark webhook <subscribe|list|remove|test>
```

Create and manage webhook subscriptions that trigger the agent when external events arrive. If webhooks aren't configured, this command prints setup instructions.

| Subcommand | What it does |
|------------|-------------|
| `subscribe` / `add` | Create a webhook route; returns the URL and HMAC secret |
| `list` / `ls` | Show all agent-created subscriptions |
| `remove` / `rm` | Delete a dynamic subscription (static routes in config.yaml are unaffected) |
| `test` | Send a test POST to verify a subscription works |

### `spark webhook subscribe`

```bash
spark webhook subscribe <name> [options]
```

| Option | What it does |
|--------|-------------|
| `--prompt` | Prompt template with `{dot.notation}` payload references |
| `--events` | Comma-separated event types to accept (e.g. `issues,pull_request`). Empty = all |
| `--description` | Human-readable description |
| `--skills` | Comma-separated skill names to load for the agent run |
| `--deliver` | Delivery target: `log` (default), `telegram`, `discord`, `slack`, `github_comment` |
| `--deliver-chat-id` | Target chat/channel ID for cross-platform delivery |
| `--secret` | Custom HMAC secret (auto-generated if omitted) |

Subscriptions persist to `~/.spark/webhook_subscriptions.json` and are hot-reloaded without a gateway restart.

---

## `spark doctor`

```bash
spark doctor [--fix]
```

Diagnoses config and dependency issues. Add `--fix` to attempt automatic repairs.

---

## `spark dump`

```bash
spark dump [--show-keys]
```

Generates a compact plain-text summary of your Spark setup — no ANSI colors, no special formatting. Paste it into GitHub issues, Discord, or Telegram when you need help.

| Option | What it does |
|--------|-------------|
| `--show-keys` | Show redacted API key prefixes (first and last 4 characters) instead of just `set`/`not set` |

**What's included:**

| Section | Details |
|---------|---------|
| **Header** | Spark version, release date, git commit hash |
| **Environment** | OS, Python version, OpenAI SDK version |
| **Identity** | Active profile name, SPARK_HOME path |
| **Model** | Configured default model and provider |
| **Terminal** | Backend type (local, docker, ssh, etc.) |
| **API keys** | Presence check for all 22 provider/tool API keys |
| **Features** | Enabled toolsets, MCP server count, memory provider |
| **Services** | Gateway status, configured messaging platforms |
| **Workload** | Cron job counts, installed skill count |
| **Config overrides** | Any config values that differ from defaults |

**Example output:**

```
--- spark dump ---
version:          0.8.0 (2026.4.8) [af4abd2f]
os:               Linux 6.14.0-37-generic x86_64
python:           3.11.14
openai_sdk:       2.24.0
profile:          default
spark_home:      ~/.spark
model:            anthropic/claude-opus-4.6
provider:         openrouter
terminal:         local

api_keys:
  openrouter           set
  openai               not set
  anthropic            set
  nous                 not set
  firecrawl            set
  ...

features:
  toolsets:           all
  mcp_servers:        0
  memory_provider:    built-in
  gateway:            running (systemd)
  platforms:          telegram, discord
  cron_jobs:          3 active / 5 total
  skills:             42

config_overrides:
  agent.max_turns: 250
  compression.threshold: 0.85
  display.streaming: True
--- end dump ---
```

:::tip
Use `spark dump` for sharing. Use `spark doctor` for interactive diagnostics. Use `spark status` for a visual overview.
:::

---

## `spark debug`

```bash
spark debug share [options]
```

Uploads a debug report (system info + recent logs) to a paste service and prints a shareable URL. Keys are always redacted — nothing sensitive is uploaded.

| Option | What it does |
|--------|-------------|
| `--lines <N>` | Log lines to include per file (default: 200) |
| `--expire <days>` | Paste expiry in days (default: 7) |
| `--local` | Print the report locally instead of uploading |

Paste services tried in order: paste.rs, dpaste.com.

```bash
spark debug share              # Upload and print URL
spark debug share --lines 500  # Include more log lines
spark debug share --expire 30  # Keep for 30 days
spark debug share --local      # Print to terminal only
```

---

## `spark backup`

```bash
spark backup [options]
```

Creates a zip archive of your Spark config, skills, sessions, and data. Excludes the Spark codebase itself. Uses SQLite's `backup()` API, so it's safe to run while Spark is active.

| Option | What it does |
|--------|-------------|
| `-o`, `--output <path>` | Output path (default: `~/spark-backup-<timestamp>.zip`) |
| `-q`, `--quick` | Snapshot only critical state files: config.yaml, state.db, .env, auth, cron jobs |
| `-l`, `--label <name>` | Label the snapshot (only used with `--quick`) |

```bash
spark backup                                # Full backup
spark backup -o /tmp/spark.zip             # Full backup to a specific path
spark backup --quick                        # Quick state-only snapshot
spark backup --quick --label "pre-upgrade" # Quick snapshot with a label
```

---

## `spark import`

```bash
spark import <zipfile> [options]
```

Restore a Spark backup into your home directory.

| Option | What it does |
|--------|-------------|
| `-f`, `--force` | Overwrite existing files without confirmation |

---

## `spark logs`

```bash
spark logs [log_name] [options]
```

View, tail, and filter Spark log files from `~/.spark/logs/` (or `<profile>/logs/` for non-default profiles).

**Available logs:**

| Name | File | What's captured |
|------|------|-----------------|
| `agent` (default) | `agent.log` | All agent activity — API calls, tool dispatch, session lifecycle |
| `errors` | `errors.log` | Warnings and errors only |
| `gateway` | `gateway.log` | Messaging gateway — platform connections, dispatch, webhook events |

**Options:**

| Option | What it does |
|--------|-------------|
| `log_name` | `agent` (default), `errors`, `gateway`, or `list` to show all files with sizes |
| `-n`, `--lines <N>` | Lines to show (default: 50) |
| `-f`, `--follow` | Follow in real time like `tail -f` |
| `--level <LEVEL>` | Minimum level: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `--session <ID>` | Filter lines containing a session ID substring |
| `--since <TIME>` | Show lines from a relative time ago: `30m`, `1h`, `2d`, etc. |
| `--component <NAME>` | Filter by component: `gateway`, `agent`, `tools`, `cli`, `cron` |

**Examples:**

```bash
spark logs                                      # Last 50 lines of agent.log
spark logs -f                                   # Follow agent.log in real time
spark logs gateway -n 100                       # Last 100 lines of gateway.log
spark logs --level WARNING --since 1h           # Warnings and errors from the last hour
spark logs --session abc123                     # Filter by session ID
spark logs errors --since 30m -f               # Follow errors.log from 30 min ago
spark logs list                                 # List all log files with sizes
```

Combine filters — a line must pass all active filters to appear:

```bash
spark logs --level WARNING --since 2h --session tg-12345
```

Spark uses Python's `RotatingFileHandler`. Rotated logs appear as `agent.log.1`, `agent.log.2`, etc., and are included in `spark logs list`.

---

## `spark config`

```bash
spark config <subcommand>
```

| Subcommand | What it does |
|------------|-------------|
| `show` | Print current config values |
| `edit` | Open `config.yaml` in your editor |
| `set <key> <value>` | Set a config value |
| `path` | Print the config file path |
| `env-path` | Print the `.env` file path |
| `check` | Check for missing or stale config |
| `migrate` | Add newly introduced options interactively |

---

## `spark pairing`

```bash
spark pairing <list|approve|revoke|clear-pending>
```

| Subcommand | What it does |
|------------|-------------|
| `list` | Show pending and approved users |
| `approve <platform> <code>` | Approve a pairing code |
| `revoke <platform> <user-id>` | Revoke a user's access |
| `clear-pending` | Clear all pending pairing codes |

---

## `spark skills`

```bash
spark skills <subcommand>
```

| Subcommand | What it does |
|------------|-------------|
| `browse` | Paginated browser for skill registries |
| `search` | Search skill registries |
| `install` | Install a skill |
| `inspect` | Preview a skill without installing |
| `list` | List installed skills |
| `check` | Check hub skills for upstream updates |
| `update` | Reinstall hub skills that have upstream changes |
| `audit` | Re-scan installed hub skills |
| `uninstall` | Remove a hub-installed skill |
| `publish` | Publish a skill to a registry |
| `snapshot` | Export/import skill configurations |
| `tap` | Manage custom skill sources |
| `config` | Enable/disable skills by platform |

```bash
spark skills browse
spark skills browse --source official
spark skills search react --source skills-sh
spark skills search https://mintlify.com/docs --source well-known
spark skills inspect official/security/1password
spark skills inspect skills-sh/vercel-labs/json-render/json-render-react
spark skills install official/migration/openclaw-migration
spark skills install skills-sh/anthropics/skills/pdf --force
spark skills check
spark skills update
spark skills config
```

Notes:
- `--force` overrides non-dangerous policy blocks for third-party/community skills.
- `--force` does not override a `dangerous` scan verdict.
- `--source skills-sh` searches the public `skills.sh` directory.
- `--source well-known` points Spark at a site exposing `/.well-known/skills/index.json`.

---

## `spark honcho`

```bash
spark honcho [--target-profile NAME] <subcommand>
```

Manage Honcho cross-session memory. Only available when `memory.provider` is set to `honcho` in your config. Use `--target-profile` to manage another profile's config without switching to it.

| Subcommand | What it does |
|------------|-------------|
| `setup` | Redirects to `spark memory setup` |
| `status [--all]` | Current Honcho config and connection status. `--all` shows a cross-profile overview |
| `peers` | Show peer identities across profiles |
| `sessions` | List known Honcho session mappings |
| `map [name]` | Map the current directory to a Honcho session name |
| `peer` | Show or update peer names and reasoning level. Options: `--user NAME`, `--ai NAME`, `--reasoning LEVEL` |
| `mode [mode]` | Show or set recall mode: `hybrid`, `context`, or `tools` |
| `tokens` | Show or set token budgets. Options: `--context N`, `--dialectic N` |
| `identity [file] [--show]` | Seed or show the AI peer identity representation |
| `enable` | Enable Honcho for the active profile |
| `disable` | Disable Honcho for the active profile |
| `sync` | Sync Honcho config to all existing profiles |
| `migrate` | Step-by-step guide from openclaw-honcho to Spark Honcho |

---

## `spark memory`

```bash
spark memory <subcommand>
```

Set up external memory provider plugins. Available providers: honcho, openviking, mem0, hindsight, holographic, retaindb, byterover, supermemory. Only one external provider can be active at a time. Built-in memory (MEMORY.md/USER.md) is always active.

| Subcommand | What it does |
|------------|-------------|
| `setup` | Interactive provider selection and configuration |
| `status` | Show current memory provider config |
| `off` | Disable external provider (built-in only) |

---

## `spark acp`

```bash
spark acp
```

Starts Spark as an ACP (Agent Client Protocol) stdio server for editor integration. Related entrypoints:

```bash
spark-acp
python -m acp_adapter
```

Install ACP support first:

```bash
pip install -e '.[acp]'
```

See [ACP Editor Integration](../integrations/acp.md) and [ACP Internals](../building/editor-extension-internals.md).

---

## `spark mcp`

```bash
spark mcp <subcommand>
```

| Subcommand | What it does |
|------------|-------------|
| `serve [-v\|--verbose]` | Run Spark as an MCP server — expose conversations to other agents |
| `add <name> [--url URL] [--command CMD] [--args ...] [--auth oauth\|header]` | Add an MCP server with automatic tool discovery |
| `remove <name>` (alias: `rm`) | Remove an MCP server from config |
| `list` (alias: `ls`) | List configured MCP servers |
| `test <name>` | Test connection to an MCP server |
| `configure <name>` (alias: `config`) | Toggle tool selection for a server |

See [MCP Config Reference](../reference/mcp-config-reference.md), [Use MCP with Spark](../guides/use-mcp.md), and [MCP Server Mode](../tools/mcp.md#running-spark-as-an-mcp-server).

---

## `spark plugins`

```bash
spark plugins [subcommand]
```

Running `spark plugins` with no subcommand opens a composite interactive screen:

- **General Plugins** — multi-select checkboxes to enable/disable installed plugins
- **Provider Plugins** — single-select configuration for Memory Provider and Context Engine

| Subcommand | What it does |
|------------|-------------|
| *(none)* | Interactive UI with plugin toggles and provider configuration |
| `install <identifier> [--force]` | Install a plugin from a Git URL or `owner/repo` |
| `update <name>` | Pull latest changes for an installed plugin |
| `remove <name>` (aliases: `rm`, `uninstall`) | Remove a plugin |
| `enable <name>` | Enable a disabled plugin |
| `disable <name>` | Disable without removing |
| `list` (alias: `ls`) | List installed plugins with enabled/disabled status |

Config keys saved by plugin selections:
- `memory.provider` — active memory provider (empty = built-in only)
- `context.engine` — active context engine (`"compressor"` = built-in default)
- `plugins.disabled` — list of disabled general plugins

See [Plugins](../automate/plugins.md) and [Build a Spark Plugin](../guides/build-a-plugin.md).

---

## `spark tools`

```bash
spark tools [--summary]
```

Without `--summary`, opens the interactive per-platform tool configuration UI.

| Option | What it does |
|--------|-------------|
| `--summary` | Print current enabled-tools summary and exit |

---

## `spark sessions`

```bash
spark sessions <subcommand>
```

| Subcommand | What it does |
|------------|-------------|
| `list` | List recent sessions |
| `browse` | Interactive session picker with search and resume |
| `export <output> [--session-id ID]` | Export sessions to JSONL |
| `delete <session-id>` | Delete one session |
| `prune` | Delete old sessions |
| `stats` | Show session-store statistics |
| `rename <session-id> <title>` | Set or change a session title |

---

## `spark insights`

```bash
spark insights [--days N] [--source platform]
```

| Option | What it does |
|--------|-------------|
| `--days <n>` | Analyze the last `n` days (default: 30) |
| `--source <platform>` | Filter by source: `cli`, `telegram`, `discord`, etc. |

---

## `spark claw`

```bash
spark claw migrate [options]
```

Migrate from OpenClaw to Spark. Reads from `~/.openclaw` (or a custom path) and writes to `~/.spark`. Automatically recognizes legacy directory names (`~/.clawdbot`, `~/.moltbot`) and config filenames (`clawdbot.json`, `moltbot.json`).

| Option | What it does |
|--------|-------------|
| `--dry-run` | Preview the migration without writing anything |
| `--preset <name>` | `full` (default, includes secrets) or `user-data` (excludes API keys) |
| `--overwrite` | Overwrite existing Spark files on conflict (default: skip) |
| `--migrate-secrets` | Include API keys (enabled by default with `--preset full`) |
| `--source <path>` | Custom OpenClaw directory (default: `~/.openclaw`) |
| `--workspace-target <path>` | Target directory for workspace instructions (AGENTS.md) |
| `--skill-conflict <mode>` | Handle skill name collisions: `skip` (default), `overwrite`, or `rename` |
| `--yes` | Skip the confirmation prompt |

**What gets migrated:**

Directly imported: SOUL.md, MEMORY.md, USER.md, AGENTS.md, skills, default model, custom providers, MCP servers, messaging platform tokens and allowlists (Telegram, Discord, Slack, WhatsApp, Signal, Matrix, Mattermost), agent defaults, session reset policies, approval rules, TTS config, browser settings, tool settings, exec timeout, command allowlist, gateway config, and API keys.

Archived for manual review: cron jobs, plugins, hooks/webhooks, memory backend (QMD), skills registry config, UI/identity, logging, multi-agent setup, channel bindings, IDENTITY.md, TOOLS.md, HEARTBEAT.md, BOOTSTRAP.md.

```bash
spark claw migrate --dry-run                             # Preview only
spark claw migrate --preset full                        # Full migration with secrets
spark claw migrate --preset user-data --overwrite       # Data only, overwrite conflicts
spark claw migrate --source /home/user/old-openclaw     # Custom source path
```

See the [full migration guide](../guides/migrate-from-openclaw.md) for the complete config key mapping and post-migration checklist.

---

## `spark dashboard`

```bash
spark dashboard [options]
```

Launches a browser-based UI for config, API keys, and session monitoring. Requires `pip install spark-agent[web]` (FastAPI + Uvicorn).

| Option | Default | What it does |
|--------|---------|-------------|
| `--port` | `9119` | Port to run on |
| `--host` | `127.0.0.1` | Bind address |
| `--no-open` | - | Don't auto-open the browser |

```bash
spark dashboard                         # Opens http://127.0.0.1:9119
spark dashboard --port 8080 --no-open  # Custom port, no browser
```

See [Web Dashboard](/docs/integrations/web-dashboard) for full documentation.

---

## `spark profile`

```bash
spark profile <subcommand>
```

Run multiple isolated Spark instances on the same machine — each with its own config, sessions, skills, and home directory.

| Subcommand | What it does |
|------------|-------------|
| `list` | List all profiles |
| `use <name>` | Set a sticky default profile |
| `create <name> [--clone] [--clone-all] [--clone-from <source>] [--no-alias]` | Create a new profile |
| `delete <name> [-y]` | Delete a profile |
| `show <name>` | Show profile details |
| `alias <name> [--remove] [--name NAME]` | Manage wrapper scripts for quick access |
| `rename <old> <new>` | Rename a profile |
| `export <name> [-o FILE]` | Export a profile to `.tar.gz` |
| `import <archive> [--name NAME]` | Import from a `.tar.gz` archive |

```bash
spark profile list
spark profile create work --clone
spark profile use work
spark profile alias work --name h-work
spark profile export work -o work-backup.tar.gz
spark profile import work-backup.tar.gz --name restored
spark -p work chat -q "Hello from work profile"
```

---

## `spark completion`

```bash
spark completion [bash|zsh]
```

Prints a shell completion script. Source it in your profile for tab-completion of commands, subcommands, and profile names.

```bash
spark completion bash >> ~/.bashrc
spark completion zsh >> ~/.zshrc
```

---

## Maintenance

| Command | What it does |
|---------|-------------|
| `spark version` | Print version info |
| `spark update` | Pull latest changes and reinstall dependencies |
| `spark uninstall [--full] [--yes]` | Remove Spark, optionally deleting all config and data |

---

## See also

- [Slash Commands Reference](./slash-commands.md)
- [CLI Interface](./index.md)
- [Sessions](../sessions.md)
- [Skills System](../skills/index.md)
- [Skins & Themes](./skins.md)
