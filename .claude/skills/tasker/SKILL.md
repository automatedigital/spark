---
name: tasker
description: Project-local ticket-driven dev workflow backed by your ticket system (Notion, Jira, Linear, GitHub Issues, or any MCP-connected tracker). Use when the user types /tasker, /tasker connect, /tasker plan, /tasker status, /tasker resume, /tasker sync, /tasker brainstorm, or /tasker decide. Connects to a ticket backend, brainstorms and triages ideas, plans tickets, then builds feature branches and opens PRs — keeping the tracker and GitHub in sync.
---

# Tasker

Project-local `/tasker` ticket-driven workflow for the current repository. The
connected **ticket backend is the source of truth** — not `PLAN.md` (do not use
`PLAN.md` unless the user explicitly asks for the old PLAN.md behavior).

Tasker is backend-agnostic. **Notion ("Spark Planner") is the reference
backend** and the mechanics below are written against it, but the same flow runs
on Jira, Linear, GitHub Issues, or any tracker exposed through an MCP server —
see [Ticket Backends](#ticket-backends) for the concept mapping. Everywhere this
doc says "Notion", "page", "data source", or a specific status name, read it as
the connected backend's equivalent from that mapping.

## Workflow

The intended end-to-end flow:

1. **Connect** your ticket system — `/tasker connect` (Notion, Jira, Linear,
   GitHub Issues, …). Enables the platform's MCP and bootstraps the ticket
   structure if it does not exist.
2. **Create ideas** in the tracker — by hand, or with `/tasker brainstorm`.
3. **Decide** which ideas most benefit the codebase — `/tasker decide`. Use
   **high reasoning** for this step.
4. **Plan** the chosen tickets in full — `/tasker plan`.
5. **Build** — `/tasker` implements planned tickets as feature branches and PRs.

`/tasker status` and `/tasker sync` support the flow at any point.

Steps 2, 4, and 5 fan out across **subagents** running in parallel wherever the
work is independent — see [Parallelism & Subagents](#parallelism--subagents).

## Commands

- `/tasker connect` - connect/verify a ticket backend, enable its MCP, and
  bootstrap the ticket structure if missing.
- `/tasker status` - summarize the ticket queue and active PR state.
- `/tasker plan` - turn unplanned tickets into implementation-ready plans.
- `/tasker` or `/tasker start` - implement selected `Planned` tickets.
- `/tasker resume` - continue selected `In progress` tickets.
- `/tasker sync` - reconcile ticket statuses and PR URLs with GitHub state.
- `/tasker brainstorm` - survey the codebase and reference repos, then create
  many new idea tickets at `Not started` for human triage.
- `/tasker decide` - triage the backlog: keep the tickets worth doing, merge
  overlapping ones, and prune the rest to `Pruned`. Use high reasoning.

## Ticket Backends

Tasker works against an abstract ticket model. Any backend that can express it —
natively or through its MCP server — is supported.

Concept model (backend-neutral):

- **Ticket** — a unit of work with a title and a human-readable body.
- **Status** — a lifecycle state. Tasker's canonical set is `Not started` ->
  `Planned` -> `In progress` -> `PR created` -> `Merged`, plus terminal
  `Pruned` and human-only `Completed` (see [Status Semantics](#status-semantics)).
- **Priority** — High / Medium / Low.
- **Type** — Bug / Feature / Idea / etc. (optional).
- **Description** — short machine-readable summary property.
- **Body** — rich content: the cover image, plan sections, and checklists.
- **PR link** — a field holding the GitHub PR URL.
- **Agent / Subagents / Rebuild flags** — optional automation hints.

Reference backend mapping:

| Concept | Notion (reference) | Jira | Linear | GitHub Issues |
| --- | --- | --- | --- | --- |
| Ticket | Database page | Issue | Issue | Issue |
| Status | `Status` property | Workflow status | Workflow state | State + labels |
| Priority | `Priority` select | Priority field | Priority | Label |
| Type | `Type` multi-select | Issue type | Label | Label |
| Description | `Description` text | Summary | Title/description | Title |
| Body | Page blocks | Description (ADF) | Description (md) | Body (md) |
| PR link | `PR URL` property | Linked PR / field | Linked PR / attachment | Linked PR / body |
| Checklists | To-do blocks | Checklist/subtasks | Sub-issues/checklist | Task-list items |

When a backend cannot express a status name, map to the nearest equivalent and
record the mapping once (e.g. Jira "To Do" = `Not started`, "Done" = `Merged`).
Do not silently reinterpret statuses — surface the mapping to the user.

## /tasker connect

Establish (or verify) the ticket backend before any other step. Idempotent —
safe to run repeatedly.

1. **Detect intent.** If the user names a platform (Notion, Jira, Linear,
   GitHub Issues, …), target it. Otherwise, ask once which tracker to use, or
   reuse the one already configured for this repo.
2. **Enable the platform's MCP.** Search available tools for the backend's MCP
   server (e.g. a Notion, Jira, or Linear MCP). If its tools are present, use
   them — richer, native tool use beats generic HTTP. If the MCP exists but is
   not connected, tell the user how to connect it and stop. If no MCP exists for
   the platform, fall back to its CLI/REST (e.g. `gh` for GitHub Issues) and say
   so.
3. **Find or bootstrap the ticket structure.** Locate the project's board /
   database / project. If it does not exist, offer to create it with the schema
   Tasker needs — the fields in the [Ticket Backends](#ticket-backends) concept
   model (Status set incl. `Not started`/`Planned`/`In progress`/`PR created`/
   `Merged`/`Pruned`/`Completed`, Priority, Type, Description, PR link, and the
   automation flags). Create it only after the user confirms.
4. **Record the binding.** Note the resolved backend + board/database id so the
   rest of this session's steps reuse it. Confirm the connection back to the
   user (workspace/project name) before proceeding.

If a required status/field cannot be created on the backend, map to the nearest
equivalent per [Ticket Backends](#ticket-backends) and surface the mapping.

## Required Setup Each Run

1. Resolve the connected ticket backend (run `/tasker connect` first if none is
   bound this session). Fetch the board/database and read its **exact** schema:
   status names, type names, priority names, and field/property names. Never
   assume — backends and even individual boards differ.
2. For Notion (reference backend), prefer the `collection://...` data source for
   scoped searches. For other backends, use their native query/list tools.
3. Use targeted `rg`, file reads, tests, and git history to identify real code
   areas before planning or implementing tickets.
4. Activate the Python environment before Python commands:
   `source venv/bin/activate`.

If the backend's tools are unavailable, stop and tell the user to connect it
(`/tasker connect`). If GitHub tools are unavailable, use `gh` where possible and
report any blocked PR or merge action clearly.

## Status Semantics

Use the exact status options from the fetched database schema.

Preferred agent-managed status flow:

`Not started` -> `Planned` -> `In progress` -> `PR created` -> `Merged`

Any pre-plan ticket may instead be sent to `Pruned` by `/tasker decide`.

`Completed` is human-only. Never set a ticket to `Completed`, even when work is
done and a PR is open. Use `PR created` for an open PR that is ready for human
review, and `Merged` only after the PR merge succeeds.

`Pruned` is an agent-managed terminal status, set only by `/tasker decide`, for
tickets that are not worth doing or were merged into another ticket. `Pruned`
requires a `Pruned` status option in the schema; if it is absent, add it (or
ask the user once) before running `/tasker decide`.

Terminal / ignored statuses: `Completed`, `Merged`, and `Pruned` tickets are
excluded as candidates from every step (`status` counts them separately but
never acts on them; `plan`, `start`, `resume`, `sync`, and `decide` skip them)
unless the user explicitly asks otherwise.

The Notion MCP `Status` property is the source of truth. Before reporting,
choosing, reconciling, or changing a ticket status, fetch the latest page or
data source through the Notion MCP and read the actual `Status` property. Do not
infer status from GitHub state, PR merge state, progress logs, screenshots,
search snippets, local memory, or branch names. If a data-source query is
rate-limited, fetch exact candidate pages individually or say the queue status
is not fully verified.

Current Spark Planner schemas may not have `Not started`. If it is absent, ask
once before planning whether to treat `Planned` tickets without a `# Tasker Plan`
section as unplanned backlog. Do not silently reinterpret statuses.

For execution, only start tickets that are both:

- status `Planned`
- contain a `# Tasker Plan` section

For resume, only use status `In progress`.

## Selection Prompt

When a command needs ticket selection:

1. Fetch/search the candidate tickets. Never include `Completed`, `Merged`, or
   `Pruned` tickets as candidates.
2. Present a numbered list with title, type, priority, status, agent, and a short
   description.
3. Ask exactly one concise question:
   - plan: `Which tickets should I plan? Reply all, a comma-separated list, or names.`
   - start: `Which planned tickets should I start? Reply all, a comma-separated list, or names.`
   - resume: `Which in-progress tickets should I resume? Reply all, a comma-separated list, or names.`
4. Accept `all`, numbers, ranges, comma-separated values, or recognizable title
   fragments. If ambiguous, ask one clarifying question.

## Parallelism & Subagents

Default to parallel execution. When a step has independent units of work, the
main `/tasker` invocation acts as a **coordinator** and fans the units out to
**subagents** (via the Agent tool) that run concurrently, then aggregates the
results. Prefer this over doing units one at a time — it is the primary speedup.

What parallelizes, by step:

- **brainstorm** — spawn one subagent per independent research stream (each
  reference repo, the local-codebase survey, the backend dedupe check). The
  coordinator merges findings and creates the tickets.
- **plan** — one subagent per selected ticket. Each does its own targeted
  repo research (`rg`, file reads, tests, and git history) and writes that
  ticket's plan. Plans touch separate tickets, so there are no write conflicts.
- **start / build** — one subagent per selected ticket, each implementing its
  ticket end-to-end on its own branch. This is the biggest win and has the
  strictest isolation rules below.
- **decide** — keep the final value/merge/prune judgement in a single
  high-reasoning coordinator, but it may fan out read-only assessment (per-ticket
  codebase impact checks) to subagents and synthesize their reports.

Rules for parallel work:

- **Isolation for code.** Each build subagent works in its **own git worktree**
  so branches never collide. Never let two subagents share a working tree. Use
  the worktree/isolation mechanism the harness provides (e.g. an isolated
  worktree per Agent).
- **Independence check before fan-out.** Only parallelize tickets that touch
  different areas. Overlap should already be resolved at `decide`, which merges
  overlapping tickets into a single **phased** ticket — so tickets reaching build
  are expected to be independent and safe to fan out. A phased ticket is one
  unit: assign it to a **single** subagent that works its phases in order. If you
  still spot two selected tickets editing the same files (e.g. they were created
  outside the brainstorm→decide flow), run them in one worker or sequentially,
  and consider sending them back through `decide` to merge into phases.
- **Serialize the shared chokepoints.** The coordinator — not the workers —
  performs merges to `main` one at a time (rebase/retest between merges to catch
  conflicts), and runs any desktop release exactly once after the last merge.
- **Concurrency cap.** Keep concurrent subagents modest (about 3–4) to avoid
  ticket-backend API rate limits and local resource contention. Queue the rest.
- **Each subagent gets the full contract.** Pass every subagent the ticket
  context, the backend binding, the Engineering Rules, and instructions to
  update its own ticket's status/checkboxes as it goes.
- **Per-ticket status ownership.** A subagent owns its ticket's status and
  checkbox updates. Different tickets are different backend records, so these
  writes do not conflict; still fetch-before-write per the backend rules.
- **Failure isolation.** One ticket failing must not abort the others. Collect
  per-ticket outcomes and report a summary; leave failed tickets `In progress`
  with a blocker note.
- **Honor the `Subagents` flag.** A ticket marked `Subagents = __YES__` is broad
  enough that its own subagent may further delegate sub-tasks internally; `__NO__`
  tickets should be handled by a single worker without deeper fan-out.
- **Prompt-cache safety.** Fan-out must not rewrite the coordinator's own
  context/toolset mid-run in cache-breaking ways (see Engineering Rules).

If subagents are unavailable in the current harness, fall back to sequential
execution and say so.

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

When several tickets are selected, plan them in parallel: spawn one subagent per
ticket per [Parallelism & Subagents](#parallelism--subagents) — each runs the
steps below for its own ticket — and have the coordinator report the planned set
when they finish.

For selected unplanned tickets:

1. Fetch the page including current body content.
2. Read title, description, type, priority, reference URL, reference files, logs,
   comments/discussions if available.
3. Use targeted `rg`, file reads, tests, and git history to identify real code
   areas, tests, and risks.
4. If the backend is Notion and the page body does not already start with a
   relevant image block, prepend a verified `image/*` URL as the first block so
   Gallery views configured with `page_content_first` render a useful cover.
5. Append or replace a `# Tasker Plan` section in the page body. Preserve the
   original report, screenshots, logs, and prior notes.
6. Update properties:
   - `Agent`: include `Codex` unless the ticket clearly belongs elsewhere.
   - `Type`: keep existing type unless clearly missing or wrong.
   - `Priority`: fill only when obvious from impact; otherwise leave unchanged.
   - `Subagents`: set `__YES__` for broad, multi-area work; otherwise `__NO__`.
   - `Status`: set to `Planned`.
7. Add a progress log entry with the planning date.

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

**Phased tickets** (produced by `/tasker decide` for merged-overlapping work):
give each `### Phase N` its own Implementation Checklist, Acceptance Criteria,
and Verification, in phase order. The build worker completes phases top to
bottom, so later phases may assume earlier ones are done.

## /tasker or /tasker start

When several planned tickets are selected, run them in parallel: the coordinator
spawns one subagent per ticket, each in its **own git worktree** on its own
branch, following the steps below end-to-end for that ticket. Only fan out
tickets that touch different areas (run overlapping ones in the same worker or
sequentially). The coordinator serializes merges to `main` (step 10) — one at a
time, rebasing/retesting between — and runs any desktop release once after the
last merge. See [Parallelism & Subagents](#parallelism--subagents).

For selected planned tickets (each worker, for its ticket):

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
9. Before setting status to `PR created`/`Merged` or moving to another ticket,
   fetch the Notion page and confirm every checkbox in the implementation
   checklist, acceptance criteria, and verification sections is checked. Do not
   leave a PR-created or merged ticket with unchecked boxes.
10. Merge only when all are true:
   - requested by the workflow or clearly expected by the user
   - branch is pushed and PR exists
   - checks pass or there are no required checks
   - branch protection/review requirements allow merge
   - no unresolved conflicts
11. Set status:
   - `PR created` when implementation is done and PR is open but not merged
   - `Merged` when merge succeeds
   - keep `In progress` and add blocker details if blocked
   - never set `Completed`; that status is reserved for human updates only
12. After a successful merge to `main`, tidy the ticket branch and worktree
    before moving to the next merge:
   - confirm the PR is merged with `gh pr view <pr> --json state,mergedAt` (do
     not infer merge success from local `gh pr merge` cleanup errors)
   - switch the coordinator checkout back to `main` and fast-forward from
     `origin/main`
   - remove the ticket worktree with `git worktree remove <path>` once its
     status is clean; if a stale generated diff blocks removal, preserve the
     diff first or report it, then remove with `--force` only for that verified
     merged worktree
   - delete the local ticket branch after the worktree is gone. Prefer
     `git branch -d <branch>`, but use `git branch -D <branch>` for verified
     squash-merged PR branches whose commits are not ancestors of `main`
   - delete the remote ticket branch. `gh pr merge --delete-branch` is not
     enough when local worktree cleanup fails; after confirming the PR is
     merged, run `git push origin --delete <branch>` if the remote ref still
     exists
   - run `git fetch --prune origin` and verify `git branch` / `git branch -r`
     no longer list the merged ticket branch
   - never delete `main`, the current branch, an unmerged branch, or a branch
     whose PR state could not be verified as merged
13. If this is the last selected ticket branch to merge and any completed ticket
    in the run has Notion `Rebuild Desktop` checked, publish the desktop release
    from merged `main` before finishing:
    - bump the desktop app to the next patch version unless the ticket specifies
      a target version
    - commit and push the version bump to `main`
    - run the macOS desktop build from `main`
    - publish the `desktop-v<VERSION>` GitHub Release asset
    - add the release URL to the ticket progress log

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
  `PR created`.
- Never set status `Completed`; if a ticket looks complete but should not be
  merged yet, report that it is ready for human review.
- If status is `In progress` but no branch/PR/progress exists, flag it in the
  response and ask before changing status.
- If `Planned` lacks `# Tasker Plan`, flag it as needing `/tasker plan`.
- If checklist is fully checked but no PR URL exists, flag it as needing PR
  creation or manual cleanup.

Do not merge PRs or change code during `/tasker sync` unless the user explicitly
asks.

## /tasker brainstorm

Generate a large batch of new ticket ideas and file them in Notion for human
triage. This mode creates tickets only — no plans, no code changes, no status
changes to existing tickets.

### Gather ideas

Fan this out: spawn subagents for the independent research streams below (each
reference repo, the local-codebase survey, the backend dedupe check) so they run
concurrently, then merge their findings before creating tickets. See
[Parallelism & Subagents](#parallelism--subagents).

1. Survey the local codebase:
   - Targeted `rg`, file reads, tests, and recent git history for architecture
     hot spots, large modules, and under-tested areas.
   - Recent git history (`git log --oneline -50`, recently merged PRs via
     `gh pr list --state merged`) for features that suggest follow-ups,
     missing polish, or regressions to guard against.
   - TODO/FIXME/HACK markers, error-handling gaps, and known-pitfall areas
     from `AGENTS.md`/`CLAUDE.md`.
   - WebUI and user-experience gaps: rough edges in the TUI, desktop app,
     gateway surfaces (Telegram/Slack), onboarding (`spark setup`,
     `spark doctor`), and skin/theme system.
2. Review recent additions and updates in the reference repos we want to draw
   ideas from:
   - <https://github.com/nousresearch/hermes-agent>
   - <https://github.com/openclaw/openclaw>
   - <https://github.com/pingdotgg/t3code>

   Use web fetch/search or `gh` (`gh api repos/<owner>/<repo>/commits`,
   releases, recent merged PRs, README/changelog diffs) to find features,
   UX patterns, and ideas shipped recently. For each idea worth borrowing,
   translate it into Spark terms — never propose verbatim copying of code.
3. Check the Spark Planner queue first and skip ideas that duplicate existing
   tickets in any status.

### Create tickets

For each idea, create a new Spark Planner page:

- `Status`: `Not started`. If the schema has no `Not started` option, ask once
  which status to use for raw ideas and use that for the whole batch.
- Title: short, imperative, specific (`Add /export command for session
  transcripts`, not `Improve sessions`).
- Icon: set a fitting emoji icon on every page.
- `Priority`: set on every ticket (High/Medium/Low) based on impact.
- Description property: a self-contained 2-3 sentence summary that reads well
  in board/table views without opening the page.
- Body: the FIRST block must be a relevant image so the Gallery view —
  configured `page_content_first` — renders a good cover. Use a real
  screenshot when one exists; otherwise a fitting themed stock image
  (e.g. Unsplash `https://images.unsplash.com/photo-<id>?auto=format&fit=crop&w=1200&q=80`).
  Rules for images:
  - Verify every URL returns HTTP 200 `image/*` before inserting (e.g.
    `curl -s -o /dev/null -w "%{http_code} %{content_type}" <url>`).
  - Every ticket in the batch must use a UNIQUE image — no repeats across the
    batch. Match the image to the ticket's theme (security, gateway, webui,
    dev-tooling, etc.).
  Then the sections —
  - `## What`: the concrete change.
  - `## Why it helps Spark`: the argument for doing it. For reference-repo
    ideas, link the source repo/commit/release AND explain why the pattern
    transfers to Spark's codebase specifically — never just "repo X did this".
  - `## Likely areas`: real file paths in this repo.
  - `## Open questions before planning`: the unknowns `/tasker plan` must
    resolve before implementation.
  - `## Progress Log`: creation date entry.
- `Type`: fill only when obvious; otherwise leave unset.
- Do NOT add a `# Tasker Plan` section. Planning happens later via
  `/tasker plan` after the human triages the batch.

### Definition of done

Every created ticket must have all of: a fitting emoji icon, a `Priority`, a
self-contained `Description` property, a unique verified cover image as the
first body block, and the four body sections above. A batch in this state is
ready for `/tasker plan` with no further cleanup. Before finishing, confirm no
two tickets share a cover image.

Aim for a generous batch (roughly 10-25 tickets) spanning codebase health,
webui, user experience, and reference-repo inspiration. It is the human's job
to prune — favor breadth over self-censoring, but every ticket must still be a
real, actionable idea, not filler.

### Finish

End with a compact summary list of created tickets (title + one-line
rationale, grouped by theme) so the user can triage quickly, then run
`/tasker decide` to triage the batch (or `/tasker plan` directly on chosen
tickets).

## /tasker decide

Triage the backlog: decide which tickets are actually worth doing, merge
overlapping ones, and prune the rest. Run this after `/tasker brainstorm` and
before `/tasker plan`. This mode changes ticket status and merges content — it
never writes code or opens PRs.

**Use high reasoning for this step.** Value judgements, overlap detection, and
merge/prune calls are the highest-leverage decisions in the whole workflow —
think hard before acting. If the harness supports a reasoning-effort control,
raise it here.

Operate only on **pre-plan** tickets: status `Not started`, plus `Planned`
tickets that have no `# Tasker Plan` section. Never keep/merge/prune a ticket
that is `Planned` with a plan, `In progress`, `PR created`, `Merged`,
`Completed`, or already `Pruned` unless the user explicitly asks.

### Assess

1. Fetch all candidate tickets from the Spark Planner data source, excluding
   the terminal/active statuses above.
2. Judge each ticket's real value to *this* codebase — not surface novelty.
   Use targeted repo inspection, git history, and the ticket body to weigh:
   does the problem actually exist in the code today, user-visible impact,
   alignment with recent direction, and effort vs. risk.
3. Cluster tickets that overlap or would touch the same code path.

### Decide and act

Sort every candidate into exactly one bucket:

- **Keep** — clearly worth doing. Leave status `Not started`. Adjust
  `Priority` to reflect its ranked value if needed.
- **Merge** — two or more tickets are the same work, should ship together, OR
  **overlap** (touch the same files / code path even if the work is distinct).
  Overlapping tickets must be merged here, at decide — never left as separate
  tickets, because separate overlapping tickets cannot be built in parallel
  safely. Pick the strongest as the survivor and fold the others in:
  - **Duplicates / same work** → collapse into the survivor. Merge the unique
    content (scope, likely files, open questions, reference links) into the
    survivor's body under a `## Merged in` heading.
  - **Overlap (distinct work, shared code)** → merge into the survivor and
    structure the combined work as ordered **phases** under a `## Phases`
    heading: `### Phase 1 — <title>`, `### Phase 2 — <title>`, … Each phase
    gets its own goal, scope, and (at plan time) its own checklist and
    acceptance criteria. Order phases so each builds cleanly on the previous.
    Retitle the survivor to reflect the combined scope if needed.
  In both cases set each absorbed ticket to `Pruned` with a progress-log line
  `Pruned: merged into <survivor title>`. Preserve the absorbed pages — set
  status, never delete.

  A phased ticket is implemented by a **single** build subagent, phase by phase
  in order (one branch; a PR per phase or one PR for the ticket, as the plan
  decides) — this is exactly how overlapping work stays collision-free while
  still being tracked as distinct phases.
- **Prune** — not actually useful to Spark: duplicates existing behavior, out
  of scope, speculative with no real underlying problem, or superseded. Set
  status `Pruned` and add a progress-log line with the one-sentence reason.

Present the full decision as a report first — Keep (ranked, with priority),
Merge (survivor <- absorbed, why), Prune (why) — and ask one confirmation
before applying. Then apply the status and content changes.

### After deciding

Surviving `Keep` tickets are the queue for `/tasker plan`. `Pruned` tickets are
terminal and ignored by every other `/tasker` step, exactly like `Completed`.
Finish with a one-line tally: kept N, merged M into K survivors, pruned P.

## Notion Update Rules

- Fetch before content updates.
- Every newly created Notion ticket body must start with a relevant image block
  for Gallery cover rendering. Before inserting an external image, verify the
  URL returns HTTP 200 with an `image/*` content type. During `/tasker plan`, if
  a selected Notion ticket is missing that first image block, prepend one before
  adding the plan.
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
- Use `rg`, focused file reads, tests, and git history for codebase orientation.
- Use `apply_patch` for manual file edits.
- Run focused tests while iterating; run broader checks before PR/merge when
  practical.
- Treat a checked Notion `Rebuild Desktop` property as explicit confirmation to
  bump the desktop version, rebuild the macOS desktop app, and publish the
  GitHub desktop release after the last relevant ticket branch is merged to
  `main`; do not ask for a second build or release confirmation. Always use the
  next desktop patch version unless the ticket specifies another version, for
  example `1.3.10` -> `desktop-v1.3.11`. Commit and push the version bump before
  building, rebuild from merged `main`, publish the `desktop-v*` GitHub Release
  asset, and record the release URL in the ticket progress log. Only skip release
  publication if the build/sign/notarization or GitHub release command fails,
  and leave the ticket in `Merged` with the blocker logged.
- Only rebuild the desktop app or create a release when the Notion ticket
  explicitly has `Rebuild Desktop` checked. Otherwise use code-level tests,
  web builds, route/API checks, and PR CI for verification. If an existing plan
  includes packaged-app or release verification while `Rebuild Desktop` is not
  checked, update that checkbox text to say it was not requested for the ticket
  and check it only after recording that note. Do not leave stale unchecked
  packaging/release boxes behind.
- When running tickets in parallel, isolate each build subagent in its own git
  worktree, only fan out tickets that touch different areas, and let the
  coordinator serialize merges to `main` (rebase/retest between merges). See
  [Parallelism & Subagents](#parallelism--subagents).
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
