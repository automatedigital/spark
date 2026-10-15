# P09 search scroll ownership repair — 15 October 2026

**Candidate `3a085fe53eb5f11b6f6deb3662f21ae6e893d4c4` passes the original
30-second guard, separate actual-intent/viewport/ownership observations, and all
four UI regression stages. The root accepted this narrow repair for integration.**
P09 remains open for memory and full-suite/integration gates. No canonical bundle,
installed package or release acceptance is claimed here.

The [evidence JSON](app-upgrade-search-scroll-fix-2026-10-15.json) contains exact
source/helper hashes, 85 capture artifact receipts, the unit-check receipts,
original and candidate outcomes, post-intent geometry and UI stage results.
Historical diagnostics are unchanged; see the separate
[original diagnosis](app-upgrade-search-scroll-2026-10-15.md).

## Minimal product change

The source commit changes only ChatPanel's search-match effect and adds its
focused regression test. Immediately before the existing direct virtualizer
scroll, the effect advances `prependRestoreGenerationRef`, clears
`pendingThreadScroll`, and clears `restoringThreadScroll`. The queued bookmark
callback keeps its existing generation check, so a callback from the retired
restore can run without writing to the new search viewport.

The hunk adds one comment and three ref updates. There is no central scroll
refactor, smooth-to-instant shortcut, changed match lookup, changed timeout,
backend, dependency, lockfile, bundle or PLAN edit. Ordinary search remains
smooth; safe mode retains its existing instant behavior. Other explicit jump
controls are unchanged. The same hunk can be applied to both future memory-pair
sources without applying the independent navigation-lifetime candidate here.

## Distinct original, test-baseline and candidate outcomes

The first original-source capture remains an **exit-0 premature guard pass**:
154.3 ms, target already mounted in overscan but above the viewport, no actual
search intent before closure. That is not search-navigation proof.

The single original follow-up remains an **exit-1 original 30-second timeout**.
Search correctly maps cached message 251 to turn 125 and native smooth offset
16,495. Nineteen still-valid bookmark fallback writes then assign top zero;
the target never mounts. The optional later observer is skipped because that
original guard fails. Its original raw labeling and all files remain preserved.

The new callback regression tests, run against an untouched original source copy,
produce the expected **3 failures / 1 pass**. They run the actual source lookup,
search effect and bookmark effect with a controlled RAF queue, rather than copying
the restoration implementation. The candidate passes all four new tests plus
existing scroll-state/timeline tests: **21 passes**. App `tsc -b` and scoped ESLint
pass. An initial test-only lint failure for two unused parameters was corrected;
both failed and final logs are retained. These tests do not mount React; the
production browser run supplies the real DOM/virtualizer evidence.

The **single candidate production capture exits 0**, with the unchanged original
guard and the separate later observer both passing. It was not a retry of a
failed candidate, and no assertion or budget was relaxed.

## Actual candidate search and ownership proof

Raw directory: `/tmp/spark-search-scroll-fix-20261015-candidate1/`.
Execution is **20:32:05–20:32:42 UTC**, source pinned to the committed candidate.
The historical instrumented source transform and baseline fixture/history/drift
setup are unchanged. Thirteen forced-GC checkpoints revisit the fixed 50- and
2,000-message chats; no new heap snapshots or heap parsing are involved.

As in the failing original capture, search begins at **scrollTop 0**, with the
absent cached bookmark anchor `turn:user:db:551`, saved top 0, session generation
25 and restore generation 64. The loaded array is the same 300 messages
`db:2251`–`db:2550`. Actual search records cached message **251** → turn **125** →
**`turn:user:db:2501`**, at document time **15,744.2 ms**. The estimated target is
228 px, and the initial centered offset is again 16,495.

At **15,744.3 ms**, before the native search scroll, the source writer records
**generation 65**, **pending bookmark null**, and **restoring false**. The old
bookmark RAF does run at **+102.9 ms**, retaining its captured generation 64;
its guard returns. There are **zero old bookmark fallback writes** after the new
intent through the separate settling observation. The sole product source writer
in that interval is the search call. Native virtualizer adjustments continue as
the viewport changes when the unchanged original guard presses Escape.

The original guard has completed by **17,260.9 ms**. Separate viewport observation
records intersection at **17,267.3 ms** and checks again **1,506.6 ms** later.
The target is then mounted at index 125 with pixel bounds **376.5–598.75** inside
the viewport **147–721.5**; scrollTop is **16,477**. This is actual viewport
intersection after recorded search intent, not just Playwright layout visibility.
The row's DOM height is 222.25 px; the proof does not require claiming every
virtualizer estimate is exact.

## Additional UI regression flows

All four candidate stages pass in the same browser context:

- **Search ownership:** correct 251→125→target ID mapping; generation advanced
  before the scroll, pending restore retired, no old fallback write, and target
  still intersects the viewport after settling.
- **Cached saved-position switching:** clear search, scroll away, switch to the
  50-message chat and back. The same anchor `turn:user:db:2491` returns at
  **−49.5 px**, exactly its saved top, and remains there after a further 1.5 seconds.
- **Small-chat search and next match:** search `Response 00` in the 50-message
  chat, confirm actual intent and viewport intersection for `turn:user:db:1`,
  press Enter, then confirm the next match `turn:user:db:3` at mapped turn 1.
- **History prepend after search:** clear search, return to the large cached
  chat, load one older page and use the existing history-anchor gate's bounded
  stable-frame check. Anchor `turn:user:db:2251` moves from **203.5 to 203.25 px**,
  drift **−0.25 px**.

The candidate records **2,388 events, zero dropped events and zero page/console
errors**. Only the initial main-frame navigation occurs. `search-outcome.png`
is captured after all UI stages, so it depicts the final history-prepend state;
the initial search viewport proof is in the recorded post-intent geometry.

## Reproducibility, isolation and remaining gates

The additive preparer is `e2e/search-scroll-fix-diagnostic.mjs`. It prepares the
historical driver unchanged, archives that generated version, then adds separate
ownership and UI checks. The historical helper and report are not edited.
Exact executable drivers, transforms, instrumented TSX, production assets,
original guard receipt, post-intent trace, UI receipts, screenshots and logs are
retained in the raw directory. Final helper/test copies and hash receipts are
under `/tmp/spark-search-scroll-fix-20261015-final/`; unit logs and the untouched
original test source copy are under `/tmp/spark-search-scroll-fix-20261015-checks/`.

Actual Node is **v22.22.1** at
`/Users/joe/.nvm/versions/node/v22.22.1/bin/node`; Chromium is 147.0.7727.15,
dark, 1440×900, DPR 1. The candidate installs its own dependencies with the same
lockfile. The root venv is active and `PYTHON` uses its interpreter; `PYTHONPATH`
uses the pinned candidate's own `src`. Backend state is synthetic and isolated
under temporary SPARK_HOME, with an unavailable loopback provider. There are no
external provider calls, message sends or user-state accesses.

The root explicitly cleared this one capture after its full pytest process
exited and the other agents closed their commands. Source/helper/report bytes
were frozen during the run. Context/browser, backend and Vite closed before the
measurement-done signal; the wrapper terminated its detached process group and
scoped post-exit process checks found no owned survivors. There were no retries
or further captures/builds/heavy commands after that signal.

Instrumentation can perturb timing. This is one bounded, specifically validated
repair, not a population performance estimate or proof that all scroll races are
resolved. Existing dependency-audit, Tauri mixed-import and large-chunk warnings
are unchanged. The inherited stdout's “Validated 1 baseline case” text does not
establish full baseline acceptance: this diagnostic intentionally runs its own
specific guard/observations. The root owns final frontend, canonical-bundle and
app gates. Memory retention and Python full-suite work remain separate, open
P09 concerns.
