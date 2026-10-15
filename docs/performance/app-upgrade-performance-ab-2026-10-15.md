# P00/P09 controlled-source performance comparison — 15 October 2026

**The earlier large startup, useful-render, selection and filtering regressions
were not reproduced by the matching-source probes. P09 remains open:** visible
stream gaps exceed the 10% investigation threshold in the ordinary samples;
small-fixture search and raw heap have slower p95 tails. No production source was
changed. [Evidence JSON](app-upgrade-performance-ab-2026-10-15.json) preserves raw
samples, exact attempts/exits, diagnostics, exclusions and artifact hashes.

## Sources, controls and retained failures

- Baseline: `2a41925cd535a273fef71a7eebb47a022f14fe21`, extracted using
  `git archive` into a temporary snapshot. Its runtime source is identical to
  `0ed3654b`; the intervening changes are documentation only.
- Current: `5311eab6d78347375b44133abec1851d8f0eb54d`. Later parent bundle,
  evidence and gateway changes are outside this comparison.
- Same M2 Max / 64 GiB host, Node **22.22.1**, Python **3.11.7** from activated
  `/Users/joe/Developer/github/spark/.venv`, Playwright **1.59.1**, Chromium
  **147.0.7727.15**. Each source has its own `npm ci`, the same existing nested
  lockfile (SHA-256 `53e7f64f5aa5eb3d4abf82859eafb76a3dafef8ec018457c1e08f9e633347f9d`),
  and an independent Vite cache. Dark, dev, 1440×900, DPR 1; same headless browser
  launch protocol and local HTTP/1.1 Vite proxy on both sides.
- Parent confirmed an idle test/build/browser window before capture; the
  navigation agent was restricted to lightweight source work. All captures
  finished before the measurement-done signal, after which parent validation
  resumed. OS, user-browser, VM and other background processes remained active;
  before/after `ps` snapshots are retained. This controls source, fixtures and
  coordinated heavy workloads, **not every background load on the shared host**.
  Available disk before setup was 25 GiB; no cleanup was performed.
- Every backend uses temporary `SPARK_HOME`, `PYTHONPATH=<source>/src`, a
  loopback-only unavailable provider URL and synthetic streams. No user state,
  external provider calls, gateway sends, production build or package operation.
- One cold thread warm-up per source was retained and excluded. Every measured
  attempt launches a fresh backend/browser/context after each source's bytecode
  and dependency caches are warmed. Ordinary thread pairs alternate A/B, B/A,
  A/B. Final matching sidebar pairs follow the same order.
- **22 bounded attempts: 21 exit 0, one exit 1; no attempt timeouts.** The failed
  first baseline sidebar probe used the current-only ARIA label. Its screenshot
  shows the card was visible. A matching title-text locator inside `role=button`
  supports both versions. The first two sidebar rounds are diagnostic only;
  final comparisons use rounds 3/4/5. The timeout, logs, screenshot and all
  earlier timings remain preserved. No assertions or budgets were relaxed.

Raw artifacts remain under `/tmp/spark-performance-ab-20261015-e0e1315d/`.
Complete generated drivers, reports, HTTP traces, screenshots, CPU profiles,
startup markers, logs and host samples are individually hashed in the JSON.
Original P00/P09 reports, captures and gate scripts were not edited.

## Matching repeated samples

Milliseconds unless indicated; **median / nearest-rank p95**, three samples per
source. At n=3, p95 is the maximum; these are bounded observations, not stable
population percentiles. Deltas compare the new matching runs with each other,
not new runs with historical P00 absolute values.

| Probe | Baseline | Current | Median / p95 delta |
| --- | ---: | ---: | ---: |
| Web backend spawn → status | 743.1 / 745.2 | 713.2 / 736.8 | −4.0% / −1.1% |
| 2,000-row thread useful render | 1456.2 / 1477.0 | 1374.5 / 1403.3 | −5.6% / −5.0% |
| First visible synthetic token | 204.3 / 231.4 | 206.8 / 227.5 | +1.2% / −1.7% |
| Maximum visible update gap | 170.8 / 189.7 | 208.5 / 217.6 | **+22.1% / +14.7%** |
| JS heap after full history, MiB | 38.83 / 50.54 | 41.10 / 56.78 | +5.9% / **+12.3%** |
| 1,000-session sidebar useful render | 1107.0 / 1264.1 | 1075.5 / 1120.4 | −2.8% / −11.4% |
| Selection, gate-style observed identity | 69.5 / 70.1 | 70.0 / 72.6 | +0.7% / +3.6% |
| Selection, browser DOM mutation | 47.2 / 48.1 | 50.8 / 50.8 | +7.6% / +5.6% |
| Loaded-title filtering | 43.1 / 43.5 | 44.9 / 46.6 | +4.2% / +7.1% |
| Full-history search including debounce | 280.7 / 283.6 | 307.5 / 347.3 | +9.5% / **+22.5%** |

The thread fixture is the existing deterministic 50/500/2,000-row seed, filtered
to the 2,000-row dark/1440 case. Initial useful render loads the bounded latest
50-message page; it does not mount all 2,000 messages. All six ordinary attempts
then loaded **39 earlier pages** and rendered all 16 stream tokens with **zero
page/console errors**. Current measured **0 px** drift in all three samples;
baseline measured **−654 / 0 / 0 px**. Baseline trial 1 is an observed anchor
correctness failure even though its driver exits 0: the original driver requires
a finite drift sample, not zero drift. Its timing remains included. Both
diagnostic attempts and both warm-ups measured 0 px and passed the unchanged
history assertions.

Sidebar fixtures contain 1,000 sessions / 10 projects and one historical message
in `scale-499`, with fixed timestamp base `1700000000`. The purpose-built probe
uses the actual Inbox surface on both versions and retains the 100 ms selection,
100 ms local filtering and 600 ms full-history search budgets. All six final
sidebar attempts pass. It does not claim the newer organization/paging gate runs
on P00, which lacks those APIs. Those correctness gates remain parent-owned.

## Findings and actionable boundaries

**Startup and useful render: no reproduced source regression.** Instrumented
`web_server` import medians were 636.6 ms baseline / 622.6 ms current; the marker
before `uvicorn.run` was 649.5 / 634.2 ms. These are nested phases of readiness,
not additional times to sum. Readiness polling is 25 ms on both sides instead of
historical 200 ms, so historical absolute readiness comparisons are unsuitable.
The app's Vite module waterfall reaches DOMContentLoaded at median 902.0 / 889.9
ms. Browser task time through first useful thread render falls 457.4 → 388.1 ms;
script time falls 310.8 → 243.3 ms. Guarded **ChatPanel** commit counts fall 10 → 5;
these counters are not a whole-app React Profiler duration.

Full-history work also improves: median guarded ChatPanel commits **821 → 213**
(−74.1%), and the first-useful-to-full-history phase **11,268.6 → 5,987.5 ms**
(−46.9%). The source diff's stable turn keys, retained size cache on prepend and
batched ResizeObserver ownership provide a concrete mechanism consistent with
these observations. This is not a source-only ablation attributing every saved
millisecond. The old 31–96% startup, 74–84% render and roughly doubled selection
figures cannot be treated as established source costs after this matching run.
Historical host conditions and differing instrumentation remain plausible
contributors; their exact individual contribution is not recoverable.

**Stream gaps: the measured threshold remains open; a source cause is unproved.**
The ordinary current gaps are 196.3/208.5/217.6 ms versus
189.7/170.8/143.9 ms. Browser EventSource callback arrival maxima are
70.8/72.6/72.8 ms baseline versus 70.3/71.5/111.7 ms current. Thus the visible gap
cannot be described as the same-sized transport gap. Both source versions use
the unchanged **80 ms buffered flush followed by requestAnimationFrame**, while
the producer requests 60 ms delays. Two- versus three-token visible groups shift
the maximum substantially. Current has seven or eight visible updates; baseline
has eight. Median per-token event-to-DOM delay per run is
75.1/57.9/75.4 ms baseline versus 67.5/68.1/85.1 ms current; none is pure UI CPU.

The separate forced-GC/1 kHz CPU-profile pair reverses the gap direction:
**206.1 → 146.1 ms**. Its largest sampled JavaScript costs are development React
`jsxDEV`/`createElement` and ChatPanel work; current does not show a higher sampled
self-time in those dominant functions. Profiling/GC changes execution, so this
pair neither cancels the ordinary result nor proves a repair. It does refute
claiming a demonstrated consistent CPU bottleneck from the ordinary maximum
alone. Proposed next probe: mark token enqueue, scheduled flush, actual flush,
React commit and row measurement with monotonic timestamps; vary arrival phase
against the unchanged 80 ms timer. Compare a production-assets pair separately.
Do not remove batching, change the throughput policy or relax the budget on the
present evidence.

**Search tail: located before response headers, exact backend owner unresolved.**
Matching small-fixture requests take **17.1/21.5/18.1 ms** baseline versus
**43.0/36.4/83.6 ms** current. Request-start-to-headers accounts for nearly all of
that interval; response-to-profile-sample is 5.5–5.8 ms versus 5.7–23.5 ms. The
completed resource waterfall shows no other completed request overlapping those
search requests; persistent SSE connections are not ruled out by that observation.
This is evidence against attributing the whole delta to sidebar DOM batching.
It does not identify SQLite query CPU, constructor/schema work, event-loop delay
or another backend function. The search handler still opens `SessionDB` and runs
FTS synchronously; the constructor initializes/checks schema. Proposed next step:
measure those phases in the actual handler before changing query plans,
connection ownership or executor placement. No current SQL function regression
is asserted from request timing alone.

**Heap: collect before attributing the tail to retention.** Ordinary baseline
samples span 26.9–50.5 MiB and current 40.6–56.8 MiB. A separate forced-GC pair
retains **20.37 → 22.58 MiB**, an increase of **2.21 MiB / 10.9%**. One pair cannot
establish a leak or explain owning objects. Current loads additional inspector,
capability and organization code, but their retained-byte contribution is not
measured. Proposed next step: repeated identical navigation/GC snapshots grouped
by constructor/module with a retained-heap slope. Preserve inspector, cursor and
scroll recovery behavior until ownership evidence justifies a targeted change.

## Dedicated 10,000-message browser search

One dedicated fixture per source contains **10,000 actual SQLite messages** in
`scale-499` with 100 matching messages, alongside the same 1,000 sessions and ten
projects. After the first search, three warm searches each require a successful
real search HTTP response containing the fixture session and a visible result.
Input-to-observation includes the debounce, API/SQLite, DOM and Playwright fill/
wait overhead; it is a conservative local browser-flow measurement.

- Baseline warm samples: **303.5, 322.0, 372.9 ms**; median / p95 **322.0 / 372.9**.
- Current warm samples: **363.4, 327.9, 317.2 ms**; median / p95 **327.9 / 363.4**.
- Both attempts **exit 0** and pass the unchanged **p95 ≤500 ms** assertion.

This supplies a bounded browser result for the warm local target, beyond the
previous SQLite-only ~11/13 ms result. It is one fixture/run per source, with
three warm queries; production assets, other query distributions and large-scale
population percentiles remain untested. No provider latency is included.

## Reproduction and verification

The new helper generates retained instrumented drivers without editing their
source, existing gates, manifests, locks or bundles. It rejects reused output
paths and mismatched locks, requires Node 22 plus an activated venv, preserves
failures/screenshots, and bounds each attempt to 240 seconds. The internal
sidebar helper is launched through `performance-ab.mjs`, not directly.

```sh
source /Users/joe/Developer/github/spark/.venv/bin/activate
export PYTHON=/Users/joe/Developer/github/spark/.venv/bin/python
export PYTHONPATH=$PWD/src
# Baseline snapshot: extract git archive 2a41925 into a new directory, then
# run npm ci in its src/spark_cli/web. Run npm ci independently in this checkout.
node src/spark_cli/web/e2e/performance-ab.mjs --source /path/to/baseline --source-sha 2a41925cd535a273fef71a7eebb47a022f14fe21 --probe thread --output-dir /tmp/new-ab-baseline-thread
node src/spark_cli/web/e2e/performance-ab.mjs --source "$PWD" --source-sha 5311eab6d78347375b44133abec1851d8f0eb54d --probe sidebar --output-dir /tmp/new-ab-current-sidebar
# Other probe: --probe search10k. Separate GC/CPU diagnostic: --probe thread --diagnostic.
# Use --prepare-only to generate/syntax-check without starting servers/browser.
```

Run one cache warm-up per source, then alternate three pairs per probe without
concurrent builds/tests. Keep diagnostic captures separate. The JSON records
exact source SHA, command arguments, generated-driver hashes, ordering,
start/end times, exclusions and exits for the completed window.

Both new `.mjs` files and both generated preparation drivers pass `node --check`;
`git diff --check` passes. All final matching attempts, both diagnostics and both
10k attempts exit 0. The locator failure and the baseline drift observation remain explicit. Production source
is unchanged, so no new Python/unit-suite claim is made.

Unresolved acceptance: ordinary stream-gap threshold, small-fixture search p95,
raw heap p95 and limited post-GC attribution; background-host control; full
18-case matrix, hosted CI, production-source A/B and installed platforms. Web
backend readiness is not actual gateway readiness. EventSource callback arrival
is not wire packet arrival. DOM intervals, heap and sampled CPU are distinct
measurements. Parent owns final integrated browser/build/package gates. No push,
PR or release was performed, and no PLAN checkbox is closed by this report.
