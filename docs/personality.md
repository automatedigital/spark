---
sidebar_position: 9
title: "Personality & SOUL.md"
description: "Customize Spark Agent's personality with a global SOUL.md, built-in personalities, and custom persona definitions"
---

# Personality & SOUL.md

Spark's personality comes from one file: `SOUL.md`. Edit it and you change how Spark talks to you — permanently, across every session.

There's also a `/personality` command for temporary session-level mode switches. But `SOUL.md` is the foundation everything else builds on.

## Where SOUL.md Lives

```bash
~/.spark/SOUL.md
```

If you're using a custom `SPARK_HOME`:

```bash
$SPARK_HOME/SOUL.md
```

Spark creates a starter file automatically if one doesn't exist yet. It will never overwrite a file you've already edited.

Spark only reads `SOUL.md` from `SPARK_HOME` — not from whatever directory you launched it in. That means your personality doesn't shift unexpectedly between projects.

## What Belongs in SOUL.md

Use `SOUL.md` for voice and character that should follow you everywhere:

- Tone (direct, warm, formal, blunt)
- Communication style (concise vs. thorough)
- How to handle uncertainty or disagreement
- What to avoid (sycophancy, over-explanation, hype)

Don't use it for project-specific instructions:

| Goes in SOUL.md | Goes in AGENTS.md |
|-----------------|-------------------|
| Tone and style | Coding conventions |
| Communication defaults | File paths and commands |
| How to handle uncertainty | Repo-specific workflows |
| Personality-level behavior | Tool preferences |

**The rule:** if it should travel with you everywhere, put it in `SOUL.md`. If it belongs to a specific project, put it in `AGENTS.md`.

## A Strong SOUL.md Example

```markdown
# Personality

You are a pragmatic senior engineer with strong taste.
You optimize for truth, clarity, and usefulness over politeness theater.

## Style
- Be direct without being cold
- Prefer substance over filler
- Push back when something is a bad idea
- Admit uncertainty plainly
- Keep explanations compact unless depth is useful

## What to avoid
- Sycophancy
- Hype language
- Repeating the user's framing if it's wrong
- Overexplaining obvious things

## Technical posture
- Prefer simple systems over clever systems
- Care about operational reality, not idealized architecture
- Treat edge cases as part of the design, not cleanup
```

A good `SOUL.md` is stable across contexts, specific enough to shape the voice, and focused on communication — not tasks.

## How Spark Uses SOUL.md

The content goes into slot #1 of the system prompt — the identity position — verbatim. No wrapper language is added.

Before injection, Spark:

1. Scans for prompt-injection patterns
2. Truncates if the file is too large

If the file is empty, whitespace-only, or unreadable, Spark falls back to a built-in default identity. The same fallback applies in subagent/delegation contexts where `skip_context_files` is set.

`SOUL.md` appears exactly once in the prompt. It's not duplicated in the context files section.

## The Full Prompt Stack

Here's where `SOUL.md` sits relative to everything else:

| Position | Content |
|----------|---------|
| **1** | **SOUL.md** (or built-in fallback) |
| 2 | Tool-aware behavior guidance |
| 3 | Memory and user context |
| 4 | Skills guidance |
| 5 | Context files (AGENTS.md, .cursorrules) |
| 6 | Timestamp |
| 7 | Platform-specific formatting hints |
| 8 | Session overlays (e.g. `/personality`) |

## Switching Modes with `/personality`

`SOUL.md` is your default. `/personality` is a session-level overlay for when you want a temporary shift:

```text
/personality
/personality concise
/personality teacher
```

Think of it as:
- `SOUL.md` = who Spark always is
- `/personality` = a mode you put it in for this conversation

Example: keep a pragmatic default SOUL, then switch to `/personality teacher` when working through a concept.

## Built-in Personalities

| Name | Description |
|------|-------------|
| **helpful** | Friendly, general-purpose assistant |
| **concise** | Brief, to-the-point responses |
| **technical** | Detailed, accurate technical expert |
| **creative** | Innovative, outside-the-box thinking |
| **teacher** | Patient educator with clear examples |
| **kawaii** | Cute expressions, sparkles, and enthusiasm |
| **catgirl** | Neko-chan with cat-like expressions, nya~ |
| **pirate** | Captain Spark, tech-savvy buccaneer |
| **shakespeare** | Bardic prose with dramatic flair |
| **surfer** | Totally chill bro vibes |
| **noir** | Hard-boiled detective narration |
| **uwu** | Maximum cute with uwu-speak |
| **philosopher** | Deep contemplation on every query |
| **hype** | MAXIMUM ENERGY AND ENTHUSIASM!!! |

## Define Your Own Personalities

Add named presets to `~/.spark/config.yaml`:

```yaml
agent:
  personalities:
    codereviewer: >
      You are a meticulous code reviewer. Identify bugs, security issues,
      performance concerns, and unclear design choices. Be precise and constructive.
```

Activate with:

```text
/personality codereviewer
```

Custom personalities work on all platforms — CLI, Telegram, Discord, Slack, WhatsApp.

## Personality vs. Appearance

These are two separate systems:

- `SOUL.md`, `agent.system_prompt`, and `/personality` — change how Spark speaks
- `display.skin` and `/skin` — change how Spark looks in the terminal

For terminal appearance, see [Skins & Themes](./cli/skins.md).

## Related Docs

- [Context Files](tools/context-files.md)
- [Configuration](configuration.md)
- [Tips & Best Practices](guides/tips-and-tricks.md)
- [SOUL.md Guide](guides/define-personality-with-soul.md)
