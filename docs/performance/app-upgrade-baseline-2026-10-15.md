# App upgrade: P00 baseline and P09 fixture audit

Source: `2a41925cd535a273fef71a7eebb47a022f14fe21`, clean on entry,
`test/spark-baseline-fixture-audit`. This is baseline evidence and an audit,
not completion of P00 architecture decisions or P09 implementation/release gates.
Only this report and its [evidence JSON](app-upgrade-baseline-2026-10-15.json)
are committed. Application source, contracts, lockfiles, manifests, canonical
bundles and the parent checkout were not edited. No push, PR or delegation.

## Environment and reproducibility

- Isolated checkout: `/Users/joe/.t3/worktrees/spark/t3-ccdb2744`.
- Root checkout discovered with `git worktree list`:
  `/Users/joe/Developer/github/spark`; its `.venv` was activated for Python,
  tests, lint and servers. `PYTHONPATH=$PWD/src` selected this checkout's source.
- macOS 27.0.1 arm64, Apple M2 Max, 64 GiB; Python 3.11.7, Node 22.22.1,
  Node Playwright 1.59.1 / Chromium 147.0.7727.15; Python Playwright 1.62.0.
- Every browser run used temporary `SPARK_HOME`, ephemeral loopback ports and
  synthetic data. Fake streams exercised the real backend callbacks, persistence
  and SSE/UI; no inference or messaging was requested. Configured fixture model
  names were `test-model`/`synthetic-only`, not live-provider measurements.
- Dependencies were initially reused from the authorized root `node_modules`.
  A concurrent `npm install` was observed; the symlink became a worktree-local
  directory during setup. Subsequent imports stabilized. This audit did not
  install dependencies or edit lockfiles. Initial failures remain recorded.
- Exact commands, working directories, exit codes, raw samples, temporary driver
  sources and artifact SHA-256 values are in the JSON. Raw files remain under
  `/tmp/spark-c-baseline-20261015/`; these local files are not committed.

## Automated checks

All pytest groups used `-q -n 0 -m 'not integration and not network'`.
The JSON retains the full file lists and commands rather than abbreviated aliases.

| Check | Result / exit |
| --- | --- |
| Delegation/tool restrictions, subagents/progress/interrupt, Kanban DB/workflow, cache goldens, lazy manifest, minimal startup, efficiency | 169 passed, 23.99 s / 0 |
| Web state, turn persistence, web server/events | 267 passed, 64.03 s / 0 |
| SQLite state, web projections, async runtime/contracts, tool scheduler | 76 passed, 3.44 s / 0 |
| `npm run lint` | Passed / 0 |
| `./node_modules/.bin/tsc -b` | Passed / 0 |
| `npm test` | 68 files, 391 tests passed / 0 |
| `python scripts/generate_tool_manifest.py --check` | 70 tools, 28 isolated modules, 4 optional guards / 0 |
| `ruff check src/` | 305 existing findings: E402 279, E741 16, E701 4, E702 4, E731 2 / 1 |
| `mypy src/agent/ src/spark_cli/` | 2,706 existing errors in 118 files; 127 source files checked / 1 |
| Temporary `vite build … --outDir … --emptyOutDir --logLevel warn`, then bundle budget against that directory | Passed / 0 |

Total: **512 focused Python tests and 391 frontend tests passed**. Full pytest was
not run. Full lint/type debt was recorded without fixes. `npm run build` was split
into TypeScript, temporary Vite build and the unchanged budget logic redirected
to temporary output, avoiding writes to canonical `web_dist`.

## Browser flows and failures

- **Multi-chat:** three simultaneous synthetic chats, live switching, refresh,
  completed status, compaction failure and backend restart passed, exit 0.
- **Recovery-state:** stalled reconnect, failure outcome, pending approval,
  three-chat switching, no automatic conversation POST and backend restart passed,
  exit 0. This restarts the web backend, not an actual messaging gateway process.
- **Chat-contracts:** existing copy/edit/retry/fork/approval/interrupt/reconnect/
  history suite passed, exit 0. Retry, fork and approval responses use browser
  route substitutions; they do not prove actual provider/control semantics.
- **Work recovery:** all nine draft/conflict/attachment/profile-identity checks
  passed in dev mode and against temporary production assets served by Vite
  preview, exit 0 each. Both themes and 1440/1024/768/390 px were exercised.
  Profile identity is simulated via the status response; this is not two real
  backend profiles. Screenshots: `screenshots/work-recovery/` in this worktree and
  `/tmp/spark-c-baseline-20261015/work-recovery-built/`.
- **Child/project supplement:** a real SQLite child snapshot with completed
  answer opened beside an active synthetic parent; backend still reported the
  parent active. A real scratch-project API creation succeeded and a synthetic
  project-bound chat appeared under its selected scope, exit 0. This proves
  snapshot/UI behavior, not provider delegation or a wizard/composer submission.
  Screenshots: `child-detail.png` and `project-scope.png` under the raw directory.
- **Initial environment failures:** multi-chat timed out waiting 15 s for Spark,
  recovery timed out waiting for Vite, and chat-contracts reported
  `ERR_MODULE_NOT_FOUND` for `playwright/index.js`, exit 1 each, during observed
  dependency installation. Each passed after prerequisites stabilized.
- **Long-history flake:** attempt 3 timed out after 15 s waiting for an earlier
  message response. Attempts 1/2 and one diagnostic attempt passed; **3/4**, not
  four successful trials. Root cause remains unresolved. The diagnostic copy only
  added failure capture; it did not relax assertions.
- **Canonical sidebar suite failed twice**, exit 1: its selected-row check waits
  for `bg-primary/12`, while App mounts `InboxSidebarSessions` cards using
  `bg-foreground/[0.11]`. The suite's old search placeholder, row markers and
  pin/paging assumptions also need reconciliation. Supplementary Inbox timings
  below are not a passing result for this suite.

Exploratory driver mistakes are retained in JSON: an unseeded row-999 title was
incorrectly treated as a message-FTS match; child selection initially ignored the
Running filter, an already-open panel, a hidden responsive duplicate, and the
project API's normalized display name. Corrected drivers measure observed UI
behavior; these are separate from application failures.

## Repeated performance samples

Values are milliseconds, median / nearest-rank p95. With three samples p95 equals
the maximum; these are a small shared-host baseline, not stable population
percentiles. The diagnostic long-thread success overlapped other verification.
Only successful long-thread captures contribute; the failed attempt is excluded
from timing statistics and retained as a correctness failure.

| Measurement | Median / p95 |
| --- | ---: |
| Backend spawn to successful `/api/status` | 652.36 / 653.68 |
| 2,000-row thread: navigation to initial useful render | 1,155.95 / 1,194.83 |
| First visible stream token, including 60 ms synthetic delay | 252.80 / 255.20 |
| First token minus configured 60 ms delay | 192.80 / 195.20 |
| Largest gap between visible stream updates, per run | 197.30 / 228.30 |
| 1,000-session sidebar: initial useful render | 1,052.06 / 1,098.16 |
| Sidebar click to selected chat-panel identity | 42.30 / 43.80 |
| Sidebar title PATCH to visible update | 35.20 / 40.00 |
| Loaded-title local filtering | 41.70 / 42.10 |
| Full-history message search, including debounce | 282.30 / 336.60 |
| SQLite FTS only: 10,000 messages, five warm searches | 10.88 / 12.79 |

Long-thread fixture: deterministic alternating user/assistant messages including
code blocks, dark theme, 1440×900. All successful captures loaded **39 earlier
pages**, mounted 8–12 message rows, and measured **0 px** sampled anchor drift.
CDP used-JS-heap samples were **35.38, 50.64, 27.63 MiB**; these are not browser
RSS or a leak test. The stream generated 16 tokens at 60 ms intervals and all 16
became visible. Visible-update gaps reflect UI batching, not transport packet gaps.
Subtracting the configured delay leaves backend/HTTP/SSE/render overhead together;
pure UI CPU time and real-provider first-token latency were not measured.

Sidebar fixture: **1,000 sessions / 10 projects**, with one searchable historical
message in `scale-499`. Three supplemental runs mounted 50 Inbox cards and found
that result beyond the loaded page. Bottom scrolling produced no offset-50
request. Source confirms Inbox does not consume `loadMoreSessions`; ordinary
browsing beyond the first page remains a gap. This is not proof of virtualizing
1,000 mounted cards. The 10,000-message search is a separate one-session SQLite
fixture with 100 matches; it does not satisfy the 10,000-message browser-p95 gate.

The temporary production build has **61 files / 3,072,668 bytes**. Initial static
JavaScript is **227.93 KiB gzip**, below the 600 KiB budget:
`index-BqSQCMnt.js` + `vendor-react-Dc-lrgX9.js`. Raw file sizes/hashes are in JSON.
Five fresh-process import samples yielded `core.run_agent` 223.60 / 257.11 ms and
`spark_cli.main` 182.41 / 363.04 ms. Efficiency fixture v1.0.0 ran 35 trials with
provider `fixture`, model `deterministic-replay-v1`, effort `medium`; those timings
measure accounting/SQLite work, not inference or lifecycle recovery.

## P09 audit and minimal additions

1. **Preserve and extend transport-boundary coverage.** Cache goldens cover
   Chat Completions/Anthropic/Codex payloads; real-interrupt tests use a real
   `AIAgent` with a slow mocked SDK response. Delegation tests mostly replace
   `AIAgent`/child execution. Efficiency JSONL and reconnect JSON are versioned,
   synthetic accounting/expected-event fixtures; `capture_baseline.py` does not
   replay them through an agent. Add one scripted provider-transport harness
   through real AIAgent callbacks, SQLite and projections, with two children in
   either completion order, duplicate/out-of-order callbacks, parent still active,
   provider error and cancellation acknowledgement before terminal.
2. **Add ownership regressions before P08.** A controlled clock with real SQLite
   and this driver's live PID reproduced unchanged heartbeat expiry (1010→1010),
   live-worker reclaim at 1011, and late original completion marking replacement
   run 2 completed with the old worker's text. Final task status was `user_review`.
   Capture claim fencing/lease extension expectations as failing tests, plus
   explicit board-owner versus execution-profile tests. Dispatcher capture at
   the subprocess boundary retained the board's `SPARK_HOME`; assignee
   `different-execution-profile` was not passed as an execution-profile selector.
   No actual worker was launched. This proves the spawn environment and the
   lease/completion defects, not live provider selection.
3. **Choose lifecycle write ownership using current evidence.** In
   `agent/subagents.py`, emit persists only when no dedicated callback exists;
   otherwise the callback owns persistence. Existing web callback tests passed.
   Do not infer duplicate writes merely from two call sites. Add an actual
   delegation-to-web trace asserting event counts/deduplication through restart.
   Future command receipts, async result delivery and unsupported capabilities
   need explicit fixtures once P01–P03 contracts exist.
4. **Extend migrations/isolation fixtures.** Current SQLite tests cover legacy
   v8 child tables, idempotent backfill and injected rollback/restart. Add a closed
   schema-12 database fixture for the future additive migration, rerun safety,
   metadata import, compression lineage, deleted source and two actual profiles.
   Inbox settlement currently uses static local key `spark.sidebar-beta.settled`;
   draft isolation tests do not verify settlement isolation between backends.
5. **Repair browser gates without hiding baseline failures.** Update sidebar
   locators/contracts to the actual Inbox, retain paging assertions and add stable
   semantic row identifiers. Expose repeat/output-directory options in baseline
   capture; filtered runs currently delete their report and screenshots in
   `finally`. Instrument backend event timing versus DOM receipt explicitly.
   Temporary copies here retain raw outputs and leave all canonical files alone.
6. **Wire the resulting gates into CI.** `web-quality.yml` runs multi-chat,
   chat-contracts, recovery and dev draft recovery, but not sidebar scale,
   baseline capture or built-assets recovery. Its path trigger covers frontend
   files/workflow only, so backend lifecycle changes can miss browser checks.
   Add focused transport/SQLite replay and relevant backend paths, current-sidebar
   scale, a bounded repeated long-thread case and served-production recovery.
   Compare same-host fixtures against this baseline; investigate >10% median/p95
   regressions without dropping failures or substituting asserted expected data.

Still unverified: actual messaging-gateway readiness, real-provider/cache latency,
full browser RSS/transport gaps, all 18 long-thread theme/viewport combinations,
two real clients/backends for settlement, planned async/receipt APIs and new
migration, project wizard/composer submission, installed macOS/Windows packages.
No source/web/package/release claim is inferred from another layer's result.
