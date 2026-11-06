# Shared hosted inspector failure — bounded causal analysis, 2026-11-06

## Decision

No causal repair is justified by the retained evidence. No fixture, production,
workflow, timeout, assertion or retry changes; no push or CI rerun. SP02 retains
ChatPanel/controller/production-scroll ownership. Zero browser configurations,
builds or pytest runs were used in this follow-up; another untriggered A/B would
not distinguish the remaining explanations on the overloaded shared host.

Started from a clean checkout initially at `1f35023a`; created
`fix/shared-inspector-causal-analysis` at the explicitly requested committed base
`3d71089ea4fb5f33596ebe4be119195ba372f49a`. The report named in the assignment did
not exist at that base or the local `origin/docs/simplicity-performance-plan`
reference; this file records the new bounded analysis. Read AGENTS, CONTEXT,
STRUCTURE, PLAN and accepted ADRs 0001/0012/0013. No PLAN acceptance changed.

## Verified retained evidence

Both supplied hosted logs fail exactly `subagent-controls.py:261`,
`assert abs(before - after) < 100`, with `(1000, 1410)`:

- PR220 run 42271396220, job 128076576320, artifact 13531975662;
  `/tmp/spark-pr220-e2e-failed.log` and `/tmp/spark-pr220-browser-gates.zip`.
  Zip SHA256 `88f9a00154244d82cd26e5da66014f151381a7e201c69ddfcf730d2debcfa45e`.
- PR214 `/tmp/spark-pr214-e2e-failed.log` and
  `/tmp/spark-pr214-browser-gates.zip`, SHA256
  `7eebc6d23493d820577af9c6c3c96ba18a363e9f63ccd11da6fe101229509fe3`.

PR220 inspector report records only the preceding capability check, no page
errors, built_web true, and no completed asset-response checks. Empty asset
results are not proof of asset failure: verification occurs later in the flow.
Its inspected failure screenshot shows the tail of answer 21, prompt/answer 22
and prompt/answer 23, with Alpha child details and retained draft/attachment.
Failure DOM includes overscanned earlier rows and cannot establish visibility.
There is no hosted pre-detachment/pre-switch keyed geometry or measurement
trajectory in this artifact. The screenshot alone cannot establish displacement.

`git diff a12205a5737d7539875d6af16b3bb58c194e8edb HEAD --
src/spark_cli/web/src/components/ChatPanel.tsx
src/spark_cli/web/e2e/subagent-controls.py` is empty at the requested base.
This confirms these two source files are unchanged from SP01; it does not exclude
CSS, environment, layout or timing effects elsewhere.

Read the prior report via
`git show origin/docs/simplicity-performance-plan:docs/reviews/PR214-linux-inspector-2026-11-06.md`
and retained `/tmp/pr214-linux-ab/summary.json`, alongside archive inventory
`/Users/joe/.t3/artifacts/pr214-linux-inspector-2026-11-06/evidence.tar.gz`.
Prior emulated Linux base/candidate both passed all 11 checks, raw 1000→1000,
visible key `turn:user:db:39` at −161.25px. They also changed scrollHeight during
return. Sparse samples and candidate's first final-1000 frame do not prove
settlement at assertion. The prior report retains exact environment, fixture
hash and commands; this follow-up did not rerun or alter those artifacts.

## Static causal boundaries

At this base, `ChatPanel.tsx` has these distinct operations:

1. `updateFollowState` (1352–1384) stores the first **overscanned virtual item**
   as scroll-state anchor. It separately bookmarks the first DOM row whose
   bottom intersects the viewport top, storing key, viewport offset and raw top.
   With overscan 10 (safe mode 4), these keys can differ. This is a real selection
   difference, not proof that the hosted wrong value came from either selection.
2. ResizeObserver batches `resizeItem` calls in rAF (1281–1350). It captures
   the scroll-state anchor before measurement and schedules a later viewport
   correction. No explicit virtualizer resize-compensation override is supplied.
   An interaction with the library's own correction remains a hypothesis: the
   retained hosted evidence does not expose which adjustments executed or their
   order. The installed library source is absent in this checkout, so this report
   does not assert its exact resolved default behavior from recollection.
3. Session reset (566–571) restores a saved bookmark into detached state.
   After history is available, restoration runs for 30 animation frames
   (1386–1407), repeatedly restoring the saved key/offset, using scrollToIndex
   when that key is unmounted, and raw top only when no matching key exists.
   Consequently equal visible content does not in general imply equal raw top
   if preceding row sizes differ. This fact does not authorize changing the gate:
   the hosted before/after content semantics are unknown.
4. During restoration `updateFollowState` ignores scroll events. History,
   measurement and render work can remain pending independently of a visible
   detached pill. The fixture sets raw top 1000, dispatches scroll, waits 100ms,
   and checks top >500, bottom distance >240 and Jump to latest visibility.
   Those checks prove detachment, not measurement or bookmark settlement.
   Return uses the unchanged 1000ms delay. Neither fixed delay is demonstrated
   to be the hosted cause. A 30-frame loop also cannot be translated to a fixed
   elapsed duration under sparse/slow frames.
5. History prepend has its own keyed/height restoration path (1491 onward).
   The retained hosted artifact does not identify a prepend during the failing
   interval; prior passing traces reported 51 messages and has-earlier true.
   Do not infer a prepend merely from changing virtual scrollHeight.

## Remaining discriminating question and handoff

At the hosted `before=1000` capture, which keyed row/offset was visible and
bookmarked, and did that same content return at `after=1410`? Was raw top or
preceding measured row geometry still changing before navigation? Without that
pair, fixture race, intentional size compensation and production mis-restoration
remain observationally compatible with the retained scalar failure.

No minimal reproduction of the hosted 410px displacement has been established;
there is therefore no production patch proposal for SP02 and no justified fixture
synchronization patch. If the parent authorizes a future discriminating experiment,
it should target one specified ordering (late preceding-row measurement across
bookmark capture/return), retain original raw assertion and also prove keyed
content before/after. A reproduction must fail before and pass after its proposed
change, including the normal 11 checks. This is an evidence requirement, not a
request to launch new generic instrumentation or known-failing hosted runs.

No issue comments were sent: this assignment explicitly requires issue 207/196
updates only after a proven fixture fix. Parent can use this committed report as
the unresolved handoff. No PR, issue closure, merge, release or production overlap.

Validation: static source/log/report inspection, hosted screenshot visual review,
archive inventory, source comparison and artifact SHA256 checks only. No runtime
success or new regression-test coverage is claimed.
