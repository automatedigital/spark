# Moving from OpenClaw to Spark Agent

Spark can pull in your OpenClaw memories, skills, API keys, and settings automatically — you don't have to start from scratch.

## Pick Your Migration Path

### Option 1: Auto-import during first run

Run `spark setup` for the first time. If Spark finds `~/.openclaw`, it offers to import everything before configuration starts. Accept the prompt and you're done.

### Option 2: CLI command (fast, scriptable)

```bash
spark claw migrate                      # Preview what will change, then migrate
spark claw migrate --dry-run            # Preview only — no files touched
spark claw migrate --preset user-data   # Import personal data, skip API keys
spark claw migrate --yes                # Skip the confirmation prompt
```

Spark always shows you a full preview before writing anything. Review it, then confirm.

**All flags:**

| Flag | What it does |
|------|-------------|
| `--source PATH` | OpenClaw directory to read from (default: `~/.openclaw`) |
| `--dry-run` | Preview only — nothing is written |
| `--preset {user-data,full}` | `user-data` skips secrets; `full` includes them (default: `full`) |
| `--overwrite` | Replace existing files instead of skipping conflicts |
| `--migrate-secrets` | Import allowlisted secrets (auto-enabled with `full` preset) |
| `--workspace-target PATH` | Copy workspace instructions (AGENTS.md) to an absolute path |
| `--skill-conflict {skip,overwrite,rename}` | What to do when a skill name already exists (default: `skip`) |
| `--yes`, `-y` | Skip confirmation prompts |

### Option 3: Ask the agent

```
> Migrate my OpenClaw setup to Spark
```

The agent runs the `openclaw-migration` skill and walks you through it step by step:

1. Shows a preview of what would change
2. Asks how you want to handle conflicts (SOUL.md, skills, etc.)
3. Lets you choose between `user-data` and `full` presets
4. Runs the migration with your choices
5. Prints a full summary of everything imported

## What Gets Imported

### `user-data` preset

| Item | From | To |
|------|------|----|
| SOUL.md | `~/.openclaw/workspace/SOUL.md` | `~/.spark/SOUL.md` |
| Memory entries | `~/.openclaw/workspace/MEMORY.md` | `~/.spark/memories/MEMORY.md` |
| User profile | `~/.openclaw/workspace/USER.md` | `~/.spark/memories/USER.md` |
| Skills | `~/.openclaw/workspace/skills/` | `~/.spark/skills/openclaw-imports/` |
| Command allowlist | `~/.openclaw/workspace/exec_approval_patterns.yaml` | Merged into `~/.spark/config.yaml` |
| Messaging settings | `~/.openclaw/config.yaml` (`TELEGRAM_ALLOWED_USERS`, `MESSAGING_CWD`) | `~/.spark/.env` |
| TTS assets | `~/.openclaw/workspace/tts/` | `~/.spark/tts/` |

Workspace files are also checked at `workspace.default/` and `workspace-main/` as fallbacks — OpenClaw renamed `workspace/` to `workspace-main/` in recent versions.

### `full` preset (adds to `user-data`)

| Item | Reads from | Writes to |
|------|-----------|-----------|
| Telegram bot token | `openclaw.json` channels config | `~/.spark/.env` |
| OpenRouter API key | `.env`, `openclaw.json`, or `openclaw.json["env"]` | `~/.spark/.env` |
| OpenAI API key | `.env`, `openclaw.json`, or `openclaw.json["env"]` | `~/.spark/.env` |
| Anthropic API key | `.env`, `openclaw.json`, or `openclaw.json["env"]` | `~/.spark/.env` |
| ElevenLabs API key | `.env`, `openclaw.json`, or `openclaw.json["env"]` | `~/.spark/.env` |

API keys are pulled from four places: inline config values, `~/.openclaw/.env`, the `openclaw.json` `"env"` sub-object, and per-agent auth profiles. Only allowlisted secrets are ever imported — anything else is skipped and reported.

## OpenClaw Format Compatibility

The migration handles both old and current OpenClaw config layouts:

- **Channel tokens** — reads flat paths (`channels.telegram.botToken`) and the newer `accounts.default` layout
- **TTS provider** — OpenClaw renamed "edge" to "microsoft"; both map to Spark's "edge"
- **Provider API types** — short (`openai`, `anthropic`) and hyphenated (`openai-completions`, `anthropic-messages`, `google-generative-ai`) values are both recognized
- **thinkingDefault** — all enum values work, including newer ones (`minimal`, `xhigh`, `adaptive`)
- **Matrix** — uses `accessToken` (not `botToken`)
- **SecretRef formats** — plain strings, env templates (`${VAR}`), and `source: "env"` SecretRefs are resolved. `source: "file"` and `source: "exec"` SecretRefs produce a warning — add those keys manually after migration

## Conflict Handling

By default, migration skips anything that already exists in Spark:

- **SOUL.md** — skipped if one already exists in `~/.spark/`
- **Memory entries** — skipped if memories are already present (avoids duplicates)
- **Skills** — skipped if a skill with the same name already exists
- **API keys** — skipped if the key is already set in `~/.spark/.env`

Use `--overwrite` to replace conflicts instead. Spark creates backups before overwriting.

For skills specifically, `--skill-conflict rename` imports conflicting skills under a new name (e.g., `skill-name-imported`).

## Reading the Migration Report

Every migration outputs a summary broken into four sections:

- **Migrated** — successfully imported items
- **Conflicts** — items skipped because they already existed
- **Skipped** — items not found in the source
- **Errors** — items that failed to import

For completed migrations, the full report is saved to `~/.spark/migration/openclaw/<timestamp>/`.

## After Migration

- **Skills need a new session** — imported skills take effect after restarting or starting a new chat.
- **WhatsApp needs re-pairing** — WhatsApp uses QR-code pairing, not token auth. Run `spark whatsapp` to pair.
- **Archive your OpenClaw directory** — after migration, Spark offers to rename `~/.openclaw/` to `.openclaw.pre-migration/` to prevent state confusion. You can also run `spark claw cleanup` later.

## Troubleshooting

### "OpenClaw directory not found"

Spark looks for `~/.openclaw` by default, then tries `~/.clawdbot` and `~/.moltbot`. If your install is elsewhere:

```bash
spark claw migrate --source /path/to/.openclaw
```

### "Migration script not found"

The script ships with Spark Agent. If you installed via pip (not git clone), the `optional-skills/` directory may be absent. Install the skill directly:

```bash
spark skills install openclaw-migration
```

### Memory overflow

If your OpenClaw `MEMORY.md` or `USER.md` exceeds Spark's character limits, excess entries go to an overflow file in the migration report directory. Review it and manually add the most important entries.

### API keys not found

Keys might live in different places depending on your OpenClaw setup:

- `~/.openclaw/.env`
- Inline in `openclaw.json` under `models.providers.*.apiKey`
- In `openclaw.json` under `"env"` or `"env.vars"`
- In `~/.openclaw/agents/main/agent/auth-profiles.json`

The migration checks all four. Keys using `source: "file"` or `source: "exec"` SecretRefs can't be resolved automatically — add them manually with `spark config set`.
