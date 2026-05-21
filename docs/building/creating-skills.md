---
sidebar_position: 3
title: "Creating Skills"
description: "How to create skills for Spark Agent - SKILL.md format, guidelines, and publishing"
---

# Creating Skills

Skills are the fastest way to add new capabilities to Spark. No Python, no code changes, no deploys — just a Markdown file that teaches the agent how to do something new.

## Skill or Tool — Which Do You Need?

| A **Skill** is the right call when... | A **Tool** is the right call when... |
|---------------------------------------|---------------------------------------|
| Instructions + shell commands + existing tools are enough | Custom Python integration is required |
| You're wrapping a CLI or API via `terminal` or `web_extract` | Auth flows or multi-component config must be baked in |
| You don't need API key management inside the agent | Binary data, streaming, or real-time events are involved |
| arXiv search, git workflows, Docker, PDF processing, email via CLI | Browser automation, TTS, vision analysis |

## Where Skills Live

```text
skills/
└── research/
    └── arxiv/
        ├── SKILL.md              # Required — the agent's instructions
        └── scripts/              # Optional — helper scripts
            └── search_arxiv.py
optional-skills/
└── productivity/
    └── ocr-and-documents/
        ├── SKILL.md
        └── scripts/
```

`skills/` ships with every Spark install. `optional-skills/` ships with the repo but isn't loaded by default — discoverable and installable via `spark skills browse`.

## SKILL.md Structure

```markdown
---
name: my-skill
description: Brief description (shown in skill search results)
version: 1.0.0
author: Your Name
license: MIT
platforms: [macos, linux]          # Optional - omit to load on all platforms
metadata:
  spark:
    tags: [Category, Subcategory, Keywords]
    related_skills: [other-skill-name]
    requires_toolsets: [web]            # Optional
    requires_tools: [web_search]        # Optional
    fallback_for_toolsets: [browser]    # Optional
    fallback_for_tools: [browser_navigate]  # Optional
    config:                              # Optional config.yaml settings
      - key: my.setting
        description: "What this setting controls"
        default: "sensible-default"
        prompt: "Display prompt for setup"
required_environment_variables:          # Optional secrets
  - name: MY_API_KEY
    prompt: "Enter your API key"
    help: "Get one at https://example.com"
    required_for: "API access"
---

# Skill Title

Brief intro.

## When to Use
Trigger conditions — when should the agent apply this skill?

## Quick Reference
Table of common commands or API calls.

## Procedure
Step-by-step instructions the agent follows.

## Pitfalls
Known failure modes and how to handle them.

## Verification
How the agent confirms it worked.
```

## Limiting to Specific Platforms

Use the `platforms` field to prevent a skill from loading on incompatible systems:

```yaml
platforms: [macos]            # macOS only (e.g., iMessage, Apple Reminders)
platforms: [macos, linux]     # macOS and Linux
platforms: [windows]          # Windows only
```

When set, the skill is automatically hidden from the system prompt, `skills_list()`, and slash commands on incompatible platforms. Omit entirely for all platforms (the default).

## Conditional Activation

Skills can show or hide themselves based on which tools and toolsets are active in the current session:

```yaml
metadata:
  spark:
    requires_toolsets: [web]           # Hide if web toolset is NOT active
    requires_tools: [web_search]       # Hide if web_search is NOT available
    fallback_for_toolsets: [browser]   # Hide if browser toolset IS active
    fallback_for_tools: [browser_navigate]  # Hide if browser_navigate IS available
```

| Field | Effect |
|-------|--------|
| `requires_toolsets` | Skill hidden when ANY listed toolset is **not** available |
| `requires_tools` | Skill hidden when ANY listed tool is **not** available |
| `fallback_for_toolsets` | Skill hidden when ANY listed toolset **is** available |
| `fallback_for_tools` | Skill hidden when ANY listed tool **is** available |

**`fallback_for_*` pattern:** Create a workaround skill that only shows when a primary tool isn't configured. Example: a `duckduckgo-search` skill with `fallback_for_tools: [web_search]` only appears when the API-key-backed web search tool is absent.

**`requires_*` pattern:** Create a skill that only makes sense alongside specific tools. Example: a web scraping workflow with `requires_toolsets: [web]` won't pollute the prompt when web tools are off.

## API Keys and Secrets

Declare secrets your skill needs with `required_environment_variables`. Missing values don't hide the skill — instead, Spark prompts for them securely when the skill loads in the local CLI:

```yaml
required_environment_variables:
  - name: TENOR_API_KEY
    prompt: Tenor API key
    help: Get a key from https://developers.google.com/tenor
    required_for: full functionality
```

Each entry supports: `name` (required), `prompt`, `help`, `required_for` (all optional).

Spark never exposes the raw secret to the model. In gateway and messaging sessions, Spark shows local setup guidance instead of collecting secrets in-band.

:::tip Sandbox passthrough is automatic
When your skill loads, all declared `required_environment_variables` that are set are automatically passed through to `execute_code` and `terminal` sandboxes — including remote backends like Docker and Modal. Your scripts can access `$TENOR_API_KEY` or `os.environ["TENOR_API_KEY"]` without extra configuration. See [Environment Variable Passthrough](../configuration.md#environment-variable-passthrough) for details.
:::

Users can also manually configure passthrough variables:

```yaml
terminal:
  env_passthrough:
    - MY_CUSTOM_VAR
```

Legacy `prerequisites.env_vars` still works as a backward-compatible alias.

## Non-Secret Config Settings

Skills can declare non-sensitive settings stored in `config.yaml` under `skills.config`:

```yaml
metadata:
  spark:
    config:
      - key: wiki.path
        description: Path to the LLM Wiki knowledge base directory
        default: "~/wiki"
        prompt: Wiki directory path
      - key: wiki.domain
        description: Domain the wiki covers
        default: ""
        prompt: Wiki domain (e.g., AI/ML research)
```

Each entry supports: `key` (required), `description` (required), `default` and `prompt` (optional).

Values end up in `config.yaml` as:

```yaml
skills:
  config:
    wiki:
      path: ~/my-research
```

`spark config migrate` scans all enabled skills, finds unconfigured settings, and prompts the user. When a skill loads, its config values are resolved and appended to the skill message so the agent sees them directly.

Set values manually anytime:

```bash
spark config set skills.config.wiki.path ~/my-wiki
```

:::tip Secrets vs. config
Use `required_environment_variables` for API keys and tokens — stored in `~/.spark/.env`, never shown to the model. Use `config` for paths, preferences, and non-sensitive settings — stored in `config.yaml`, visible in `config show`.
:::

## OAuth and File-Based Credentials

Skills that use OAuth or file-based credentials declare files that need to be mounted into remote sandboxes:

```yaml
required_credential_files:
  - path: google_token.json
    description: Google OAuth2 token (created by setup script)
  - path: google_client_secret.json
    description: Google OAuth2 client credentials
```

When loaded, Spark checks for these files. Missing files trigger `setup_needed`. Present files are:
- Mounted into Docker containers as read-only bind mounts
- Synced into Modal sandboxes (at creation and before each command, so mid-session OAuth works)
- Available on the local backend with no special handling

See `skills/productivity/google-workspace/SKILL.md` for a complete example using both.

## Writing Good Skills

**No external dependencies.** Prefer stdlib Python, `curl`, and existing Spark tools (`web_extract`, `terminal`, `read_file`). If a dependency is required, document the install steps inside the skill.

**Lead with the common case.** Put the most frequent workflow first. Edge cases go at the bottom. This keeps token usage low.

**Use helper scripts.** For XML/JSON parsing or complex multi-step logic, put scripts in `scripts/`. Don't make the LLM write parsers inline on every run.

**Test it.** Run the skill and verify the agent actually follows the instructions:

```bash
spark chat --toolsets skills -q "Use the X skill to do Y"
```

## Choosing Where Your Skill Lives

| Location | When to use it |
|----------|---------------|
| `skills/` | Broadly useful to most users — document handling, web research, common dev workflows |
| `optional-skills/` | Official but not universally needed — paid service integrations, heavy dependencies |
| Skills Hub | Specialized, community-contributed, or niche skills |

## Publishing

### To the Skills Hub

```bash
spark skills publish skills/my-skill --to github --repo owner/repo
```

### To a Custom Repository

```bash
spark skills tap add owner/repo
```

Users can then search and install from your repository.

## Security Scanning

All hub-installed skills go through a scanner that checks for data exfiltration patterns, prompt injection, destructive commands, and shell injection.

| Trust Level | Source | Behavior |
|-------------|--------|----------|
| `builtin` | Ships with Spark | Always trusted |
| `official` | `optional-skills/` in repo | Builtin trust, no third-party warning |
| `trusted` | `openai/skills`, `anthropics/skills` | Trusted |
| `community` | Everything else | Non-dangerous findings can be overridden with `--force`; `dangerous` verdicts stay blocked |

Skills can be discovered via:
- Direct GitHub identifiers (e.g., `openai/skills/k8s`)
- `skills.sh` identifiers (e.g., `skills-sh/vercel-labs/json-render/json-render-react`)
- Well-known endpoints served from `/.well-known/skills/index.json`

If you want your skills discoverable without a GitHub-specific installer, serve them from a well-known endpoint in addition to publishing them in a repo or marketplace.
