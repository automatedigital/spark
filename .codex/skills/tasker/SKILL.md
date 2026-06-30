---
name: tasker
description: Spark-specific Notion Planner workflow. Use when the user types /tasker, /tasker plan, /tasker status, /tasker resume, or /tasker sync in the Spark repository. Plans and executes Spark Planner Notion tickets, updates ticket block checklists/progress, opens PRs, and reconciles Notion with GitHub.
---

# Spark Tasker

Project-local `/tasker` for the Spark codebase. Notion "Spark Planner" is the
source of truth. Do not use `PLAN.md` for this workflow unless the user
explicitly asks for the old PLAN.md tasker behavior.

## Commands

- `/tasker status` - summarize Spark Planner queue and active PR state.
- `/tasker plan` - turn unplanned Notion tickets into implementation-ready plans.
- `/tasker` or `/tasker start` - implement selected `Planned` tickets.
- `/tasker resume` - continue selected `In progress` tickets.
- `/tasker sync` - reconcile Notion statuses and PR URLs with GitHub state.

## Required Setup Each Run

1. Use Notion search/fetch tools to find the `Spark Planner` database.
2. Fetch the database and read its exact schema, data source id, status names,
   type names, priority names, and property names.
3. Prefer the `collection://...` data source for scoped Notion searches.
4. Use `graphify query "<ticket-specific question>"` before planning or
   implementing tickets when `graphify-out/graph.json` exists.
5. Activate the Python environment before Python commands:
   `source venv/bin/activate`.

If Notion tools are unavailable, stop and tell the user to connect the Notion
app. If GitHub tools are unavailable, use `gh` where possible and report any
blocked PR or merge action clearly.

## Status Semantics

Use the exact status options from the fetched database schema.

Preferred status flow:

`Not started` -> `Planned` -> `In progress` -> `Completed` -> `Merged`

Current Spark Planner schemas may not have `Not started`. If it is absent, ask
once before planning whether to treat `Planned` tickets without a `# Tasker Plan`
section as unplanned backlog. Do not silently reinterpret statuses.

For execution, only start tickets that are both:

- status `Planned`
- contain a `# Tasker Plan` section

For resume, only use status `In progress`.

## Selection Prompt

When a command needs ticket selection:

1. Fetch/search the candidate tickets.
2. Present a numbered list with title, type, priority, status, agent, and a short
   description.
3. Ask exactly one concise question:
   - plan: `Which tickets should I plan? Reply all, a comma-separated list, or names.`
   - start: `Which planned tickets should I start? Reply all, a comma-separated list, or names.`
   - resume: `Which in-progress tickets should I resume? Reply all, a comma-separated list, or names.`
4. Accept `all`, numbers, ranges, comma-separated values, or recognizable title
   fragments. If ambiguous, ask one clarifying question.

## /tasker status

Show a compact queue summary:

- counts by status
- unplanned backlog candidates
- planned tickets ready to implement
- in-progress tickets with branch/PR if discoverable
- recent completed/merged tickets
- stale or inconsistent tickets, for example `Planned` without a plan or PR URL
  present while status is still `In progress`

Do not modify tickets in status mode unless the user asks.

## /tasker plan

For selected unplanned tickets:

1. Fetch the page including current body content.
2. Read title, description, type, priority, reference URL, reference files, logs,
   comments/discussions if available.
3. Use `graphify query` and targeted `rg`/file reads to identify real code areas,
   tests, and risks.
4. Append or replace a `# Tasker Plan` section in the page body. Preserve the
   original report, screenshots, logs, and prior notes.
5. Update properties:
   - `Agent`: include `Codex` unless the ticket clearly belongs elsewhere.
   - `Type`: keep existing type unless clearly missing or wrong.
   - `Priority`: fill only when obvious from impact; otherwise leave unchanged.
   - `Subagents`: set `__YES__` for broad, multi-area work; otherwise `__NO__`.
   - `Status`: set to `Planned`.
6. Add a progress log entry with the planning date.

### Plan Template

Use this exact section shape unless the ticket needs a small adaptation:

```markdown
# Tasker Plan
Updated: YYYY-MM-DD

## Summary
[What needs to change and why.]

## Scope
- In scope:
- Out of scope:

## Likely Files
- `path/to/file`

## Implementation Checklist
- [ ] Reproduce or confirm the current behavior
- [ ] Add or update regression coverage
- [ ] Implement the smallest safe fix
- [ ] Run targeted verification
- [ ] Update documentation or generated assets if needed
- [ ] Open PR and link it here

## Acceptance Criteria
- [ ] User-visible behavior is fixed
- [ ] Regression test or clear manual verification exists
- [ ] Existing behavior outside the scope is unchanged

## Verification
- [ ] `source venv/bin/activate && python -m pytest ... -q`
- [ ] `npm run test -- ...`
- [ ] Manual check: ...

## Progress Log
- YYYY-MM-DD: Planned by Tasker.
```

Every checklist item should be concrete enough for a later agent to execute and
check off without rereading the whole conversation.

## /tasker or /tasker start

For selected planned tickets:

1. Fetch the ticket body and schema.
2. Set status to `In progress`.
3. Add a progress log entry with timestamp and branch name.
4. Create or switch to a branch named `<short-ticket-slug>`, for example
   `download-logs-button`. Do not include agent or workflow prefixes.
5. Work through `# Tasker Plan` checklist top to bottom.
6. After each verified subtask, update the Notion checkbox immediately:
   - fetch current content first
   - use exact `old_str`/`new_str` replacement
   - do not batch checkoffs until the end
7. Commit intentionally, push, and open a PR.
8. Write the PR URL to the Notion `PR URL` property.
9. Before setting status to `Completed`/`Merged` or moving to another ticket,
   fetch the Notion page and confirm every checkbox in the implementation
   checklist, acceptance criteria, and verification sections is checked. Do not
   leave a completed or merged ticket with unchecked boxes.
10. Merge only when all are true:
   - requested by the workflow or clearly expected by the user
   - branch is pushed and PR exists
   - checks pass or there are no required checks
   - branch protection/review requirements allow merge
   - no unresolved conflicts
11. Set status:
   - `Completed` when implementation is done and PR is open but not merged
   - `Merged` when merge succeeds
   - keep `In progress` and add blocker details if blocked

Do not mark a checkbox complete unless the work and verification for that item
are actually done.

## /tasker resume

For selected `In progress` tickets:

1. Fetch the ticket and locate branch/PR from progress log or `PR URL`.
2. Inspect local git status before touching files.
3. Continue from the first unchecked checklist item.
4. Preserve user changes. Never reset or discard unrelated work.
5. Update Notion progress and checkboxes as tasks complete.
6. Push/update PR and status when finished.

## /tasker sync

Reconcile Notion against GitHub and local repo state:

- If PR URL exists and PR is merged, set status `Merged`.
- If PR URL exists and PR is open with completed checklist, set status
  `Completed`.
- If status is `In progress` but no branch/PR/progress exists, flag it in the
  response and ask before changing status.
- If `Planned` lacks `# Tasker Plan`, flag it as needing `/tasker plan`.
- If checklist is fully checked but no PR URL exists, flag it as needing PR
  creation or manual cleanup.

Do not merge PRs or change code during `/tasker sync` unless the user explicitly
asks.

## Notion Update Rules

- Fetch before content updates.
- Use `insert_content` for appending progress log entries.
- Use `update_content` with exact snippets for checkbox changes.
- Preserve child pages/databases. Never use `replace_content` if it would delete
  child content unless the user explicitly confirms.
- Keep progress entries short and factual:
  `- YYYY-MM-DD HH:MM: Completed regression test for session hydration.`
- Prefer page properties for machine-readable state and page body for human
  implementation context.

## Engineering Rules

- Follow `AGENTS.md` for Spark-specific architecture, testing, profiles, and
  prompt-cache constraints.
- Use `rg` for search and `graphify query` for codebase orientation.
- Use `apply_patch` for manual file edits.
- Run focused tests while iterating; run broader checks before PR/merge when
  practical.
- After modifying code, run `graphify update .` before finishing.
- Never hardcode `~/.spark`; use `get_spark_home()` and `display_spark_home()`.
- Do not change toolsets, reload memories, or rebuild system prompts
  mid-conversation in ways that break prompt caching.

## Stop Conditions

Stop and ask the user when:

- ticket selection is ambiguous
- a Notion status option needed by the workflow is missing and no fallback has
  been approved
- a ticket needs product/design clarification that cannot be inferred
- verification fails for a reason that changes the implementation strategy
- merge is blocked by checks, review policy, conflicts, or permissions
