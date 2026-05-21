---
sidebar_position: 3
sidebar_label: "Git Worktrees"
title: "Git Worktrees"
description: "Run multiple Spark agents safely on the same repository using git worktrees and isolated checkouts"
---

# Git Worktrees

Two problems come up constantly on large, long-lived repos:

1. You want two agents running on the same codebase at the same time.
2. You want to try a risky refactor without touching your main branch.

Git worktrees solve both. Each worktree gives an agent its own directory, its own branch, and its own checkpoint history — without cloning the entire repo again.

## Why a Single Checkout Causes Problems

Spark treats whatever directory you launched it from as the project root. Run two agents in the same checkout and they step on each other:

- One agent rewrites a file the other is reading.
- Rollback history from two separate experiments gets tangled.
- You lose track of which changes belong to which task.

With worktrees, each agent is fully isolated:

| What's isolated | Per worktree? |
|-----------------|---------------|
| Branch and working directory | Yes |
| `/rollback` checkpoint history | Yes |
| Uncommitted file edits | Yes |

See also: [Checkpoints and /rollback](./checkpoints.md).

## The Fast Path: `spark -w`

The `-w` flag handles everything automatically. Run it from inside any repo:

```bash
cd /path/to/your/repo
spark -w
```

Spark creates a temporary worktree under `.worktrees/`, checks out an isolated branch, and runs your full CLI session there. You never touch `git worktree` directly.

Combine it with a one-shot query:

```bash
spark -w -q "Fix issue #123"
```

For parallel agents, open multiple terminals and run `spark -w` in each. Every invocation gets its own worktree and branch automatically.

## Manual Worktree Setup

If you want explicit control over branch names and locations:

```bash
# From the main repo root
cd /path/to/your/repo

# Create a new branch + worktree directory
git worktree add ../repo-feature feature/spark-experiment
```

Then launch Spark inside that directory:

```bash
cd ../repo-feature
spark
```

Spark sees `../repo-feature` as the project root and tracks checkpoints separately from any other worktree.

## Running Two Agents in Parallel

```bash
cd /path/to/your/repo

git worktree add ../repo-experiment-a feature/spark-a
git worktree add ../repo-experiment-b feature/spark-b
```

```bash
# Terminal 1
cd ../repo-experiment-a
spark

# Terminal 2
cd ../repo-experiment-b
spark
```

Each process works on its own branch and can use `/rollback` without affecting the other. Useful for:

- Trying two different solutions to the same problem
- Running a CLI session and a gateway session in parallel
- Executing large-scale batch refactors on separate features

## Cleaning Up When You're Done

Decide whether to keep the work first, then remove the worktree:

```bash
# Keep the changes — merge the branch as usual first
# Then remove the worktree
cd /path/to/your/repo
git worktree remove ../repo-feature
```

A few things to know:

- `git worktree remove` refuses if there are uncommitted changes. Use `--force` only if you're sure you want to discard them.
- Removing a worktree does **not** delete the branch. Delete it separately with `git branch -d` if you're done.
- Spark checkpoint data under `~/.spark/checkpoints/` is not pruned automatically, but it's typically very small.

## Best Practices

- **One worktree per experiment.** Focused diffs make for reviewable PRs.
- **Name branches after the task.** `feature/spark-checkpoints-docs` is searchable; `feature/tmp` is not.
- **Commit often at milestones.** Let [checkpoints and /rollback](./checkpoints.md) handle granular recovery between commits.
- **Don't run Spark from the bare repo root when using worktrees.** Work inside the worktree directory so each agent has a clear scope.

## The Three-Layer Safety Net

| Layer | Tool | Scope |
|-------|------|-------|
| Experiment isolation | git worktrees | Separate working directories |
| High-level history | git branches + commits | Milestone snapshots |
| Fine-grained recovery | checkpoints + `/rollback` | Per-edit undo inside each worktree |

All three together mean a runaway agent edit is always recoverable.
