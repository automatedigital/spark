---
sidebar_position: 12
title: "Working with Skills"
description: "Find, install, use, and create skills - on-demand knowledge that teaches Spark new workflows"
---

# Working with Skills

Skills are knowledge documents you drop into Spark to teach it new workflows — from generating ASCII art to managing GitHub pull requests. They only cost tokens when actually used, and they're as easy to build as writing a markdown file.

For the full technical reference, see [Skills System](../skills/index.md).

---

## What's already installed?

Check in chat or from the terminal:

```bash
/skills             # inside any chat session
spark skills list   # from the CLI
```

Output looks like this:

```
ascii-art         Generate ASCII art using pyfiglet, cowsay, boxes...
arxiv             Search and retrieve academic papers from arXiv...
github-pr-workflow Full PR lifecycle - create branches, commit...
plan              Plan mode - inspect context, write a markdown...
excalidraw        Create hand-drawn style diagrams using Excalidraw...
```

Search by keyword:

```bash
/skills search docker
/skills search music
```

Browse optional skills that aren't active by default:

```bash
/skills browse
/skills search blockchain
```

---

## Invoking a skill

Every installed skill becomes a slash command automatically:

```bash
/ascii-art Make a banner that says "HELLO WORLD"
/plan Design a REST API for a todo app
/github-pr-workflow Create a PR for the auth refactor

# Just the name — Spark loads it and waits for your task
/excalidraw
```

You can also ask naturally: "use the excalidraw skill to diagram this system." Spark will load it via `skill_view`.

### How loading actually works

Skills use a three-level loading pattern that keeps token costs down:

| Step | What happens | Token cost |
|---|---|---|
| `skills_list()` | Compact list of all skills (~3k tokens). Loaded at session start. | Low, once |
| `skill_view(name)` | Full SKILL.md for one skill. Loaded when needed. | Medium, on demand |
| `skill_view(name, file_path)` | A specific reference file within the skill. | Small, only if needed |

Skills that you never invoke in a session cost zero tokens.

---

## Installing from the Hub

Some official skills ship with Spark but stay inactive until you explicitly install them:

```bash
spark skills install official/research/arxiv
/skills install official/creative/songwriting-and-ai-music
```

After installation:
1. The skill directory copies to `~/.spark/skills/`
2. It shows up in `skills_list` output
3. It becomes a slash command

:::tip
Installed skills take effect in new sessions. Use `/reset` to start fresh, or `--now` to immediately invalidate the prompt cache (at the cost of extra tokens on the next turn).
:::

Verify it landed:

```bash
spark skills list | grep arxiv
/skills search arxiv
```

---

## Configuring a skill

Some skills need API keys or settings. They declare what they need in their frontmatter:

```yaml
metadata:
  spark:
    config:
      - key: tenor.api_key
        description: "Tenor API key for GIF search"
        prompt: "Enter your Tenor API key"
        url: "https://developers.google.com/tenor/guides/quickstart"
```

When a skill with config is first loaded, Spark prompts you for the values. They go into `config.yaml` under `skills.config.*`.

Manage skill config from the CLI:

```bash
spark skills config gif-search    # interactive config for one skill
spark config get skills.config    # view all skill config
```

---

## Build your own skill

Skills are markdown files with YAML frontmatter. You can write one in five minutes.

### 1. Create the directory

```bash
mkdir -p ~/.spark/skills/my-category/my-skill
```

### 2. Write SKILL.md

```markdown title="~/.spark/skills/my-category/my-skill/SKILL.md"
---
name: my-skill
description: Brief description of what this skill does
version: 1.0.0
metadata:
  spark:
    tags: [my-tag, automation]
    category: my-category
---

# My Skill

## When to Use
Use this skill when the user asks about [specific topic] or needs to [specific task].

## Procedure
1. First, check if [prerequisite] is available
2. Run `command --with-flags`
3. Parse the output and present results

## Pitfalls
- Common failure: [description]. Fix: [solution]
- Watch out for [edge case]

## Verification
Run `check-command` to confirm the result is correct.
```

### 3. Add reference files (optional)

Skills can bundle supporting files that the agent loads on demand:

```
my-skill/
 SKILL.md
 references/
    api-docs.md
    examples.md
 templates/
    config.yaml
 scripts/
     setup.sh
```

Reference them from your SKILL.md:

```markdown
For API details, load the reference: `skill_view("my-skill", "references/api-docs.md")`
```

### 4. Test it

```bash
spark chat -q "/my-skill help me with the thing"
```

No registration step. Drop a skill folder in `~/.spark/skills/` and it's live on the next session.

:::info
The agent can also create and update skills itself via `skill_manage`. After solving a complex problem, Spark may offer to save the approach as a skill for next time.
:::

---

## Control which skills show up where

```bash
spark skills
```

This opens an interactive TUI where you enable or disable skills per platform (CLI, Telegram, Discord, etc.). Useful for keeping development skills off your Telegram bot.

---

## Skills vs. Memory at a glance

| | Skills | Memory |
|---|---|---|
| **Stores** | Procedural knowledge — how to do things | Factual knowledge — what things are |
| **Loaded** | On demand, only when relevant | Injected into every session |
| **Size** | Can be large (hundreds of lines) | Should stay compact |
| **Token cost** | Zero until invoked | Small but constant |
| **Examples** | "How to deploy to Kubernetes" | "User prefers dark mode, lives in PST" |
| **Created by** | You, the agent, or Hub install | The agent, from conversations |

If you'd put it in a reference doc, it's a skill. If you'd put it on a sticky note, it's memory.

---

## Tips that actually matter

**Stay focused.** A skill about "all of DevOps" is useless. A skill about "deploy a Python app to Fly.io" is something Spark can actually act on.

**Say yes when the agent offers to save a skill.** Agent-authored skills capture the exact workflow — including the pitfalls discovered along the way. Those are the best skills you'll have.

**Use subdirectories.** Organize into `~/.spark/skills/devops/`, `~/.spark/skills/research/`, etc. It keeps the list readable and helps Spark find relevant skills faster.

**Update stale skills.** If a skill leads you into a known failure, tell Spark to update it. An unmaintained skill is worse than no skill.

---

*For the complete skills reference — frontmatter fields, conditional activation, external directories, and more — see [Skills System](../skills/index.md).*
