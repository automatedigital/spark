---
sidebar_position: 8
title: "Code Execution"
description: "Sandboxed Python execution with RPC tool access - collapse multi-step workflows into a single turn"
---

# Code Execution (Programmatic Tool Calling)

Multi-step workflows normally consume a lot of context — each tool result enters the conversation, ballooning token usage. `execute_code` changes that. The agent writes a Python script, runs it in a sandboxed child process, and only the script's `print()` output comes back. Intermediate results stay out of the context window entirely.

## The Core Idea

```python
# The agent writes scripts like this:
from spark_tools import web_search, web_extract

results = web_search("Python 3.13 features", limit=5)
for r in results["data"]["web"]:
    content = web_extract([r["url"]])
    # ... filter and process ...
print(summary)  # Only this reaches the LLM
```

The script talks to Spark tools over a Unix domain socket RPC channel. Tools behave identically to normal calls — same rate limits, same error handling. The difference is that nothing intermediate enters the conversation.

**Tools available inside scripts:** `web_search`, `web_extract`, `read_file`, `write_file`, `search_files`, `patch`, `terminal` (foreground only).

## When the Agent Reaches for This

The agent uses `execute_code` automatically when a task involves:

- 3+ tool calls with processing logic between them
- Filtering or transforming large datasets
- Looping over search results or file matches

You don't have to ask for it explicitly.

## How It Works — Step by Step

1. The agent writes a Python script using `from spark_tools import ...`
2. Spark generates a `spark_tools.py` stub with RPC function stubs
3. Spark opens a Unix domain socket and starts a listener thread
4. The script runs in a child process — tool calls travel over the socket
5. Only `print()` output is returned to the LLM

## Practical Examples

### Scan Config Files for a Setting

```python
from spark_tools import search_files, read_file
import json

matches = search_files("database", path=".", file_glob="*.yaml", limit=20)
configs = []
for match in matches.get("matches", []):
    content = read_file(match["path"])
    configs.append({"file": match["path"], "preview": content["content"][:200]})

print(json.dumps(configs, indent=2))
```

### Research Multiple URLs in One Turn

```python
from spark_tools import web_search, web_extract
import json

results = web_search("Rust async runtime comparison 2025", limit=5)
summaries = []
for r in results["data"]["web"]:
    page = web_extract([r["url"]])
    for p in page.get("results", []):
        if p.get("content"):
            summaries.append({
                "title": r["title"],
                "url": r["url"],
                "excerpt": p["content"][:500]
            })

print(json.dumps(summaries, indent=2))
```

### Bulk Find-and-Replace Across a Codebase

```python
from spark_tools import search_files, patch

matches = search_files("old_api_call", path="src/", file_glob="*.py")
fixed = 0
for match in matches.get("matches", []):
    result = patch(
        path=match["path"],
        old_string="old_api_call(",
        new_string="new_api_call(",
        replace_all=True
    )
    if "error" not in str(result):
        fixed += 1

print(f"Fixed {fixed} files out of {len(matches.get('matches', []))} matches")
```

### Run Tests and Parse Results

```python
from spark_tools import terminal
import json

result = terminal("cd /project && python -m pytest --tb=short -q 2>&1", timeout=120)
output = result.get("output", "")

report = {
    "passed": output.count(" passed"),
    "failed": output.count(" failed"),
    "errors": output.count(" error"),
    "exit_code": result.get("exit_code", -1),
    "summary": output[-500:] if len(output) > 500 else output
}

print(json.dumps(report, indent=2))
```

## Resource Limits

| Resource | Limit | What Happens |
|----------|-------|--------------|
| **Timeout** | 5 minutes (300s) | SIGTERM, then SIGKILL after 5s grace |
| **Stdout** | 50 KB | Truncated with `[output truncated at 50KB]` |
| **Stderr** | 10 KB | Included in output on non-zero exit |
| **Tool calls** | 50 per execution | Error returned when limit reached |

Override any of these in `~/.spark/config.yaml`:

```yaml
code_execution:
  timeout: 300       # Max seconds per script (default: 300)
  max_tool_calls: 50 # Max tool calls per execution (default: 50)
```

## Error Handling

The response always includes `status`, `output`, `tool_calls_made`, and `duration_seconds`.

| Situation | What the Agent Sees |
|-----------|-------------------|
| Non-zero exit | Full stderr traceback included in output |
| Timeout | `"Script timed out after 300s and was killed."` |
| User interrupt | `[execution interrupted - user sent a new message]` |
| Tool call limit | Error returned from subsequent tool calls |

## Security

:::danger Security Model
The child process runs with a minimal environment. API keys, tokens, and credentials are stripped by default.
:::

Variables with these substrings in their name are excluded: `KEY`, `TOKEN`, `SECRET`, `PASSWORD`, `CREDENTIAL`, `PASSWD`, `AUTH`. Only safe system variables pass through (`PATH`, `HOME`, `LANG`, `SHELL`, `PYTHONPATH`, `VIRTUAL_ENV`, etc.).

### Getting API Keys Into Scripts

**Via skills** — when a skill declares `required_environment_variables` in its frontmatter, those variables are automatically passed through to `execute_code` and `terminal` sandboxes after the skill loads.

**Explicit allowlist** — for everything else:

```yaml
terminal:
  env_passthrough:
    - MY_CUSTOM_KEY
    - ANOTHER_TOKEN
```

See the [Configuration guide](/docs/configuration#environment-variable-passthrough) for full details.

## `execute_code` vs `terminal` — Which to Use

| Scenario | Use |
|----------|-----|
| Multi-step workflows with tool calls between | `execute_code` |
| Filtering or processing large tool outputs | `execute_code` |
| Looping over search results | `execute_code` |
| Simple shell command | `terminal` |
| Running a build or test suite | `terminal` |
| Interactive or background processes | `terminal` |
| Needs API keys in environment | `terminal` (most pass through automatically) |

**Rule of thumb:** `execute_code` when you need Spark tools with logic between them. `terminal` for shell commands, builds, and processes.

## Platform Support

Code execution requires Unix domain sockets. It runs on **Linux and macOS only**. On Windows, it's automatically disabled and the agent falls back to sequential tool calls.
