# P09 browser gates: implementation and unresolved acceptance

Base **f771a18f**, isolated `/tmp/spark-p09-gates`, branch
`fix/p09-browser-gates`. [Evidence JSON](app-upgrade-browser-gates-2026-10-15.json)
contains commands/exits, raw samples, failure traces and artifact hashes.
This evidence predates parent `6cb9677` and its backup work. **P09 remains open.**

## Implemented scope

- Canonical sidebar gate uses semantic selection/status, scoped preferences,
  server pin metadata and shared action menus. It retains the 60-row mount,
  single-flight offset-50 paging, 100 ms selection/local-filter and 600 ms
  full-history budgets. It exercises 1,000 sessions / 10 projects, both Inbox and
  Threads paging, SSE insertion/unread/anchor, deletion, duplicate pin placements,
  project collapse/drag, keyboard focus, stale CAS and two real isolated profile
  databases containing the same session ID. Initial hydration asserts 50 snapshot
  shells; the app no longer requests `/api/sessions?offset=0` on normal startup.
- `baseline-capture.mjs` accepts `--repeat 1..10`, `--case` and `--output-dir`.
  Repeated/filtered reports and failure screenshots survive in separate run
  directories. Default 18-case selection/publication remains intact. Failed
  repetitions make the aggregate fail. History request diagnostics remain strict;
  rejected losing response promises are consumed without hiding the timeout.
- `browser-gates.mjs` bounds attempts to 240 seconds (sidebar/longthread) or
  300 seconds (production recovery), retains logs/exits, and kills process groups.
- Production helper runs unchanged `work-recovery.py` assertions against freshly
  built assets and a copied Python source tree under temporary output. It redirects
  only the report destination and verifies backend import origin. Canonical
  `web_dist`, package/lockfiles and installed applications are untouched.
- Web-quality watches backend lifecycle paths and runs focused lifecycle,
  persistence, profile, cache/lazy/manifest checks plus repeated sidebar,
  production recovery and longthread gates. Existing Node/Python Playwright setup
  remains. Artifacts upload even on failure. **Hosted CI was not executed.**
  The replay-agent test must be integrated before that CI command can run.

## Results and blockers

- Focused existing backend targets: **272 passed in 81.00 s**, exit 0; manifest
  verification, script syntax, helper Ruff and YAML parsing passed. Initial pytest
  invocation exited 4 for a wrong web-state test path; corrected and rerun.
  Full-source Ruff has **299 findings on this base**, separately from this scope.
- Production-built recovery: **9 checks passed**, exit 0, including drafts,
  attachments, concurrent edits, late acknowledgements and same-origin profile
  identity. Both themes and 1440/1024/768/390 widths ran.
- Longthread: **4/5 passed; aggregate exit 1**. Attempt 4 emitted React
  `Maximum update depth exceeded` through virtualizer `measureElement` and the
  ChatPanel measured-row callback. Last pagination responses were HTTP 200;
  the panel disappeared and the harness rejected its third same-URL recovery.
  This establishes a render failure, not a slow-history-API diagnosis. P00's exact
  response timeout was not identically reproduced; a common cause is unproven.
- Sidebar: **2/3 passed; aggregate exit 1**. Attempt 2 changed the visible anchor
  from `session:scale-032` to `session:scale-073` after SSE insertion. Its local
  filtering also measured 102.8 ms, above the retained 100 ms budget. Earlier
  title-update batches had five-second timeouts; final successful probes took
  3.4–4.8 seconds. These remain app investigation items, with assertions retained.

## Same-host performance against raw P00

macOS 27.0.1, M2 Max / 64 GiB, Python 3.11.7, Node 22.22.1, Chromium
147.0.7727.15. Comparison batches used worktree-local dependency copies and ran
sequentially. Initial shared-dependency/Node-25 exploratory runs are retained but
excluded: shared Vite cache produced invalid-hook failures. Shared-host load is
uncontrolled. Dev, dark, 1440×900, DPR 1; fixtures match P00.

Values below are **median / nearest-rank p95**, with median / p95 percentage
change in parentheses. At these sample sizes p95 is the maximum.

| Probe | Current ms | Change from P00 |
| --- | ---: | ---: |
| Backend spawn → status | 850.82 / 1476.11 | +30.4% / +125.8% |
| 2,000 rows: initial useful render | 1531.19 / 1774.65 | +32.5% / +48.5% |
| First visible token, including synthetic delay | 197.65 / 385.80 | −21.8% / +51.2% |
| First token minus 60 ms synthetic delay | 137.65 / 325.80 | −28.6% / +66.9% |
| Largest visible update gap | 232.15 / 253.50 | +17.7% / +11.0% |
| 1,000 sessions: useful render | 1180.32 / 1225.67 | +12.2% / +11.6% |
| Click → chat-panel identity | 88.00 / 97.20 | +108.0% / +121.9% |
| Local title filtering | 44.70 / 102.80 | +7.2% / +144.2% |
| Full-history search, including debounce | 281.00 / 287.20 | −0.5% / −14.7% |

Four successful history captures loaded all **39 earlier pages**, mounted bounded
rows and sampled **0 px drift**. Sidebar mounted **20 rows**. Longthread timing
statistics exclude the failed capture; sidebar includes completed probes from
its later-failed attempt. Heap median/p95 was 40.26/56.03 MiB (+13.8%/+10.6%).
Title PATCH median/p95 was 4651.3/4780.3 ms; this probe adds a remote-result chat
switch before returning to the selected thread, unlike P00, so its raw delta
must not be attributed to isolated rendering cost.

The stream emits 16 synthetic tokens at 60 ms intervals. Subtracting the first
60 ms leaves HTTP/backend/SSE/UI overhead together. No real inference or messaging;
no pure UI CPU, transport packet gaps or full browser RSS claim.

All regressions above 10% need lead investigation and integrated reruns. Full
18-case matrix, 10k-message browser search p95, newer P06/P07 integration,
canonical release build, hosted CI and installed macOS/Windows gates remain open.

Reproduce from this checkout with the root venv active, Node 22 on PATH,
`PYTHON=/Users/joe/Developer/github/spark/.venv/bin/python` and `PYTHONPATH=$PWD/src`:

```sh
node src/spark_cli/web/e2e/browser-gates.mjs --suite sidebar --repeat 3 --output-dir /tmp/p09-sidebar-new
node src/spark_cli/web/e2e/browser-gates.mjs --suite longthread --repeat 5 --output-dir /tmp/p09-history-new
node src/spark_cli/web/e2e/browser-gates.mjs --suite production-recovery --output-dir /tmp/p09-built-new
```
