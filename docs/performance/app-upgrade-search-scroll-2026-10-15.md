# P09 cached-history search scroll diagnosis — 15 October 2026

**The second original-source diagnostic reproduces the 30-second missing-row
failure and records a competing bookmark restore writer. Mapping is correct.
No product fix is implemented or accepted.** The first run's premature guard
pass is preserved separately. Retiring the restore may be the repair start point;
its sufficiency has not been tested.

The [evidence JSON](app-upgrade-search-scroll-2026-10-15.json) records source and
helper hashes, selected source/native events, geometry, all outcomes and 163
artifact hash receipts. The earlier retained-context attempts and reports are
unchanged. P09 and all package/release gates remain open.

## Controlled source and flow

Both runs archive exact `e8d6713ddd59c029f6dcd6d915df9ca42b4c71eb` into separate
temporary source directories, independent of the parallel navigation-lifetime
candidate. Each installs its own 306 packages with the existing nested lockfile,
then builds instrumented production assets into its own temporary output.
Actual Node is **v22.22.1**, executable
`/Users/joe/.nvm/versions/node/v22.22.1/bin/node`. The root venv is activated,
`PYTHON` points to its interpreter, and `PYTHONPATH` uses each snapshot's own
`src`. Browser is Chromium 147.0.7727.15, dark, 1440×900, DPR 1.

The existing synthetic baseline fixture, full-history loading and scroll-drift
setup precede thirteen fixed forced-GC checkpoints, cycles 0–12. Only the same
50- and 2,000-message chats are revisited. No new heap snapshots or heap parsing
were needed. This is a search diagnosis, not a heap-slope comparison.

The unchanged guard clicks `Search messages (⌘F)`, fills literal
`Response 1952:`, waits up to **30 seconds** for the matching `[data-row-id]`
with Playwright `state:visible`, then presses Escape. No selector, timeout or
assertion was relaxed. The added follow-up observation is distinct: after a
successful original guard, wait up to 5 seconds for recorded search intent and
up to 10 seconds for viewport intersection, then observe a further 1.5 seconds.
Its bounded outcomes never replace the original result.

The target is assistant `db:2502`, global message index 1951; user `db:2501`,
global index 1950; owning turn `turn:user:db:2501`. Both runs observe the cached
300-message array `db:2251`–`db:2550` (fixture messages 1701–2000), relative target
message **251**, owning turn **125**. The API page limit of 50 is not the loaded
array size on revisit.

## First run: original guard passes without search navigation

Raw evidence: `/tmp/spark-search-scroll-20261015-original-prep2/`.
Execution is 20:16:36–20:16:58 UTC, exit **0**, thirteen checkpoints, 252 retained
probe events, zero dropped events and zero browser errors. There is one initial
main-frame navigation and no later reload.

The guard completes in **154.3 ms**, before the 300 ms search debounce. There is
**no `search:intent` event** before closure. The target is already mounted in
overscan at index 125, but its pixel bounds are **−163.5 to 58.75**, wholly above
the viewport **147 to 721.5**. ScrollTop is **17,017**, clientHeight **575**,
scrollHeight **20,045**, virtual total **19,968**; mounted range is **117–141**.
The outcome screenshot shows later responses, not Response 1952.

This is an unchanged guard pass, **not a viewport/search-navigation pass**.
Playwright's visibility condition can succeed for a mounted offscreen row. Its
immediate success lets this driver close before search executes. The only source
writers after the click are three bookmark `saved.top` fallback writes to 17,017.
The diagnostic lookup reads 251→125 correctly, but the actual search effect has
not executed. The first run is a non-reproduction of the missing-row failure.

## Cleared follow-up: original failure and conflicting ownership reproduced

Raw evidence: `/tmp/spark-search-scroll-20261015-original-followup1/`.
Execution ends at 20:20:16 UTC, exit **1**. The unchanged original guard fails
with **`locator.waitFor: Timeout 30000ms exceeded`**. There are thirteen
checkpoints, 1,835 events, zero dropped events and zero browser errors. Again,
only the initial main-frame navigation is recorded.

The optional post-guard observer is **skipped because the original guard fails**.
Its raw receipt retains `requested:true, outcome:not-requested`, the helper's
initial default string; the JSON explicitly explains that labeling limit. No
failure is relabeled as a successful observation. Search and writer events are
captured during the original 30-second wait, so the actual ownership sequence
is available despite skipping that later observer.

At **14,874.5 ms** document time, search records matches `[251]`, mapped index
**125**, actual ID **`turn:user:db:2501`**, `safeMode:false`. The native call at
14,874.8 ms is `scrollTo({top:16495, behavior:"smooth"})` under source owner
**ChatPanel:1118**. The target's estimate is 228 px, measurement interval
16,650–16,878, and measured-size-cache entry is absent. This proves correct
mapping and delivery of the requested offset to the browser in this attempt.

A pending bookmark owns anchor **`turn:user:db:551`**, absent from the loaded
cached range, with saved top **0**. Its fallback at **ChatPanel:1358** performs
**nineteen `scrollTop = 0` writes after the search request**: first at
**+13.7 ms**, last at **+796.0 ms**. Native setter records confirm the writes.
Both owners retain session generation **25** and restore generation **64**;
search does not invalidate the existing restore generation.

The first ordering is source-confirmed: search schedules virtualizer reconcile
RAF **630**; already-pending bookmark RAF **629** runs first and sets top to
zero; RAF 630 then reconciles and schedules RAF 632 without another native
scroll request. Bookmark and reconcile RAFs continue interleaving. Virtualizer
reconciliation runs until approximately **+5,000 ms**, matching the dependency's
bounded reconcile path. The search target offset stays unchanged, and only one
native search scroll request is recorded.

All recorded post-intent scrollTop values remain **0**; there is no native scroll
event and the target **never mounts or intersects the viewport**. Final mounted
range is **0–14**, clientHeight **538**, viewport **184–721.5**, scrollHeight
**20,045**, virtual total **19,968**. Matching-row pixel bounds are unavailable
because that row is unmounted; no bounds are invented from its estimate.

The only post-intent source writers are the single search call and nineteen
bookmark fallback writes. There are **no bottom-clamp, auto-follow or measurement
anchor writes**, and no resize/measurement events, in that interval. Thus this
run identifies a concrete competing valid restore owner; it does not demonstrate
a target measurement-convergence failure. The target is never measured here.

## Repair start point, unimplemented

At search intent, retire pending bookmark restoration and invalidate its RAF
generation before issuing the search scroll. Clear pending/restoring ownership
coherently so a retired callback cannot write later. Review the existing
`jumpToIndex` generation invalidation and anchor semantics as the nearby pattern.

This is a proposal for a separate repair candidate. **No cancellation control,
instant-scroll control or repaired source has run**, so cancellation sufficiency
and measurement behavior after a successful mount remain unproved. The unchanged
original guard plus separately confirmed intent and stable viewport intersection
are distinct acceptance evidence. Cached switching, saved-position restoration
and history prepend behavior would need their own repair checks.

## Instrumentation, preservation and limits

Committed helpers are `e2e/search-scroll-diagnostic.mjs` and
`e2e/search-scroll-source.mjs`. The Vite transform labels all eighteen source
scroll writers and records mapping, mode/anchor, pending bookmark, session/restore
generations, scroll/viewport/total geometry, virtual range, target estimate/cache,
mounted bounds and virtualizer intent/offset/adjustments. Browser wrappers record
native scroll writers and ResizeObserver/RAF schedule/run/cancel ordering. Stored
events contain plain data, not retained DOM nodes, callbacks or timeline objects.
Only the last switch and guard event interval is retained; all thirteen checkpoint
DOM receipts remain in `cycles.json`.

Exact generated drivers, transforms, instrumented TSX, source receipts,
production assets, logs, screenshots and attempt receipts remain in each raw
directory. Final helper copies and a standalone hash manifest are in
`/tmp/spark-search-scroll-20261015-final-helpers/`. Attempts are never reused or
overwritten. `/tmp/spark-search-scroll-20261015-original-prep1/` remains an unused
preparation with fewer probe fields; it was never executed.

Two initial source-preparation checks failed and were corrected before execution:
a provisional writer count of seventeen was actually eighteen, and a shared
restore-generation string required a contextual seam. Generated-driver/transform
Node syntax and transformed TSX syntax passed. `git diff --check` passed. No
further tests, builds or captures followed the final measurement-done signal.

Each run had explicit root clearance and used synthetic isolated SPARK_HOME,
a deliberately unavailable loopback provider and no external provider calls or
message sends. Context/browser and Vite/backend processes closed before each
measurement-done signal; the wrapper also terminated its detached group. Scoped
post-exit process checks found no owned survivors. Other OS/user activity was
not globally stopped. Instrumentation adds synchronous reads/logging and can
change timing; these two runs do not establish population incidence or latency.

`npm ci` reports five dependency vulnerabilities; the lockfile is unchanged and
no audit repair was attempted. Production builds emit existing Tauri mixed-import
and large-chunk warnings. The inherited driver's stdout says “Validated 1 baseline
case”; this limited diagnostic bypasses the full baseline validator and makes
**no full-baseline, release-budget, installed-package or launch claim**. No product
source, backend, canonical bundle, lockfile or PLAN changes are included.
