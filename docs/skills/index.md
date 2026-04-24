---
sidebar_position: 2
title: "Skills System"
description: "On-demand knowledge documents - progressive disclosure, agent-managed skills, and the Skills Hub"
---

# Skills System

Skills are on-demand knowledge documents the agent loads when it needs them. They follow a **progressive disclosure** pattern — only pulling in full content when relevant — which keeps token usage low. Skills conform to the [agentskills.io](https://agentskills.io/specification) open standard.

All skills live in **`~/.spark/skills/`**. This is the single source of truth. Bundled skills are copied here on fresh install. Hub-installed and agent-created skills land here too. The agent can modify or delete any skill.

You can also point Spark at **external skill directories** — additional folders scanned alongside the local one. See [External Skill Directories](#external-skill-directories) below.

See also:

- [Bundled Skills Catalog](/docs/skills/catalog)
- [Official Optional Skills Catalog](/docs/skills/optional-catalog)

---

## Invoke a Skill

Every installed skill becomes a slash command. Use it directly from the CLI or any connected messaging platform:

```bash
/gif-search funny cats
/axolotl help me fine-tune Llama 3 on my dataset
/github-pr-workflow create a PR for the auth refactor
/plan design a rollout for migrating our auth provider

# Load the skill and let the agent ask what you need:
/excalidraw
```

The bundled `plan` skill is a good example of custom behavior: running `/plan [request]` tells Spark to inspect context, write a markdown plan to `.spark/plans/` in the active workspace, and stop — it doesn't execute the work.

You can also reach skills through natural conversation:

```bash
spark chat --toolsets skills -q "What skills do you have?"
spark chat --toolsets skills -q "Show me the axolotl skill"
```

---

## How Progressive Disclosure Works

The agent loads skill content in three levels, only going deeper when needed:

```
Level 0: skills_list()           -> [{name, description, category}, ...]   (~3k tokens)
Level 1: skill_view(name)        -> Full content + metadata       (varies)
Level 2: skill_view(name, path)  -> Specific reference file       (varies)
```

The full skill content only loads when the agent actually needs it.

---

## SKILL.md Format

```markdown
---
name: my-skill
description: Brief description of what this skill does
version: 1.0.0
platforms: [macos, linux]     # Optional - restrict to specific OS platforms
metadata:
  spark:
    tags: [python, automation]
    category: devops
    fallback_for_toolsets: [web]    # Optional - conditional activation (see below)
    requires_toolsets: [terminal]   # Optional - conditional activation (see below)
    config:                          # Optional - config.yaml settings
      - key: my.setting
        description: "What this controls"
        default: "value"
        prompt: "Prompt for setup"
---

# Skill Title

## When to Use
Trigger conditions for this skill.

## Procedure
1. Step one
2. Step two

## Pitfalls
- Known failure modes and fixes

## Verification
How to confirm it worked.
```

### Platform-Specific Skills

Restrict a skill to certain operating systems with the `platforms` field:

| Value | Matches |
|-------|---------|
| `macos` | macOS (Darwin) |
| `linux` | Linux |
| `windows` | Windows |

```yaml
platforms: [macos]            # macOS only (e.g., iMessage, Apple Reminders, FindMy)
platforms: [macos, linux]     # macOS and Linux
```

When set, the skill is automatically hidden from the system prompt, `skills_list()`, and slash commands on incompatible platforms. Omit the field to load on all platforms.

### Conditional Activation (Fallback Skills)

Skills can show or hide themselves based on which tools are available in the current session. This is most useful for **fallback skills** — free or local alternatives that appear only when a premium tool is unavailable.

```yaml
metadata:
  spark:
    fallback_for_toolsets: [web]      # Show ONLY when these toolsets are unavailable
    requires_toolsets: [terminal]     # Show ONLY when these toolsets are available
    fallback_for_tools: [web_search]  # Show ONLY when these specific tools are unavailable
    requires_tools: [terminal]        # Show ONLY when these specific tools are available
```

| Field | Behavior |
|-------|----------|
| `fallback_for_toolsets` | Skill is **hidden** when the listed toolsets are available. Shown when they're missing. |
| `fallback_for_tools` | Same, but checks individual tools instead of toolsets. |
| `requires_toolsets` | Skill is **hidden** when the listed toolsets are unavailable. Shown when they're present. |
| `requires_tools` | Same, but checks individual tools. |

**Example:** The built-in `duckduckgo-search` skill uses `fallback_for_toolsets: [web]`. When you have `FIRECRAWL_API_KEY` set, the web toolset is active and `web_search` is used — the DuckDuckGo skill stays hidden. Remove the API key and DuckDuckGo automatically appears as the fallback.

Skills without any conditional fields always show up.

---

## Secure Setup on Load

Skills can declare required environment variables without disappearing from discovery:

```yaml
required_environment_variables:
  - name: TENOR_API_KEY
    prompt: Tenor API key
    help: Get a key from https://developers.google.com/tenor
    required_for: full functionality
```

When a missing value is encountered, Spark asks for it securely — but only in the local CLI when the skill is actually loaded. You can skip setup and keep using the skill. Messaging surfaces never ask for secrets in chat; they tell you to use `spark setup` or `~/.spark/.env` locally instead.

Once set, declared env vars are **automatically passed through** to `execute_code` and `terminal` sandboxes — the skill's scripts can use `$TENOR_API_KEY` directly. For non-skill env vars, use the `terminal.env_passthrough` config option. See [Environment Variable Passthrough](/docs/configuration#environment-variable-passthrough) for details.

### Skill Config Settings

Skills can also declare non-secret config settings (paths, preferences) stored in `config.yaml`:

```yaml
metadata:
  spark:
    config:
      - key: wiki.path
        description: Path to the wiki directory
        default: "~/wiki"
        prompt: Wiki directory path
```

Settings are stored under `skills.config` in your `config.yaml`. `spark config migrate` prompts for unconfigured settings; `spark config show` displays them. When a skill loads, its resolved config values are injected automatically into the context.

See [Skill Settings](/docs/configuration#skill-settings) and [Creating Skills - Config Settings](/docs/building/creating-skills#config-settings-configyaml) for details.

---

## Skill Directory Structure

```text
~/.spark/skills/                  # Single source of truth
 mlops/                         # Category directory
    axolotl/
       SKILL.md               # Main instructions (required)
       references/            # Additional docs
       templates/             # Output formats
       scripts/               # Helper scripts callable from the skill
       assets/                # Supplementary files
    vllm/
        SKILL.md
 devops/
    deploy-k8s/                # Agent-created skill
        SKILL.md
        references/
 .hub/                          # Skills Hub state
    lock.json
    quarantine/
    audit.log
 .bundled_manifest              # Tracks seeded bundled skills
```

---

## External Skill Directories

If you maintain skills outside of Spark — for example, a shared `~/.agents/skills/` used by multiple AI tools — you can tell Spark to scan those directories too.

Add `external_dirs` under the `skills` section in `~/.spark/config.yaml`:

```yaml
skills:
  external_dirs:
    - ~/.agents/skills
    - /home/shared/team-skills
    - ${SKILLS_REPO}/skills
```

Paths support `~` expansion and `${VAR}` environment variable substitution.

### How it works

- **Read-only**: External dirs are only scanned for discovery. When the agent creates or edits a skill, it always writes to `~/.spark/skills/`.
- **Local precedence**: If the same skill name exists locally and in an external dir, the local version wins.
- **Full integration**: External skills appear in the system prompt index, `skills_list`, `skill_view`, and as `/skill-name` slash commands — no different from local skills.
- **Non-existent paths are silently skipped**: Missing directories produce no errors. Useful for optional shared directories that may not exist on every machine.

### Example

```text
~/.spark/skills/               # Local (primary, read-write)
 devops/deploy-k8s/
    SKILL.md
 mlops/axolotl/
     SKILL.md

~/.agents/skills/               # External (read-only, shared)
 my-custom-workflow/
    SKILL.md
 team-conventions/
     SKILL.md
```

All four skills appear in your skill index. Creating a local skill called `my-custom-workflow` shadows the external version.

---

## Agent-Managed Skills (skill_manage tool)

The agent can create, update, and delete its own skills via the `skill_manage` tool. This is the agent's **procedural memory** — when it figures out a non-trivial workflow, it saves the approach for future reuse.

### When the Agent Creates Skills

- After completing a complex task (5+ tool calls) successfully
- When it hit errors or dead ends and found the working path
- When you corrected its approach
- When it discovered a non-trivial workflow

### Actions

| Action | Use for | Key params |
|--------|---------|------------|
| `create` | New skill from scratch | `name`, `content` (full SKILL.md), optional `category` |
| `patch` | Targeted fixes (preferred) | `name`, `old_string`, `new_string` |
| `edit` | Major structural rewrites | `name`, `content` (full SKILL.md replacement) |
| `delete` | Remove a skill entirely | `name` |
| `write_file` | Add/update supporting files | `name`, `file_path`, `file_content` |
| `remove_file` | Remove a supporting file | `name`, `file_path` |

:::tip
Prefer `patch` for updates — it's more token-efficient than `edit` because only the changed text appears in the tool call.
:::

---

## Skills Hub

Browse, search, install, and manage skills from online registries, `skills.sh`, direct well-known skill endpoints, and official optional skills.

### Common commands

```bash
spark skills browse                              # Browse all hub skills (official first)
spark skills browse --source official            # Browse only official optional skills
spark skills search kubernetes                   # Search all sources
spark skills search react --source skills-sh     # Search the skills.sh directory
spark skills search https://mintlify.com/docs --source well-known
spark skills inspect openai/skills/k8s           # Preview before installing
spark skills install openai/skills/k8s           # Install with security scan
spark skills install official/security/1password
spark skills install skills-sh/vercel-labs/json-render/json-render-react --force
spark skills install well-known:https://mintlify.com/docs/.well-known/skills/mintlify
spark skills list --source hub                   # List hub-installed skills
spark skills check                               # Check installed hub skills for upstream updates
spark skills update                              # Reinstall hub skills with upstream changes when needed
spark skills audit                               # Re-scan all hub skills for security
spark skills uninstall k8s                       # Remove a hub skill
spark skills publish skills/my-skill --to github --repo owner/repo
spark skills snapshot export setup.json          # Export skill config
spark skills tap add myorg/skills-repo           # Add a custom GitHub source
```

### Supported hub sources

| Source | Example | Notes |
|--------|---------|-------|
| `official` | `official/security/1password` | Optional skills shipped with Spark. |
| `skills-sh` | `skills-sh/vercel-labs/agent-skills/vercel-react-best-practices` | Searchable via `spark skills search <query> --source skills-sh`. Spark resolves alias-style skills when the skills.sh slug differs from the repo folder. |
| `well-known` | `well-known:https://mintlify.com/docs/.well-known/skills/mintlify` | Skills served directly from `/.well-known/skills/index.json` on a website. Search using the site or docs URL. |
| `github` | `openai/skills/k8s` | Direct GitHub repo/path installs and custom taps. |
| `clawhub`, `lobehub`, `claude-marketplace` | Source-specific identifiers | Community or marketplace integrations. |

### Integrated hubs and registries

Spark integrates with these skills ecosystems and discovery sources:

#### 1. Official optional skills (`official`)

Maintained in the Spark repository itself and installed with builtin trust.

- Catalog: [Official Optional Skills Catalog](../../skills/optional-catalog)
- Source in repo: `optional-skills/`
- Example:

```bash
spark skills browse --source official
spark skills install official/security/1password
```

#### 2. skills.sh (`skills-sh`)

Vercel's public skills directory. Spark can search it directly, inspect skill detail pages, resolve alias-style slugs, and install from the underlying source repo.

- Directory: [skills.sh](https://skills.sh/)
- CLI/tooling repo: [vercel-labs/skills](https://github.com/vercel-labs/skills)
- Official Vercel skills repo: [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills)
- Example:

```bash
spark skills search react --source skills-sh
spark skills inspect skills-sh/vercel-labs/json-render/json-render-react
spark skills install skills-sh/vercel-labs/json-render/json-render-react --force
```

#### 3. Well-known skill endpoints (`well-known`)

URL-based discovery from sites that publish `/.well-known/skills/index.json`. Not a centralized hub — a web discovery convention.

- Example live endpoint: [Mintlify docs skills index](https://mintlify.com/docs/.well-known/skills/index.json)
- Reference server implementation: [vercel-labs/skills-handler](https://github.com/vercel-labs/skills-handler)
- Example:

```bash
spark skills search https://mintlify.com/docs --source well-known
spark skills inspect well-known:https://mintlify.com/docs/.well-known/skills/mintlify
spark skills install well-known:https://mintlify.com/docs/.well-known/skills/mintlify
```

#### 4. Direct GitHub skills (`github`)

Install directly from GitHub repositories or GitHub-based taps.

Default taps (browsable without any setup):
- [openai/skills](https://github.com/openai/skills)
- [anthropics/skills](https://github.com/anthropics/skills)
- [VoltAgent/awesome-agent-skills](https://github.com/VoltAgent/awesome-agent-skills)
- [garrytan/gstack](https://github.com/garrytan/gstack)

- Example:

```bash
spark skills install openai/skills/k8s
spark skills tap add myorg/skills-repo
```

#### 5. ClawHub (`clawhub`)

A third-party skills marketplace integrated as a community source.

- Site: [clawhub.ai](https://clawhub.ai/)
- Spark source id: `clawhub`

#### 6. Claude marketplace-style repos (`claude-marketplace`)

Spark supports marketplace repos that publish Claude-compatible plugin/marketplace manifests.

Known integrated sources include:
- [anthropics/skills](https://github.com/anthropics/skills)
- [aiskillstore/marketplace](https://github.com/aiskillstore/marketplace)

Spark source id: `claude-marketplace`

#### 7. LobeHub (`lobehub`)

Search and convert agent entries from LobeHub's public catalog into installable Spark skills.

- Site: [LobeHub](https://lobehub.com/)
- Public agents index: [chat-agents.lobehub.com](https://chat-agents.lobehub.com/)
- Backing repo: [lobehub/lobe-chat-agents](https://github.com/lobehub/lobe-chat-agents)
- Spark source id: `lobehub`

### Security scanning and `--force`

All hub-installed skills go through a **security scanner** that checks for data exfiltration, prompt injection, destructive commands, supply-chain signals, and other threats.

`spark skills inspect ...` surfaces upstream metadata when available:
- repo URL
- skills.sh detail page URL
- install command
- weekly installs
- upstream security audit statuses
- well-known index/endpoint URLs

Use `--force` when you've reviewed a third-party skill and want to override a non-dangerous policy block:

```bash
spark skills install skills-sh/anthropics/skills/pdf --force
```

Important behavior:
- `--force` can override policy blocks for caution/warn-style findings.
- `--force` does **not** override a `dangerous` scan verdict.
- Official optional skills (`official/...`) are treated as builtin trust and skip the third-party warning panel.

### Trust levels

| Level | Source | Policy |
|-------|--------|--------|
| `builtin` | Ships with Spark | Always trusted |
| `official` | `optional-skills/` in the repo | Builtin trust, no third-party warning |
| `trusted` | Trusted registries/repos such as `openai/skills`, `anthropics/skills` | More permissive policy than community sources |
| `community` | Everything else (`skills.sh`, well-known endpoints, custom GitHub repos, most marketplaces) | Non-dangerous findings can be overridden with `--force`; `dangerous` verdicts stay blocked |

### Update lifecycle

The hub tracks provenance to re-check upstream copies of installed skills:

```bash
spark skills check          # Report which installed hub skills changed upstream
spark skills update         # Reinstall only the skills with updates available
spark skills update react   # Update one specific installed hub skill
```

This uses the stored source identifier plus the current upstream bundle content hash to detect drift.

:::tip GitHub rate limits
Skills hub operations use the GitHub API, which has a rate limit of 60 requests/hour for unauthenticated users. If you see rate-limit errors during install or search, set `GITHUB_TOKEN` in your `.env` file to increase the limit to 5,000 requests/hour. The error message includes an actionable hint when this happens.
:::

### Slash commands (inside chat)

All the same commands work with `/skills`:

```text
/skills browse
/skills search react --source skills-sh
/skills search https://mintlify.com/docs --source well-known
/skills inspect skills-sh/vercel-labs/json-render/json-render-react
/skills install openai/skills/skill-creator --force
/skills check
/skills update
/skills list
```

Official optional skills still use identifiers like `official/security/1password` and `official/migration/openclaw-migration`.
