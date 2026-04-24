---
sidebar_position: 10
title: "Migrate from OpenClaw"
description: "Complete guide to migrating your OpenClaw / Clawdbot setup to Spark Agent - what gets migrated, how config maps, and what to check after."
---

# Migrate from OpenClaw

One command brings your OpenClaw (or legacy Clawdbot/Moldbot) setup into Spark — config, keys, skills, memory, and messaging tokens.

```bash
spark claw migrate
```

It always shows a preview before touching anything. Review the list, then confirm.

---

## Quick commands

```bash
# Interactive preview + confirm
spark claw migrate

# Preview only — no changes made
spark claw migrate --dry-run

# Migrate everything including API keys, no prompt
spark claw migrate --preset full --yes
```

Spark reads from `~/.openclaw/` by default. Legacy `~/.clawdbot/` and `~/.moltbot/` directories are detected automatically. Legacy config filenames (`clawdbot.json`, `moltbot.json`) are recognized too.

---

## Options

| Option | What it does |
|--------|-------------|
| `--dry-run` | Show the preview, then stop. Nothing changes. |
| `--preset <name>` | `full` (default, includes secrets) or `user-data` (excludes API keys). |
| `--overwrite` | Overwrite existing Spark files on conflicts. Default is to skip. |
| `--migrate-secrets` | Include API keys. On by default with `--preset full`. |
| `--source <path>` | Point at a custom OpenClaw directory. |
| `--workspace-target <path>` | Where to place the migrated `AGENTS.md`. |
| `--skill-conflict <mode>` | `skip` (default), `overwrite`, or `rename`. |
| `--yes` | Skip the confirmation prompt after the preview. |

---

## What gets migrated

### Persona, memory, and instructions

| What | From (OpenClaw) | To (Spark) | Notes |
|------|----------------|------------|-------|
| Persona | `workspace/SOUL.md` | `~/.spark/SOUL.md` | Direct copy |
| Workspace instructions | `workspace/AGENTS.md` | `AGENTS.md` at `--workspace-target` | Requires `--workspace-target` flag |
| Long-term memory | `workspace/MEMORY.md` | `~/.spark/memories/MEMORY.md` | Parsed, merged, and deduped using `` delimiter |
| User profile | `workspace/USER.md` | `~/.spark/memories/USER.md` | Same merge logic as memory |
| Daily memory files | `workspace/memory/*.md` | `~/.spark/memories/MEMORY.md` | All daily files merged into main memory |

Workspace files are also checked at `workspace.default/` and `workspace-main/` as fallbacks (OpenClaw renamed `workspace/` to `workspace-main/` in recent versions, and uses `workspace-{agentId}` for multi-agent setups).

### Skills (4 source locations)

| Source | OpenClaw location | Spark destination |
|--------|------------------|-------------------|
| Workspace skills | `workspace/skills/` | `~/.spark/skills/openclaw-imports/` |
| Managed/shared skills | `~/.openclaw/skills/` | `~/.spark/skills/openclaw-imports/` |
| Personal cross-project | `~/.agents/skills/` | `~/.spark/skills/openclaw-imports/` |
| Project-level shared | `workspace/.agents/skills/` | `~/.spark/skills/openclaw-imports/` |

Conflict behavior is controlled by `--skill-conflict`: `skip` leaves the existing Spark skill alone, `overwrite` replaces it, `rename` creates a `-imported` copy alongside it.

### Model and provider config

| What | OpenClaw path | Spark destination | Notes |
|------|--------------|-------------------|-------|
| Default model | `agents.defaults.model` | `config.yaml` → `model` | Can be a string or `{primary, fallbacks}` object |
| Custom providers | `models.providers.*` | `config.yaml` → `custom_providers` | Maps `baseUrl`, `apiType`/`api` — handles both short and hyphenated format values |
| Provider API keys | `models.providers.*.apiKey` | `~/.spark/.env` | Requires `--migrate-secrets`. See [API key resolution](#api-key-resolution) below. |

### Agent behavior

| What | OpenClaw path | Spark path | Mapping |
|------|--------------|------------|---------|
| Max turns | `agents.defaults.timeoutSeconds` | `agent.max_turns` | `timeoutSeconds / 10`, capped at 200 |
| Verbose mode | `agents.defaults.verboseDefault` | `agent.verbose` | "off" / "on" / "full" |
| Reasoning effort | `agents.defaults.thinkingDefault` | `agent.reasoning_effort` | "always"/"high"/"xhigh" → "high", "auto"/"medium"/"adaptive" → "medium", "off"/"low"/"none"/"minimal" → "low" |
| Compression | `agents.defaults.compaction.mode` | `compression.enabled` | "off" → false, anything else → true |
| Compression model | `agents.defaults.compaction.model` | `compression.summary_model` | Direct copy |
| Human delay | `agents.defaults.humanDelay.mode` | `human_delay.mode` | "natural" / "custom" / "off" |
| Human delay timing | `agents.defaults.humanDelay.minMs` / `.maxMs` | `human_delay.min_ms` / `.max_ms` | Direct copy |
| Timezone | `agents.defaults.userTimezone` | `timezone` | Direct copy |
| Exec timeout | `tools.exec.timeoutSec` | `terminal.timeout` | Direct copy |
| Docker sandbox | `agents.defaults.sandbox.backend` | `terminal.backend` | "docker" → "docker" |
| Docker image | `agents.defaults.sandbox.docker.image` | `terminal.docker_image` | Direct copy |

### Session reset policies

| OpenClaw path | Spark path | Notes |
|--------------|------------|-------|
| `session.reset.mode` | `session_reset.mode` | "daily", "idle", or both |
| `session.reset.atHour` | `session_reset.at_hour` | Hour (0–23) for daily reset |
| `session.reset.idleMinutes` | `session_reset.idle_minutes` | Minutes of inactivity |

If the structured `session.reset` object isn't present, the migration falls back to inferring from `session.resetTriggers` (a simple string array like `["daily", "idle"]`).

### MCP servers

| OpenClaw field | Spark field | Notes |
|----------------|------------|-------|
| `mcp.servers.*.command` | `mcp_servers.*.command` | Stdio transport |
| `mcp.servers.*.args` | `mcp_servers.*.args` | |
| `mcp.servers.*.env` | `mcp_servers.*.env` | |
| `mcp.servers.*.cwd` | `mcp_servers.*.cwd` | |
| `mcp.servers.*.url` | `mcp_servers.*.url` | HTTP/SSE transport |
| `mcp.servers.*.tools.include` | `mcp_servers.*.tools.include` | Tool filtering |
| `mcp.servers.*.tools.exclude` | `mcp_servers.*.tools.exclude` | |

### TTS (text-to-speech)

The migration reads TTS settings from three OpenClaw locations, in priority order:

1. `messages.tts.providers.{provider}.*` — canonical location
2. `talk.providers.{provider}.*` — top-level fallback
3. `messages.tts.{provider}.*` — oldest flat format

| What | Spark destination |
|------|------------------|
| Provider name | `config.yaml` → `tts.provider` |
| ElevenLabs voice ID | `config.yaml` → `tts.elevenlabs.voice_id` |
| ElevenLabs model ID | `config.yaml` → `tts.elevenlabs.model_id` |
| OpenAI model | `config.yaml` → `tts.openai.model` |
| OpenAI voice | `config.yaml` → `tts.openai.voice` |
| Edge TTS voice | `config.yaml` → `tts.edge.voice` (both "edge" and "microsoft" recognized) |
| TTS assets | `~/.spark/tts/` (file copy) |

### Messaging platforms

| Platform | OpenClaw path | Spark `.env` variable | Notes |
|----------|--------------|----------------------|-------|
| Telegram | `channels.telegram.botToken` or `.accounts.default.botToken` | `TELEGRAM_BOT_TOKEN` | Supports string or [SecretRef](#secretref-handling). Both flat and accounts layout. |
| Telegram | `credentials/telegram-default-allowFrom.json` | `TELEGRAM_ALLOWED_USERS` | Comma-joined from `allowFrom[]` array |
| Discord | `channels.discord.token` or `.accounts.default.token` | `DISCORD_BOT_TOKEN` | |
| Discord | `channels.discord.allowFrom` or `.accounts.default.allowFrom` | `DISCORD_ALLOWED_USERS` | |
| Slack | `channels.slack.botToken` or `.accounts.default.botToken` | `SLACK_BOT_TOKEN` | |
| Slack | `channels.slack.appToken` or `.accounts.default.appToken` | `SLACK_APP_TOKEN` | |
| Slack | `channels.slack.allowFrom` or `.accounts.default.allowFrom` | `SLACK_ALLOWED_USERS` | |
| WhatsApp | `channels.whatsapp.allowFrom` or `.accounts.default.allowFrom` | `WHATSAPP_ALLOWED_USERS` | Auth via Baileys QR — requires re-pairing after migration |
| Signal | `channels.signal.account` or `.accounts.default.account` | `SIGNAL_ACCOUNT` | |
| Signal | `channels.signal.httpUrl` or `.accounts.default.httpUrl` | `SIGNAL_HTTP_URL` | |
| Signal | `channels.signal.allowFrom` or `.accounts.default.allowFrom` | `SIGNAL_ALLOWED_USERS` | |
| Matrix | `channels.matrix.accessToken` or `.accounts.default.accessToken` | `MATRIX_ACCESS_TOKEN` | Uses `accessToken`, not `botToken` |
| Mattermost | `channels.mattermost.botToken` or `.accounts.default.botToken` | `MATTERMOST_BOT_TOKEN` | |

### Other config

| What | OpenClaw path | Spark path | Notes |
|------|-------------|------------|-------|
| Approval mode | `approvals.exec.mode` | `config.yaml` → `approvals.mode` | "auto"→"off", "always"→"manual", "smart"→"smart" |
| Command allowlist | `exec-approvals.json` | `config.yaml` → `command_allowlist` | Merged and deduped |
| Browser CDP URL | `browser.cdpUrl` | `config.yaml` → `browser.cdp_url` | |
| Browser headless | `browser.headless` | `config.yaml` → `browser.headless` | |
| Brave search key | `tools.web.search.brave.apiKey` | `.env` → `BRAVE_API_KEY` | Requires `--migrate-secrets` |
| Gateway auth token | `gateway.auth.token` | `.env` → `SPARK_GATEWAY_TOKEN` | Requires `--migrate-secrets` |
| Working directory | `agents.defaults.workspace` | `.env` → `MESSAGING_CWD` | |

### Archived — no direct Spark equivalent

These land in `~/.spark/migration/openclaw/<timestamp>/archive/` for manual review:

| What | Archive file | How to recreate in Spark |
|------|-------------|--------------------------|
| `IDENTITY.md` | `archive/workspace/IDENTITY.md` | Merge into `SOUL.md` |
| `TOOLS.md` | `archive/workspace/TOOLS.md` | Spark has built-in tool instructions |
| `HEARTBEAT.md` | `archive/workspace/HEARTBEAT.md` | Use cron jobs for periodic tasks |
| `BOOTSTRAP.md` | `archive/workspace/BOOTSTRAP.md` | Use context files or skills |
| Cron jobs | `archive/cron-config.json` | Recreate with `spark cron create` |
| Plugins | `archive/plugins-config.json` | See [plugins guide](/docs/tools/hooks) |
| Hooks/webhooks | `archive/hooks-config.json` | Use `spark webhook` or gateway hooks |
| Memory backend | `archive/memory-backend-config.json` | Configure via `spark honcho` |
| Skills registry | `archive/skills-registry-config.json` | Use `spark skills config` |
| UI/identity | `archive/ui-identity-config.json` | Use `/skin` command |
| Logging | `archive/logging-diagnostics-config.json` | Set in `config.yaml` logging section |
| Multi-agent list | `archive/agents-list.json` | Use Spark profiles |
| Channel bindings | `archive/bindings.json` | Manual setup per platform |
| Complex channels | `archive/channels-deep-config.json` | Manual platform config |

---

## API key resolution

When `--migrate-secrets` is on, keys are pulled from four sources in priority order:

1. `models.providers.*.apiKey` and TTS provider keys in `openclaw.json`
2. `~/.openclaw/.env`
3. The `"env"` or `"env"."vars"` sub-object in `openclaw.json`
4. `~/.openclaw/agents/main/agent/auth-profiles.json`

Each source fills gaps left by the previous one. Keys not in the allowlist below are never copied.

**Supported keys:** `OPENROUTER_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, `GEMINI_API_KEY`, `ZAI_API_KEY`, `MINIMAX_API_KEY`, `ELEVENLABS_API_KEY`, `TELEGRAM_BOT_TOKEN`, `VOICE_TOOLS_OPENAI_KEY`

---

## SecretRef handling

OpenClaw stores tokens in three formats. The migration resolves all three:

```json
// Plain string
"channels": { "telegram": { "botToken": "123456:ABC-DEF..." } }

// Environment template
"channels": { "telegram": { "botToken": "${TELEGRAM_BOT_TOKEN}" } }

// SecretRef object
"channels": { "telegram": { "botToken": { "source": "env", "id": "TELEGRAM_BOT_TOKEN" } } }
```

For env templates and `source: "env"` SecretRefs, the migration looks up the value in `~/.openclaw/.env` and the `openclaw.json` env sub-object.

`source: "file"` and `source: "exec"` SecretRefs cannot be resolved automatically. The migration warns about these — add them manually with `spark config set`.

---

## After migration: your checklist

1. **Check the migration report** — printed on completion with counts of migrated, skipped, and conflicting items.
2. **Review archived files** — anything in `~/.spark/migration/openclaw/<timestamp>/archive/` needs manual attention.
3. **Start a new session** — imported skills and memory entries only take effect in new sessions.
4. **Verify API keys** — run `spark status` to confirm provider authentication.
5. **Test messaging** — if you migrated platform tokens, restart the gateway: `systemctl --user restart spark-gateway`
6. **Check session policies** — run `spark config get session_reset` to confirm the reset behavior matches your expectations.
7. **Re-pair WhatsApp** — WhatsApp uses QR code pairing (Baileys), not token migration. Run `spark whatsapp` to pair again.
8. **Clean up** — after confirming everything works, run `spark claw cleanup` to rename leftover OpenClaw directories to `.pre-migration/` and prevent state confusion.

---

## Troubleshooting

### "OpenClaw directory not found"

The migration checks `~/.openclaw/`, then `~/.clawdbot/`, then `~/.moltbot/`. If your installation lives elsewhere, pass `--source /path/to/your/openclaw`.

### "No provider API keys found"

Keys can live in several places depending on your OpenClaw version: inline in `openclaw.json` under `models.providers.*.apiKey`, in `~/.openclaw/.env`, in the `openclaw.json` `"env"` sub-object, or in `agents/main/agent/auth-profiles.json`. The migration checks all four. If keys use `source: "file"` or `source: "exec"` SecretRefs, add them manually with `spark config set`.

### "Skills not appearing after migration"

Imported skills land in `~/.spark/skills/openclaw-imports/`. Start a new session for them to take effect, or run `/skills` to verify they are loaded.

### "TTS voice not migrated"

OpenClaw stores TTS settings in two places: `messages.tts.providers.*` and the top-level `talk` config. The migration checks both. If your voice ID was set via the OpenClaw UI and stored elsewhere, set it manually: `spark config set tts.elevenlabs.voice_id YOUR_VOICE_ID`.
