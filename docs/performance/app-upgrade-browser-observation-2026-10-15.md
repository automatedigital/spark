# P09 browser observation audit

Base `b432e028a55868fa043d6620ebddc8c791d0f571`, isolated branch
`fix/p09-browser-observation`. Scope is the two browser measurement scripts and
this report; app source, canonical bundles, lockfiles and PLAN are unchanged.
[Machine-readable evidence](app-upgrade-browser-observation-2026-10-15.json)
contains exact samples, commands, exits, source hashes and retained artifact paths.

## Original evidence retained

The parent Node 22 run in
`/tmp/spark-upgrade-20261015/final-browser-node22/` passed multi-chat,
chat-contracts and recovery. Its three sidebar attempts failed the existing
100 ms selection budget (**125.2, 166.0, 124.8 ms**). Its matrix stopped at dark/2,000/1440: history loaded
all 39 earlier pages with 0 px sampled drift, no page/console errors, five
efficiency events, but an empty stream sample array. These remain failed runs.

The parent's independent selection diagnostic in
`/tmp/spark-upgrade-20261015/selection-observation-diagnostic/failure.json`
kept the original assertion and failed at 101 ms. The same click/session commit
was observed in the browser at 69.4 ms; local search was 34.8 ms and full-history
search 292.9 ms. This motivates separating browser commit time from the original
automation-observed duration; it does not establish an app speedup.

The matrix failure also lacks `startedAt` and reports `expectedTokenCount:null`.
A stale panel reference alone cannot explain losing the window-owned trace
object. Document replacement is a separate hypothesis. Concurrent parent
source/document/helper edits make a development-server reload possible, but
the original run did not record navigation evidence and cannot prove that cause.

## Proof protocol

The first controlled proof preserves the original assertions and metrics.
Selection adds a MutationObserver before the same inline `element.click()` and
timestamps the same current panel's `data-session-id` commit using the browser
clock. The original end sample remains after Playwright's completion wait and
row `aria-current` read.

The stream proof keeps the original fixed-panel observer and adds a separate
observer on the stable document body that queries the current panel. It records
both sample series, original-node connectivity, node identity transitions,
document `performance.timeOrigin`, main-frame navigations and a pagehide archive
in temporary-origin sessionStorage. Archived samples are diagnostic evidence,
never replacement passing metrics after an interrupted document.

No synthetic delay, token count, budget, timeout or correctness assertion is
relaxed. No retries are added to an individual measurement. Root coordinates
execution windows so these runs do not overlap the retained-context experiment.

## Original-assertion proof pair

Root cleared a bounded setup/proof window after the other experiment closed.
Worktree-local `npm ci` used the unchanged nested lockfile and verified
`v22.22.1`, executable `/Users/joe/.nvm/versions/node/v22.22.1/bin/node`.
The activated root venv supplied Python; backend import paths selected this
checkout's `src`, and every fixture used temporary Spark state.

- Targeted dark/2,000/1440: **exit 0 in 15.84 s**, 39 earlier pages, no history
  recovery reloads, 0 px drift and no page/console errors. Both fixed/fresh
  observers captured seven updates through token 16. At every update the
  original panel remained connected and identical to the current panel. Trace
  and current document time origins matched, with no main-frame navigation or
  pagehide archive. The efficiency counter recorded 19 events. There is no
  stale-node or document-replacement proof in this run, so it does not justify
  changing the authoritative stream observer or explain the earlier failure.
- Sidebar: **exit 0 in 11.97 s** under the original 100 ms gate. Legacy
  selection was **71.6 ms**, versus **47.8 ms** for the browser's same-session
  commit, a **23.8 ms** observation tail. Local search was 17.6 ms, full-history
  search 279.6 ms and title update 35.5 ms; no correctness failures. The
  initial panel identity was absent, so the observer measured a real transition
  rather than accepting an already selected session.

Artifacts and the exact first-proof script copies are retained under
`/tmp/spark-upgrade-20261015/browser-observation/` in `proof-stream/`,
`proof-sidebar/` and `proof-source/`. Both process groups exited and a scoped
process inventory found no remaining captures. Further measurement windows were
root-controlled; the final fixed batch below ran after explicit clearance.

## Scoped measurement change

Root authorized `selectionMs` to use the browser's same `data-session-id`
commit, retaining the original strict **<100 ms** budget. The script rejects
an already selected session and a missing/non-finite commit timestamp. The
unchanged row `aria-current` assertion still verifies semantic selection.
`selectionLegacyObservedMs` preserves the original timing endpoint after the
Playwright completion wait and row attribute read; the report also records its
tail beyond the browser commit. The two same-click comparisons prove overhead
for those samples, not that every historical sidebar failure was measurement-only.

The authoritative stream observer still captures the original fixed panel.
Fresh-panel samples remain a separate diagnostic series. Missing trace and
mid-capture document changes now have explicit blocking error reasons; archived
samples never replace missing live measurements. No app source was repaired and
no lost-event, stale-node or reload cause is claimed as established.

## Final fixed batch

The final batch ran serially with no watched-file edits or concurrent root
installs/tests/builds/browser work: sidebar **3/3**, targeted dark/2,000/1440
**3/3**, full matrix **18/18**; all aggregate exits 0, no timeouts. Durations were
36.83 s, 46.95 s and 120.27 s respectively. No failed attempt was retried to
obtain these results; the repetitions were fixed before execution. Before/after
SHA-256 maps confirm both scripts and both report drafts were unchanged during
the entire batch. Report completion happened offline after all process groups
closed; the final process inventory contained only the inventory shell itself.

Exact sidebar values in ms (raw browser precision is retained in JSON):

| Attempt | Browser commit | Legacy observation | Observation tail | Local search | Full-history search | Title update |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 57.3 | 91.6 | 34.3 | 75.7 | 286.4 | 17.9 |
| 2 | 47.3 | 70.3 | 23.0 | 42.8 | 281.0 | 35.5 |
| 3 | 49.5 | 75.7 | 26.2 | 78.2 | 281.1 | 33.8 |

Every sidebar correctness check passed, including the bounded 50-shell initial
snapshot, offset-50 paging, <=60 mounted rows, insertion anchor/unread behavior,
selection/search, pin/project/drag behavior, keyboard focus, stale CAS and two
isolated profile databases. Browser selection/local search retain **<100 ms**;
full-history search retains **<600 ms**. The original title timeout and all
correctness assertions remain active.

The targeted 2,000-row captures each loaded 39 earlier pages, had no recovery
reloads, sampled 0 px drift and emitted no page/console errors. Authoritative
fixed-panel and diagnostic fresh-panel updates matched **7/7, 7/7, 8/8**, with
identical token-count progressions through token 16. First visible tokens were
204.6, 164.4 and 211.7 ms; largest rendered-update gaps were 234.5, 188.4 and
145.7 ms. All had 19 efficiency events, the same connected panel throughout,
matching trace/document time origins, zero main-frame navigations and no
pagehide archives. These are synthetic combined timings, not a new P00
performance comparison.

Full matrix coverage was dark/light × 50/500/2,000 rows × 1440/1024/768 px,
900 px high, DPR 1, development mode. Update counts below are ordered by those
three widths; fixed and fresh observers agreed in every case.

| Theme | Transcript rows | Earlier pages per case | Fixed/fresh rendered updates at 1440 / 1024 / 768 |
| --- | ---: | ---: | --- |
| Dark | 50 | 0 | 8 / 8 / 8 |
| Dark | 500 | 9 | 7 / 8 / 8 |
| Dark | 2,000 | 39 | 8 / 8 / 8 |
| Light | 50 | 0 | 8 / 8 / 8 |
| Light | 500 | 9 | 7 / 8 / 7 |
| Light | 2,000 | 39 | 7 / 8 / 8 |

All 18 cases ended with **16 visible tokens**, 19 efficiency events, 0 px
sampled drift and zero page/console errors: **140 authoritative rendered
updates** total. Every trace remained present with matching document time
origin; original/current panels stayed connected and identical, including all
recorded identity samples and the final node-state check. There were no
mid-stream navigations or archives. The original **16 tokens / 60 ms producer
delay**, positive update/elapsed/event and final-visible-token assertions are
unchanged. Fresh or archived samples never feed the authoritative metrics.

Saved dark/2,000/1440 and light/2,000/768 screenshots were visually inspected:
the selected transcript and sidebar were present with legible message rows,
without a blank or missing panel in those samples. This is a two-screenshot review,
not a visual review of every case or an accessibility sign-off.

The prior missing-trace failure remains **unexplained**, rather than
retrospectively solved by these passing captures. No stale-node, lost-event,
Vite-reload or app-fix claim is made. **P09 remains open** for root's broader
acceptance and integration work.

## Source provenance and reproduction

All captures used isolated app/backend source at full base
`b432e028a55868fa043d6620ebddc8c791d0f571`; the two scripts were the only
measurement code changes. The app-source Git tree was
`5915f1d69916a3c3d4d9498ab9b56512345250ab` at `src/spark_cli/web/src`.
Offline inspection of root at `481da654288db397e8573d5af77fe53cb2da3783`
found no app-source diff from that measured base. The isolated backend did not
include later root-only commits. This is not acceptance of later integrations.
Script SHA-256 values for the exact final measurements are retained in the
JSON and `final/source-before.json` / `source-after.json`.

Node was verified again immediately before the final batch as **v22.22.1** at
`/Users/joe/.nvm/versions/node/v22.22.1/bin/node`; Chromium was
**147.0.7727.15**. Both scripts passed `node --check`; `git diff --check` passed.
No app-source unit/type/lint suite was rerun for these measurement-only edits.
Temporary builds were confined to artifact directories; canonical bundles,
lockfiles and PLAN remained unchanged. No push, release or package work ran.

With the root venv active and the above Node directory prepended to PATH, set
`PYTHON=/Users/joe/Developer/github/spark/.venv/bin/python` and
`PYTHONPATH=$PWD/src`. The final serial commands from repository root were
equivalent to:

```sh
node src/spark_cli/web/e2e/browser-gates.mjs --suite sidebar --repeat 3 --output-dir /tmp/spark-upgrade-20261015/browser-observation/final/sidebar
node src/spark_cli/web/e2e/browser-gates.mjs --suite longthread --repeat 3 --output-dir /tmp/spark-upgrade-20261015/browser-observation/final/targeted2k
node src/spark_cli/web/e2e/baseline-capture.mjs --repeat 1 --output-dir /tmp/spark-upgrade-20261015/browser-observation/final/matrix
```

The actual runner used the web directory as cwd and the absolute verified Node
executable; exact argument arrays and exits are in `final/results.json`.
The enclosing timeouts were 800/800/360 seconds and are recorded in the evidence JSON.
Use fresh output directories when reproducing; existing artifacts are preserved.

## Precision boundaries

The selection observer timestamps DOM identity commit, not a painted frame or
completed history fetch. MutationObserver scheduling remains inside the measured
duration. The legacy duration additionally includes automation polling and
protocol trips. Values from different definitions cannot establish a performance
improvement against P00.

Stream samples count rendered marker text, not received network packets or
provider tokens. Multiple synthetic events can coalesce into one render.
Efficiency event totals are broad counters, not proof that every token event
arrived. The 60 ms producer delay and HTTP/backend/SSE/render costs remain
combined; no real provider or messaging I/O is used. Browser host scheduling and
observer overhead limit timing precision. Dev captures do not prove served
production assets or installed-package behavior.
The passing captures did not exercise the new missing-trace/document-change
error branches; no forced-reload negative test is claimed.
