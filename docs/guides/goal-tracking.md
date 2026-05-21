---
sidebar_position: 13
title: "Goal Tracking"
description: "Set durable objectives that Spark pursues across every session, with real-time management from the Dashboard Kanban board"
---

# Goal Tracking

`/goal` lets you set a durable, verifiable objective that Spark actively works toward across every session — not just for one conversation, but until you mark it done. The active goal is injected into the agent's system prompt automatically, so you never have to remind Spark what you're trying to accomplish.

Goals are backed by the **Kanban board** in the Dashboard, so you can manage them from the web UI in real time without touching the CLI.

---

## Quick start

```
/goal Ship the auth service rewrite
```

Add a stopping condition so Spark knows when it's finished:

```
/goal Ship the auth service rewrite -- all tests green and deployed to staging
```

That's it. From now on, every session starts with this in context:

```
## Active Goal
**Objective:** Ship the auth service rewrite
**Done when:** all tests green and deployed to staging
```

Check progress any time with `/goal status`. When the work is done:

```
/goal done
```

---

## Why stopping conditions matter

A goal without a stopping condition is just a wish. Stopping conditions give Spark a clear finish line:

| Vague | Specific |
|-------|----------|
| "improve performance" | "p95 API latency below 200ms on the checkout endpoint" |
| "clean up the codebase" | "zero ruff warnings, mypy passes on src/agent/ and src/spark_cli/" |
| "write documentation" | "all public functions in src/tools/ have docstrings, README updated" |

Use the `--` separator (or `when:` / `done when:`) to add one inline:

```
/goal Migrate to the new payment provider -- first successful live transaction in prod
```

---

## All subcommands

| Command | What it does |
|---------|--------------|
| `/goal <objective>` | Set a new active goal (archives any previous one) |
| `/goal <objective> -- <done when>` | Set a goal with a stopping condition |
| `/goal` or `/goal status` | Show the active goal, task ID, and link to the Dashboard |
| `/goal pause` | Pause — Spark acknowledges the goal but stops actively pursuing it |
| `/goal resume` | Resume a paused goal |
| `/goal done` | Mark the goal complete and move it to the done column |
| `/goal clear` | Archive the goal without marking it done |
| `/goal history` | Show recent completed and cleared goals |

---

## How Spark uses the goal

The active goal is prepended to the system prompt at session start. When the user's request is unrelated to the goal, Spark completes it as asked and notes any relevant progress or blockers. When the request is directly related, Spark prioritises it.

Changing the goal mid-session (`/goal <new objective>`) invalidates the cached system prompt — the new goal takes effect on the very next turn, no restart needed.

---

## Dashboard integration

Goals are stored as tasks on the **`goals` board** in `kanban.db` — the same database the Tasks board uses. This means the Dashboard and CLI are always in sync.

### Switching to the Goals board

Open the Dashboard → **Tasks** page and click **🎯 Goals** in the header. The button toggles between the default tasks board and the goals board. You can also type `goals` manually in the Board input field.

### Managing goals from the Dashboard

| Action | How |
|--------|-----|
| View the active goal | Goals board, `todo` or `ready` column |
| Pause a goal | Drag the card to the `blocked` column |
| Resume a goal | Drag from `blocked` back to `todo` |
| Mark done | Drag to `done`, or use the Complete action in the task detail panel |
| Archive/clear | Drag to `archived` |
| Edit the objective | Click the task title in the detail panel |
| Edit the stopping condition | Edit the task body in the detail panel |
| See change history | Open the task, scroll to Events |

All changes sync back to the CLI immediately — the SSE event stream fires on every state change.

### Real-time sync example

```
/goal Migrate the billing service to Stripe
```

1. A card appears on the goals board in the Dashboard instantly.
2. Drag it to `blocked` (e.g. waiting on API credentials) → `/goal status` shows it as paused.
3. Drag it back to `todo` → the next CLI session resumes pursuing it.
4. When the work is done, click **Complete** in the Dashboard → the goal disappears from the active list in both places.

---

## Breaking a goal into tasks

Big goals usually require multiple tasks. Use `/kanban` or the Dashboard's default board to create the individual work items, then dispatch workers to tackle them in parallel.

```
/goal Complete the API v2 migration -- all v1 endpoints return 410 Gone

# Then break it down on the task board:
/kanban create "Audit v1 endpoint usage" assignee:me
/kanban create "Write v2 equivalents" assignee:agent-1
/kanban create "Update client SDKs" assignee:agent-2
/kanban dispatch
```

The goal stays in context across all these sessions. Workers can read it via the Kanban task detail if you include it in the task body.

---

## Multiple goals and history

Only one goal is **active** at a time. Setting a new goal automatically archives the previous one. Paused (blocked) goals stay visible on the goals board so you can track them.

View past goals:

```
/goal history
```

For a full audit trail, open the goals board in the Dashboard and enable the `archived` column (use the board filter or set `archived=true` in the API query).

---

## Tips

- **Start a new session after setting a goal** — the system prompt is rebuilt for each new session, so existing open sessions won't pick up a goal set mid-session until the next turn.
- **One clear goal beats a vague multi-part one.** If the goal has unrelated sub-objectives, split them into separate goals and alternate between them using `/goal clear` and `/goal <next objective>`.
- **The goal appears in every conversation's system prompt**, including background sessions (`/background`) and gateway chats — so messaging integrations are goal-aware too.
- **Goals survive profile switches** — each profile has its own `kanban.db`, so goals are profile-scoped.

---

## See also

- [Slash Commands Reference](../cli/slash-commands.md#goal-tracking) — full `/goal` subcommand reference
- [Task Board](../web-dashboard.md) — Dashboard and Kanban board overview
- [Dream](../cli/slash-commands.md#dream) — offline reflection that consolidates session memory; pairs well with long-running goals
- [Automate with Cron](automate-with-cron.md) — schedule recurring tasks alongside your goals
