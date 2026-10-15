# P09 request, stream and retained-heap attribution — 15 October 2026

**No query or render-CPU source defect was established. No application source
was changed. P09 remains open.** Monotonic probes locate stream delay mainly
before the flush callback, the earlier small-fixture search regression does not
reproduce, and both production versions retain approximately 0.52 MiB per repeated
navigation cycle. That common growth is an unresolved retention objection;
similarity to baseline does not establish that it is harmless.

[Evidence JSON](app-upgrade-performance-attribution-2026-10-15.json) contains all
11 attempts, raw summaries, additive gap decompositions, post-GC samples,
constructor deltas, sampled retaining paths and artifact hashes. **Five attempts
exit 0; six exit 1.** Failed assertions were unexpected, retained results of the
extended diagnostic flow, not deliberately expected failures or passing gates.
Original reports, failures, assertions and budgets remain unchanged.

## Scope and controls

- Baseline: `2a41925cd535a273fef71a7eebb47a022f14fe21`, the original archive at
  `/tmp/spark-performance-ab-20261015-e0e1315d/baseline`. Current:
  **`60fae7c62f3303fb2e7e9ff73334a5d7d4d6d9f0`** in this isolated worktree.
  This is a separate comparison from the parent's later navigation candidate
  (`ebae486` / `8a1aa73`) and its canonical browser/package acceptance.
- Actual measured Node: **v22.22.1**. Before capture, `command -v node` returned
  **`/Users/joe/.nvm/versions/node/v22.22.1/bin/node`**. Every attempt records
  `node:v22.22.1`; the wrapper rejects other majors and launches its Node children
  using `process.execPath`. A fresh post-capture check returned the same version
  and exact executable. No Homebrew `node@22` path was prepended or assumed.
  Python: activated `/Users/joe/Developer/github/spark/.venv/bin/python` (3.11.7).
  M2 Max / 64 GiB host; Chromium 147.0.7727.15 / Playwright 1.59.1.
- This worktree received its own `npm ci`; the baseline retains its independent
  dependency installation. Existing nested lock SHA-256:
  `53e7f64f5aa5eb3d4abf82859eafb76a3dafef8ec018457c1e08f9e633347f9d`.
- Root explicitly cleared the window before capture and held coordinated heavy
  work until measurement-done. Captures ran sequentially, 18:47:48–18:56:54 UTC;
  measurement-done/process verification was sent at 18:57:56 UTC. Host snapshots
  remain attached to every attempt. Background OS/user/VM work was not isolated.
  A pre-existing T3 preview browser was left alone; no owned capture process
  survived cleanup.
- Temporary `SPARK_HOME`, loopback unavailable provider URL, synthetic local
  streams, no external inference/sends and no user-profile writes. Source,
  canonical bundle, lockfile, PLAN, gateway and child navigation were untouched.

## What was instrumented

The new helper reuses a retained copy of the existing matching-source driver.
Checked Vite transforms add marks in the actual `useChatStreamController`
enqueue, schedule, timeout, RAF, flush and state-update paths, and a ChatPanel
layout effect immediately after the DOM commit. MutationObserver samples remain
the existing visible-text observation. A wrapped ResizeObserver records callback
duration/count; it does **not** isolate every virtualizer/layout operation.

The real backend is wrapped with a pure ASGI request/response marker, without a
new task/thread boundary. Actual `SessionDB.__init__`, `_init_schema`,
`search_messages` and `close` calls record monotonic wall and thread-CPU spans.
Constructor and schema are nested; never sum them as independent phases.
Browser fetch invocation, headers and JSON completion are recorded separately.
These spans do not measure socket queueing before ASGI, and browser/server
timestamps are not treated as a synchronized network trace.

Each thread attempt loads the same 2,000-row fixture through all 39 earlier pages,
then captures nine 16-token streams. The first has ordinary 60 ms delays; eight
diagnostics vary only the **first** token delay through 0/20/40/60 ms twice.
Subsequent producer delays remain 60 ms; the existing 80 ms batching policy stays
intact. Initial-delay changes are phase exploration, not a controlled browser
frame-clock phase lock. Each attempt retains all samples, including single-update
streams where no meaningful inter-update maximum exists.

Heap diagnostics run before the stream trials. After full history, the browser
revisits only the existing 50-row and 2,000-row chats for 12 cycles. Probe histories
and resource timings are cleared before each forced GC; samples cover cycles
0–12 and snapshots cover cycles 2 and 12. Current code may restore a cached tail
after navigation; it does not reload 39 pages every cycle. This is repeated
navigation retention, not repeated full-history loading. GC/snapshot time is
excluded from stream timings. Fixed-flow growth still needs an owner and an
uninstrumented/quiescent comparison before it can be called a leak.

Production diagnostics build each selected source with the same probe transform
into its **own temporary output**, then serve it through Vite preview with the
same local API proxy. These are instrumented production assets, not the canonical
Python-served release bundle or an installed app. Production builds finish before
browser capture; no startup benchmark is claimed.

## Stream phases: waiting is located; a CPU owner is not established

Per-attempt median / nearest-rank p95 of maximum DOM-update gaps, ms:

| Mode / attempt | Baseline | Current |
| --- | ---: | ---: |
| Dev pair 1 | 191.0 / 203.1 (n=8) | 154.0 / 209.9 (n=9) |
| Dev pair 2 | 215.0 / 229.3 (n=7) | 180.2 / 210.8 (n=9) |
| Production diagnostic | 213.7 / 272.3 (n=6) | 201.9 / 238.6 (n=9) |

These are descriptive diagnostics, not independent population estimates or a
replacement for the earlier ordinary +22.1% median / +14.7% p95 result. Baseline
has **six additional streams with only one visible update and zero token-enqueue
marks**: three dev and three production. All 54 streams eventually display all
16 tokens, but those six appear through final history/snapshot rendering and do
not establish streaming continuity. Their absent gap values are explicit, not
converted to zero or silently dropped from counts. The table conditions its gap
statistic on having multiple updates. Failed attempts remain failed.

For current dev's 209.9 ms example, the actual phases add exactly:
**39.8 ms previous DOM → next schedule + 87.0 ms timeout interval + 77.9 ms
timeout → flush/RAF callback + 5.2 ms flush → DOM = 209.9 ms**.
Current production's largest 238.6 ms example is
**46.1 + 81.4 + 109.0 + 2.1 ms**. Baseline production's 272.3 ms example is
**18.7 + 81.2 + 169.7 + 2.7 ms**.

Actual timeout medians stay approximately 81–82 ms. Production flush → layout
effect medians are **2.2 ms baseline / 1.8 ms current**; corresponding RAF-wait
medians are **77.9 / 53.7 ms**. The former is a commit interval, **not pure CPU
self-time**. The latter can contain other browser work and frame scheduling;
it is not proved idle time, GPU delay, a particular source function or an OS
cause. Production still has long waits, so development React alone does not
explain them. No batching removal, throughput change or budget relaxation is
justified. Confidence is high about these local phase locations, low about a
general source cause or stable relative maximum-gap distribution.

## Search: no reproduced query regression

Each sidebar attempt performs 20 warm browser searches and 20 direct local HTTP
searches against the actual SQLite handler. Browser searches require a real
successful response containing `scale-499` and a visible result; they include the
unchanged 250 ms debounce and driver observation overhead. Fixture remains 1,000
sessions / ten projects / one historical matching message. This does not replace
the previous dedicated 10,000-message result.

Median / nearest-rank p95, ms; 20 samples per cell:

| Probe | Baseline pair 1 | Current pair 1 | Baseline pair 2 | Current pair 2 |
| --- | ---: | ---: | ---: | ---: |
| Browser flow | 296.2 / 307.0 | 295.6 / 308.3 | 335.6 / 358.6 | 310.3 / 335.5 |
| Browser fetch → headers | 6.35 / 11.60 | 5.75 / 9.50 | 9.15 / 12.50 | 9.30 / 13.20 |
| Direct HTTP | 3.01 / 5.20 | 2.75 / 3.73 | 5.11 / 8.40 | 3.13 / 3.84 |

Browser-request ASGI → headers medians are **3.50 / 2.97 ms** in pair 1 and
**5.47 / 5.17 ms** in pair 2 (baseline/current). Constructor medians are
**0.67 / 0.66** and **1.11 / 1.09 ms**; FTS medians are **0.20 / 0.18** and
**0.36 / 0.27 ms**. The constructor's nested schema checks are also recorded.
No current query/constructor regression accounts for the earlier 36–84 ms
request tail in these captures. That historical tail's exact cause remains
unresolved; its original samples remain valid observations. No query, schema
cache, connection-sharing or executor change was made.

## Heap: shared growth remains an objection

OLS uses cycles 2–12 after the first two navigation warm-ups. Cycles are serial,
correlated samples; R² describes a fit, not confidence in leak causality.

| Capture | Baseline MiB/cycle | Current MiB/cycle |
| --- | ---: | ---: |
| Dev pair 1 | 0.630 | 0.588 |
| Dev pair 2 | 0.537 | 0.469 |
| Production | **0.5192** | **0.5281** |

Production cycle-2 → cycle-12 retained heap is **12.31→17.68 MiB baseline** and
**12.19→17.53 MiB current**. Slope delta is **+1.7%**, R² **0.994 / 0.999**.
No plateau appears in this bounded flow. This does not reproduce a new 2.21 MiB
retained offset, establish harmless growth or exclude an existing source defect.
There are two dev processes and only one production process per source; no
unbounded-session, long-idle, uninstrumented or installed-platform claim follows.

Post-GC snapshot differences group **shallow live-node sizes**, not dominator
retained bytes. Current's largest generic groups include Object +556,732 bytes,
object-element arrays +398,796 bytes, Array +257,872 bytes and Context +106,420
bytes. Repeated long timeline-signature strings and multiple old turn objects
are present. The report preserves both snapshots and their group deltas rather
than attributing all added bytes to those constructors or to inspector code.

Source ownership leads at `60fae7c6`:

- **Older timelines:** a sampled production root path, excluding weak edges and
  ephemeron value edges, runs from the active `spark:compose` EventListener to
  `ChatPanel.tsx:1032–1039`, then through shared render contexts alternating
  `handlePromoteToBrief` (`:997`) and `attachPath` (`:934`), finally reaching
  older `threadTimeline.turns` arrays (`:1153–1176`). One sampled path has 14
  prior callback-context pairs. This is more than only the active timeline.
  Their draft setters are scoped in `hooks/useChatDraft.ts:32–37`. Generated
  source locations are recorded with snapshot object IDs: script 7,
  zero-based `19:467`, `17:108624`, `17:107507` in `index-YFJYGuU4.js`.
- **Bounded active reference:** a separate path through the safe-render
  PerformanceObserver callback (`ChatPanel.tsx:479`) reaches
  `timelineTurnsRef.current` (`:1209–1210`). That ref is assigned the current
  timeline and does not alone demonstrate historical accumulation. Its observer
  disconnects at `:499`.
- **No listener-count proof:** the compose effect removes its previous listener
  at `:1038`; search keydown cleanup is at `:1027`. A rooted active listener can
  retain shared lexical contexts without any duplicate subscriptions. Snapshot
  paths do not count active listener registrations, prove an ever-growing
  subscription set or identify all dominating owners.
- `lib/threadTimelineModel.ts:225–227` stores signatures/source messages in
  WeakMaps; signature insertion is at `:659–666`. An initial path through their
  ephemeron value edges is insufficient evidence of a strong leak. The later
  diagnostic explicitly excludes those edges and targets the associated turn
  keys. No dominator calculation or source-only callback-scope ablation was run.

**P09 “no unbounded subscriptions” is not established by this report.** The
common growth and old-context paths justify a separate narrow ownership task,
not a claim of an introduced leak or a verified repair. Root assigned that
follow-up separately; no further capture or speculative source edit was made.

## Attempt ledger and exact failures

Chronological capture order; every attempt is bounded to 240 seconds, with no
attempt-level timeout:

| Attempt directory suffix | Exit | Result |
| --- | ---: | --- |
| dev-b1-thread | 1 | Extended reload diagnostic: cancelled file-tree fetch emits console error |
| dev-c1-thread | 0 | All original driver assertions pass |
| dev-b1-sidebar | 0 | Original selection/filter/search budgets pass |
| dev-c1-sidebar | 0 | Original selection/filter/search budgets pass |
| dev-c2-thread | 1 | Two cancelled file-tree fetch console errors |
| dev-b2-thread | 1 | Stable anchor missing: before row exists, after null, drift null |
| production-c1-thread | 0 | Temporary production assets; original assertions pass |
| production-b1-thread | 1 | Helper Vite build fails before browser: `/tmp` versus `/private/tmp` index path |
| production-b2-thread | 0 | One bounded retry after helper realpath correction; assertions pass |
| dev-c2-sidebar | 1 | Original selection 158.6 ms exceeds strict 100 ms budget |
| dev-b2-sidebar | 1 | Original selection 156.4 ms exceeds strict 100 ms budget |

These are not strict xfails. Diagnostic intent does not make unexpected assertion
failures acceptable. All six completed thread captures still loaded 39 pages and
recorded nine complete 16-token traces; all four sidebar captures finished their
20+20 search diagnostics before final gate evaluation. Their data can inform
attribution without converting their exit status to passing acceptance.
The failed baseline build error is a helper defect, not a Spark source defect:
Vite received an emitted index asset name beginning `../../.../private/tmp/...`.
The helper now canonicalizes its root with `realpath`; it does not modify the
archive. Both final production outputs use the same source-mark injection;
the helper revision difference is recorded, not hidden.

Artifacts have prefix `/tmp/spark-performance-attribution-20261015-96a3d59e-`.
Current production snapshots are in `production-c1-thread/heap-cycle-{2,12}.heapsnapshot`;
baseline snapshots are in `production-b2-thread/heap-cycle-{2,12}.heapsnapshot`.
Sampled graph paths are `/tmp/spark-attribution-heap-key-paths-current-production.json`;
the initial insufficient WeakMap traversal is separately retained. Raw generated
drivers retain the then-valid backend helper path under `web/e2e`; the identical
backend helper was subsequently moved to `scripts/` to keep Python diagnostics
outside the application package. Final preparation checks use that new path.

## Reproduction and verification

Only run captures after coordinating another exclusive window. Output paths
must be new. The selected source needs its own matching-lock `npm ci`.

```sh
source /Users/joe/Developer/github/spark/.venv/bin/activate
export PYTHON=/Users/joe/Developer/github/spark/.venv/bin/python
export PYTHONPATH=/absolute/selected-source/src
/Users/joe/.nvm/versions/node/v22.22.1/bin/node \
  src/spark_cli/web/e2e/performance-attribution.mjs \
  --source /absolute/selected-source --source-sha EXACT_SHA \
  --probe thread --heap --mode production --output-dir /tmp/NEW-DIRECTORY
# --probe sidebar: 20 browser + 20 direct search samples, no heap capture.
# --prepare-only: checked source seams and generated syntax, no servers/build/browser.
python scripts/summarize_performance_attribution.py \
  --prefix /tmp/spark-performance-attribution-20261015-96a3d59e \
  --output /tmp/NEW-SUMMARY.json
```

Both final `.mjs` helpers and generated preparation drivers pass `node --check`;
the two Python helpers pass Ruff and compilation; `git diff --check` passes.
Summary validation checks 11 attempts / 5 passing exits / 54 final 16-token
streams / four sets of 20 browser and 20 direct searches, plus exact additive
gap decompositions and synthetic percentile/slope calculations. Original gate
failures above are included, not waived. Application unit/full suites, final
canonical bundle, full 18-case matrix, actual gateway readiness, hosted CI,
installed desktop packages and rollout remain parent-owned separate gates.
