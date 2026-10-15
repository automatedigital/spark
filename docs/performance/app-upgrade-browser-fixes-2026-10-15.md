# P09 focused browser repairs

Base `336797df`, branch `fix/p09-browser-virtualizer`. This is a scoped follow-up
to [the original gates](app-upgrade-browser-gates-2026-10-15.md), which remain
unchanged. [New raw evidence](app-upgrade-browser-fixes-2026-10-15.json) retains
source hashes, final captures, earlier failed attempts, request phases and log
hashes. **P09 remains open.**

## Repairs and source causes

- **ChatPanel measurement:** the failing stack runs through `commitAttachRef`
  into `measureElement` and a React update. The component also installed a second
  resize observer and cleared all keyed sizes on prepend. Ref attachment now
  only registers observation; one observer batches sizes into an animation frame
  and calls `resizeItem`. A prepend retains sizes by stable turn ID. Key callbacks
  remain stable across measurement-only renders. Removed rows are unobserved;
  pending measurement/anchor frames are cancelled on teardown. Existing history
  anchoring and bottom-following behavior remain exercised by the browser gate.
- **Sidebar anchoring:** React's scroll handler can precede the virtualizer's
  native offset listener. Searching `getVirtualItems()` then searches the old
  overscanned range, which may contain no rows at the new DOM offset. The trace
  shows `scrollTop=600` with visible `scale-032`, followed by an incorrect
  restoration to `1396` and `scale-073`. Capture now looks up the actual DOM
  offset across the complete measured model. Restoration uses one keyed pixel
  offset, protects a newer DOM scroll awaiting its native event, and disables
  competing native browser anchoring. Three regression tests cover stale observed
  offsets, paging with distinct pin/project placements and empty lists.
- **First title event:** request instrumentation found both slow requests and a
  separate dropped event. A title PATCH returned in 172 ms but sequence 1 never
  reached the browser; the later restore arrived as sequence 2. The pinned server
  only performs SSE journal replay when `after_sequence` is truthy, so cursor zero
  leaves a snapshot-to-subscription gap. The client now reconciles deltas once
  when a zero-cursor connection opens. Three transport tests prove recovery through
  the actual event parser/cursor, no additional healthy polling, and no extra
  fetch for nonzero server replay. No backend code changed.

No inspector, project dialog, ChatPage, subagent API/control, package/lockfile,
generated manifest, production bundle, PLAN or original evidence edits. No push,
PR, release or installed-package claim.

## Verification

Worktree-local `npm ci` used the existing nested lockfile and Node 22.22.1.
All Python fixture/server launches used the activated root venv,
`PYTHON=/Users/joe/Developer/github/spark/.venv/bin/python` and
`PYTHONPATH=$PWD/src`; every backend used temporary `SPARK_HOME` state. The
repository Playwright fallback was explicitly authorized after preview failures.

- `npx tsc -b --pretty false`: exit 0.
- `npm run lint`: exit 0.
- `npm test`: **411 passed in 72 files**, exit 0, including six new regressions.
- `node --check e2e/sidebar-scale.mjs` and `git diff --check`: exit 0.
- Final longthread: **5/5 passed**, aggregate exit 0. Every capture loaded all
  **39 earlier pages**, sampled **0 px anchor drift**, and recorded zero React/
  console errors and zero same-URL recovery navigations. The saved dark/1440
  screenshot was visually checked: the panel and measured turns remain visible
  without overlapping transcript rows.
- Final sidebar: **2/3 passed**, aggregate exit 1. **All three SSE anchor checks
  passed**, including the previously failing `scale-032` anchor. Selection
  (84.1–99.4 ms), local filtering (49.3–93.5 ms) and full-history search
  (288.5–389.5 ms) remained within their unchanged budgets in every attempt.
  Attempt 2 timed out the title probe: Chromium queued its PATCH **5515.1 ms
  before request start**, then received headers **9.4 ms** later. The harness's
  restore ran before that late PATCH; its eventual title overwrote the restore
  and the later Scale chat 000 click timed out after 15 seconds. This is retained
  as a failed attempt. Other title probes took 658.5 and 4610.8 ms. No title loss
  after a fast PATCH occurred in this final batch; title reliability remains open.
- Each longthread capture built to a new temporary directory. The unchanged
  bundle-budget script checked the final temporary build: **235.36 KiB gzip /
  600 KiB budget**, exit 0. Canonical `web_dist` was untouched.

The final gate commands, run sequentially without concurrent local unit/build
work, are:

```sh
node src/spark_cli/web/e2e/browser-gates.mjs --suite longthread --repeat 5 --output-dir /tmp/spark-p09-fixes-history-20261015-handoff
node src/spark_cli/web/e2e/browser-gates.mjs --suite sidebar --repeat 3 --output-dir /tmp/spark-p09-fixes-sidebar-20261015-handoff
```

Earlier batches are retained. The initial measurement repair passed longthread
5/5. A preliminary sidebar 3/3 pass was followed by instrumented anchor failures;
those are not erased or described as success. The full-model capture then
preserved all three anchors in the pre-handoff batch, which still failed on title
delivery and selection timing. These observations motivated the zero-cursor fix.

## Title latency and remaining acceptance

The successful diagnostic requests took 3.09–3.32 seconds overall. Chromium
reported 3.05–3.28 seconds before request start/DNS/connect, only 5–7 ms from
request start to response headers, and about 27–31 ms from the delivered event to
render. Thus delayed sidebar batching is not the cause of those samples.
Outstanding request captures include preview detection for old/new projects,
workspace tree/git/status/log calls, chat detail requests and SSE subscriptions.
Connection/resource scheduling under that fanout is a lead for the owning app
surfaces; its exact owner remains unproved. The zero-cursor repair addresses the
separate demonstrated delivery gap, not this entire latency distribution.

Final measurements are compared with raw P00 samples retained in the original
JSON. Dark, dev, 1440×900, DPR 1, provider-free synthetic fixtures on the same M2
Max host; shared host load remains uncontrolled. Nearest-rank p95 is the maximum
at these sample sizes. The title probe now switches to a full-history result and
back before PATCH, unlike P00, so its raw delta is not isolated rendering cost.
DOM update gaps are not transport packet gaps; heap is not full browser RSS.

| Probe | Final median / p95 ms | Change from raw P00 median / p95 |
| --- | ---: | ---: |
| Backend spawn to status | 856.8 / 1278.7 | 31.3% / 95.6% |
| 2,000-row useful render | 2010.5 / 2199.0 | 73.9% / 84.0% |
| First visible synthetic token | 241.2 / 284.2 | -4.6% / 11.4% |
| Visible stream update gap | 242.8 / 265.8 | 23.1% / 16.4% |
| 1,000-session useful render | 1276.1 / 1314.0 | 21.3% / 19.7% |
| Selection | 87.3 / 99.4 | 106.4% / 126.9% |
| Local filtering | 51.8 / 93.5 | 24.2% / 122.1% |
| Full-history search | 316.9 / 389.5 | 12.3% / 15.7% |
| Title update (changed flow from P00) | 2634.7 / 4610.8 | 7384.8% / 11427.0% |

Title timing statistics include only the two completed probes; the failed
five-second probe remains explicit above and in raw evidence. Other sidebar
probes include measurements completed before the later failure. Heap median/p95
was 46.71/56.95 MiB, +32.0%/+12.5% against raw P00. **Startup, render, stream-gap,
selection, filtering, search and heap regressions above 10% remain unresolved.**
The added one-time zero-cursor request is not evidence of a performance repair;
profile the integrated app under controlled load before closing that gate.

The full 18-case matrix, 10k-message search p95, integrated inspector/recovery,
canonical bundle/release, hosted CI and installed macOS/Windows acceptance remain
parent-owned gates. Retained performance budgets and assertions were not relaxed.
