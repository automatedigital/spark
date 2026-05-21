---
sidebar_position: 8
title: "Context Files"
description: "Project context files - .spark.md, AGENTS.md, CLAUDE.md, global SOUL.md, and .cursorrules - automatically injected into every conversation"
---

# Context Files

Drop a file in your project and Spark reads it every turn. No setup required. These files let you encode your project's architecture, conventions, and rules so you never repeat yourself to the agent.

## Supported Files

| File | What It Does | Where Spark Looks |
|------|-------------|-------------------|
| **.spark.md** / **SPARK.md** | Project instructions — highest priority | Walks up to git root |
| **AGENTS.md** | Architecture, conventions, notes | CWD at startup + subdirectories progressively |
| **CLAUDE.md** | Claude Code context (also recognized by Spark) | CWD at startup + subdirectories progressively |
| **SOUL.md** | Global personality and tone for this Spark instance | `SPARK_HOME/SOUL.md` only |
| **.cursorrules** | Cursor IDE conventions | CWD only |
| **.cursor/rules/*.mdc** | Cursor rule modules | CWD only |

:::info Priority system
Only **one** project context type loads per session — first match wins: `.spark.md` → `AGENTS.md` → `CLAUDE.md` → `.cursorrules`. **SOUL.md** always loads independently as the agent identity.
:::

## AGENTS.md — Your Project's Readme for the Agent

This is the main file. Tell Spark how your project is organized, what conventions to follow, and what to avoid.

### Example

```markdown
# Project Context

This is a Next.js 14 web application with a Python FastAPI backend.

## Architecture
- Frontend: Next.js 14 with App Router in `/frontend`
- Backend: FastAPI in `/backend`, uses SQLAlchemy ORM
- Database: PostgreSQL 16
- Deployment: Docker Compose on a Hetzner VPS

## Conventions
- Use TypeScript strict mode for all frontend code
- Python code follows PEP 8, use type hints everywhere
- All API endpoints return JSON with `{data, error, meta}` shape
- Tests go in `__tests__/` directories (frontend) or `tests/` (backend)

## Important Notes
- Never modify migration files directly - use Alembic commands
- The `.env.local` file has real API keys, don't commit it
- Frontend port is 3000, backend is 8000, DB is 5432
```

### Progressive Subdirectory Discovery

Spark loads the root `AGENTS.md` into the system prompt at startup. As the agent navigates into subdirectories — via `read_file`, `terminal`, `search_files`, etc. — it discovers and loads context files from those directories at the moment they become relevant.

```
my-project/
  AGENTS.md              <- Loaded at startup (system prompt)
  frontend/
    AGENTS.md            <- Discovered when agent reads frontend/ files
  backend/
    AGENTS.md            <- Discovered when agent reads backend/ files
  shared/
    AGENTS.md            <- Discovered when agent reads shared/ files
```

Two advantages over loading everything upfront:
- **No system prompt bloat** — subdirectory hints only appear when needed
- **Stable prompt cache** — the system prompt doesn't change mid-conversation, so cached tokens are reused

Each subdirectory is visited at most once per session. Reading `backend/src/main.py` also discovers `backend/AGENTS.md` even if `backend/src/` has no context file.

:::info
Subdirectory context files go through the same [security scan](#security-prompt-injection-protection) as startup files.
:::

### Monorepo Setup

Put per-package instructions in nested AGENTS.md files:

```markdown
<!-- frontend/AGENTS.md -->
# Frontend Context

- Use `pnpm` not `npm` for package management
- Components go in `src/components/`, pages in `src/app/`
- Use Tailwind CSS, never inline styles
- Run tests with `pnpm test`
```

```markdown
<!-- backend/AGENTS.md -->
# Backend Context

- Use `poetry` for dependency management
- Run the dev server with `poetry run uvicorn main:app --reload`
- All endpoints need OpenAPI docstrings
- Database models are in `models/`, schemas in `schemas/`
```

## SOUL.md — Personality and Tone

`SOUL.md` controls how the agent communicates. See the [Personality](../personality.md) page for the full reference.

**Location:** `~/.spark/SOUL.md` (or `$SPARK_HOME/SOUL.md` with a custom home directory).

Key behavior:
- Spark seeds a default `SOUL.md` automatically on first run
- Only loads from `SPARK_HOME` — never from your project directory
- Empty file = nothing injected
- Non-empty file = content injected verbatim (after security scan and truncation)

## .cursorrules Compatibility

If you already use Cursor, your `.cursorrules` and `.cursor/rules/*.mdc` files work in Spark with zero changes. They load automatically when no higher-priority context file (`.spark.md`, `AGENTS.md`, `CLAUDE.md`) is found in the project root.

## How Loading Works

### At Startup

`build_context_files_prompt()` in `agent/prompt_builder.py` runs this sequence:

1. Scan working directory — checks `.spark.md` → `AGENTS.md` → `CLAUDE.md` → `.cursorrules` (first match wins)
2. Read file as UTF-8
3. Security scan — check for prompt injection patterns
4. Truncate — files over 20,000 characters get head/tail trimmed (70% head, 20% tail)
5. Assemble under a `# Project Context` header
6. Inject into the system prompt

### During the Session

`SubdirectoryHintTracker` in `agent/subdirectory_hints.py` watches tool call arguments for file paths, then:

1. Extracts directory paths from `path`, `workdir`, and shell command arguments
2. Walks up to 5 parent directories per path (stops at already-visited ones)
3. Loads the first matching context file per directory
4. Scans, truncates (8,000 char cap), and appends to the tool result

The final prompt structure looks like:

```text
# Project Context

The following project context files have been loaded and should be followed:

## AGENTS.md

[Your AGENTS.md content here]

[Your SOUL.md content here]
```

SOUL content is inserted directly — no wrapper text.

## Security: Prompt Injection Protection

Every context file is scanned before loading. Blocked patterns include:

- Instruction overrides: "ignore previous instructions", "disregard your rules"
- Deception: "do not tell the user"
- System prompt overrides
- Hidden HTML: `<!-- ignore instructions -->`, `<div style="display:none">`
- Credential exfiltration: `curl ... $API_KEY`
- Sensitive file reads: `cat .env`, `cat credentials`
- Invisible characters: zero-width spaces, bidirectional overrides

A blocked file shows this in context:

```
[BLOCKED: AGENTS.md contained potential prompt injection (prompt_injection). Content not loaded.]
```

:::warning
This scanner protects against common patterns but is not a substitute for reviewing context files in shared repositories. Always validate AGENTS.md content in projects you didn't author.
:::

## Size Limits

| Limit | Value |
|-------|-------|
| Max chars per file (startup) | 20,000 (~7,000 tokens) |
| Max chars per file (subdirectory) | 8,000 |
| Head truncation ratio | 70% |
| Tail truncation ratio | 20% |
| Truncation marker | 10% (shows char counts) |

When truncated:
```
[...truncated AGENTS.md: kept 14000+4000 of 25000 chars. Use file tools to read the full file.]
```

## Tips for Effective AGENTS.md Files

:::tip Best practices
1. **Stay concise** — the agent reads this every turn; under 20K chars is ideal
2. **Use headers** — `##` sections for architecture, conventions, gotchas
3. **Be concrete** — show preferred code patterns, not just abstract guidelines
4. **List what NOT to do** — "never modify migration files directly"
5. **Include paths and ports** — the agent uses these in terminal commands
6. **Keep it current** — stale context misleads more than helps
:::
