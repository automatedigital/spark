# P09 retained render contexts: rejected narrow ablations — 15 October 2026

**Neither narrow callback ablation fixes the retained timeline growth. No app
source change is shipped.** Original `ChatPanel.tsx` is restored; experimental
helpers/tests are removed from the checkout and preserved in `/tmp`. This report
and its [evidence JSON](app-upgrade-retained-contexts-2026-10-15.json) are the only
intentional committed files. P09 remains open.

## Source and controls

The committed base is `8a1aa734`, including canonical P06 `ebae486f`.
`ChatPanel.tsx`, `useChatSessionController.ts`, and `useChatDraft.ts` match
`60fae7c6` before these experiments. The parent's historical attribution contrast
was actual source `60fae7c6` versus `2a41925`, whose production slopes were similar
at **0.52813 / 0.51924 MiB per cycle**. That supplied contrast does not establish
an upgrade-introduced leak or establish that growth is harmless. The new strict
pairs compare original root source with exact temporary source variants, not
new timings with historical absolute timings.

- Verified executable: `/Users/joe/.nvm/versions/node/v22.22.1/bin/node`,
  **v22.22.1**. The misleading Homebrew `node@22` symlink was not used.
- Own `npm ci` installed 306 packages using the existing nested lockfile; no
  dependency, lockfile, manifest, canonical bundle, gateway, approval, navigation
  or PLAN changes.
- Activated `/Users/joe/Developer/github/spark/.venv`, Python 3.11.7;
  `PYTHON` points to that interpreter and `PYTHONPATH` to the candidate's `src`.
  Chromium 147.0.7727.15, dark, 1440×900, DPR 1; temporary production Vite assets.
  The inherited baseline report's `mode:dev` field is stale metadata: the
  `served.json` receipt and temporary build logs identify actual production mode.
- Same worktree, dependencies, fixture and probe on each side of a pair. The
  helper transforms only the existing attribution seams. Every backend uses
  isolated synthetic state under temporary `SPARK_HOME`; no user state,
  external provider calls or external sends.
- Thirteen forced-GC checkpoints, cycles 0–12; snapshots at 2 and 12. Each cycle
  revisits only the same existing 50-row and 2,000-row chats. Probe histories and
  resource timings are cleared before collection. Fits use all eleven samples
  at cycles 2–12, not two endpoints alone.
- Parent explicitly cleared both capture windows and paused other heavy work.
  All owned backend, browser and process groups closed before each
  measurement-done signal. Background OS/user activity was not globally stopped.

Raw attempts are `/tmp/spark-retained-contexts-20261015-79e97ff9-*`. The JSON
records exact source hashes, source patches, archived helper/test bytes, raw
metrics, strong paths, attempt dates/exits and 412 artifact hashes. Original
performance reports, failed attempts and assertions remain unchanged.

## Why the original sampled path was insufficient

The original attribution graph led from active `spark:compose` EventListener
through shared render contexts containing `handlePromoteToBrief` and `attachPath`
to old `threadTimeline.turns`. The compose effect already has cleanup. Neither
that graph nor these captures proves duplicated listener registrations. WeakMap
ephemeron-value paths alone were excluded from the new ownership analysis.

For each snapshot, the offline census identifies timeline turns by their own
`assistantMessages`, `workItems`, `workSummary`, `timestamps` and `visibleItems`
properties. It follows strong shortest paths from GC roots, excluding weak and
`part of key` ephemeron-value edges. Array counts include arrays owned through a
timeline wrapper or direct turn elements, including one shared empty array.
These are live-object counts and shallow bytes, **not dominator retained bytes**.
Shortest paths establish reachability, not exclusive ownership.

Both source experiments reroute the old-generation path through other callbacks:

| Source | Observed long strong callback chain |
| --- | --- |
| Fresh original | search `turnIndexForMessageIndex` ↔ `attachPath` |
| Attach/promote factories | search `turnIndexForMessageIndex` ↔ `summarizeContextItem` |
| Lookup-only factory | `jumpToIndex` ↔ `attachPath` |

The graph points to a broader shared-render-context ownership problem. It does
not demonstrate a subscription-count leak, nor justify removing the compose
listener, PerformanceObserver, timeline cache or intended UI behavior.

## First candidate: attach/promote factories, rejected

This moved only construction of `attachPath` and `handlePromoteToBrief` into
separate module factories returned with the original dependency keys. Compose
registration and all callback behavior were unchanged.

| Post-GC snapshot, cycle 2 → 12 | Original `before2` | Two factories `after1` |
| --- | ---: | ---: |
| Unique strongly reachable timeline turns | 1,350 → 3,100 | 1,350 → 3,100 |
| Distinct timeline arrays, including shared empty array | 7 → 27 | 7 → 27 |
| Timeline-turn shallow bytes | 108,000 → 248,000 | 108,000 → 248,000 |
| All snapshot nodes' summed shallow bytes | 15,133,698 → 20,821,626 | 15,799,894 → 21,494,834 |

All-node shallow growth is 5,687,928 versus 5,694,940 bytes, **+0.12%**. This
rejects sufficiency of the candidate. All-node shallow bytes are a snapshot
census, not `JSHeapUsedSize` and not a retained-owner byte measurement.

`before2` records 12.228 → 17.560 MiB, OLS **0.529406 MiB/cycle**, R² 0.99933.
The after run failed after heap capture, before final report serialization;
that wrapper had no separate sample checkpoint. **No after slope is available
or inferred.** Both snapshots are intact.

Original ChatPanel SHA-256 is
`a9110c902f4438096248c3f193573b9a69d903bf8bcbe892e77af25d4a2c29ae`;
rejected two-factory ChatPanel is
`7cd7cd5bebad2c01c5a5dd1c59f99217f97940fc692b58e56da2843807c14de7`.
An intermediate three-factory source was prepared, archived and **never captured**;
it is explicitly separate in the JSON.

## Second candidate: lookup-only factory, also rejected

The parent requested the smallest cut: start again from original ChatPanel,
leave attach/promote unchanged, and construct only `turnIndexForMessageIndex`
outside its render scope. The `[chatMessages]` dependency, loop, user-message
counting, clamping and return behavior were identical. Candidate ChatPanel hash:
`d2aaaaa2779c962d419482391e4d70f9916265a1a708df6cf0fd77edf39c3dd0`.

| Cycles 2 → 12 | Fresh original | Lookup only |
| --- | ---: | ---: |
| `JSHeapUsedSize`, MiB | 12.171 → 17.544 | 12.013 → 17.087 |
| OLS MiB/cycle | 0.529764 | 0.496863 |
| R² | 0.99931 | 0.99497 |
| Unique strongly reachable timeline turns | 1,350 → 3,100 | 1,350 → 3,100 |
| Timeline arrays, including shared empty array | 7 → 27 | 7 → 27 |
| Timeline-turn shallow bytes | 108,000 → 248,000 | 108,000 → 248,000 |

The slope is 6.21% lower in this single pair, but remains positive; retained turn
and array growth is identical. This is **not a retention fix** or stable
population performance estimate. Both full attempts fail the identical added
search guard after their separately saved heap checkpoints.

## Failed assertions and UI boundary

Five bounded attempts were retained: one exit 0, four exit 1; no attempt-level
240-second timeout. No assertion, timeout or performance budget was relaxed.

| Attempt | Result |
| --- | --- |
| `before1` | Probe-wrapper `ReferenceError: assert is not defined` in the added post-snapshot UI guard. My serialization error, not an app failure. Fixed with equivalent explicit checks; failed evidence preserved. |
| `before2` | Exit 0: original history/stream checks and compose/draft-switch/promote guards pass. |
| `after1` | Snapshots and compose/draft-switch/promote guards pass; original phase-7 final-token wait times out after 15 seconds. |
| `lookup-before1` | Heap checkpoint complete; added search-scroll guard times out after 30 seconds on original source. |
| `lookup-after1` | Heap checkpoint complete; identical search-scroll guard times out after 30 seconds. |

For `after1`, the failed original assertion waits for literal `phase-7 token 16.`.
The screenshot shows selected `baseline_thread_stream_phase_7` with only the
setup user row; page and console error lists are empty. Every stream intentionally
reloads once. That driver did not record main-frame/timeOrigin/pagehide around
the failure, so **an additional unexpected document reload is neither proved
nor excluded**. Later drivers add those diagnostics and preserve heap samples
before any UI/stream phase, but both fail before streams. There is no later
stream lifecycle outcome to claim.

The search guard clicks the exact `Search messages (⌘F)` title, fills literal
`Response 1952:`, and waits for a matching `[data-row-id]` to become visible.
The fixture target is assistant **`db:2502`**, global zero-based message **1951**;
its user is **`db:2501`**, global index **1950**, turn **`turn:user:db:2501`**.
The API page limit is 50, but `localTurnCache` preserves/merges the last **300**
messages on revisit. Thus the expected loaded range is rows 1701–2000; the
target is relative message **251**, turn **125**. An earlier working assumption
of relative 1/turn 0 was corrected; the fixture was not changed.

The cycle-12 array census on both sides contains 12 arrays of 150 turns,
13 arrays of 25 turns, one 1,000-turn full-history array and the shared empty
array. Some arrays share turn objects; array-element totals are not unique-object
counts. This supports the cached-300 accounting and multiple old generations.

Both screenshots show the search count **1 / 1**. Before failure mounts user IDs
2251–2279 by twos (rows 1701–1729); its screenshot visibly starts at Prompt 1701 /
Response 1702 and reaches Prompt 1707. After failure mounts user IDs 2521–2549
by twos (rows 1971–1999); its screenshot shows the tail of Response 1992, then
Prompt 1993 / Response 1994 through Response 2000. Mounted overscan ranges are
distinct from visible screenshot content. **ScrollTop, row pixel bounds and
internal virtualizer range were not recorded and are unavailable.** This failed
expectation needs separate fixture-versus-source diagnosis; it is not attributed
to either experimental memory change. Neither lookup run reaches later streams.

## Reproduction and handover

The unchanged attribution helper is in worktree
`/Users/joe/.t3/worktrees/spark/t3-96a3d59e`, with
`e2e/performance-attribution{,-source}.mjs`,
`scripts/performance_attribution_backend.py` and its existing summarizer.
The additive wrapper, offline graph census, source variants and report assembler
are `/tmp/spark-retained-contexts-79e97ff9-*`; exact generated drivers are retained
per attempt. JSON includes the rejected patches and helper/test source so their
meaning is reviewable without relying on a later dirty checkout.

```sh
source /Users/joe/Developer/github/spark/.venv/bin/activate
export PYTHON=/Users/joe/Developer/github/spark/.venv/bin/python
export PYTHONPATH=/path/to/candidate/src
/Users/joe/.nvm/versions/node/v22.22.1/bin/node \
  /tmp/spark-retained-contexts-79e97ff9-probe.mjs \
  --source /path/to/candidate --source-sha EXACT-VARIANT \
  --probe thread --heap --mode production --output-dir /tmp/NEW-UNUSED
# --prepare-only generates/syntax-checks without build/server/browser.
```

Prepare-only syntax checks and `git diff --check` pass. Experimental unit tests
were prepared, **never executed**, archived, and removed with the rejected
source. No extra tests/captures followed the final measurement-done. Production
helper builds do not establish release bundle budgets or package acceptance.

Next step belongs to the parent: an independent source-design review of shared
render-context ownership and separate search-scroll diagnosis. No more callback
edits, extra captures, fix acceptance, issue closure, release or package claim is
made here.
