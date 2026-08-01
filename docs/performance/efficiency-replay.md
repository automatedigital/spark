# Efficiency replay report

Captured on 2026-08-01 on the same macOS host and Spark virtual environment.
The deterministic workload is fixture version `1.0.0`, pinned to provider
`fixture`, model `deterministic-replay-v1`, and reasoning effort `medium`.
The committed baseline contains three trials per case. The candidate contains
five trials per case and identifies source commit `64270e5a`; its report records
`source_dirty: true`, so the raw report, rather than that commit alone, is the
authority for these numbers.

## Replay latency and request size

Values are milliseconds. Prompt-token and serialized-snapshot counts were
identical between conditions, which confirms that these timing comparisons did
not obtain their gains by silently changing the fixture input.

| Case | Baseline median / p95 | Candidate median / p95 | Median change | Prompt tokens | Snapshot bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| Direct answer | 8.790 / 10.416 | 6.153 / 7.367 | -30.0% | 16 | 57 |
| Code edit | 9.095 / 11.324 | 5.848 / 6.443 | -35.7% | 127 | 114 |
| Multi-tool research | 15.830 / 15.962 | 5.784 / 8.090 | -63.5% | 115 | 94 |
| Large-file read | 15.073 / 16.608 | 6.295 / 6.343 | -58.2% | 88 | 104 |
| Long session | 7.763 / 16.406 | 6.533 / 7.473 | -15.8% | 3,087 | 11,865 |
| Reconnect | 9.162 / 18.355 | 17.645 / 29.591 | **+92.6%** | 23 | 86 |
| Concurrent chats | 10.922 / 12.153 | 6.558 / 6.997 | -40.0% | 18 | 67 |

The reconnect fixture is a measured regression: its candidate median is 8.483
ms slower and p95 is 11.236 ms slower. It still performs exactly one reconnect
and one recovery action with zero healthy HTTP polls in every trial, and the
live browser restart test recovered authoritatively without a stuck `Working`
state. This should remain a monitored latency budget rather than being described
as a speed improvement.

Fresh-process imports improved materially:

| Import | Baseline median / p95 | Candidate median / p95 | Median change |
| --- | ---: | ---: | ---: |
| `core.run_agent` | 781.956 / 2,214.524 ms | 110.386 / 113.275 ms | -85.9% |
| `spark_cli.main` | 153.138 / 249.150 ms | 76.811 / 106.984 ms | -49.8% |

The separate five-process lazy-startup measurement, taken from exact commits on
the same host and environment, corroborates the import result. Importing
`core.run_agent` fell from a 0.501152-second median at `43f2f9c4` to 0.105458
seconds at `f481414d` (-79.0%). Loaded modules fell from 1,428 to 415 (-70.9%)
and median peak RSS fell from 91,504 KiB to 43,024 KiB (-53.0%). Candidate p95
was 0.147947 seconds, below both the 0.45-second budget and 0.35-second stretch
budget.

## Token, cache, tool, and output accounting

The request ledger preserves separate conversation, schema, injected-context,
and tool-result token buckets. Fixture medians are unchanged between baseline
and candidate. The largest case is the long-session replay at 3,087 estimated
prompt tokens: 2,671 conversation, 415 tool-result, one schema, and zero
injected-context tokens. Provider cache-read and cache-write counters are
implemented, but the hermetic fixture provider does not exercise a real
provider cache, so this replay makes no cache-hit-rate claim.

The response-efficiency evaluation scored 39 baseline and 39 candidate rows
with the same pinned fixture model. Median output fell from 42.5 to 7.0 tokens,
an 83.53% reduction. Candidate correctness, autonomy, actionability, safety,
and concision each scored 5.0; weighted quality improved from 4.9692 to 5.0,
with no blocking findings and no follow-up turns. Both conditions had 100% tool
success, zero fallbacks, 1 ms median routing latency, and reported cost of
$0.00. The release decision passed.

## Scheduler and shared runtime

Four independent simulated 500 ms tools completed in a 0.5091-second median
and 0.5113-second p95 across seven trials, comfortably inside the 1.2-second
budget. The shared runtime created one loop and one credential-scoped client;
119 of 120 client acquisitions reused it. Twenty concurrent simulated requests
completed in 0.0073 seconds with a normalized 20.59x speedup. One thousand
randomized batches, including at least 100 cancellations, produced 1,000
complete deterministic result sets with no failures, retries, orphaned workers,
callbacks after close, or shutdown leaks.

## Persistence and event delivery

The fixture's create-plus-message path remains two SQLite write transactions in
both conditions. Candidate median measured DB write time was 0.555 ms versus
0.472 ms at baseline, a 0.083 ms (+17.6%) regression. Fresh-database growth rose
from 53,560 to 90,640 bytes (+69.2%) because the candidate creates the richer
ordered-event/checkpoint schema. That is a one-time fresh-database footprint,
not evidence of lower storage use. The dedicated 100-message hot-path test is
the relevant amplification measure: it uses one transaction and more than 50%
fewer encoded bytes than repeatedly materializing full snapshots.

Session events have a session-local monotonic sequence and idempotency key.
Messages, tool results, usage, status, counters, and their projection commit in
one iteration transaction; subscribers are notified only after commit. Settled
checkpoints bound replay, legacy rows are backfilled with restart-safe keys, and
the old JSON export remains readable. Crash-boundary, 20-writer ordering, and
export-equivalence tests cover recovery without duplicate or cross-session
events.

## Browser and network result

The live Playwright 1.62 / Chromium 151 acceptance run exercised a roughly
140,000-character result, simultaneous chats, switching, hard refresh,
background/foreground, and a backend restart at 390, 820, and 1,440 px. The
12-second settled healthy window made zero status, sessions, event, snapshot,
delta, turn-status, or stream-snapshot requests. It produced no application
console or page errors and no non-2xx response before the forced outage. No
selected or background session remained stuck in `Working`. Initial render and
selection took 30, 25, and 28 React commits respectively, and document width
never exceeded viewport width.

## Evidence and interpretation

- Raw baseline: `tests/efficiency/fixtures/baseline-v1.json`
- Raw candidate: `docs/performance/efficiency-candidate-v1.json`
- Response evaluation: `evals/response_efficiency/results/fixture-summary.json`
- Scheduler/runtime: `docs/performance/scheduler-runtime-benchmark.json`
- Lazy startup: `docs/performance/lazy-startup-benchmark.json`
- Ordered persistence: `docs/performance/session-events.md`
- Live browser acceptance: `docs/performance/browser-efficiency.md`

The candidate demonstrates large import, general replay, scheduler, browser,
output-token, module-count, and RSS gains without a scored quality loss. The
result is not uniformly faster or smaller: reconnect latency, the tiny
create-plus-message DB write time, and fresh-schema bytes regressed. Those three
measurements are explicitly retained as follow-up budgets; the reconnect and
fresh-database results must not be used to claim across-the-board latency or
storage improvement.
