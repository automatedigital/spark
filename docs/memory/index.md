---
sidebar_position: 3
title: "Persistent Memory"
description: "How Spark Agent remembers across sessions - MEMORY.md, USER.md, and session search"
---

# Persistent Memory

Spark remembers things. Across sessions, across days, across projects. You don't have to re-explain your setup, your preferences, or what you've already done.

Here's how it works.

## Two Memory Stores

| File | Holds | Limit |
|------|-------|-------|
| **MEMORY.md** | Agent's working notes — environment facts, project conventions, lessons learned | 2,200 chars (~800 tokens) |
| **USER.md** | Your profile — preferences, communication style, expectations | 1,375 chars (~500 tokens) |

Both files live in `~/.spark/memories/`. At the start of every session, their contents are injected into the system prompt as a frozen snapshot. The agent reads them as part of its context and manages them via the `memory` tool.

## What Memory Looks Like in the Prompt

```
MEMORY (your personal notes) [67% - 1,474/2,200 chars]

User's project is a Rust web service at ~/code/myapi using Axum + SQLx

This machine runs Ubuntu 22.04, has Docker and Podman installed

User prefers concise responses, dislikes verbose explanations
```

The header shows capacity so the agent knows when to consolidate. Entries are separated by `§` delimiters and can span multiple lines.

**Why it's frozen:** The system prompt snapshot is taken once at session start and never changes mid-session. This preserves the LLM's prefix cache, which keeps costs down. Changes the agent makes during a session are saved to disk immediately — they just won't appear in the prompt until the next session. Tool responses always show the live state.

## The Memory Tool

The agent uses the `memory` tool to manage both stores. There's no `read` action — memory is already in context.

| Action | What it does |
|--------|-------------|
| `add` | Add a new entry |
| `replace` | Swap out an existing entry (uses substring matching via `old_text`) |
| `remove` | Delete an entry (uses substring matching via `old_text`) |

**Substring matching example:**

```python
# Memory contains: "User prefers dark mode in all editors"
memory(action="replace", target="memory",
       old_text="dark mode",
       content="User prefers light mode in VS Code, dark mode in terminal")
```

`old_text` just needs to uniquely identify one entry — you don't need the full text. If it matches multiple entries, the tool asks for something more specific.

## What Goes Where

### `memory` — Agent's Working Notes

Facts about the environment, projects, and workflows:

- OS, shell, installed tools, project structure
- Build commands, test patterns, code conventions
- Tool quirks and workarounds
- Completed tasks with dates
- Techniques that worked

### `user` — Your Profile

Facts about you:

- Name, role, timezone
- Communication preferences (concise vs. detailed, preferred formats)
- Things to avoid
- Workflow habits
- Technical background

## What Gets Saved vs. Skipped

The agent saves proactively. You don't need to ask.

**Save these:**

| Situation | Example | Target |
|-----------|---------|--------|
| User preference | "I prefer TypeScript over JavaScript" | `user` |
| Environment fact | "Server runs Debian 12 with PostgreSQL 16" | `memory` |
| Correction | "Don't use `sudo` for Docker, user is in docker group" | `memory` |
| Convention | "Project uses tabs, 120-char line width, Google-style docstrings" | `memory` |
| Completed work | "Migrated DB from MySQL to PostgreSQL on 2026-01-15" | `memory` |
| Explicit request | "Remember my API key rotation happens monthly" | `memory` |

**Skip these:**

- Vague statements: "User asked about Python"
- Re-discoverable facts: "Python 3.12 supports f-string nesting"
- Raw data dumps: large code blocks, log files, tables
- Session-specific ephemera: temp file paths, one-off debug context
- Content already in SOUL.md or AGENTS.md

## Managing Capacity

| Store | Limit | Typical entries |
|-------|-------|----------------|
| `memory` | 2,200 chars | 8–15 entries |
| `user` | 1,375 chars | 5–10 entries |

When an `add` would exceed the limit, the tool returns an error listing current entries. The agent should then consolidate — merge related entries, remove stale ones — and retry.

**Good entries are dense:**

```
# Good: multiple related facts, one entry
User runs macOS 14 Sonoma, uses Homebrew, has Docker Desktop and Podman. Shell: zsh + oh-my-zsh. Editor: VS Code with Vim keybindings.

# Good: specific, actionable
Project ~/code/api uses Go 1.22, sqlc for DB queries, chi router. Run tests with 'make test' before merging.

# Good: useful context with specifics
Staging server (10.0.1.50) needs SSH port 2222, not 22. Key is at ~/.ssh/staging_ed25519.

# Bad: too vague
User has a project.

# Bad: too verbose
On January 5th, 2026, the user asked me to look at their project which is located at...
```

When memory is above 80% capacity (shown in the prompt header), consolidate before adding.

## Built-in Protections

**Duplicate prevention** — the tool silently rejects exact duplicate entries.

**Security scanning** — entries are checked for prompt injection patterns, credential exfiltration attempts, invisible Unicode characters, and SSH backdoor patterns before being saved. Anything suspicious is rejected with an explanation.

## Search Past Conversations

Memory holds ~1,300 tokens of curated facts. For everything else, use session search.

```bash
spark sessions list    # browse past sessions
```

The `session_search` tool queries SQLite FTS5 across all stored sessions and summarizes relevant results with Gemini Flash.

| | Persistent Memory | Session Search |
|--|------------------|----------------|
| **Capacity** | ~1,300 tokens | All sessions (unlimited) |
| **Speed** | Instant — already in context | Requires search + LLM summarization |
| **Best for** | Facts that should always be available | "Did we discuss X last week?" |
| **Management** | Agent curates actively | Automatic — all sessions stored |
| **Token cost** | Fixed per session | On-demand only |

## Configure Memory

```yaml
# ~/.spark/config.yaml
memory:
  memory_enabled: true
  user_profile_enabled: true
  memory_char_limit: 2200   # ~800 tokens
  user_char_limit: 1375     # ~500 tokens
```

## Go Deeper with External Providers

Spark ships with 8 external memory provider plugins — Honcho, OpenViking, Mem0, Hindsight, Holographic, RetainDB, ByteRover, and Supermemory. They run **alongside** built-in memory and add capabilities like knowledge graphs, semantic search, automatic fact extraction, and cross-session user modeling.

```bash
spark memory setup      # pick a provider and configure it
spark memory status     # check what's active
```

See the [Memory Providers](./providers.md) guide for details on each one.
