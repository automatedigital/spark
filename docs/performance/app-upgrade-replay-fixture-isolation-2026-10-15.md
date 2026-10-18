# Replay fixture isolation follow-up — 15 October 2026

Scope: the gateway async-delivery fixture, HTTP orchestration replay fixture,
and provider-boundary async replay fixture. The starting commit is
`a45a6e4b67059dc5489baa5c905c7e44093ce538`, including the earlier cache/CLI
restoration repairs, caller policy and Telegram topic changes. No application,
runtime, gateway, CLI, bundle, lockfile or PLAN source is changed.

## Config precedence reproduced

The HTTP replay wrote `delegation.async_enabled: true` to its temporary
profile, but the real delegate loader prefers populated `core.cli.CLI_CONFIG`.
Running CLI initialization before the first HTTP replay deterministically
produced **one failed, one passed / 11.77s**. The tool response was
`{"error": "Async execution is disabled"}` and neither child entered its HTTP
gate. Raw evidence: `config-before.txt`.

The fixture now binds the actual CLI config slot to the same synthetic config
written to the profile. It does not replace the loader, agent, credential
resolution, SDK, tools or SQLite. This follows the existing gateway fixture's
runtime-config binding. Monkeypatch restores the previous slot after teardown.

## Interrupt attribution and real worker reuse

A bounded profiling plugin recorded calls to the real `set_interrupt`, their
thread targets, stacks and whether their function globals matched the canonical
module. The gateway finalizer calls `parent.interrupt()` even for an idle parent
whose conversation already finished and cleared its own signal. It then closed
the parent without clearing the newly set worker-thread signal. The captured
calls used canonical module globals; these runs did **not** establish a retained
module alias as the cause.

An ordinary gateway-then-main-thread-echo pair passed: the echo did not reuse the
interrupted worker. A separate, read-only diagnostic hook submitted a real
`LocalEnvironment.execute("echo fixture-cleanup")` to the actual shared runtime
pool after the gateway fixture finalized. The thread ID matched the cached
parent's execution thread. Before cleanup, the gateway test passed but the
diagnostic failed with return code **130**, output `[Command interrupted]`:
**one passed, one teardown error / 11.60s** (`worker-reuse-before.txt`,
`worker-probe-before.json`). No agent, tool, interrupt method, runtime executor
or signal registry was replaced by this hook.

The gateway fixture now calls each owned parent's real `clear_interrupt()` after
the adapter tasks and child workers drain, before closing that parent. Its
synthetic adapter also installs the real runner's approval-authorizer callback,
matching production adapter wiring. It does not fabricate authorization.

The async replay fixture likewise clears its owned parents through their real
API after child workers drain and asserts that draining completed. It no longer
swaps the process interrupt registry. This clears signals through the same
loaded function that set them, including parents stopped before their first
conversation. There is no global autouse clearing or production semantic change.

After the repairs, the combined five-case repro passed **5 tests / 13.75s**:
CLI initialization, idle gateway Stop, the HTTP replay, async child cancellation,
and main-thread live echo. The post-finalizer worker probe also ran on the same
parent worker, returned **0**, and printed exactly `fixture-cleanup`.
Evidence: `repros-after.txt`, `worker-probe-after.json`.

## Mixed-order checks and limits

Before the parent-owned cleanup repair, all CLI tests followed by the gateway
fixture suite, async-cancel case and live echo passed **471 tests / 142.51s**.
Full collection followed by execution of only async-cancel and live echo also
passed **2 tests / 30.41s** (15 collection skips, 12,793 deselected). These
negative reproductions are retained; they do not reproduce or dismiss the root
broad run's 46 failures. The worker-reuse diagnostic establishes a concrete
fixture leak without claiming to reconstruct that exact xdist schedule.

The final combined run passed **574 tests / 203.22s**. Its two existing warning
families are the unknown `ssh` marker and an unawaited `Process.communicate`
coroutine. CI-selected source Ruff rules and `git diff --check` also pass.
All owned test commands have exited. Commands and evidence hashes are recorded
in the companion JSON. The combined run includes CLI collection and runtime,
both async replay suites, gateway
delivery, real local shell/file/performance cases, cache goldens, lazy manifest,
lazy import and minimal startup gates in one serial process. An outer synthetic
`SPARK_HOME` covers collection-time imports; the suite's existing autouse fixture
isolates each executing test. The real HTTP replay SDK/adapter/SQLite/interrupt
pipeline remains in use, with synthetic external I/O and no external provider or
messaging-service calls.

All Python commands activate the root checkout's `.venv` and set `PYTHONPATH` to
this worktree's `src`, avoiding the editable root checkout's source. Diagnostic
plugins and unabridged logs remain in
`/tmp/spark-upgrade-replay-fixture-isolation-20261015`; commands and SHA-256 hashes
are in the companion JSON. An initial diagnostic invocation using pytest `-p`
was rejected during collection because Spark's CLI pre-parser interpreted it as
its profile option; the retry used `PYTEST_PLUGINS` without changing application
code. That failure log is retained too.

The original broad result remains **62 failed, 12,559 passed, 151 skipped /
555.54s**, recorded in
`/tmp/spark-upgrade-20261015/full-local-pytest-caller-policy.txt`. The root agent
must run the final broad suite after integration. No exclusions, xfails, timeout
or performance budget changes are introduced here; package/browser gates and
PLAN remain outside this fixture-only repair.
