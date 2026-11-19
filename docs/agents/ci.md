# CI verification and troubleshooting

## Trigger policy

The automatic quality workflows use read-only tokens, job
timeouts and per-workflow/ref concurrency with `cancel-in-progress: true`.
Push checks run only on `main`; feature branches are checked through their PR,
avoiding duplicate feature push and PR runs. A post-merge `main` run verifies
the integrated commit and is separate acceptance evidence.

- `python-quality.yml`: Every PR reports Ruff, mypy, and pytest. Qualifying PRs
  run startup, packaging, cache, discovery, transport and persistence contracts
  plus the affected cron, artifact, or file-tool tests when applicable. Mixed
  backend areas, shared code, dependency and fixture changes, and unknown paths
  run the full gate. An unavailable or mismatched Git diff also runs the full
  gate. Pushes to `main` and manual dispatch always run the full fast suite.
  Both paths keep separate non-serial and serial runs, the two slow ownership
  contracts, and tool manifest validation. The workflow logs its selected scope.
- `web-quality.yml`: frontend lint, types and unit tests on frontend and shared
  backend changes. Run browser acceptance locally. An explicit manual dispatch
  runs the full Ubuntu browser fallback after the frontend checks pass.
- `release-contracts.yml`: PR/manual Windows persistence contracts. Windows adds
  distinct atomic replacement, open-file and path behavior; Linux cases already
  run in Python quality, so there is no duplicate Ubuntu persistence job.
- `web-supply-chain.yml`: nested frontend manifest/lockfile and workflow changes.
- `python-dependency-audit.yml`: dependency PRs, weekly schedule and manual runs.
- `actionlint.yml`: workflow edits. Windows desktop beta packaging is manual.

Keep meaningful failures blocking. Do not rerun an unchanged failure repeatedly,
increase timeouts, remove assertions or narrow triggers just to obtain green CI.
Inspect the failed job and exact head first; fix the cause, then validate the
updated head. Superseded/cancelled runs do not establish current acceptance.

## Local gate commands

Activate `.venv` with the dev/web extras installed before Python checks. Pytest's
command-line marker expression replaces the configured one, so preserve the
external-service exclusions. The CI fast-test split is sequential:

```bash
source .venv/bin/activate
python -m pytest tests/ -m "not serial and not slow and not integration and not network" -q --timeout=60 -n 4
python -m pytest tests/ -m "serial and not slow and not integration and not network" -q --timeout=60 -n 0
```

For a scoped PR, substitute the exact targets printed by the selector for
`tests/` in both commands. The full workflow runs two small regression selections
first and excludes those same node IDs from the later non-serial pass.

The Python job also runs these separately, preserving the slow cases formerly
inside the browser job and the generated-schema gate:

```bash
python -m pytest tests/tools/test_subagent_worktree.py tests/core/test_kanban_worker_ownership.py -m "slow and not integration and not network" -q -n 0
python scripts/generate_tool_manifest.py --check
```

Use `-n 0` for focused selections containing serial tests. The explicit 60-second
timeout above matches hosted CI; repository pytest defaults remain unchanged.
The full suite and browser/package acceptance remain separate requirements where
applicable. Follow [AGENTS.md](../../AGENTS.md) for those gates and isolated
`SPARK_HOME` manual servers. Verify the actual Node 22 version and executable
before frontend acceptance runs.

Full `ruff check src/` has baseline debt: the 2026-11-17 audit at `440cbaae`
found 298 findings (E402/E701/E702/E731/E741). Report new findings separately;
do not add ignores to conceal them. The hosted ratchet command is:

```bash
ruff check src/ --select UP015,F,B,I,W,UP028,UP031,UP035,UP037,UP042 --ignore B027
```

## Local web build and browser acceptance

Run the affected browser flows for web and shared-backend changes. For full
browser acceptance, run the block below from the root of a disposable checkout
at the candidate commit. The build writes to the tracked `web_dist/` directory
and draft recovery writes into `web/screenshots/` in that checkout.

Use Python 3.11 with `.[dev,web]` installed in `.venv` and Node 22. The Node
lockfile and Python Playwright 1.62.0 require separate Chromium revisions.
On macOS install both as shown below. On Ubuntu 24.04 use
`npx playwright install --with-deps chromium` for the first install.

```bash
(
  set -e
  lock=/tmp/automatedigital-local-ci-heavy.lock
  mkdir "$lock" || { echo "Heavy validation busy. Retry once the lock is free." >&2; exit 1; }
  trap 'rmdir "$lock"' EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  source .venv/bin/activate
  export PYTHON="$(command -v python)"
  reports="$(mktemp -d "${TMPDIR:-/tmp}/spark-browser-gates.XXXXXX")"
  printf 'Browser reports: %s\n' "$reports"
  cd src/spark_cli/web
  node --version
  node -p process.execPath
  node -e 'if (process.versions.node.split(".")[0] !== "22") process.exit(1)'
  npm ci
  npm run lint
  npx tsc --noEmit -p tsconfig.app.json
  npm test
  npx playwright install chromium
  python -m pip install playwright==1.62.0
  python -m playwright install chromium
  node e2e/integration-settings.mjs
  npm run test:e2e
  COMPOSER_HISTORY_OUTPUT="$reports/composer-history" node e2e/composer-history.mjs
  STASH_OUTPUT="$reports/prompt-stash" node e2e/prompt-stash.mjs
  MERMAID_OUTPUT="$reports/mermaid" node e2e/mermaid.mjs
  MERMAID_COMPLETION_OUTPUT="$reports/mermaid-completion" node e2e/mermaid-completion.mjs
  node e2e/cron-overrides.mjs
  node e2e/cron-outputs.mjs
  node e2e/chat-contracts.mjs
  npm run test:e2e:recovery
  python e2e/work-recovery.py
  node e2e/browser-gates.mjs --suite sidebar --repeat 3 --output-dir "$reports/sidebar"
  npm run build
  node e2e/browser-gates.mjs --suite production-recovery --built-assets ../web_dist --output-dir "$reports/production-recovery"
  SPARK_E2E_BUILT_WEB=1 SPARK_E2E_REPORTS="$reports/inspector" python e2e/subagent-controls.py
  SPARK_E2E_BUILT_WEB=1 SPARK_E2E_REPORTS="$reports/navigation" python e2e/subagent-navigation.py
  node e2e/browser-gates.mjs --suite longthread --repeat 3 --output-dir "$reports/longthread"
)
```

Record the candidate SHA, commands and results. For an Ubuntu comparison or
when local acceptance is unavailable, manually run **web-quality** for the
candidate ref and confirm the run's SHA. Hosted browser diagnostics upload on
failure and expire after three days. A failed browser gate still requires
resolution before claiming browser acceptance.

## Desktop packaging

Build packages on the target platform. On a Mac with Xcode Command Line Tools,
Rust, Node 22 and Python 3.11, run `bash scripts/build_desktop.sh`. Signed,
notarized builds also need the signing identity and notary profile documented
in `scripts/release.env.example`.

On Windows x64, use PowerShell 7, Python 3.11, Node 22, Rust stable with the MSVC
toolchain, Visual Studio C++ Build Tools with a Windows SDK, and WebView2.
Install `python -m pip install -e ".[web,pty,messaging,dev]"` in a Windows venv,
then run `./scripts/build_desktop_windows.ps1`. Use the manual **Windows desktop
beta** fallback for native worktree and packaged lifecycle validation or when a
local Windows builder is unavailable. It retains the versioned unsigned NSIS
installer for 30 days. Publishing a verified installer is a separate release
step. Web/browser acceptance and installed-package acceptance are separate.

## Replay and output-test isolation

The November 17 campaign found a retry replay deadline expiring during SDK
client setup, followed by late HTTP dispatch contaminating another replay.
The corrective coverage separates setup expiry (zero dispatches) from in-flight
expiry (one request, unchanged 150 ms budget and <500 ms return bound). Await
worker cleanup before restoring transport monkeypatches; do not substitute a
larger deadline for synchronization. Runtime dispatch must recheck retired
ownership and its captured budget after client setup.

A quiet retry-output test also timed out in unrelated goal/Kanban prompt reads.
Keep that unit test isolated from goal persistence and curator scheduling, and
patch its retry-delay calculation rather than process-wide `time.sleep`.
Goal/persistence and retry-deadline contracts retain their own coverage.

Focused reproduction, without a provider or live profile:

```bash
source .venv/bin/activate
python -m pytest tests/run_agent/test_retry_transport_replay.py tests/run_agent/test_stream_capability_fallback.py::test_root_and_children_negotiate_without_duplicate_dispatch_or_file_tools tests/run_agent/test_run_agent.py::TestExecuteToolCalls::test_run_conversation_suppresses_retry_noise_in_parseable_quiet_mode -q -n 0
```

Focused passes do not supersede a failed hosted job. Validate corrective changes
on their current head and refresh dependent PRs after merge. Hosted browser and
cross-platform persistence checks do not prove an installed desktop package or
a live deployment works.

## November 17 right-sizing audit

Before: seven code-change PR jobs (three Python, two frontend/browser, two
persistence). After: six, retaining the Windows persistence job and all distinct
behavior checks. No dependency, assertion, timeout or retry policy was relaxed.
The browser job no longer repeats 25 backend test modules: fast cases run in the
Python fast/serial split; its only two slow cases run explicitly there too.
In green main run `44135008533`, the duplicate backend step took 5m32s. Removing
it saves that observed browser-job work minus the two slow cases moved to Python;
this is an estimate until the revised hosted run completes, not a latency promise.

The long-thread harness served Vite but built temporary assets that no consumer
read. Remove those three unused compiles while retaining all three independent
browser attempts, seeded profiles and assertions. Canonical production build and
isolated production-recovery build remain: they exercise distinct served bundles.
Node and Python Playwright browser installs remain because their pinned versions
use different browser revisions; sharing that cache would select the wrong binary.
Desktop packaging stays manual, outside ordinary PR quality work.

Inspected campaign cancellations belonged to superseded correction heads; the
sampled jobs had acquired runners and were cancelled during execution. No
runner-acquisition failure was found in that sample. Historic dependency-update
failures were real npm peer conflicts, handled by scoped deferrals in #263 and
tracked major-toolchain coordination in #262, not forced installs. An earlier
actionlint SC2016 finding was corrected with a targeted literal-JavaScript
annotation. These historical outcomes do not replace current-head checks.

A later serial run exposed a transient-observation race in the busy-follow-up
replay: the runtime handled the interrupt and cleared its flag before the test's
poll sampled it. Latch the flag/message observation at the real HTTP close
boundary instead of polling a flag that correctly resets. Keep exactly-once
follow-up, cache identity, transcript and request-count assertions unchanged.

The retained Windows gate subsequently exposed a real canvas revision collision:
requesting an mtime one nanosecond ahead can round back to the old revision.
Verify the temporary file's actual revision advances before atomic replacement;
reject publication if the filesystem cannot represent it. Precision-simulation
regressions supplement, rather than replace, hosted Windows contention tests.

## November 18 production browser build

The full browser gate uses one fresh `npm run build` for production recovery, the
child inspector and navigation. The build step checks types and bundle budgets
before any of those browser gates run. Recovery copies those assets into its
temporary backend tree and records the supplied build path and manifest.
Standalone recovery without `--built-assets` still builds into its own temporary
tree. Missing or incomplete explicitly supplied assets fail the gate.

The sidebar browser gate waits for second-page rows to render before capturing
the scroll anchor for the SSE insertion check. Seeing the request alone can
leave pagination and insertion overlapping in this fixture. The test still
requires one second-page request and the same visible anchor after insertion.
