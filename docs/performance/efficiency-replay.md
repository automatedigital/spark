# Efficiency replay report

Captured on 2026-08-01 on the same macOS host and Spark virtual environment.
The deterministic workload is fixture version `1.0.0`, pinned to provider
`fixture`, model `deterministic-replay-v1`, and reasoning effort `medium`.
The committed baseline contains three trials per case. The final candidate
contains five trials per case and identifies exact clean source commit
`4f38048858ca24565722eb26705a454cb4b71d2c` with `source_dirty: false`.

## Replay latency and request size

Values are milliseconds. Prompt-token and serialized-snapshot counts were
identical between conditions, which confirms that these timing comparisons did
not obtain their gains by silently changing the fixture input.

| Case | Baseline median / p95 | Candidate median / p95 | Median change | Prompt tokens | Snapshot bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| Direct answer | 8.790 / 10.416 | 6.794 / 7.500 | -22.7% | 16 | 57 |
| Code edit | 9.095 / 11.324 | 6.585 / 6.714 | -27.6% | 127 | 114 |
| Multi-tool research | 15.830 / 15.962 | 6.634 / 7.555 | -58.1% | 115 | 94 |
| Large-file read | 15.073 / 16.608 | 6.509 / 6.555 | -56.8% | 88 | 104 |
| Long session | 7.763 / 16.406 | 6.510 / 6.596 | -16.1% | 3,087 | 11,865 |
| Reconnect | 9.162 / 18.355 | 6.475 / 6.612 | -29.3% | 23 | 86 |
| Concurrent chats | 10.922 / 12.153 | 6.475 / 6.514 | -40.7% | 18 | 67 |

The final clean replay removed the earlier reconnect timing outlier. It still
performs exactly one reconnect and one recovery action with zero healthy HTTP
polls in every trial, while the live browser restart test recovered
authoritatively without a stuck `Working` state.

Fresh-process imports improved materially:

| Import | Baseline median / p95 | Candidate median / p95 | Median change |
| --- | ---: | ---: | ---: |
| `core.run_agent` | 781.956 / 2,214.524 ms | 97.711 / 105.377 ms | -87.5% |
| `spark_cli.main` | 153.138 / 249.150 ms | 72.357 / 74.816 ms | -52.8% |

The separate five-process lazy-startup measurement, taken from exact commits on
the same host and environment, corroborates the import result. Importing
`core.run_agent` fell from a 0.501152-second median at `43f2f9c4` to 0.109356
seconds at clean release candidate `4f380488` (-78.2%). Loaded modules fell from
1,428 to 414 (-71.0%) and median peak RSS fell from 91,504 KiB to 42,416 KiB
(-53.6%). Candidate p95 was 0.113989 seconds, below both the 0.45-second budget and 0.35-second stretch
budget.

## Token, cache, tool, and output accounting

The request ledger preserves separate conversation, schema, injected-context,
and tool-result token buckets. Fixture medians are unchanged between baseline
and candidate. The largest case is the long-session replay at 3,087 estimated
prompt tokens: 2,671 conversation, 415 tool-result, one schema, and zero
injected-context tokens. Provider cache-read and cache-write counters are
implemented, but the hermetic fixture provider does not exercise a real
provider cache, so this replay makes no cache-hit-rate claim.

The response-efficiency policy fixture scored 39 baseline and 39 candidate
rows. Median fixture output fell from 42.5 to 7.0 tokens, an 83.53% reduction.
This deterministic fixture validates response contracts and exceptions; it is
not presented as observed provider output. Candidate correctness, autonomy,
actionability, safety, and concision each scored 5.0; weighted quality improved
from 4.9692 to 5.0, with no blocking findings or follow-up turns.

A provider-reconciled A/B then exercised Spark's assembled prompt, turn-local
response contract, Codex Responses payload, and output accounting with
`gpt-5.6-luna`, low reasoning, no tools, and isolated context. With the feature
disabled versus enabled, median output fell from 245 to 68 tokens (72.24%) and
median visible words fell from 182 to 47 (74.18%). All three candidate answers
were manually reviewed as correct and complete. The contract added roughly 170
input tokens to these deliberately cold, single-turn agents; its static prompt
portion is cacheable in normal sessions.

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
- Live provider A/B: `docs/performance/response-live-ab-v1.json`
- Scheduler/runtime: `docs/performance/scheduler-runtime-benchmark.json`
- Lazy startup: `docs/performance/lazy-startup-benchmark.json`
- Ordered persistence: `docs/performance/session-events.md`
- Live browser acceptance: `docs/performance/browser-efficiency.md`

The candidate demonstrates large import, general replay, scheduler, browser,
output-token, module-count, and RSS gains without a scored quality loss. The
result is not uniformly faster or smaller: the tiny create-plus-message DB write
time, fresh-schema bytes, and desktop package sizes regressed. Those measurements
are explicitly retained as follow-up budgets and must not be used to claim
across-the-board latency, storage, or package-size improvement.
