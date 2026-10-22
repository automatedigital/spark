# Spark issue and feature PR plan

Updated: 2026-10-22. Baseline: `64af0d26976714b747dd4f1cc5b495c47c7f7567` (`main`).

Deliver ten independently scoped defect fixes and ten useful features, each implemented by a delegated agent in an isolated worktree with a GitHub issue and pull request. Reference research uses current pinned revisions of [T3 Code](https://github.com/pingdotgg/t3code) and [Hermes Agent](https://github.com/nousresearch/hermes-agent), checked against existing Spark functionality.

## Status

Research underway; 0/20 implementation PRs created, 0/20 accepted, 0/20 merged. Placeholder rows are allocation slots, not confirmed findings. The lead alone updates this plan. PR creation, validation, merge and release are separate states; completion requires reviewed evidence, not an agent summary.

The previous upgrade plan and its unfinished performance/native gates are preserved in [the historical plan](docs/plans/app-upgrade-2026-10-15.md). Existing issues #130, #139 and #140 retain those gates. No historical acceptance is silently carried forward.

## Delivery rules

- Confirm each defect from current source and a focused reproduction; identify upstream source and the absent Spark capability for every feature.
- Each packet records issue, agent task ID, allowed paths, dependencies, acceptance flow and PR evidence. Use descriptive `fix/` and `feat/` branches.
- Isolated worktrees start at the committed baseline. Preserve unrelated dirty work; use synthetic `SPARK_HOME`; activate `.venv` for Python and verify Node 22 for frontend checks.
- Keep one writer for shared migrations, manifests, lockfiles and production bundles. Source PRs must disclose pending bundle/browser/package gates.
- Agents create and link their PRs, report exact head SHA/check results, and do not merge, publish releases or poll PRs. The lead checks results and links all deliverables to this thread.
- Run focused regressions and relevant lint/type/manifest/cache gates. Web/chat/gateway behavior also requires the documented browser flows. Do not mark unexecuted checks as passed.

## Packet tracker

| ID | Outcome | Status | Issue | Agent task | PR / evidence |
| --- | --- | --- | --- | --- | --- |
| I01 | Pending evidence-based selection | Research | — | — | — |
| I02 | Pending evidence-based selection | Research | — | — | — |
| I03 | Pending evidence-based selection | Research | — | — | — |
| I04 | Pending evidence-based selection | Research | — | — | — |
| I05 | Pending evidence-based selection | Research | — | — | — |
| I06 | Pending evidence-based selection | Research | — | — | — |
| I07 | Pending evidence-based selection | Research | — | — | — |
| I08 | Pending evidence-based selection | Research | — | — | — |
| I09 | Pending evidence-based selection | Research | — | — | — |
| I10 | Pending evidence-based selection | Research | — | — | — |
| F01 | Pending evidence-based selection | Research | — | — | — |
| F02 | Pending evidence-based selection | Research | — | — | — |
| F03 | Pending evidence-based selection | Research | — | — | — |
| F04 | Pending evidence-based selection | Research | — | — | — |
| F05 | Pending evidence-based selection | Research | — | — | — |
| F06 | Pending evidence-based selection | Research | — | — | — |
| F07 | Pending evidence-based selection | Research | — | — | — |
| F08 | Pending evidence-based selection | Research | — | — | — |
| F09 | Pending evidence-based selection | Research | — | — | — |
| F10 | Pending evidence-based selection | Research | — | — | — |

## Research and acceptance evidence

- Backend and tool audit: running.
- Web/API/gateway audit: running.
- Current upstream feature comparison: running.
