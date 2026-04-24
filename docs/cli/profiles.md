---
sidebar_position: 2
---

# Profiles: Running Multiple Agents

Want a coding assistant, a personal bot, and a research agent — all on one machine? Profiles give you completely isolated Spark instances that never share config, sessions, memory, or API keys.

## How profiles work

Each profile is just its own directory with its own everything: `config.yaml`, `.env`, `SOUL.md`, sessions, skills, cron jobs, state database. When you create a profile named `coder`, Spark creates a `~/.local/bin/coder` wrapper script. That script is just `spark -p coder` under the hood — but now `coder` works as its own top-level command.

The default profile lives at `~/.spark`. It requires no migration — your existing setup is already a profile.

## Get started in 30 seconds

```bash
spark profile create coder       # creates profile + "coder" shell command
coder setup                       # configure API keys and model for coder
coder chat                        # start chatting
```

`coder` is now fully independent. Different model, different API keys, different memory.

---

## Creating profiles

### Fresh profile

```bash
spark profile create mybot
```

Starts with bundled skills seeded. Run `mybot setup` to configure keys, model, and gateway tokens.

### Clone config from your current profile (`--clone`)

```bash
spark profile create work --clone
```

Copies `config.yaml`, `.env`, and `SOUL.md` from your active profile. Same API keys and model, but fresh sessions and memory. Tweak from there:

```bash
nano ~/.spark/profiles/work/.env       # different API keys
nano ~/.spark/profiles/work/SOUL.md    # different personality
```

### Clone everything (`--clone-all`)

```bash
spark profile create backup --clone-all
```

Copies everything: config, keys, personality, all memories, full session history, skills, cron jobs, plugins. A complete snapshot. Useful for backups or forking an agent that already has rich context.

### Clone from a specific profile

```bash
spark profile create work --clone --clone-from coder
```

:::tip Honcho memory + profiles
When Honcho is enabled, `--clone` automatically creates a dedicated AI peer for the new profile while sharing the same user workspace. Each profile builds its own observations and identity. See [Honcho — multi-agent / profiles](../memory/providers.md#honcho) for details.
:::

---

## Targeting a profile

You have three ways to target a profile for any command.

### Use the generated command alias

Every profile automatically gets `~/.local/bin/<name>`:

```bash
coder chat                    # chat with the coder agent
coder setup                   # configure coder's settings
coder gateway start           # start coder's gateway
coder doctor                  # check coder's health
coder skills list             # list coder's skills
coder config set model.model anthropic/claude-sonnet-4
```

### Use the `-p` flag

Target a profile one-off without changing your default:

```bash
spark -p coder chat
spark --profile=coder doctor
spark chat -p coder -q "hello"   # works in any position
```

### Set a sticky default

```bash
spark profile use coder
spark chat                    # targets coder
spark tools                   # configures coder's tools
spark profile use default     # switch back
```

Works just like `kubectl config use-context`. The CLI always shows which profile is active — in the prompt (`coder ` vs ``), in the startup banner, and via `spark profile`.

---

## Running gateways

Each profile runs its own gateway as a separate process with its own bot token.

```bash
coder gateway start           # starts coder's gateway
assistant gateway start       # starts assistant's gateway (separate process)
```

**Different tokens per profile:** Each profile has its own `.env` file.

```bash
nano ~/.spark/profiles/coder/.env      # coder's Telegram/Discord tokens
nano ~/.spark/profiles/assistant/.env  # assistant's tokens
```

**Token locks:** If two profiles accidentally share a bot token, the second gateway is blocked immediately with a clear error naming the conflict. Works for Telegram, Discord, Slack, WhatsApp, and Signal.

**Persistent services:** Each profile gets its own named service.

```bash
coder gateway install         # creates spark-gateway-coder (systemd/launchd)
assistant gateway install     # creates spark-gateway-assistant
```

---

## Per-profile configuration

Each profile has its own config, keys, and personality:

```bash
coder config set model.model anthropic/claude-sonnet-4
echo "You are a focused coding assistant." > ~/.spark/profiles/coder/SOUL.md
```

Files per profile:
- **`config.yaml`** — model, provider, toolsets, all settings
- **`.env`** — API keys, bot tokens
- **`SOUL.md`** — personality and instructions

---

## Keeping profiles up to date

`spark update` pulls the codebase once and syncs new bundled skills to all profiles:

```bash
spark update
# -> Code updated (12 commits)
# -> Skills synced: default (up to date), coder (+2 new), assistant (+2 new)
```

Your modified skills are never overwritten.

---

## `spark profile` subcommand reference

### `spark profile list`

```bash
spark profile list
```

Lists all profiles. The active profile is marked with `*`.

```
  default
* work
  dev
  personal
```

### `spark profile use`

```bash
spark profile use <name>
```

Sets the sticky default. Use `default` to return to the base profile.

### `spark profile create`

```bash
spark profile create <name> [options]
```

| Option | What it does |
|--------|-------------|
| `--clone` | Copy `config.yaml`, `.env`, and `SOUL.md` from the current profile |
| `--clone-all` | Copy everything from the current profile |
| `--clone-from <profile>` | Clone from a specific profile instead of the current one |
| `--no-alias` | Skip wrapper script creation |

### `spark profile delete`

```bash
spark profile delete <name> [--yes]
```

Stops the gateway, removes the service, removes the command alias, and deletes all profile data. You'll be asked to type the profile name to confirm. Use `--yes` to skip.

:::warning
Permanently deletes the profile's entire directory including all config, memories, sessions, and skills. Cannot delete the currently active profile.
:::

:::note
You cannot delete the default profile (`~/.spark`). To remove everything, use `spark uninstall`.
:::

### `spark profile show`

```bash
spark profile show <name>
```

Shows path, model, gateway status, skills count, and file status.

```
Profile: work
Path:    ~/.spark/profiles/work
Model:   anthropic/claude-sonnet-4 (anthropic)
Gateway: stopped
Skills:  12
.env:    exists
SOUL.md: exists
Alias:   ~/.local/bin/work
```

### `spark profile alias`

```bash
spark profile alias <name> [options]
```

Regenerates the wrapper script at `~/.local/bin/<name>`. Useful if the alias was deleted or if you've moved your Spark installation.

| Option | What it does |
|--------|-------------|
| `--remove` | Remove the wrapper script instead of creating it |
| `--name <alias>` | Use a custom alias name |

```bash
spark profile alias work               # Create/update ~/.local/bin/work
spark profile alias work --name mywork # Create ~/.local/bin/mywork
spark profile alias work --remove      # Remove the wrapper script
```

### `spark profile rename`

```bash
spark profile rename <old-name> <new-name>
```

Updates the directory and shell alias atomically.

```bash
spark profile rename mybot assistant
# ~/.spark/profiles/mybot -> ~/.spark/profiles/assistant
# ~/.local/bin/mybot -> ~/.local/bin/assistant
```

### `spark profile export` / `import`

```bash
spark profile export <name> [-o <path>]
spark profile import <archive> [--name <name>]
```

```bash
spark profile export work                                  # Creates work.tar.gz
spark profile export work -o ./work-2026-03-29.tar.gz
spark profile import ./work-2026-03-29.tar.gz
spark profile import ./work-2026-03-29.tar.gz --name work-restored
```

---

## Shell tab completion

```bash
# Bash
eval "$(spark completion bash)"

# Zsh
eval "$(spark completion zsh)"
```

Add to your `~/.bashrc` or `~/.zshrc` for persistent completion. After installation:

- `spark profile <TAB>` — completes subcommands
- `spark profile use <TAB>` — completes profile names
- `spark -p <TAB>` — completes profile names

---

## Under the hood

Profiles use the `SPARK_HOME` environment variable. Running `coder chat` sets `SPARK_HOME=~/.spark/profiles/coder` before launching Spark. Every path in the codebase resolves via `get_spark_home()`, so config, sessions, memory, skills, state database, gateway PID, logs, and cron jobs all automatically scope to the right directory.

---

## See also

- [CLI commands](./commands-reference.md)
- [FAQ — profiles](../reference/faq.md#profiles)
