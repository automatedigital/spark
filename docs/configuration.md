---
sidebar_position: 2
title: "Configuration"
description: "Configure Spark Agent - config.yaml, providers, models, API keys, and more"
---

# Configuration

Everything Spark needs lives under `~/.spark/`. Here's the full layout at a glance:

```text
~/.spark/
 config.yaml     # Settings (model, terminal, TTS, compression, etc.)
 .env            # API keys and secrets
 auth.json       # OAuth provider credentials (Spark Portal, etc.)
 SOUL.md         # Primary agent identity (slot #1 in system prompt)
 memories/       # Persistent memory (MEMORY.md, USER.md)
 skills/         # Agent-created skills (managed via skill_manage tool)
 cron/           # Scheduled jobs
 sessions/       # Gateway sessions
 logs/           # Logs (errors.log, gateway.log - secrets auto-redacted)
```

## The Quick Rule

**Secrets go in `.env`. Everything else goes in `config.yaml`.**

When a value appears in both, `config.yaml` wins for non-secret settings.

Full precedence order (highest to lowest):

1. CLI arguments — `spark chat --model anthropic/claude-sonnet-4` (one-time override)
2. `~/.spark/config.yaml` — your primary config
3. `~/.spark/.env` — required for API keys, tokens, passwords
4. Built-in defaults

## Managing Config

```bash
spark config              # View current configuration
spark config edit         # Open config.yaml in your editor
spark config set KEY VAL  # Set a specific value
spark config check        # Check for missing options (after updates)
spark config migrate      # Interactively add missing options

# Examples
spark config set model anthropic/claude-opus-4
spark config set terminal.backend docker
spark config set OPENROUTER_API_KEY sk-or-...  # Routes to .env automatically
```

:::tip
`spark config set` automatically routes values to the correct file — API keys land in `.env`, everything else in `config.yaml`.
:::

## Environment Variable Substitution

Reference environment variables inside `config.yaml` using `${VAR_NAME}`:

```yaml
auxiliary:
  vision:
    api_key: ${GOOGLE_API_KEY}
    base_url: ${CUSTOM_VISION_URL}

delegation:
  api_key: ${DELEGATION_KEY}
```

Multiple references in one value work: `url: "${HOST}:${PORT}"`. Undefined variables stay verbatim (`${UNDEFINED_VAR}`). Only `${VAR}` syntax is supported — bare `$VAR` is not expanded.

For AI provider setup (OpenRouter, Anthropic, Copilot, custom endpoints, self-hosted LLMs, fallback models), see [AI Providers](integrations/providers.md).

---

## Terminal Backend

Pick where the agent's shell commands actually execute.

```yaml
terminal:
  backend: local    # local | docker | ssh | modal | daytona | singularity
  cwd: "."          # Working directory
  timeout: 180      # Per-command timeout in seconds
  env_passthrough: []  # Env var names to forward into sandboxed execution
  singularity_image: "docker://nikolaik/python-nodejs:python3.11-nodejs20"
  modal_image: "nikolaik/python-nodejs:python3.11-nodejs20"
  daytona_image: "nikolaik/python-nodejs:python3.11-nodejs20"
```

| Backend | Where commands run | Isolation | Best for |
|---------|-------------------|-----------|----------|
| **local** | Your machine directly | None | Development, personal use |
| **docker** | Docker container | Full (namespaces, cap-drop) | Safe sandboxing, CI/CD |
| **ssh** | Remote server via SSH | Network boundary | Remote dev, powerful hardware |
| **modal** | Modal cloud sandbox | Full (cloud VM) | Ephemeral cloud compute, evals |
| **daytona** | Daytona workspace | Full (cloud container) | Managed cloud dev environments |
| **singularity** | Singularity/Apptainer container | Namespaces (--containall) | HPC clusters, shared machines |

For cloud sandboxes (Modal, Daytona): `container_persistent: true` preserves filesystem state across sandbox recreation — but does not guarantee the same live sandbox, PID space, or background processes remain running.

Full tables and security notes: see [cli-config.yaml.example](cli-config.yaml.example) and [Tools](tools/index.md).

---

## Skills Config

Skills declare their own settings in their SKILL.md frontmatter. These are stored under `skills.config` in `config.yaml`:

```yaml
skills:
  config:
    wiki:
      path: ~/wiki   # Used by the llm-wiki skill
```

- `spark config migrate` finds unconfigured skill settings and prompts you to fill them in
- `spark config show` lists all skill settings and which skill they belong to
- Values are injected into the skill context automatically when it loads

Set values manually:

```bash
spark config set skills.config.wiki.path ~/my-research-wiki
```

See [Creating Skills - Config Settings](building/creating-skills.md#config-settings-configyaml) for how to declare settings in your own skills.

---

## Memory

```yaml
memory:
  memory_enabled: true
  user_profile_enabled: true
  memory_char_limit: 2200   # ~800 tokens
  user_char_limit: 1375     # ~500 tokens
```

---

## File Read Safety

Controls how much content a single `read_file` call can return. Reads that exceed the limit are rejected with an error prompting the agent to use `offset` and `limit` for smaller ranges — preventing a minified JS bundle or large data file from flooding the context window.

```yaml
file_read_max_chars: 100000  # default — ~25-35K tokens
```

Tune this to match your model's context window:

```yaml
# Large context model (200K+)
file_read_max_chars: 200000

# Small local model (16K context)
file_read_max_chars: 30000
```

Spark also deduplicates reads automatically — if the same file region is read twice without changes, a lightweight stub is returned instead of re-sending the content. This resets on context compression.

---

## Git Worktree Isolation

Run multiple agents on the same repo without conflicts:

```yaml
worktree: true    # Always create a worktree (same as spark -w)
# worktree: false # Default - only when -w flag is passed
```

When enabled, each CLI session creates a fresh worktree under `.worktrees/` with its own branch. Agents can edit files, commit, push, and open PRs without stepping on each other. Clean worktrees are removed on exit; dirty ones are kept for manual recovery.

Copy gitignored files into each worktree via `.worktreeinclude` in your repo root:

```
# .worktreeinclude
.env
.venv/
node_modules/
```

---

## Context Compression

Spark automatically compresses long conversations to stay within your model's context window. The summarizer is a separate LLM call — you can point it at any provider.

```yaml
compression:
  enabled: true
  threshold: 0.50      # Compress at this % of context limit
  target_ratio: 0.20   # Fraction of threshold to preserve as recent tail
  protect_last_n: 20   # Min recent messages to keep uncompressed

auxiliary:
  compression:
    model: "google/gemini-3-flash-preview"
    provider: "auto"   # "auto", "openrouter", "nous", "codex", "main", etc.
    base_url: null     # Custom OpenAI-compatible endpoint (overrides provider)
```

:::info Legacy config migration
Older configs with `compression.summary_model`, `compression.summary_provider`, and `compression.summary_base_url` are automatically migrated to `auxiliary.compression.*` on first load (config version 17). No manual action needed.
:::

### Common setups

**Default (auto-detect) — no config needed:**
```yaml
compression:
  enabled: true
  threshold: 0.50
```
Uses the first available provider (OpenRouter -> Spark Portal -> Codex) with Gemini Flash.

**Force a specific provider:**
```yaml
auxiliary:
  compression:
    provider: nous
    model: gemini-3-flash
```

**Custom endpoint (self-hosted, Ollama, DeepSeek, etc.):**
```yaml
auxiliary:
  compression:
    model: glm-4.7
    base_url: https://api.z.ai/api/coding/paas/v4
```

### Provider precedence

| `provider` | `base_url` | Result |
|---|---|---|
| `auto` (default) | not set | Auto-detect best available |
| `nous` / `openrouter` / etc. | not set | Force that provider |
| any | set | Use the custom endpoint directly |

:::warning Summary model context length
The summary model must have a context window at least as large as your main model's. If it's smaller, summarization will fail and the middle turns will be **dropped silently**. Verify context length when overriding the model.
:::

---

## Context Engine

Controls what happens when you approach the token limit:

```yaml
context:
  engine: "compressor"   # default — built-in lossy summarization
```

To use a plugin engine (e.g., LCM for lossless context management):

```yaml
context:
  engine: "lcm"   # must match the plugin's name
```

Plugin engines are never auto-activated — you must set `context.engine` explicitly. Browse available engines via `spark plugins` -> Provider Plugins -> Context Engine.

---

## Iteration Budget Pressure

When a complex task is burning through its 90-turn iteration budget, Spark warns the model before it hits the wall:

| Threshold | Level | What the model sees |
|-----------|-------|---------------------|
| **70%** | Caution | `[BUDGET: 63/90. 27 iterations left. Start consolidating.]` |
| **90%** | Warning | `[BUDGET WARNING: 81/90. Only 9 left. Respond NOW.]` |

Warnings are injected into the last tool result as a `_budget_warning` field — not as separate messages — to preserve prompt caching.

```yaml
agent:
  max_turns: 90   # Max iterations per conversation turn (default: 90)
```

When the budget is exhausted, the CLI shows: `Iteration budget reached (90/90) - response may be incomplete`. If it runs out mid-task, the agent generates a summary before stopping.

### Streaming Timeouts

| Timeout | Default | Local providers | Env var |
|---------|---------|----------------|---------|
| Socket read timeout | 120s | Auto-raised to 1800s | `SPARK_STREAM_READ_TIMEOUT` |
| Stale stream detection | 180s | Auto-disabled | `SPARK_STREAM_STALE_TIMEOUT` |
| API call (non-streaming) | 1800s | Unchanged | `SPARK_API_TIMEOUT` |

Local endpoints (localhost, LAN IPs) are detected automatically — no manual config needed for most setups.

---

## Context Pressure Warnings

Separate from iteration budget tracking, this tells you how close the conversation is to triggering compression:

| Progress | Level | What happens |
|----------|-------|-------------|
| **>= 60%** to threshold | Info | CLI shows a cyan progress bar; gateway sends an informational notice |
| **>= 85%** to threshold | Warning | CLI shows a bold yellow bar; gateway warns compaction is imminent |

CLI example:
```
   context  62% to compaction  48k threshold (50%)  approaching compaction
```

Gateway example:
```
 Context:  62% to compaction (threshold: 50% of window).
```

Context pressure is automatic — no configuration needed. It never modifies the message stream.

---

## Credential Pool Strategies

When you have multiple API keys or tokens for the same provider:

```yaml
credential_pool_strategies:
  openrouter: round_robin    # cycle through keys evenly
  anthropic: least_used      # always pick the least-used key
```

Options: `fill_first` (default), `round_robin`, `least_used`, `random`. See [Credential Pools](providers/credential-pools.md).

---

## Auxiliary Models

Side tasks (vision, web extract, compression, MCP dispatch, memory flush, etc.) use the same `provider / model / base_url / api_key` pattern as the main model:

```yaml
auxiliary:
  vision:
    provider: "auto"
    model: ""
    base_url: ""
    api_key: ""
  web_extract: { provider: "auto", model: "", base_url: "", api_key: "" }
  compression:
    model: ""
    provider: "auto"
    base_url: ""
```

`provider: "main"` means "use the same endpoint as chat" — valid only under `auxiliary:`, not at the top-level `model.provider`. See [Integrations: providers](./integrations/providers.md) for provider IDs, OAuth, and fallback behavior.

---

## Reasoning Effort

Spark can send a reasoning-effort preference to providers and models that support thinking controls:

```yaml
agent:
  reasoning_effort: ""   # empty = medium (default). Options: none, minimal, low, medium, high, xhigh
```

Unset defaults to `"medium"` — a good balance for most tasks. Higher effort improves complex reasoning at the cost of more tokens and latency.

Configure it from the model picker or direct command:

```bash
spark model                  # choose Reasoning from the first menu
spark model reasoning high   # set default effort
spark model reasoning        # show current setting
```

Change it inside a running chat with `/reasoning`:

```
/reasoning           # Show current level
/reasoning high      # Set to high
/reasoning none      # Disable reasoning
/reasoning show      # Show model thinking above each response
/reasoning hide      # Hide model thinking
```

`display.show_reasoning` only controls whether returned reasoning text is shown in the UI; it does not change model thinking depth.

---

## Tool-Use Enforcement

Some models describe what they'd do instead of actually doing it. This injects system prompt guidance that steers them back to making real tool calls:

```yaml
agent:
  tool_use_enforcement: "auto"   # "auto" | true | false | ["model-substring", ...]
```

| Value | Behavior |
|-------|----------|
| `"auto"` (default) | Enabled for `gpt`, `codex`, `gemini`, `gemma`, `grok`. Disabled for Claude, DeepSeek, Qwen, etc. |
| `true` | Always enabled, regardless of model |
| `false` | Always disabled |
| `["gpt", "codex", "qwen"]` | Enabled only when the model name contains one of the listed substrings |

Three tiers of guidance may be injected when enabled:

1. **General** (all matched models) — make tool calls immediately, keep working, don't end turns with promises
2. **OpenAI-specific** (GPT and Codex) — don't abandon work on partial results, don't hallucinate instead of using tools
3. **Google-specific** (Gemini and Gemma) — conciseness, absolute paths, parallel tool calls, verify-before-edit

If you see a model frequently describing actions rather than taking them, add it:

```yaml
agent:
  tool_use_enforcement: ["gpt", "codex", "gemini", "grok", "my-custom-model"]
```

---

## TTS Configuration

```yaml
tts:
  provider: "edge"              # "edge" | "elevenlabs" | "openai" | "minimax" | "mistral" | "neutts"
  speed: 1.0                    # Global speed multiplier (fallback for all providers)
  edge:
    voice: "en-US-AriaNeural"   # 322 voices, 74 languages
    speed: 1.0
  elevenlabs:
    voice_id: "pNInz6obpgDQGcFmaJgB"
    model_id: "eleven_multilingual_v2"
  openai:
    model: "gpt-4o-mini-tts"
    voice: "alloy"              # alloy, echo, fable, onyx, nova, shimmer
    speed: 1.0                  # clamped to 0.25-4.0 by the API
    base_url: "https://api.openai.com/v1"
  minimax:
    speed: 1.0
  neutts:
    ref_audio: ''
    ref_text: ''
    model: neuphonic/neutts-air-q4-gguf
    device: cpu
```

**Speed fallback:** provider-specific speed (e.g. `tts.edge.speed`) -> global `tts.speed` -> `1.0` default.

This controls both the `text_to_speech` tool and spoken replies in voice mode.

---

## Display Settings

```yaml
display:
  tool_progress: all      # off | new | all | verbose
  tool_progress_command: false  # Enable /verbose in messaging gateway
  tool_progress_overrides: {}   # Per-platform overrides
  interim_assistant_messages: true  # Gateway: send mid-turn updates as separate messages
  skin: default
  compact: false
  resume_display: full    # full | minimal
  bell_on_complete: false # Terminal bell when agent finishes
  show_reasoning: false   # Show model thinking above each response
  streaming: false        # Stream tokens to terminal as they arrive
  show_cost: false        # Show estimated cost in the CLI status bar
  tool_preview_length: 0  # Max chars for tool call previews (0 = no limit)
```

| Mode | What you see |
|------|-------------|
| `off` | Silent — just the final response |
| `new` | Tool indicator only when the tool changes |
| `all` | Every tool call with a short preview (default) |
| `verbose` | Full args, results, and debug logs |

Cycle through modes in the CLI with `/verbose`. To enable `/verbose` in messaging platforms, set `tool_progress_command: true`.

### Per-platform progress overrides

Different platforms need different verbosity. Signal, for example, can't edit messages — each progress update becomes a separate message:

```yaml
display:
  tool_progress: all
  tool_progress_overrides:
    signal: 'off'
    telegram: verbose
    slack: 'off'
```

Valid platform keys: `telegram`, `discord`, `slack`, `signal`, `whatsapp`, `matrix`, `mattermost`, `email`, `sms`, `homeassistant`, `dingtalk`, `feishu`, `wecom`, `weixin`, `bluebubbles`, `qqbot`.

`interim_assistant_messages` is gateway-only. When enabled, Spark sends completed mid-turn updates as separate messages. This is independent from `tool_progress`.

**Overflow handling:** Streamed text that exceeds a platform's message length limit (~4096 chars) automatically starts a new message.

---

## Privacy

```yaml
privacy:
  redact_pii: false  # Strip PII from LLM context (gateway only)
```

When `true`, PII is redacted from the system prompt before sending to the LLM:

| Field | Treatment |
|-------|-----------|
| Phone numbers (user ID on WhatsApp/Signal) | Hashed to `user_<12-char-sha256>` |
| User IDs | Hashed to `user_<12-char-sha256>` |
| Chat IDs | Numeric portion hashed, platform prefix preserved |
| User names / usernames | Not affected (user-chosen, publicly visible) |

Hashes are deterministic — the same user always maps to the same hash, so the model can still distinguish users in group chats. Applies to WhatsApp, Signal, and Telegram. Discord and Slack are excluded because their mention systems require real IDs.

---

## Speech-to-Text (STT)

```yaml
stt:
  provider: "local"            # "local" | "groq" | "openai" | "mistral"
  local:
    model: "base"              # tiny, base, small, medium, large-v3
  openai:
    model: "whisper-1"         # whisper-1 | gpt-4o-mini-transcribe | gpt-4o-transcribe
```

- `local` uses `faster-whisper` on your machine. Install separately: `pip install faster-whisper`
- `groq` uses Groq's Whisper endpoint and reads `GROQ_API_KEY`
- `openai` uses the OpenAI speech API and reads `VOICE_TOOLS_OPENAI_KEY`

If the requested provider is unavailable, Spark falls back: `local` -> `groq` -> `openai`.

Overrides via environment:

```bash
STT_GROQ_MODEL=whisper-large-v3-turbo
STT_OPENAI_MODEL=whisper-1
GROQ_BASE_URL=https://api.groq.com/openai/v1
STT_OPENAI_BASE_URL=https://api.openai.com/v1
```

---

## Voice Mode (CLI)

```yaml
voice:
  record_key: "ctrl+b"
  max_recording_seconds: 120
  auto_tts: false
  silence_threshold: 200
  silence_duration: 3.0
```

Use `/voice on` to enable microphone mode. Press `record_key` to start/stop. Use `/voice tts` to toggle spoken replies. See [Voice Mode](voice/voice-mode.md) for full setup.

---

## Streaming

### CLI Streaming

```yaml
display:
  streaming: true
  show_reasoning: true   # Also stream reasoning tokens (optional)
```

Responses appear token-by-token. Tool calls are still captured silently. Falls back to normal display if the provider doesn't support streaming.

### Gateway Streaming (Telegram, Discord, Slack)

```yaml
streaming:
  enabled: true
  transport: edit         # "edit" (progressive message editing) or "off"
  edit_interval: 0.3
  buffer_threshold: 40
  cursor: " "
```

The bot sends a message on the first token, then progressively edits it. Platforms that don't support message editing (Signal, Email, Home Assistant) are auto-detected and streaming is gracefully disabled.

:::note
Streaming is disabled by default. Enable it in `~/.spark/config.yaml`.
:::

---

## Group Chat Session Isolation

```yaml
group_sessions_per_user: true  # true = per-user isolation, false = one shared session per chat
```

With `true` (default): Alice and Bob each get their own session in shared channels. With `false`: everyone shares one context, token budget, and interrupt state.

Direct messages are unaffected. See [Sessions](sessions.md) and the [Discord guide](chat-platforms/discord.md) for more.

---

## Unauthorized DM Behavior

```yaml
unauthorized_dm_behavior: pair   # pair | ignore

whatsapp:
  unauthorized_dm_behavior: ignore
```

- `pair` (default): Denies access but sends a one-time pairing code in DMs
- `ignore`: Silently drops unauthorized DMs

Platform sections override the global default.

---

## Quick Commands

Run shell commands instantly with no LLM involved — zero tokens, instant output. Useful on messaging platforms for quick checks:

```yaml
quick_commands:
  status:
    type: exec
    command: systemctl status spark-agent
  disk:
    type: exec
    command: df -h /
  gpu:
    type: exec
    command: nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total --format=csv,noheader
```

Type `/status`, `/disk`, or `/gpu` in the CLI or any messaging platform. The command runs locally and returns output directly.

- **30-second timeout** — long-running commands are killed with an error
- **Priority** — quick commands are checked before skill commands
- **Works everywhere** — CLI, Telegram, Discord, Slack, WhatsApp, Signal, Email, Home Assistant

---

## Human Delay

Simulate human-like response pacing in messaging platforms:

```yaml
human_delay:
  mode: "off"      # off | natural | custom
  min_ms: 800
  max_ms: 2500
```

---

## Code Execution

```yaml
code_execution:
  timeout: 300          # Max execution time in seconds
  max_tool_calls: 50    # Max tool calls within code execution
```

---

## Web Search Backends

```yaml
web:
  backend: firecrawl    # firecrawl | parallel | tavily | exa
```

| Backend | Env Var | Search | Extract | Crawl |
|---------|---------|--------|---------|-------|
| **Firecrawl** (default) | `FIRECRAWL_API_KEY` | yes | yes | yes |
| **Parallel** | `PARALLEL_API_KEY` | yes | yes | - |
| **Tavily** | `TAVILY_API_KEY` | yes | yes | yes |
| **Exa** | `EXA_API_KEY` | yes | yes | - |

If `web.backend` is not set, the backend is auto-detected from available API keys. Set `FIRECRAWL_API_URL` to point at a self-hosted Firecrawl instance.

---

## Browser

```yaml
browser:
  inactivity_timeout: 120        # Seconds before auto-closing idle sessions
  command_timeout: 30
  record_sessions: false         # Record sessions as WebM to ~/.spark/browser_recordings/
  camofox:
    managed_persistence: false   # Persist cookies/logins across restarts
```

See the [Browser feature page](tools/browser.md) for details on Browserbase, Browser Use, and local Chrome CDP setup.

---

## Timezone

```yaml
timezone: "America/New_York"   # IANA timezone (default: "" = server-local time)
```

Affects timestamps in logs, cron scheduling, and system prompt time injection. Any IANA identifier works (`America/New_York`, `Europe/London`, `Asia/Kolkata`, `UTC`).

---

## Discord

```yaml
discord:
  require_mention: true
  free_response_channels: ""    # Comma-separated channel IDs — no @mention needed
  auto_thread: true             # Auto-create threads on @mention
```

---

## Security

```yaml
security:
  redact_secrets: true
  tirith_enabled: true
  tirith_path: "tirith"
  tirith_timeout: 5
  tirith_fail_open: true
  website_blocklist:
    enabled: false
    domains: []
    shared_files: []
```

- `redact_secrets` — strips API key patterns from tool output before they enter the conversation or logs
- `tirith_enabled` — scans terminal commands with [Tirith](https://github.com/StackGuardian/tirith) before execution
- `tirith_fail_open` — when `true`, commands proceed if Tirith is unavailable

### Website Blocklist

Block specific domains from web and browser tools:

```yaml
security:
  website_blocklist:
    enabled: false
    domains:
      - "*.internal.company.com"
      - "admin.example.com"
      - "*.local"
    shared_files:
      - "/etc.spark/blocked-sites.txt"
```

Domain rules support exact matches, wildcard subdomains (`*.internal.company.com`), and TLD wildcards (`*.local`). The policy is cached for 30 seconds.

---

## Permissions

The quickest way to set the agent's permission level is during setup:

```bash
spark setup permissions   # or choose it from the main spark setup menu
```

Three levels are available:

| Level | Toolsets | Approval mode | Best for |
|-------|----------|---------------|----------|
| **Locked down** | `spark-cli` only | `manual` | Minimal footprint; every risky command is confirmed |
| **Standard** | terminal, file, web, code execution, vision, memory, skills, session search, delegation, cronjob | `manual` | Every-day use — full tool access with a safety net |
| **Full / Yolo** | Everything (standard + browser, tts, image_gen, moa) | `off` | Trusted/sandboxed environments; no confirmation prompts |

You can adjust either dimension independently after setup:

```bash
spark tools                                           # toggle individual toolsets
spark config set approvals.mode manual|smart|off      # change approval behaviour
```

Or in `config.yaml`:

```yaml
# Standard level — common toolsets on, approvals on
toolsets:
  - spark-cli
  - web
  - terminal
  - file
  - code_execution
  - vision
  - skills
  - memory
  - session_search
  - delegation
  - cronjob

approvals:
  mode: manual
```

---

## Smart Approvals

```yaml
approvals:
  mode: manual   # manual | smart | off
```

| Mode | Behavior |
|------|----------|
| `manual` (default) | Prompt before executing any flagged command |
| `smart` | Use an auxiliary LLM to assess risk. Low-risk commands are auto-approved; genuinely risky ones are escalated |
| `off` | Skip all approval checks. Equivalent to `SPARK_YOLO_MODE=true` |

:::warning
`approvals.mode: off` disables all safety checks for terminal commands. Only use this in trusted, sandboxed environments.
:::

---

## Checkpoints

Automatic filesystem snapshots before destructive operations. See [Checkpoints & Rollback](checkpoints.md) for full details.

```yaml
checkpoints:
  enabled: true
  max_snapshots: 50
```

---

## Delegation

```yaml
delegation:
  # model: "google/gemini-3-flash-preview"
  # provider: "openrouter"
  # base_url: "http://localhost:1234/v1"
  # api_key: "local-key"
```

Subagents inherit the parent's provider and model by default. Set `delegation.provider` and `delegation.model` to route them to a cheaper/faster model for narrowly-scoped tasks.

**Precedence:** `delegation.base_url` -> `delegation.provider` -> parent provider. `delegation.model` -> parent model.

---

## Clarify

```yaml
clarify:
  timeout: 120   # Seconds to wait for user response
```

---

## Context Files (SOUL.md, AGENTS.md)

| File | Purpose | Scope |
|------|---------|-------|
| `SOUL.md` | Primary agent identity — slot #1 in the system prompt | `~/.spark/SOUL.md` or `$SPARK_HOME/SOUL.md` |
| `.spark.md` / `SPARK.md` | Project-specific instructions (highest priority) | Walks to git root |
| `AGENTS.md` | Project instructions, coding conventions | Recursive directory walk |
| `CLAUDE.md` | Claude Code context files | Working directory only |
| `.cursorrules` | Cursor IDE rules | Working directory only |
| `.cursor/rules/*.mdc` | Cursor rule files | Working directory only |

Project context files use a priority system — only ONE type is loaded (first match wins): `.spark.md` -> `AGENTS.md` -> `CLAUDE.md` -> `.cursorrules`. SOUL.md is always loaded independently.

See also: [Personality & SOUL.md](personality.md) and [Context Files](tools/context-files.md).

---

## Working Directory

| Context | Default |
|---------|---------|
| **CLI (`spark`)** | Current directory where you run the command |
| **Messaging gateway** | Spark workspace `~/.spark/workspace` (override with `MESSAGING_CWD`) |
| **Docker / Singularity / Modal / SSH** | User's home directory inside the container |

```bash
# In ~/.spark/.env or ~/.spark/config.yaml:
MESSAGING_CWD=/home/myuser/projects
TERMINAL_CWD=/workspace
```
