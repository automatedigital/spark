# CI verification and troubleshooting

## Trigger policy

The automatic quality workflows use path filters, read-only tokens, job
timeouts and per-workflow/ref concurrency with `cancel-in-progress: true`.
Push checks run only on `main`; feature branches are checked through their PR,
avoiding duplicate feature push and PR runs. A post-merge `main` run verifies
the integrated commit and is separate acceptance evidence.

- `python-quality.yml`: Python source, tests and package metadata; Ruff ratchet,
  incremental mypy, parallel fast tests followed by serial fast tests.
- `web-quality.yml`: frontend and shared backend changes; frontend checks,
  real-backend browser flows, lifecycle/cache/discovery contracts and manifest
  validation. Backend changes can affect Chat, so these triggers stay broad.
- `release-contracts.yml`: PR/manual persistence contracts on Ubuntu and Windows.
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
