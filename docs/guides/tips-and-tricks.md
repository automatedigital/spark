---
sidebar_position: 1
title: "Tips & Best Practices"
description: "Practical advice to get the most out of Spark Agent - prompt tips, CLI shortcuts, context files, memory, cost optimization, and security"
---

# Tips & Best Practices

Quick wins organized by topic. Scan the headers and jump to what's relevant.

---

## Get Better Results

### Be Specific

Vague prompts produce vague results. Instead of "fix the code," say "fix the TypeError in `api/handlers.py` on line 47 — `process_request()` receives `None` from `parse_body()`." More context up front means fewer back-and-forth rounds.

### Front-Load Your Request

Put the relevant details at the start: file paths, error messages, expected behavior. Paste tracebacks directly — the agent can parse them. One well-crafted message beats three rounds of clarification.

### Use Context Files for Recurring Instructions

If you keep repeating the same instructions ("use tabs not spaces," "we use pytest," "the API is at `/api/v2`"), put them in an `AGENTS.md` file. The agent reads it automatically every session — zero effort after setup.

### Let the Agent Work

Don't hand-hold every step. "Find and fix the failing test" beats "open `tests/test_foo.py`, look at line 42, then..." The agent has file search, terminal access, and code execution. Let it explore.

### Check for Existing Skills

Before writing a long prompt explaining how to do something, see if there's already a skill for it. Type `/skills` to browse, or invoke one directly: `/axolotl`, `/github-pr-workflow`, etc.

---

## CLI Power User Tips

### Multi-Line Input

Press **Alt+Enter** (or **Ctrl+J**) to add a newline without sending. Compose multi-line prompts, paste code blocks, or structure complex requests before hitting Enter.

### Paste Detection

The CLI auto-detects multi-line pastes. Paste a code block or traceback directly — it won't treat each line as a separate message. Everything buffers and sends as one.

### Interrupt and Redirect

Press **Ctrl+C** once to interrupt mid-response, then type a new message to redirect. Double-press within 2 seconds to force exit. Essential when the agent starts going the wrong direction.

### Resume Sessions with `-c`

Forgot something from your last session? Run `spark -c` to resume exactly where you left off. Or resume by title: `spark -r "my research project"`.

### Paste Images from Clipboard

Press **Ctrl+V** to paste a screenshot or diagram directly into chat. The agent uses vision to analyze it — no need to save to a file first.

### Slash Command Autocomplete

Type `/` and press **Tab** to see all available commands — built-ins and every installed skill. You don't need to memorize anything.

:::tip
Use `/verbose` to cycle tool output modes: **off → new → all → verbose**. "All" is great for watching what the agent does; "off" is cleanest for simple Q&A.
:::

---

## Context Files

### AGENTS.md: Your Project's Brain

Drop an `AGENTS.md` in your project root with architecture decisions, coding conventions, and project-specific instructions. The agent reads it automatically every session.

```markdown
# Project Context
- This is a FastAPI backend with SQLAlchemy ORM
- Always use async/await for database operations
- Tests go in tests/ and use pytest-asyncio
- Never commit .env files
```

### SOUL.md: Set a Default Voice

Edit `~/.spark/SOUL.md` (or `$SPARK_HOME/SOUL.md`) to give Spark a stable personality across every session. Spark seeds a starter SOUL automatically and uses that global file as the instance-wide identity.

```markdown
# Soul
You are a senior backend engineer. Be terse and direct.
Skip explanations unless asked. Prefer one-liners over verbose solutions.
Always consider error handling and edge cases.
```

`SOUL.md` = durable personality. `AGENTS.md` = project-specific instructions. For a full walkthrough, see [Use SOUL.md with Spark](/docs/guides/define-personality-with-soul).

### .cursorrules Compatibility

Already have a `.cursorrules` or `.cursor/rules/*.mdc` file? Spark reads those too. No need to duplicate your coding conventions.

### How Discovery Works

Spark loads the top-level `AGENTS.md` from the current working directory at session start. Subdirectory `AGENTS.md` files are discovered lazily during tool calls and injected into tool results — they're not loaded up front.

:::tip
Keep context files focused and concise. Every character counts against your token budget since they're injected into every message.
:::

---

## Memory & Skills

### Memory vs. Skills: What Goes Where

**Memory** stores facts: your environment, preferences, project locations, things the agent has learned about you. **Skills** store procedures: multi-step workflows, tool instructions, reusable recipes.

- Memory = what
- Skills = how

### When to Create a Skill

If a task takes 5+ steps and you'll do it again, turn it into a skill. Say "save what you just did as a skill called `deploy-staging`." Next time, `/deploy-staging` loads the full procedure automatically.

### Managing Memory Capacity

Memory is intentionally bounded (~2,200 chars for MEMORY.md, ~1,375 chars for USER.md). When it fills up, the agent consolidates. You can prompt it: "clean up your memory" or "replace the old Python 3.9 note — we're on 3.12 now."

### Save Things Explicitly

After a productive session, say "remember this for next time." You can also be precise: "save to memory that we require `ruff check` and the full pytest suite to pass before merging to main."

:::warning
Memory is a frozen snapshot — changes made during a session don't appear in the prompt until the next session starts. The agent writes to disk immediately, but the current session's prompt cache doesn't update mid-session.
:::

---

## Performance & Cost

### Don't Break the Prompt Cache

Most LLM providers cache the system prompt prefix. Keep your system prompt stable (same context files, same memory) and subsequent messages in a session get **cache hits** — significantly cheaper. Avoid switching models or rebuilding the system prompt mid-session.

### Use /compress Before Hitting Limits

Long sessions accumulate tokens. When responses slow down or get truncated, run `/compress`. It summarizes conversation history, preserves key context, and cuts token count dramatically. Use `/usage` to check where you stand.

### Delegate for Parallel Work

Need to research three topics at once? Ask the agent to use `delegate_task` with parallel subtasks. Each subagent runs independently, and only final summaries come back — keeps your main context lean.

### Batch with execute_code

Instead of running terminal commands one at a time, have the agent write a script. "Write a Python script to rename all `.jpeg` files to `.jpg` and run it" is faster and cheaper than renaming files one by one.

### Match the Model to the Task

Use `/model` to switch mid-session. Use a frontier model (Claude Sonnet/Opus, GPT-4o) for complex reasoning and architecture decisions. Switch to a lighter model for formatting, renaming, or boilerplate.

:::tip
Run `/usage` periodically to see token consumption. Run `/insights` for a broader view of usage patterns over the last 30 days.
:::

---

## Messaging Tips

### Set a Home Channel

Use `/sethome` in your preferred Telegram or Discord chat to designate it as the home channel. Cron results and scheduled task outputs go here. Without it, proactive messages have nowhere to land.

### Name Your Sessions

Use `/title auth-refactor` or `/title research-llm-quantization` to name sessions. Named sessions are easy to find with `spark sessions list` and resume with `spark -r "auth-refactor"`. Unnamed ones pile up fast.

### DM Pairing for Team Access

Instead of manually collecting user IDs, enable DM pairing. A teammate DMs the bot, gets a one-time code, and you approve it with `spark pairing approve telegram XKGH5N7P`. Simple and doesn't require restarting the gateway.

### Tool Progress Display

Use `/verbose` to control how much tool activity appears. In messaging platforms, less is usually more — "new" shows just new tool calls. In the CLI, "all" gives a satisfying live view.

:::tip
On messaging platforms, sessions auto-reset after idle time (default: 24 hours) or daily at 4 AM. Adjust per-platform in `~/.spark/config.yaml` if you need longer sessions.
:::

---

## Security

### Use Docker for Untrusted Code

When working with unfamiliar repos or running unknown code, use Docker as your terminal backend. Commands inside the container can't harm your host.

```bash
# In your .env:
TERMINAL_BACKEND=docker
TERMINAL_DOCKER_IMAGE=spark-sandbox:latest
```

### Avoid Windows Encoding Pitfalls

On Windows, default encodings like `cp125x` can't represent all Unicode characters, causing `UnicodeEncodeError` in files or scripts. Always open files with an explicit encoding:

```python
with open("results.txt", "w", encoding="utf-8") as f:
    f.write(" All good\n")
```

In PowerShell, switch the session to UTF-8:

```powershell
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
```

### Think Before Choosing "Always"

When the agent triggers a dangerous command approval (`rm -rf`, `DROP TABLE`, etc.), you get four options: **once**, **session**, **always**, **deny**. Start with "session" until you're confident. "Always" permanently allowlists the pattern.

### Understand Container Behavior

Spark checks every command against a list of dangerous patterns before execution — recursive deletes, SQL drops, piping curl to shell, and more. Don't disable this in production.

:::warning
When running in a container backend (Docker, Singularity, Modal, Daytona), dangerous command checks are **skipped** because the container is the security boundary. Make sure your container images are properly locked down.
:::

### Lock Down Messaging Bots

Never set `GATEWAY_ALLOW_ALL_USERS=true` on a bot with terminal access. Use platform allowlists or DM pairing.

```bash
# Recommended: explicit allowlists per platform
TELEGRAM_ALLOWED_USERS=123456789,987654321
DISCORD_ALLOWED_USERS=123456789012345678

# Or use a cross-platform allowlist
GATEWAY_ALLOWED_USERS=123456789,987654321
```

---
