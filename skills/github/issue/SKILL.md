---
name: issue
description: Draft a detailed, redacted GitHub issue from the current Spark session, screenshots, logs, and reproduction notes; always ask for approval before creating it.
version: 1.0.0
author: Spark Agent
license: MIT
metadata:
  spark:
    tags: [GitHub, Issues, Bug-Reports, Spark, Diagnostics]
    related_skills: [github-issues, github-auth]
---

# Spark Issue Drafting

Use this skill when the user invokes `/issue` or asks to file a Spark bug from the current conversation.

## Outcome

Prepare a GitHub issue draft that is detailed enough for a maintainer to reproduce and triage, redacted enough to share safely, and explicit enough that the user can approve or revise it before anything is submitted.

## Collect Evidence

Gather only evidence relevant to the reported bug:

- User description and expected behavior.
- Current session id and recent turn context, summarized rather than pasted wholesale.
- Spark version, git SHA, OS/platform, active profile, and whether the issue happened in CLI, browser dashboard, remote dashboard, or macOS desktop app.
- Reproduction steps, including exact commands if the user ran any.
- Relevant screenshots or files referenced with `@path`.
- Recent redacted logs, especially files under `references/logs/`.
- Browser/desktop mode details such as dashboard URL, Tauri/webview version when available, and whether the issue reproduces in the standalone web UI.

Prefer repository-local evidence first. For screenshots, include file paths and a one-sentence visual description. For logs, quote only short relevant snippets and summarize the rest.

## Redaction Rules

Never include:

- API keys, bearer tokens, dashboard tokens, OAuth codes, cookies, or authorization headers.
- Full secret values from `.env`, config files, keychains, or provider credentials.
- Unrelated home-directory file contents or unrelated session content.
- Long raw logs when a short excerpt and summary is enough.

Replace sensitive values with clear placeholders such as `[REDACTED_API_KEY]`, `[REDACTED_TOKEN]`, or `[REDACTED_HOME_PATH]`. Keep paths only when they help reproduce the bug; otherwise shorten them.

## Draft Format

Use `skills/github/github-issues/templates/bug-report.md` as the base structure. Add Spark-specific fields:

```markdown
## Bug Description

## Steps to Reproduce

## Expected Behavior

## Actual Behavior

## Environment

- Spark version:
- Git SHA:
- OS/platform:
- Surface: CLI / browser dashboard / remote dashboard / macOS desktop
- Active profile:
- Session id:

## Evidence

- Screenshots:
- Logs:
- Related files:

## Error Output

## Additional Context
```

## Approval Gate

Before creating or updating any GitHub issue, show the user:

- Exact issue title.
- Full issue body.
- Labels.
- Assignees, if any.
- Attachment/reference list.
- The command or API request you plan to run.

Ask for explicit approval. Do not submit, comment, attach, or upload anything until the user approves that exact content.

## Submission Workflow

Use the existing GitHub issue workflow:

1. Prefer `gh issue create` when `gh auth status` succeeds.
2. Fall back to the GitHub REST API with `GITHUB_TOKEN` only if `gh` is unavailable.
3. If authentication is missing, stop with the draft and tell the user what is needed.

Do not add a new tool for issue creation unless the existing `github-issues` workflow cannot perform the required action.
