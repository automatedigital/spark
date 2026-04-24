---
sidebar_position: 9
sidebar_label: "Context References"
title: "Context References"
description: "Inline @-syntax for attaching files, folders, git diffs, and URLs directly into your messages"
---

# Context References

Type `@` in any message to pull content directly into your prompt. Spark expands the reference and appends everything under an `--- Attached Context ---` section before sending to the agent.

No manual copy-pasting. No separate upload step.

## Reference Types

| Syntax | What You Get |
|--------|-------------|
| `@file:path/to/file.py` | Full file contents |
| `@file:path/to/file.py:10-25` | Lines 10–25 (1-indexed, inclusive) |
| `@folder:path/to/dir` | Directory tree with file metadata |
| `@diff` | `git diff` — unstaged changes |
| `@staged` | `git diff --staged` — staged changes |
| `@git:5` | Last 5 commits with patches (max 10) |
| `@url:https://example.com` | Fetched web page content |

## Examples

```text
Review @file:src/main.py and suggest improvements

What changed since last commit? @diff

Compare @file:old_config.yaml and @file:new_config.yaml

What's the structure of @folder:src/components?

Summarize this paper @url:https://arxiv.org/abs/2301.00001
```

You can stack multiple references in one message:

```text
This test is failing. Here's the test @file:tests/test_auth.py
and the implementation @file:src/auth.py:50-80
```

Trailing punctuation (`,` `.` `;` `!` `?`) is stripped automatically from reference values.

## Line Ranges

Target exactly the code you care about:

```text
@file:src/main.py:42        # Single line
@file:src/main.py:10-25     # Lines 10 through 25
```

Lines are 1-indexed. Invalid ranges silently return the full file.

## Tab Completion in the CLI

Type `@` and the CLI offers completions:

- `@` alone → shows all reference types (`@diff`, `@staged`, `@file:`, `@folder:`, `@git:`, `@url:`)
- `@file:` and `@folder:` → filesystem path completion with file size metadata
- `@` + partial text → matching files and folders from the current directory

## Practical Workflows

```text
# Security review of current changes
Review @diff and check for security issues

# Debug with full context
Here's the failing test @file:tests/test_auth.py
and the relevant source @file:src/auth.py:50-80

# Understand a new project
What does this do? @folder:src @file:README.md

# Compare research approaches
@url:https://arxiv.org/abs/2301.00001 vs @url:https://arxiv.org/abs/2301.00002
```

## Size Limits

| Threshold | Value | Behavior |
|-----------|-------|----------|
| Soft limit | 25% of context length | Warning appended, expansion proceeds |
| Hard limit | 50% of context length | Expansion refused, original message returned unchanged |
| Folder entries | 200 files max | Extras replaced with `- ...` |
| Git commits | 10 max | `@git:N` clamped to [1, 10] |

For large files, use line ranges to inject only the relevant sections.

## Security

### Blocked Paths

These paths are always blocked from `@file:` to prevent credential exposure:

**Files:**
- `~/.ssh/id_rsa`, `~/.ssh/id_ed25519`, `~/.ssh/authorized_keys`, `~/.ssh/config`
- `~/.bashrc`, `~/.zshrc`, `~/.profile`, `~/.bash_profile`, `~/.zprofile`
- `~/.netrc`, `~/.pgpass`, `~/.npmrc`, `~/.pypirc`
- `$SPARK_HOME/.env`

**Directories (all contents blocked):**
- `~/.ssh/`, `~/.aws/`, `~/.gnupg/`, `~/.kube/`, `$SPARK_HOME/skills/.hub/`

### Path Traversal Protection

All paths resolve relative to the working directory. References outside the workspace root are rejected.

### Binary Files

Binary files are detected via MIME type and null-byte scanning. Known text extensions (`.py`, `.md`, `.json`, `.yaml`, `.toml`, `.js`, `.ts`, etc.) skip MIME detection. Binary files are rejected with a warning.

## Error Handling

Bad references produce inline warnings — they never crash the message:

| Condition | Warning |
|-----------|---------|
| File not found | "file not found" |
| Binary file | "binary files are not supported" |
| Folder not found | "folder not found" |
| Git command fails | Warning with git stderr |
| URL returns nothing | "no content extracted" |
| Sensitive path | "path is a sensitive credential file" |
| Outside workspace | "path is outside the allowed workspace" |

## Platform Availability

Context references work in the **interactive CLI**. On messaging platforms (Telegram, Discord, etc.) the `@` syntax is not expanded — those messages pass through to the agent as-is. The agent can still read files via `read_file`, `search_files`, and `web_extract`.

## Context References and Compression

When a conversation gets compressed, expanded reference content is included in the summary. This means:

- Large files injected via `@file:` contribute to context usage
- After compression, that content is summarized, not preserved verbatim
- Use line ranges to keep context injection lean
