# Integrated Python regression follow-up — 15 October 2026

The first broad run after the approval stack **failed**: 79 failed, 12,438
passed, 151 skipped, 136 warnings in 454.54 seconds. The original log remains
`/tmp/spark-upgrade-20261015/full-local-pytest-integrated-approval.txt`.
These failures are not reclassified as baseline or environment exclusions.

## Cache cleanup compatibility: 32 failures

Legacy direct `_run_agent` callers construct runners without the optional agent
cache. Acquisition already checks for that cache and lock, but the new worker
finally block accessed `_agent_cache_lock` unconditionally, masking the turn's
result or original error. Cleanup now uses the same optional-lock condition.
Fully initialized cached runners retain lock-protected owner-identity cleanup.

The reasoning representative fails before the repair while the live-shell and
CLI representatives pass (one failed, two passed / 6.37s). After repair:

```sh
source .venv/bin/activate
python -m pytest -q -n 0 tests/gateway/test_reasoning_command.py tests/gateway/test_run_progress_topics.py tests/gateway/test_web_stale_retry.py tests/run_agent/test_anthropic_error_handling.py tests/cron/test_codex_execution_paths.py
```

**37 passed / 127.51s**. Log: `gateway-legacy-cache-compatibility.txt` under the
same temporary evidence directory. These existing cases verify original results,
provider retries and progress behavior rather than duplicating the new guard.

## Replay interrupt-state leakage: 46 failures

The async replay can interrupt a parent that has never entered a conversation.
Its real interrupt API targets the calling thread in that case. The fixture
did not restore that process-global signal, so subsequent real local commands
returned code 130 and file operations failed. This is test-state leakage; the
production interrupt API has not been changed.

Before repair, running the two cases below in one worker produces **one passed,
one failed / 0.69s**; the echo case passes in a separate process. The fixture now
isolates the interrupt registry through its existing monkeypatch lifetime, while
retaining real interrupt behavior during each replay and draining its children.

```sh
python -m pytest -q -n 0 tests/run_agent/test_async_delegation.py::test_cancel_one_child_preserves_sibling_and_duplicate_acceptance tests/tools/test_file_tools_live.py::TestLocalEnvironmentExecute::test_echo_exact_output
python -m pytest -q -n 0 tests/run_agent/test_async_delegation.py tests/tools/test_file_sync_perf.py::TestLocalPerf tests/tools/test_file_tools_live.py
```

After repair the second command passes **73 tests / 41.57s**, including the live
shell/file checks. Logs: `interrupt-fixture-leak-before.txt` and
`interrupt-fixture-leak-after.txt`. An existing unknown `ssh` marker warning
remains; no test is skipped to repair this group.

## CLI module restoration: one broad-run failure

The resume-display case passes alone and with full collection but without prior
tests. The serial CLI suite reproduces it plus 12 related module reload errors:
**13 failed, 448 passed / 15.11s**. The provider-resolution fixture restores
`sys.modules` after temporarily importing CLI modules, but left `core.cli` on the
parent package pointing at the temporary module. Consequently two import forms
could use different config globals, and reload could reject that stale module.

The fixture now restores the parent-package reference along with its module
cache. The same serial CLI command then passes **461 tests / 15.40s**:

```sh
python -m pytest tests/cli/ -q -n 0 -m 'not integration and not network'
```

Logs: `cli-suite-isolation-before.txt` and `cli-suite-isolation-after.txt`.
One existing unawaited `Process.communicate` warning remains in each run.

## Acceptance limit

Focused groups cover all three observed failure families. A fresh broad run
after the remaining integrations is still required; these focused passes do
not turn the failed broad run into a pass. Caller-authorization review findings,
memory retention, search-scroll diagnosis and package gates remain separate.
CI-selected Ruff and whitespace checks pass for the cleanup change.
