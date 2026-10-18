# P09 functional browser acceptance — 2026-10-17

Base: `99be7b43e1de8caf7c7f90e48f67c241ce0396bd`. Clean checkout before work.
Only inspector fixture/evidence changes; no application source or bundle changes.
Node verified as v22.22.1 at `/Users/joe/.nvm/versions/node/v22.22.1/bin/node`.
Python: `/Users/joe/Developer/github/spark/.venv/bin/python`, activated root venv,
with `PYTHONPATH` pointing at this checkout's `src`. Dependencies installed with
the nested lockfile into this worktree. All fixtures use temporary Spark homes,
ephemeral ports, synthetic streams/transports and no model or external sends.

## Executed gates

All commands below exited 0. Paths are relative to repository root.

| Command | Actual acceptance |
| --- | --- |
| `node src/spark_cli/web/e2e/multi-chat.mjs` | Three live chats, no cross-thread tokens/stale loading, compaction failure, persisted transcript after backend restart |
| `node src/spark_cli/web/e2e/chat-contracts.mjs` | Existing edit/retry/fork/copy/tool/approval/stop/redirect browser contracts |
| `node src/spark_cli/web/e2e/recovery-state.mjs` | Stalled reconnect, no prompt POST, failed outcome, retained approval, three-chat switching, gateway/backend restart |
| `node src/spark_cli/web/e2e/chat-history-anchor.mjs` | Two pagination trials, -0.5 px drift each |
| `SPARK_E2E_OUTPUT_DIR=$ART/sidebar node src/spark_cli/web/e2e/sidebar-scale.mjs` | 1,000 sessions/10 projects, bounded rows, offset-50 paging, full-history search, SSE insertion anchor/unread, delete, server pins, drag, focus, stale revision rejection, two real profile databases with duplicate session ID |
| `python src/spark_cli/web/e2e/work-recovery.py` (report destination overridden through importlib) | Nine existing flows: refresh/switch drafts, failed send, late acknowledgement, concurrent browser-tab conflict, isolated thread drafts, ready/interrupted/failed attachments, profile identity isolation at the same origin; both themes at 1440/1024/768/390 px |
| `python src/spark_cli/web/e2e/subagent-controls.py` | 11 dev-mode flows: per-child capabilities, three live chat/draft/attachment/scroll retention, Stop/Retry receipt reuse, late acknowledgements, SSE/snapshot reconciliation, event/message cursor paging, result copy, offline/reconnect, narrow keyboard overlay, real process restart/epoch reconciliation, failed project creation |
| `python src/spark_cli/web/e2e/subagent-navigation.py` | Six dev-mode flows: actual task board, late task lookup fencing, collisions/unowned rejection, lost worktree acknowledgement/idempotent link, late project acceptance fencing, deleted task/removed checkout and refresh without replay |
| Same inspector and navigation commands with `SPARK_E2E_BUILT_WEB=1 SPARK_E2E_ASSET_DIR=$ART/assets` | Same 11 + 6 flows through Python-served, independently built hashed production assets; no page errors |

`ART=/tmp/spark-finish-20261017-browser-00a025d1`. Full commands are in
`$ART/commands.txt`; each suite has its own log. Inspector/navigation/work-recovery
and sidebar directories contain JSON reports and screenshots. Multi-chat artifacts
also remain in the ignored `web/screenshots/e2e` directory. Production was built
with `(cd src/spark_cli/web && ./node_modules/.bin/vite build --outDir $ART/assets --emptyOutDir)`;
the manifest is `$ART/assets/.vite/manifest.json`. Canonical `web_dist` was untouched.

## Retained failure and fixture repair

The first dev inspector run failed waiting for `retry-alpha` after switching back.
It released a held HTTP response and immediately remounted the originating child,
without waiting for acknowledgement processing. The fixture now waits for the
persisted receipt while the other child remains selected, then asserts no output
bleed and switches back. It retains the uncertain-response/request-ID assertions.
Original failure, DOM, screenshot and partial report remain in `$ART/controls-dev`.
The corrected run is `$ART/controls-dev-fixed`.

The historical 200-only asset assertion is replaced by byte/digest evidence and
strict ETag revalidation. A 304 requires its browser conditional validator to
match the response ETag and a previously observed 200 body. Independently, every
ETag-bearing asset is fetched unconditionally (200, same body SHA-256) and then
conditionally (304, same ETag, empty body). This exercises real revalidation even
when Chromium serves reloads as cached 200 responses. No blanket 304 allowance.
Final production run: 21 observed asset responses (all 200), 21 successful
explicit 200/body-hash → conditional 304/ETag/empty-body revalidations, 11 checks,
zero page errors. The earlier production run is retained separately as
`$ART/controls-production-before-explicit-revalidation`.

## Boundaries

- Schema-12 upgrade and eligible old-metadata import are not newly exercised by
  these browser fixtures. Sidebar verifies rejection of unscoped legacy pins;
  it does not prove eligible migration. Root owns the separate compatibility evidence.
- Deleted task/checkout and thread deletion pass. A generic empty/deleted external
  source fixture is not present in these gates; do not infer that broader claim.
- The previously reported nine production work-recovery checks and broad Python/
  frontend totals were not rerun or counted as new evidence here.
- These runs do not prove a real provider worker, installed desktop, staging,
  performance/retention acceptance, or absence of console-only errors. Inspector
  records page errors; deliberate failed transports remain part of its fixtures.
  The earlier reload-cancelled FileTreePane console diagnostic was not reproduced
  as a functional failure here; no UI change or console filtering was introduced.
- Production build passed; touched-file Ruff and `git diff --check` passed.
  No full-suite repetition, publishing, installed-app changes or user-state writes.
