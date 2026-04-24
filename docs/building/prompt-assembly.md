---
sidebar_position: 5
title: "Prompt Assembly"
description: "How Spark builds the system prompt, preserves cache stability, and injects ephemeral layers"
---

# Prompt Assembly

Spark splits the system prompt into two distinct categories: things that stay **stable** across turns (cached), and things that change **per-call** (ephemeral). Getting this split right matters a lot — it controls token costs, cache hit rates, and whether memory behaves predictably.

Primary files:
- `run_agent.py`
- `agent/prompt_builder.py`
- `tools/memory_tool.py`

## The 10 Layers of a Cached System Prompt

Spark assembles the stable system prompt in this order at session start:

| # | Layer | Source |
|---|-------|--------|
| 1 | Agent identity | `~/.spark/SOUL.md`, or `DEFAULT_AGENT_IDENTITY` fallback |
| 2 | Tool-aware behavior guidance | Hardcoded in `prompt_builder.py` |
| 3 | Memory provider static block | Active provider (e.g., Honcho), when enabled |
| 4 | Optional system message | Config or API override |
| 5 | Frozen MEMORY snapshot | `~/.spark/memories/` at session start |
| 6 | Frozen USER profile snapshot | `~/.spark/USER.md` at session start |
| 7 | Skills index | Installed skills in `~/.spark/skills/` |
| 8 | Context files | `AGENTS.md`, `.cursorrules`, `.cursor/rules/*.mdc` (not SOUL.md again) |
| 9 | Timestamp + session ID | Generated at assembly time |
| 10 | Platform hint | CLI, Telegram, Discord, etc. |

When `skip_context_files` is set (subagent delegation), layer 1 uses `DEFAULT_AGENT_IDENTITY` instead of `SOUL.md`.

## What the Assembled Prompt Looks Like

Here's a simplified real-world example with all layers present:

```
# Layer 1: Agent Identity (from ~/.spark/SOUL.md)
You are Spark, an AI assistant created by Automate Digital.
You are an expert software engineer and researcher.
You value correctness, clarity, and efficiency.
...

# Layer 2: Tool-aware behavior guidance
You have persistent memory across sessions. Save durable facts using
the memory tool: user preferences, environment details, tool quirks,
and stable conventions. Memory is injected into every turn, so keep
it compact and focused on facts that will still matter later.
...
When the user references something from a past conversation or you
suspect relevant cross-session context exists, use session_search
to recall it before asking them to repeat themselves.

# Tool-use enforcement (for GPT/Codex models only)
You MUST use your tools to take action - do not describe what you
would do or plan to do without actually doing it.
...

# Layer 3: Honcho static block (when active)
[Honcho personality/context data]

# Layer 4: Optional system message (from config or API)
[User-configured system message override]

# Layer 5: Frozen MEMORY snapshot
## Persistent Memory
- User prefers Python 3.12, uses pyproject.toml
- Default editor is nvim
- Working on project "atlas" in ~/code/atlas
- Timezone: US/Pacific

# Layer 6: Frozen USER profile snapshot
## User Profile
- Name: Alice
- GitHub: alice-dev

# Layer 7: Skills index
## Skills (mandatory)
Before replying, scan the skills below. If one clearly matches
your task, load it with skill_view(name) and follow its instructions.
...
<available_skills>
  software-development:
    - code-review: Structured code review workflow
    - test-driven-development: TDD methodology
  research:
    - arxiv: Search and summarize arXiv papers
</available_skills>

# Layer 8: Context files (from project directory)
# Project Context
The following project context files have been loaded and should be followed:

## AGENTS.md
This is the atlas project. Use pytest for testing. The main
entry point is src/atlas/main.py. Always run `make lint` before
committing.

# Layer 9: Timestamp + session
Current time: 2026-03-30T14:30:00-07:00
Session: abc123

# Layer 10: Platform hint
You are a CLI AI Agent. Try not to use markdown but simple text
renderable inside a terminal.
```

## Your SOUL.md Is Layer 1

`SOUL.md` at `~/.spark/SOUL.md` is the agent's identity — it becomes the very first section of the system prompt. The loader in `prompt_builder.py`:

```python
# From agent/prompt_builder.py (simplified)
def load_soul_md() -> Optional[str]:
    soul_path = get_spark_home() / "SOUL.md"
    if not soul_path.exists():
        return None
    content = soul_path.read_text(encoding="utf-8").strip()
    content = _scan_context_content(content, "SOUL.md")  # Security scan
    content = _truncate_content(content, "SOUL.md")       # Cap at 20k chars
    return content
```

When `load_soul_md()` returns content, it replaces `DEFAULT_AGENT_IDENTITY`. Then `build_context_files_prompt(skip_soul=True)` prevents SOUL.md from loading again as a context file.

If `SOUL.md` doesn't exist, this fallback identity is used:

```
You are Spark Agent, an intelligent AI assistant created by Automate Digital.
You are helpful, knowledgeable, and direct. You assist users with a wide
range of tasks including answering questions, writing and editing code,
analyzing information, creative work, and executing actions via your tools.
You communicate clearly, admit uncertainty when appropriate, and prioritize
being genuinely useful over being verbose unless otherwise directed below.
Be targeted and efficient in your exploration and investigations.
```

## How Context Files Are Chosen (First Match Wins)

`build_context_files_prompt()` uses a priority system — at most one project context type loads per session:

```python
# From agent/prompt_builder.py (simplified)
def build_context_files_prompt(cwd=None, skip_soul=False):
    cwd_path = Path(cwd).resolve()

    # Priority: first match wins - only ONE project context loaded
    project_context = (
        _load_spark_md(cwd_path)       # 1. .spark.md / SPARK.md (walks to git root)
        or _load_agents_md(cwd_path)    # 2. AGENTS.md (cwd only)
        or _load_claude_md(cwd_path)    # 3. CLAUDE.md (cwd only)
        or _load_cursorrules(cwd_path)  # 4. .cursorrules / .cursor/rules/*.mdc
    )
    ...
```

| Priority | Files | Search scope | Notes |
|----------|-------|-------------|-------|
| 1 | `.spark.md`, `SPARK.md` | CWD up to git root | Spark-native project config |
| 2 | `AGENTS.md` | CWD only | Common agent instruction file |
| 3 | `CLAUDE.md` | CWD only | Claude Code compatibility |
| 4 | `.cursorrules`, `.cursor/rules/*.mdc` | CWD only | Cursor compatibility |

All context files go through the same safety pipeline before injection:

- **Security scan** — checked for prompt injection patterns (invisible unicode, "ignore previous instructions", credential exfiltration attempts)
- **Truncation** — capped at 20,000 characters using a 70/20 head/tail ratio with a truncation marker
- **YAML frontmatter strip** — `.spark.md` frontmatter is removed (reserved for future config overrides)

## What Stays Ephemeral (Not Cached)

These layers are injected at API-call time only — they never become part of the stable cached prefix:

- `ephemeral_system_prompt`
- Prefill messages
- Gateway-derived session context overlays
- Later-turn memory provider recall injected into the current-turn user message

Keeping these separate is what makes the stable prefix actually stable for caching.

## Memory Snapshots Are Frozen at Session Start

MEMORY and USER profile data are captured once when the session begins. If you write to memory mid-session, the disk file updates — but the running system prompt does not. The new data appears in the next session or after a forced rebuild.

## Why It's Split This Way

This architecture makes three things true simultaneously:

1. **Low cost** — the stable prefix is cached by the provider; you pay to write it once, not on every turn.
2. **Correct memory semantics** — a mid-session memory write doesn't retroactively change what the agent "knew" at the start.
3. **Safe extensibility** — the gateway, ACP, and CLI can all inject context without mutating the cached prompt state.

## Related Docs

- [Context Compression & Prompt Caching](./context-compression-and-caching.md)
- [Session Storage](./session-storage.md)
- [Gateway Internals](./gateway-internals.md)
