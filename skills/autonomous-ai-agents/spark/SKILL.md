---
name: spark-agent
description: Complete guide to using and extending Spark Agent — CLI usage, setup, configuration, spawning additional agents, gateway platforms, skills, voice, tools, profiles, and a concise contributor reference. Load this skill when helping users configure Spark, troubleshoot issues, spawn agent instances, or make code contributions.
version: 2.0.0
author: Spark Agent + Teknium
license: MIT
metadata:
  spark:
    tags: [spark, setup, configuration, multi-agent, spawning, cli, gateway, development]
    homepage: https://github.com/automatedigital/spark
    related_skills: [claude-code, codex, opencode]
---

# Spark Agent

Spark Agent is an open-source AI agent framework by Automate Digital that runs in your terminal, messaging platforms, and IDEs. It belongs to the same category as Claude Code (Anthropic), Codex (OpenAI), and OpenClaw — autonomous coding and task-execution agents that use tool calling to interact with your system. Spark works with any LLM provider (OpenRouter, Anthropic, OpenAI, DeepSeek, local models, and 15+ others) and runs on Linux, macOS, and WSL.

What makes Spark different:

- **Self-improving through skills** — Spark learns from experience by saving reusable procedures as skills. When it solves a complex problem, discovers a workflow, or gets corrected, it can persist that knowledge as a skill document that loads into future sessions. Skills accumulate over time, making the agent better at your specific tasks and environment.
- **Persistent memory across sessions** — remembers who you are, your preferences, environment details, and lessons learned. Pluggable memory backends (built-in, Honcho, Mem0, and more) let you choose how memory works.
- **Multi-platform gateway** — the same agent runs on Telegram, Discord, Slack, WhatsApp, Signal, Matrix, Email, and 10+ other platforms with full tool access, not just chat.
- **Provider-agnostic** — swap models and providers mid-workflow without changing anything else. Credential pools rotate across multiple API keys automatically.
- **Profiles** — run multiple independent Spark instances with isolated configs, sessions, skills, and memory.
- **Extensible** — plugins, MCP servers, custom tools, webhook triggers, cron scheduling, and the full Python ecosystem.

People use Spark for software development, research, system administration, data analysis, content creation, home automation, and anything else that benefits from an AI agent with persistent context and full system access.

**This skill helps you work with Spark Agent effectively** — setting it up, configuring features, spawning additional agent instances, troubleshooting issues, finding the right commands and settings, and understanding how the system works when you need to extend or contribute to it.

**Docs:** https://spark.automatedigital.ai/docs/

## Quick Start

```bash
# Install
curl -fsSL https://raw.githubusercontent.com/automatedigital/spark/main/scripts/install.sh | bash

# Interactive chat (default)
spark

# Single query
spark chat -q "What is the capital of France?"

# Setup wizard
spark setup

# Change model/provider
spark model

# Check health
spark doctor
```

---

## CLI Reference

### Global Flags

```
spark [flags] [command]

  --version, -V             Show version
  --resume, -r SESSION      Resume session by ID or title
  --continue, -c [NAME]     Resume by name, or most recent session
  --worktree, -w            Isolated git worktree mode (parallel agents)
  --skills, -s SKILL        Preload skills (comma-separate or repeat)
  --profile, -p NAME        Use a named profile
  --yolo                    Skip dangerous command approval
  --pass-session-id         Include session ID in system prompt
```

No subcommand defaults to `chat`.

### Chat

```
spark chat [flags]
  -q, --query TEXT          Single query, non-interactive
  -m, --model MODEL         Model (e.g. anthropic/claude-sonnet-4)
  -t, --toolsets LIST       Comma-separated toolsets
  --provider PROVIDER       Force provider (openrouter, anthropic, nous, etc.)
  -v, --verbose             Verbose output
  -Q, --quiet               Suppress banner, spinner, tool previews
  --checkpoints             Enable filesystem checkpoints (/rollback)
  --source TAG              Session source tag (default: cli)
```

### Configuration

```
spark setup [section]      Interactive wizard (model|terminal|gateway|tools|agent)
spark model                Interactive model/provider picker
spark config               View current config
spark config edit          Open config.yaml in $EDITOR
spark config set KEY VAL   Set a config value
spark config path          Print config.yaml path
spark config env-path      Print .env path
spark config check         Check for missing/outdated config
spark config migrate       Update config with new options
spark login [--provider P] OAuth login (nous, openai-codex)
spark logout               Clear stored auth
spark doctor [--fix]       Check dependencies and config
spark status [--all]       Show component status
```

### Tools & Skills

```
spark tools                Interactive tool enable/disable (curses UI)
spark tools list           Show all tools and status
spark tools enable NAME    Enable a toolset
spark tools disable NAME   Disable a toolset

spark skills list          List installed skills
spark skills search QUERY  Search the skills hub
spark skills install ID    Install a skill
spark skills inspect ID    Preview without installing
spark skills config        Enable/disable skills per platform
spark skills check         Check for updates
spark skills update        Update outdated skills
spark skills uninstall N   Remove a hub skill
spark skills publish PATH  Publish to registry
spark skills browse        Browse all available skills
spark skills tap add REPO  Add a GitHub repo as skill source
```

### MCP Servers

```
spark mcp serve            Run Spark as an MCP server
spark mcp add NAME         Add an MCP server (--url or --command)
spark mcp remove NAME      Remove an MCP server
spark mcp list             List configured servers
spark mcp test NAME        Test connection
spark mcp configure NAME   Toggle tool selection
```

### Gateway (Messaging Platforms)

```
spark gateway run          Start gateway foreground
spark gateway install      Install as background service
spark gateway start/stop   Control the service
spark gateway restart      Restart the service
spark gateway status       Check status
spark gateway setup        Configure platforms
```

Supported platforms: Telegram, Discord, Slack, WhatsApp, Signal, Email, SMS, Matrix, Mattermost, Home Assistant, DingTalk, Feishu, WeCom, BlueBubbles (iMessage), Weixin (WeChat), API Server, Webhooks. Open WebUI connects via the API Server adapter.

Platform docs: https://spark.automatedigital.ai/docs/messaging/

### Sessions

```
spark sessions list        List recent sessions
spark sessions browse      Interactive picker
spark sessions export OUT  Export to JSONL
spark sessions rename ID T Rename a session
spark sessions delete ID   Delete a session
spark sessions prune       Clean up old sessions (--older-than N days)
spark sessions stats       Session store statistics
```

### Cron Jobs

```
spark cron list            List jobs (--all for disabled)
spark cron create SCHED    Create: '30m', 'every 2h', '0 9 * * *'
spark cron edit ID         Edit schedule, prompt, delivery
spark cron pause/resume ID Control job state
spark cron run ID          Trigger on next tick
spark cron remove ID       Delete a job
spark cron status          Scheduler status
```

### Webhooks

```
spark webhook subscribe N  Create route at /webhooks/<name>
spark webhook list         List subscriptions
spark webhook remove NAME  Remove a subscription
spark webhook test NAME    Send a test POST
```

### Profiles

```
spark profile list         List all profiles
spark profile create NAME  Create (--clone, --clone-all, --clone-from)
spark profile use NAME     Set sticky default
spark profile delete NAME  Delete a profile
spark profile show NAME    Show details
spark profile alias NAME   Manage wrapper scripts
spark profile rename A B   Rename a profile
spark profile export NAME  Export to tar.gz
spark profile import FILE  Import from archive
```

### Credential Pools

```
spark auth add             Interactive credential wizard
spark auth list [PROVIDER] List pooled credentials
spark auth remove P INDEX  Remove by provider + index
spark auth reset PROVIDER  Clear exhaustion status
```

### Other

```
spark insights [--days N]  Usage analytics
spark update               Update to latest version
spark pairing list/approve/revoke  DM authorization
spark plugins list/install/remove  Plugin management
spark honcho setup/status  Honcho memory integration (requires honcho plugin)
spark memory setup/status/off  Memory provider config
spark completion bash|zsh  Shell completions
spark acp                  ACP server (IDE integration)
spark claw migrate         Migrate from OpenClaw
spark uninstall            Uninstall Spark
```

---

## Slash Commands (In-Session)

Type these during an interactive chat session.

### Session Control
```
/new (/reset)        Fresh session
/clear               Clear screen + new session (CLI)
/retry               Resend last message
/undo                Remove last exchange
/title [name]        Name the session
/compress            Manually compress context
/stop                Kill background processes
/rollback [N]        Restore filesystem checkpoint
/background <prompt> Run prompt in background
/queue <prompt>      Queue for next turn
/resume [name]       Resume a named session
```

### Configuration
```
/config              Show config (CLI)
/model [name]        Show or change model
/provider            Show provider info
/personality [name]  Set personality
/reasoning [level]   Set reasoning (none|minimal|low|medium|high|xhigh|show|hide)
/verbose             Cycle: off → new → all → verbose
/voice [on|off|tts]  Voice mode
/yolo                Toggle approval bypass
/skin [name]         Change theme (CLI)
/statusbar           Toggle status bar (CLI)
```

### Tools & Skills
```
/tools               Manage tools (CLI)
/toolsets            List toolsets (CLI)
/skills              Search/install skills (CLI)
/skill <name>        Load a skill into session
/cron                Manage cron jobs (CLI)
/reload-mcp          Reload MCP servers
/plugins             List plugins (CLI)
```

### Gateway
```
/approve             Approve a pending command (gateway)
/deny                Deny a pending command (gateway)
/restart             Restart gateway (gateway)
/sethome             Set current chat as home channel (gateway)
/update              Update Spark to latest (gateway)
/platforms (/gateway) Show platform connection status (gateway)
```

### Utility
```
/branch (/fork)      Branch the current session
/btw                 Ephemeral side question (doesn't interrupt main task)
/fast                Toggle priority/fast processing
/browser             Open CDP browser connection
/history             Show conversation history (CLI)
/save                Save conversation to file (CLI)
/paste               Attach clipboard image (CLI)
/image               Attach local image file (CLI)
```

### Info
```
/help                Show commands
/commands [page]     Browse all commands (gateway)
/usage               Token usage
/insights [days]     Usage analytics
/status              Session info (gateway)
/profile             Active profile info
```

### Exit
```
/quit (/exit, /q)    Exit CLI
```

---

## Key Paths & Config

```
~/.spark/config.yaml       Main configuration
~/.spark/.env              API keys and secrets
~/.spark/skills/           Installed skills
~/.spark/sessions/         Session transcripts
~/.spark/logs/             Gateway and error logs
~/.spark/auth.json         OAuth tokens and credential pools
~/.spark/spark-agent/     Source code (if git-installed)
```

Profiles use `~/.spark/profiles/<name>/` with the same layout.

### Config Sections

Edit with `spark config edit` or `spark config set section.key value`.

| Section | Key options |
|---------|-------------|
| `model` | `default`, `provider`, `base_url`, `api_key`, `context_length` |
| `agent` | `max_turns` (90), `tool_use_enforcement` |
| `terminal` | `backend` (local/docker/ssh/modal), `cwd`, `timeout` (180) |
| `compression` | `enabled`, `threshold` (0.50), `target_ratio` (0.20) |
| `display` | `skin`, `tool_progress`, `show_reasoning`, `show_cost` |
| `stt` | `enabled`, `provider` (local/groq/openai/mistral) |
| `tts` | `provider` (edge/elevenlabs/openai/minimax/mistral/neutts) |
| `memory` | `memory_enabled`, `user_profile_enabled`, `provider` |
| `security` | `tirith_enabled`, `website_blocklist` |
| `delegation` | `model`, `provider`, `base_url`, `api_key`, `max_iterations` (50), `reasoning_effort` |
| `smart_model_routing` | `enabled`, `cheap_model` |
| `checkpoints` | `enabled`, `max_snapshots` (50) |

Full config reference: https://spark.automatedigital.ai/docs/configuration

### Providers

20+ providers supported. Set via `spark model` or `spark setup`.

| Provider | Auth | Key env var |
|----------|------|-------------|
| OpenRouter | API key | `OPENROUTER_API_KEY` |
| Anthropic | API key | `ANTHROPIC_API_KEY` |
| Spark Portal | OAuth | `spark login --provider nous` |
| OpenAI Codex | OAuth | `spark login --provider openai-codex` |
| GitHub Copilot | Token | `COPILOT_GITHUB_TOKEN` |
| Google Gemini | API key | `GOOGLE_API_KEY` or `GEMINI_API_KEY` |
| DeepSeek | API key | `DEEPSEEK_API_KEY` |
| xAI / Grok | API key | `XAI_API_KEY` |
| Hugging Face | Token | `HF_TOKEN` |
| Z.AI / GLM | API key | `GLM_API_KEY` |
| MiniMax | API key | `MINIMAX_API_KEY` |
| MiniMax CN | API key | `MINIMAX_CN_API_KEY` |
| Kimi / Moonshot | API key | `KIMI_API_KEY` |
| Alibaba / DashScope | API key | `DASHSCOPE_API_KEY` |
| Xiaomi MiMo | API key | `XIAOMI_API_KEY` |
| Kilo Code | API key | `KILOCODE_API_KEY` |
| AI Gateway (Vercel) | API key | `AI_GATEWAY_API_KEY` |
| OpenCode Zen | API key | `OPENCODE_ZEN_API_KEY` |
| OpenCode Go | API key | `OPENCODE_GO_API_KEY` |
| Qwen OAuth | OAuth | `spark login --provider qwen-oauth` |
| Custom endpoint | Config | `model.base_url` + `model.api_key` in config.yaml |
| GitHub Copilot ACP | External | `COPILOT_CLI_PATH` or Copilot CLI |

Full provider docs: https://spark.automatedigital.ai/docs/integrations/providers

### Toolsets

Enable/disable via `spark tools` (interactive) or `spark tools enable/disable NAME`.

| Toolset | What it provides |
|---------|-----------------|
| `web` | Web search and content extraction |
| `browser` | Browser automation (Browserbase, Camofox, or local Chromium) |
| `terminal` | Shell commands and process management |
| `file` | File read/write/search/patch |
| `code_execution` | Sandboxed Python execution |
| `vision` | Image analysis |
| `image_gen` | AI image generation |
| `tts` | Text-to-speech |
| `skills` | Skill browsing and management |
| `memory` | Persistent cross-session memory |
| `session_search` | Search past conversations |
| `delegation` | Subagent task delegation |
| `cronjob` | Scheduled task management |
| `clarify` | Ask user clarifying questions |
| `messaging` | Cross-platform message sending |
| `search` | Web search only (subset of `web`) |
| `todo` | In-session task planning and tracking |
| `rl` | Reinforcement learning tools (off by default) |
| `moa` | Mixture of Agents (off by default) |
| `homeassistant` | Smart home control (off by default) |

Tool changes take effect on `/reset` (new session). They do NOT apply mid-conversation to preserve prompt caching.

---

## Voice & Transcription

### STT (Voice → Text)

Voice messages from messaging platforms are auto-transcribed.

Provider priority (auto-detected):
1. **Local faster-whisper** — free, no API key: `pip install faster-whisper`
2. **Groq Whisper** — free tier: set `GROQ_API_KEY`
3. **OpenAI Whisper** — paid: set `VOICE_TOOLS_OPENAI_KEY`
4. **Mistral Voxtral** — set `MISTRAL_API_KEY`

Config:
```yaml
stt:
  enabled: true
  provider: local        # local, groq, openai, mistral
  local:
    model: base          # tiny, base, small, medium, large-v3
```

### TTS (Text → Voice)

| Provider | Env var | Free? |
|----------|---------|-------|
| Edge TTS | None | Yes (default) |
| ElevenLabs | `ELEVENLABS_API_KEY` | Free tier |
| OpenAI | `VOICE_TOOLS_OPENAI_KEY` | Paid |
| MiniMax | `MINIMAX_API_KEY` | Paid |
| Mistral (Voxtral) | `MISTRAL_API_KEY` | Paid |
| NeuTTS (local) | None (`pip install neutts[all]` + `espeak-ng`) | Free |

Voice commands: `/voice on` (voice-to-voice), `/voice tts` (always voice), `/voice off`.

---

## Spawning Additional Spark Instances

Run additional Spark processes as fully independent subprocesses — separate sessions, tools, and environments.

### When to Use This vs delegate_task

| | `delegate_task` | Spawning `spark` process |
|-|-----------------|--------------------------|
| Isolation | Separate conversation, shared process | Fully independent process |
| Duration | Minutes (bounded by parent loop) | Hours/days |
| Tool access | Subset of parent's tools | Full tool access |
| Interactive | No | Yes (PTY mode) |
| Use case | Quick parallel subtasks | Long autonomous missions |

### One-Shot Mode

```
terminal(command="spark chat -q 'Research GRPO papers and write summary to ~/research/grpo.md'", timeout=300)

# Background for long tasks:
terminal(command="spark chat -q 'Set up CI/CD for ~/myapp'", background=true)
```

### Interactive PTY Mode (via tmux)

Spark uses prompt_toolkit, which requires a real terminal. Use tmux for interactive spawning:

```
# Start
terminal(command="tmux new-session -d -s agent1 -x 120 -y 40 'spark'", timeout=10)

# Wait for startup, then send a message
terminal(command="sleep 8 && tmux send-keys -t agent1 'Build a FastAPI auth service' Enter", timeout=15)

# Read output
terminal(command="sleep 20 && tmux capture-pane -t agent1 -p", timeout=5)

# Send follow-up
terminal(command="tmux send-keys -t agent1 'Add rate limiting middleware' Enter", timeout=5)

# Exit
terminal(command="tmux send-keys -t agent1 '/exit' Enter && sleep 2 && tmux kill-session -t agent1", timeout=10)
```

### Multi-Agent Coordination

```
# Agent A: backend
terminal(command="tmux new-session -d -s backend -x 120 -y 40 'spark -w'", timeout=10)
terminal(command="sleep 8 && tmux send-keys -t backend 'Build REST API for user management' Enter", timeout=15)

# Agent B: frontend
terminal(command="tmux new-session -d -s frontend -x 120 -y 40 'spark -w'", timeout=10)
terminal(command="sleep 8 && tmux send-keys -t frontend 'Build React dashboard for user management' Enter", timeout=15)

# Check progress, relay context between them
terminal(command="tmux capture-pane -t backend -p | tail -30", timeout=5)
terminal(command="tmux send-keys -t frontend 'Here is the API schema from the backend agent: ...' Enter", timeout=5)
```

### Session Resume

```
# Resume most recent session
terminal(command="tmux new-session -d -s resumed 'spark --continue'", timeout=10)

# Resume specific session
terminal(command="tmux new-session -d -s resumed 'spark --resume 20260225_143052_a1b2c3'", timeout=10)
```

### Tips

- **Prefer `delegate_task` for quick subtasks** — less overhead than spawning a full process
- **Use `-w` (worktree mode)** when spawning agents that edit code — prevents git conflicts
- **Set timeouts** for one-shot mode — complex tasks can take 5-10 minutes
- **Use `spark chat -q` for fire-and-forget** — no PTY needed
- **Use tmux for interactive sessions** — raw PTY mode has `\r` vs `\n` issues with prompt_toolkit
- **For scheduled tasks**, use the `cronjob` tool instead of spawning — handles delivery and retry

---

## Troubleshooting

### Voice not working
1. Check `stt.enabled: true` in config.yaml
2. Verify provider: `pip install faster-whisper` or set API key
3. In gateway: `/restart`. In CLI: exit and relaunch.

### Tool not available
1. `spark tools` — check if toolset is enabled for your platform
2. Some tools need env vars (check `.env`)
3. `/reset` after enabling tools

### Model/provider issues
1. `spark doctor` — check config and dependencies
2. `spark login` — re-authenticate OAuth providers
3. Check `.env` has the right API key
4. **Copilot 403**: `gh auth login` tokens do NOT work for Copilot API. You must use the Copilot-specific OAuth device code flow via `spark model` → GitHub Copilot.

### Changes not taking effect
- **Tools/skills:** `/reset` starts a new session with updated toolset
- **Config changes:** In gateway: `/restart`. In CLI: exit and relaunch.
- **Code changes:** Restart the CLI or gateway process

### Skills not showing
1. `spark skills list` — verify installed
2. `spark skills config` — check platform enablement
3. Load explicitly: `/skill name` or `spark -s name`

### Gateway issues
Check logs first:
```bash
grep -i "failed to send\|error" ~/.spark/logs/gateway.log | tail -20
```

Common gateway problems:
- **Gateway dies on SSH logout**: Enable linger: `sudo loginctl enable-linger $USER`
- **Gateway dies on WSL2 close**: WSL2 requires `systemd=true` in `/etc/wsl.conf` for systemd services to work. Without it, gateway falls back to `nohup` (dies when session closes).
- **Gateway crash loop**: Reset the failed state: `systemctl --user reset-failed spark-gateway`

### Platform-specific issues
- **Discord bot silent**: Must enable **Message Content Intent** in Bot → Privileged Gateway Intents.
- **Slack bot only works in DMs**: Must subscribe to `message.channels` event. Without it, the bot ignores public channels.
- **Windows HTTP 400 "No models provided"**: Config file encoding issue (BOM). Ensure `config.yaml` is saved as UTF-8 without BOM.

### Auxiliary models not working
If `auxiliary` tasks (vision, compression, session_search) fail silently, the `auto` provider can't find a backend. Either set `OPENROUTER_API_KEY` or `GOOGLE_API_KEY`, or explicitly configure each auxiliary task's provider:
```bash
spark config set auxiliary.vision.provider <your_provider>
spark config set auxiliary.vision.model <model_name>
```

---

## Where to Find Things

| Looking for... | Location |
|----------------|----------|
| Config options | `spark config edit` or [Configuration docs](https://spark.automatedigital.ai/docs/configuration) |
| Available tools | `spark tools list` or [Tools reference](https://spark.automatedigital.ai/docs/reference/tools-reference) |
| Slash commands | `/help` in session or [Slash commands reference](https://spark.automatedigital.ai/docs/cli/slash-commands) |
| Skills catalog | `spark skills browse` or [Skills catalog](https://spark.automatedigital.ai/docs/skills/catalog) |
| Provider setup | `spark model` or [Providers guide](https://spark.automatedigital.ai/docs/integrations/providers) |
| Platform setup | `spark gateway setup` or [Messaging docs](https://spark.automatedigital.ai/docs/messaging/) |
| MCP servers | `spark mcp list` or [MCP guide](https://spark.automatedigital.ai/docs/tools/mcp) |
| Profiles | `spark profile list` or [Profiles docs](https://spark.automatedigital.ai/docs/cli/profiles) |
| Cron jobs | `spark cron list` or [Cron docs](https://spark.automatedigital.ai/docs/automation/cron) |
| Memory | `spark memory status` or [Memory docs](https://spark.automatedigital.ai/docs/memory) |
| Env variables | `spark config env-path` or [Env vars reference](https://spark.automatedigital.ai/docs/reference/environment-variables) |
| CLI commands | `spark --help` or [CLI reference](https://spark.automatedigital.ai/docs/cli/commands-reference) |
| Gateway logs | `~/.spark/logs/gateway.log` |
| Session files | `~/.spark/sessions/` or `spark sessions browse` |
| Source code | `~/.spark/spark-agent/` |

---

## Contributor Quick Reference

For PR authors: full developer docs: https://spark.automatedigital.ai/docs/developer-guide/

### Project Layout

```
spark-agent/
├── run_agent.py          # AIAgent — core conversation loop
├── model_tools.py        # Tool discovery and dispatch
├── toolsets.py           # Toolset definitions
├── cli.py                # Interactive CLI (SparkCLI)
├── spark_state.py       # SQLite session store
├── agent/                # Prompt builder, context compression, memory, model routing, credential pooling, skill dispatch
├── spark_cli/           # CLI subcommands, config, setup, commands
│   ├── commands.py       # Slash command registry (CommandDef)
│   ├── config.py         # DEFAULT_CONFIG, env var definitions
│   └── main.py           # CLI entry point and argparse
├── tools/                # One file per tool
│   └── registry.py       # Central tool registry
├── gateway/              # Messaging gateway
│   └── platforms/        # Platform adapters (telegram, discord, etc.)
├── cron/                 # Job scheduler
├── tests/                # ~3000 pytest tests
└── docs/                 # Documentation (guides, reference, developer-guide)
```

Config: `~/.spark/config.yaml` (settings), `~/.spark/.env` (API keys).

### Adding a Tool (3 files)

**1. Create `tools/your_tool.py`:**
```python
import json, os
from tools.registry import registry

def check_requirements() -> bool:
    return bool(os.getenv("EXAMPLE_API_KEY"))

def example_tool(param: str, task_id: str = None) -> str:
    return json.dumps({"success": True, "data": "..."})

registry.register(
    name="example_tool",
    toolset="example",
    schema={"name": "example_tool", "description": "...", "parameters": {...}},
    handler=lambda args, **kw: example_tool(
        param=args.get("param", ""), task_id=kw.get("task_id")),
    check_fn=check_requirements,
    requires_env=["EXAMPLE_API_KEY"],
)
```

**2. Add import** in `model_tools.py` → `_discover_tools()` list.

**3. Add to `toolsets.py`** → `_SPARK_CORE_TOOLS` list.

All handlers must return JSON strings. Use `get_spark_home()` for paths, never hardcode `~/.spark`.

### Adding a Slash Command

1. Add `CommandDef` to `COMMAND_REGISTRY` in `spark_cli/commands.py`
2. Add handler in `cli.py` → `process_command()`
3. (Optional) Add gateway handler in `gateway/run.py`

All consumers (help text, autocomplete, Telegram menu, Slack mapping) derive from the central registry automatically.

### Agent Loop (High Level)

```
run_conversation():
  1. Build system prompt
  2. Loop while iterations < max:
     a. Call LLM (OpenAI-format messages + tool schemas)
     b. If tool_calls → dispatch each via handle_function_call() → append results → continue
     c. If text response → return
  3. Context compression triggers automatically near token limit
```

### Testing

```bash
python -m pytest tests/ -o 'addopts=' -q   # Full suite
python -m pytest tests/tools/ -q            # Specific area
```

- Tests auto-redirect `SPARK_HOME` to temp dirs — never touch real `~/.spark/`
- Run full suite before pushing any change
- Use `-o 'addopts='` to clear any baked-in pytest flags

### Commit Conventions

```
type: concise subject line

Optional body.
```

Types: `fix:`, `feat:`, `refactor:`, `docs:`, `chore:`

### Key Rules

- **Never break prompt caching** — don't change context, tools, or system prompt mid-conversation
- **Message role alternation** — never two assistant or two user messages in a row
- Use `get_spark_home()` from `spark_constants` for all paths (profile-safe)
- Config values go in `config.yaml`, secrets go in `.env`
- New tools need a `check_fn` so they only appear when requirements are met
