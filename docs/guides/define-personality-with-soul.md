---
sidebar_position: 7
title: "Use SOUL.md with Spark"
description: "How to use SOUL.md to shape Spark Agent's default voice, what belongs there, and how it differs from AGENTS.md and /personality"
---

# Use SOUL.md with Spark

`SOUL.md` is how you make Spark sound like yours. It sits at slot #1 in the system prompt — before anything else — and defines who the agent is, how it speaks, and what it avoids.

Edit this file and Spark feels different every session, automatically.

## What Goes in SOUL.md

Use it for identity and voice:

- Tone and personality
- Communication style
- How direct or warm the agent should be
- What to avoid stylistically
- How to handle uncertainty, disagreement, and ambiguity

**Simple rule:** if it should apply everywhere, it belongs in `SOUL.md`.

## What Doesn't Go in SOUL.md

Don't use it for project-specific details:

- Coding conventions or file paths
- Commands, ports, or service addresses
- Architecture notes or workflow instructions

Those belong in `AGENTS.md`. If the instruction only makes sense for one project, it goes there.

## Where the File Lives

```text
~/.spark/SOUL.md
```

With a custom Spark home:

```text
$SPARK_HOME/SOUL.md
```

## First-Run Behavior

Spark seeds a starter `SOUL.md` automatically if one doesn't exist. Open it, read it, and start editing.

Two things to know:
- If you already have a `SOUL.md`, Spark never overwrites it
- If the file exists but is empty, nothing gets added to the prompt

## How Spark Uses It

At session start, Spark reads `SOUL.md`, scans it for prompt-injection patterns, truncates if needed, and uses it as the agent identity. It **completely replaces** the built-in default identity text — no wrapper language, no prefix. What you write is what the agent gets.

If the file is missing or empty, Spark falls back to a built-in default.

## A Good First Edit

You don't need to rewrite the whole file. Change just a few lines so it sounds like you:

```markdown
You are direct, calm, and technically precise.
Prefer substance over politeness theater.
Push back clearly when an idea is weak.
Keep answers compact unless deeper detail is useful.
```

That alone noticeably shifts how Spark feels.

## Example Styles

### Pragmatic Engineer

```markdown
You are a pragmatic senior engineer.
You care more about correctness and operational reality than sounding impressive.

## Style
- Be direct
- Be concise unless complexity requires depth
- Say when something is a bad idea
- Prefer practical tradeoffs over idealized abstractions

## Avoid
- Sycophancy
- Hype language
- Overexplaining obvious things
```

### Research Partner

```markdown
You are a thoughtful research collaborator.
You are curious, honest about uncertainty, and excited by unusual ideas.

## Style
- Explore possibilities without pretending certainty
- Distinguish speculation from evidence
- Ask clarifying questions when the idea space is underspecified
- Prefer conceptual depth over shallow completeness
```

### Teacher / Explainer

```markdown
You are a patient technical teacher.
You care about understanding, not performance.

## Style
- Explain clearly
- Use examples when they help
- Do not assume prior knowledge unless the user signals it
- Build from intuition to details
```

### Tough Reviewer

```markdown
You are a rigorous reviewer.
You are fair, but you do not soften important criticism.

## Style
- Point out weak assumptions directly
- Prioritize correctness over harmony
- Be explicit about risks and tradeoffs
- Prefer blunt clarity to vague diplomacy
```

## What Makes a Strong SOUL.md

**Strong:**
- Stable and broadly applicable
- Specific in voice and tone
- Concise — not a dump of every instruction you've ever thought of

**Weak:**
- Full of project-specific details that belong in `AGENTS.md`
- Contradictory instructions
- Micro-managing every response shape
- Generic filler like "be helpful" and "be clear" (Spark already tries to be those things)

## Suggested Structure

Headings aren't required, but they help keep things organized:

```markdown
# Identity
Who Spark is.

# Style
How Spark should sound.

# Avoid
What Spark should not do.

# Defaults
How Spark should behave when ambiguity appears.
```

## SOUL.md vs /personality

These work together, not against each other.

- `SOUL.md` = your durable baseline voice
- `/personality` = a temporary mode switch for one session

Example: your default SOUL is pragmatic and direct. You switch to `/personality teacher` for a session, then come back to your base voice without touching the file.

## SOUL.md vs AGENTS.md

This is the most common mistake. Quick reference:

| SOUL.md | AGENTS.md |
|---------|-----------|
| "Be direct." | "Use pytest, not unittest." |
| "Avoid hype language." | "Frontend lives in `frontend/`." |
| "Prefer short answers unless depth helps." | "Never edit migrations directly." |
| "Push back when the user is wrong." | "The API runs on port 8000." |

## How to Edit It

```bash
nano ~/.spark/SOUL.md
```

or

```bash
vim ~/.spark/SOUL.md
```

Then restart Spark or start a new session.

## A Practical Workflow

1. Start with the seeded default file
2. Trim anything that doesn't sound like the voice you want
3. Add 4–8 lines that clearly define tone and defaults
4. Talk to Spark for a while
5. Adjust based on what still feels off

Iteration beats trying to design the perfect personality in one sitting.

## Troubleshooting

### I edited SOUL.md but Spark still sounds the same

Check:
- You edited `~/.spark/SOUL.md` or `$SPARK_HOME/SOUL.md` — not some repo-local copy
- The file isn't empty
- You restarted the session after editing
- A `/personality` overlay isn't dominating the result

### Spark is ignoring parts of my SOUL.md

Possible causes:
- Higher-priority instructions are overriding it
- The file contains conflicting guidance
- The file is too long and got truncated
- Some text resembles prompt-injection content and got blocked by the scanner

### My SOUL.md became too project-specific

Move project instructions into `AGENTS.md` and keep `SOUL.md` focused on identity and style.

## Related Docs

- [Personality & SOUL.md](/docs/personality)
- [Context Files](/docs/tools/context-files)
- [Configuration](/docs/configuration)
- [Tips & Best Practices](/docs/guides/tips-and-tricks)
