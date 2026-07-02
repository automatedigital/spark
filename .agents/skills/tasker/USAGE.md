# How to use `/tasker` — step-by-step guide

`/tasker` runs a ticket-driven dev loop: your tracker (Notion, Jira, Linear,
GitHub Issues, or any MCP-connected tool) holds the work, and the agent
brainstorms, triages, plans, and builds — fanning out to sub-agents in parallel
where it's safe. This is the quick-start guide; see `SKILL.md` for full mechanics.

## Step 1 — Connect your tracker

```
/tasker connect
```

Say which platform (or let it reuse the one already set up). It enables that
platform's MCP, finds your board/database, and offers to create the right ticket
structure if it doesn't exist. Run once per project; safe to re-run.

## Step 2 — Get ideas into the tracker

Either add tickets yourself, or:

```
/tasker brainstorm
```

Surveys your codebase + reference repos and files a batch of `Not started` idea
tickets — each with an icon, priority, cover image, and a
"what / why it helps us / likely files / open questions" body.

## Step 3 — Decide what's worth doing

```
/tasker decide
```

Reviews the backlog (use **high reasoning** here — it's the highest-leverage
step). It **keeps** the valuable tickets, **merges** overlapping ones —
collapsing duplicates, and turning same-code-path work into a single **phased**
ticket — and **prunes** the rest to `Pruned`. It shows you the plan and asks once
before applying.

## Step 4 — Plan the keepers

```
/tasker plan
```

Turns chosen tickets into full implementation plans (scope, checklist,
acceptance, verification). Multiple tickets plan in parallel; phased tickets get
a checklist per phase.

## Step 5 — Build

```
/tasker
```

Implements planned tickets as feature branches + PRs. Independent tickets run in
parallel sub-agents (each in its own git worktree); phased tickets run as one
worker, phase by phase. Merges to `main` are serialized by the coordinator.

---

## Anytime helpers

- `/tasker status` — queue summary + active PR state (read-only)
- `/tasker resume` — continue an in-progress ticket
- `/tasker sync` — reconcile ticket statuses / PR URLs with GitHub

## Good to know

- **Source of truth is your tracker**, not `PLAN.md`.
- **Status flow:** `Not started → Planned → In progress → PR created → Merged`.
  `Pruned` (discarded/merged) and `Completed` (you set this) are terminal and
  ignored by future steps.
- **`Rebuild Desktop` checkbox** on a ticket = build + release the macOS app
  after merge.
- **Typical run:** `connect → brainstorm → decide → plan → /tasker`, triaging in
  your tracker between steps.
