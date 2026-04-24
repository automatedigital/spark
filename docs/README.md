# Docs Navigation Guide

Use this file to orient yourself quickly. Every section of the docs has a job — here's what lives where and when you'd reach for it.

## Starting points

| You are... | Start here |
|---|---|
| New to Spark | `docs/getting-started/installation.md` → `docs/getting-started/quickstart.md` |
| Looking for something specific | `docs/getting-started/learning-path.md` — paths by goal |
| On an older version | `docs/getting-started/updating.md` |

## By task

### Using the CLI

- `docs/cli/` — Full TUI reference: keybindings, session management, background tasks, tool progress display
- `docs/cli/slash-commands.md` — Every `/command` for both the CLI and messaging platforms
- `docs/cli/profiles.md` — Multiple isolated agents on the same machine
- `docs/cli/skins.md` — Visual themes: colors, spinners, branding

### Looking up commands or config

- `docs/cli/commands-reference.md` — Every `spark <command>` with flags and examples
- `docs/configuration.md` — All runtime config keys
- `docs/reference/environment-variables.md` — Supported env vars
- `docs/reference/tools-reference.md` — What each built-in tool does
- `docs/reference/toolsets-reference.md` — How toolsets work and how to compose them

### Connecting to platforms or APIs

- `docs/chat-platforms/` — Slack, Discord, Telegram, WhatsApp, and more
- `docs/integrations/` — ACP editor extension, API server, web dashboard, provider integrations
- `docs/providers/` — Request routing, fallback behavior, credential pool management

### Building and extending

- `docs/building/` — Architecture, agent loop, tools runtime, prompt assembly
- `docs/tools/` — Per-tool docs
- `docs/automate/` — Batch jobs, cron scheduling, plugin automation
- `docs/memory/` — Memory providers and Honcho integration

### Other capabilities

- `docs/voice/` — Voice mode setup and TTS options
- `docs/sessions.md` / `docs/checkpoints.md` — Session lifecycle and state saving
- `docs/guides/` — Step-by-step how-to guides (deploy, MCP, reduce costs, voice, etc.)

## Less common sections

| Section | Purpose |
|---|---|
| `docs/specs/` | Design and specification documents |
| `docs/plans/` | Active and archived planning docs |
| `docs/migration/` | Notes for migrating from older versions |
| `docs/skills/` | Skill catalogs and optional skill listings |

## Quick orientation rules

- **New here?** Start in `docs/getting-started/` — installation, quickstart, then pick a learning path.
- **Need exact flags or behavior?** `docs/reference/` and `docs/cli/commands-reference.md`.
- **Hacking on Spark's internals?** Start with `docs/building/architecture.md`, then dive into `docs/tools/`.
- **Setting up a chat bot?** Use `docs/chat-platforms/` and `docs/integrations/` together.
