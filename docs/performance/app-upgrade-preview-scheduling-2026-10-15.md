# P09 preview request scheduling repair

Base `c152d2ee05173e555f4472b2a21cf3f486fd000f`, branch
`fix/preview-request-scheduling`. [Raw evidence](app-upgrade-preview-scheduling-2026-10-15.json)
contains source hashes, the instrumented pre-fix capture, final reports,
Chromium request phases, filtered NetLog events and artifact hashes. The
[original gates](app-upgrade-browser-gates-2026-10-15.md) and
[prior repairs/failed title attempt](app-upgrade-browser-fixes-2026-10-15.md)
are unchanged. **The focused sidebar gate passes 3/3; P09 remains open.**

## Proven cause

The actual ChatPage keeps the preview pane mounted behind CSS while Files is
visible. `WorkspacePreviewPanel` ignored `visible` for its reads: each selected
project started a local listener scan, status/log reads and a dedicated preview
SSE. Cleanup stopped polling and suppressed some state updates but did not abort
fetch. Switching project-0 → project-9 → workspace → project-0 retained three
slow scans and queued another project-0 scan.

A pre-fix run of the unchanged sidebar assertions passed, but its title update
took **3533.4 ms**. Chromium NetLog directly records
`SOCKET_POOL_STALLED_MAX_SOCKETS_PER_GROUP` on the title PATCH's connection job
(source 1256), from timestamp 415551982 to socket assignment at 415555473.
At PATCH creation, six transmitted requests remained alive on that HTTP/1.1
origin: notifications SSE; shared detail SSE; project-0 preview SSE; and detection
for project-0, project-9 and `__workspace__`. The JSON retains the exact request
sources and phases. This establishes browser connection saturation, rather than
inferring it from a generic pending-request list.

The three scans took **4990.3, 5084.2 and 5018.7 ms** to response headers. The
queued duplicate took **9895.2 ms** overall. The PATCH spent **3490.851 ms** before
transmission and **6.092 ms** from request start to headers. Its wait ended just
after the first scan completed. The backend detection endpoint synchronously
walks listener/process cwd data using `lsof` on this host; no backend repair was
needed to establish or remove the unnecessary browser work.

The earlier failed PATCH with **5515.1 ms** before transmission and **9.4 ms** to
headers, its late overwrite of the restored title, and the resulting locator
timeout remain in the previous report. The new pre-fix sample reproduces the
same scheduling mechanism within the five-second correctness budget.

## Repair and boundaries

- Preview observers run while the pane is visible. Hide/project teardown aborts
  their HTTP reads and closes their SSE. One owner schedules each poll after its
  previous request settles, preventing slow scans from overlapping.
- Preview read APIs accept optional AbortSignals and forward them to the existing
  fetch transport. Late responses are fenced even if they race cancellation.
- Project-local component state is keyed by slug, so the previous project's URL,
  logs and controls cannot appear or drive work in the newly selected project.
- URL changes update the refresh callback without reopening the preview SSE or
  refetching its initial status/logs.
- The streamed external viewer pauses frame SSE/polling while hidden. It retains
  its component/backend browser and reconnects without repeating navigation;
  observer state changes no longer retrigger the navigation effect. Local iframe
  and native browser behavior retain their existing lifecycle.

Explicit Start/Stop/navigation/tab actions remain user actions. Closing an
observer does not stop the backend app/browser. A synchronous scan already
executing on the server may finish after client abort; browser connection
ownership is released. No shared-fetch deduplication, backend, schema, inspector,
project creation, sidebar virtualizer or ChatPanel changes were made.

The sidebar harness only gains CDP request/response/cancellation records and a
Chromium NetLog. Its flow, restore behavior, timeouts, budgets and assertions are
unchanged; the implementation repair accounts for the improvement.

## Verification

Node **22.22.1**, worktree-local `npm ci` using the existing nested lockfile.
Python/server fixtures use activated `/Users/joe/Developer/github/spark/.venv`,
`PYTHON=/Users/joe/Developer/github/spark/.venv/bin/python`, `PYTHONPATH=$PWD/src`
and temporary `SPARK_HOME` directories. Repository Playwright fallback was
already authorized after two T3 preview timeouts. No user profile was accessed.

- TypeScript build (`npx tsc -b --pretty false`): **exit 0**.
- ESLint (`npm run lint`): **exit 0**.
- Vitest (`npm test`): **416 passed / 73 files**, **exit 0**. Five new tests cover
  serialized slow scans, abort/late-response fencing, retry/cleanup, one-shot
  reads and all seven preview read APIs forwarding cancellation.
- Real React/browser fixture (`node e2e/preview-lifecycle.mjs`): **exit 0**.
  Checks initially hidden zero reads/SSE; hide abort/close; late responses;
  project switch URL reset; navigation retaining SSE; explicit Start; reopen
  revalidation; and external frame stream pause/reopen without re-navigation.
  Its API responses are controlled deferred fixtures, not a real external site.
- Temporary Vite production build: **exit 0**, **235.53 KiB gzip / 600 KiB budget**
  using the unchanged bundle check against `/tmp/spark-p09-preview-build-20261015`.
  Existing Vite chunk/static-plus-dynamic Tauri import warnings remain.
- Sidebar: **3/3 passed**, aggregate **exit 0**, sequentially after unit/build work.
  All three preserve the SSE anchor (`scale-041`), with no correctness or page
  errors. Selection **74.4–85.0 ms**, local search **45.3–56.7 ms**, full-history
  search **274.2–296.2 ms**, all within the original budgets. Every trace contains
  **zero preview requests** while the real app is on Files. Screenshots retain
  the selected chat and Files pane; final capture visually checked.
- Production-built recovery: **1/1 suite passed**, aggregate **exit 0**;
  **all 9 draft/attachment/switch/refresh/profile checks passed** against newly
  built temporary assets and copied runtime source.
- Both changed/new `.mjs` files pass `node --check`; `git diff --check` passes.
  Python implementation was unchanged; no new pytest claim is made.

| Final sidebar attempt | Title render ms | Before transmission ms | Request to headers ms | Event to render ms |
| --- | ---: | ---: | ---: | ---: |
| 1 | 15.8 | 0.533 | 5.943 | 7.9 |
| 2 | 18.6 | 0.573 | 7.429 | 8.7 |
| 3 | 18.4 | 0.609 | 7.431 | 8.9 |

Commands from repository root, with the venv/Python environment above:

```sh
node src/spark_cli/web/e2e/preview-lifecycle.mjs
node src/spark_cli/web/e2e/browser-gates.mjs --suite sidebar --repeat 3 --output-dir /tmp/spark-p09-preview-sidebar-20261015-final
node src/spark_cli/web/e2e/browser-gates.mjs --suite production-recovery --repeat 1 --output-dir /tmp/spark-p09-preview-recovery-20261015-final
```

## Performance and remaining objections

Same synthetic 1,000-session/10-project fixture, dark, dev, 1440×900, DPR 1,
provider-free on the shared M2 Max host. Host load is uncontrolled. Three trials
are bounded evidence; nearest-rank p95 is their maximum. The P00 title probe did
not switch into a full-history result and back, so its delta is not isolated
rendering cost. NetLog was enabled in both the new before and after runs.

| Sidebar probe | Final median / p95 ms | Delta from raw P00 median / p95 |
| --- | ---: | ---: |
| Useful render | 1200.9 / 1215.8 | +14.2% / +10.7% |
| Selection | 83.6 / 85.0 | +97.6% / +94.1% |
| Local filter | 55.8 / 56.7 | +33.8% / +34.7% |
| Full-history search | 277.3 / 296.2 | -1.8% / -12.0% |
| Title update (changed flow) | 18.4 / 18.6 | -47.7% / -53.5% |

**Useful render, selection and filtering regressions above 10% remain open.**
The prior long-thread measurements were not rerun here: startup +31.3%/+95.6%,
render +73.9%/+84.0%, first-token p95 +11.4%, visible update gap +23.1%/+16.4%,
and heap +32.0%/+12.5% remain unresolved as recorded. Their raw summaries are
carried into the new JSON without presenting them as fresh measurements. Prior
long-thread correctness was 5/5 with 39 earlier pages and zero anchor drift;
final integrated source acceptance remains parent-owned.

Notifications still use a separate SSE and model-status duplicates were observed;
this patch does not claim to remove every possible connection-pressure source.
The focused title scheduling defect is repaired in the exercised flow; the full
18-case matrix, controlled performance runs, 10k-message search p95, integrated
inspector/recovery, hosted CI, canonical bundle, installed macOS/Windows and
release gates remain open. No PLAN checkboxes, original evidence, lockfiles,
generated artifacts, canonical bundle, push, PR or release changes.
