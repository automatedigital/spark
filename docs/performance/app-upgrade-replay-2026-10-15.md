# P09 runtime transport replay evidence

Base: `bed0d01007b47e78e6a90c8f8f5db0a754bf2ac0`, branch
`test/p09-transport-replay`, clean on entry. Worktree:
`/Users/joe/.t3/worktrees/spark/t3-147b1894`. This report records a test contribution,
**not P09 acceptance**. No runtime, frontend, config, worker, roadmap, lockfile,
generated manifest or bundle edits; no push, PR or child-agent spawn.

## Boundary and provenance

The new [test module](../../tests/run_agent/test_orchestration_replay.py) runs real
AIAgent roots/children, actual SDK JSON/SSE parsing, delegate and read_file tools,
production lifecycle/web callbacks, SQLite transactions/receipts and web-journal
fanout. Both JSON and SSE root responses are exercised; children use SSE.
Root identities and an initial active projection are seeded; root HTTP execution
remains blocked while child completion assertions run. This does not exercise
the web request wrapper's authoritative root-terminal transition.

Only external HTTP I/O is replaced at `httpx.HTTPTransport.handle_request`;
cancellation also holds HTTP transport close acknowledgement. A real SQLite
trigger injects commit failure. Compression calls the real auxiliary SDK through
the same HTTP boundary, in both legacy-split and typed-checkpoint modes. The
process-loss fixture runs real agents/workers and exits with `os._exit(73)` after
acceptance and both child requests. Restart reconciles the actual dead PID;
there is no fake process-liveness result or reconstructed child/domain event.

[Fixture schema/provenance](../../tests/fixtures/app_upgrade/replay/README.md)
describes authored synthetic protocol data. The `.invalid` origin, model, key,
file contents and messages are synthetic; no credentials or user data are saved.
Global profile/web state is isolated per test. Two-profile coverage uses distinct
real databases and identical session/request IDs, with sequential profile changes.

Environment: macOS 27.0.1 arm64, Python 3.11.7, OpenAI SDK 2.24.0, httpx 0.28.1,
pytest 9.0.2. All Python commands activated
`/Users/joe/Developer/github/spark/.venv`; `PYTHONPATH="$PWD/src"` selects this
worktree (module origins independently verified). No dependency installs.

## Invariant coverage

- Two real child HTTP/tool runs complete alpha/beta or beta/alpha while the real
  root's next provider response remains blocked. Child/app identities persist;
  neither child completion changes the root projection or ends its session.
- Lost dispatch acceptance, two concurrent retrying callers and changed-payload
  conflict retain the original handles and create no extra attempts.
- Duplicate captured lifecycle callbacks add no events/publications. An unseen
  delayed started callback preserves terminal projection across real callback,
  SQLite, web journal and DB reopen. Durable and web cursor identities are checked.
- Cancellation returns durable `stopping` before blocked HTTP close acknowledges
  terminal interruption. Sibling work continues; late replies do not undo Stop.
  Parent Stop interrupts both children; explicit resume appends stored outcomes.
- Actual HTTP 400 provider rejection is a child failure with an active root.
  Aborted SQLite completion commit cannot publish completed success.
- Real process death yields uncertain jobs/receipts, idempotent restart and no
  automatic SDK request. Uncertain retry is rejected; explicit parent recovery
  delivers the two stored uncertain outcomes.
- A real provider-issued clarify call produces a durable decision through the
  real web callback. Both children completing cannot resolve it or allow settle;
  its ID persists across DB reopen, and an explicit answer releases the root.
- Actual legacy and typed compression retain child identity/status access and
  append results at the next explicit parent boundary. Repeated boundaries do
  not duplicate delivery. Cached system/schema data stays stable outside compression.
- Identical session/request IDs in two actual profile databases yield distinct
  attempts. Foreign child status is rejected; delivering in one database cannot
  acknowledge or expose the other's results.

## Results and reproduction

All pytest commands use `-q -n 0 -m 'not integration and not network'`.

| Check | Result | Exit |
| --- | --- | --- |
| Final new replay module, including strengthened durable-event audit | 15 passed, 2 strict xfailed, 24.39 s | 0 |
| Surrounding runtime/cache/lazy gates, including new module | 202 passed, 2 strict xfailed, 1 manifest freshness failure, 84.84 s | 1 |
| Sidebar metadata, persisted web turns, async control routes, web state | 73 passed, 6.14 s | 0 |
| Both defect tests with `--runxfail` | 2 failed at intended invariant assertions, 15 deselected, 4.27 s | 1 |
| Ruff on new Python files | All checks passed | 0 |
| Pinned worktree manifest `--check` | Expected generated-manifest drift at supplied base | 1 |
| Parent checkout manifest `--check`, read-only | 70 tools, 28 isolated modules, 4 optional guards | 0 |

The manifest was not edited or regenerated. Parent has since integrated its P04
helper and generated manifest; those source commits were not imported into this
pinned test worktree. Its passing manifest check does not make this checkout's
failed check pass. The checks establish no repository-wide Ruff/mypy debt; full
Ruff, mypy and full pytest were not run here.

```bash
source /Users/joe/Developer/github/spark/.venv/bin/activate
export PYTHONPATH="$PWD/src"
python -m pytest tests/run_agent/test_orchestration_replay.py -q -n 0 -m 'not integration and not network'
python -m pytest tests/run_agent/test_orchestration_replay.py tests/run_agent/test_async_delegation.py tests/core/test_child_lifecycle.py tests/core/test_runtime_commands.py tests/agent/test_subagents.py tests/agent/test_subagent_progress.py tests/tools/test_delegate.py tests/tools/test_delegate_toolset_scope.py tests/run_agent/test_caching_golden.py tests/run_agent/test_compression_boundary.py tests/run_agent/test_primary_runtime_restore.py tests/run_agent/test_real_interrupt_subagent.py tests/efficiency/test_context_checkpoint.py tests/test_model_tools_lazy_imports.py tests/test_minimal_startup.py tests/tools/test_lazy_manifest.py -q -n 0 -m 'not integration and not network'
python -m pytest tests/spark_cli/test_sidebar_metadata.py tests/test_web_turn_persistence.py tests/spark_cli/test_async_subagent_routes.py tests/spark_cli/test_web_state.py -q -n 0 -m 'not integration and not network'
python -m pytest tests/run_agent/test_orchestration_replay.py -q -n 0 -m 'not integration and not network' -k 'stream_unsupported or lost_dispatch_ack_retry_after_real_compression' --runxfail
ruff check tests/run_agent/test_orchestration_replay.py tests/fixtures/app_upgrade/replay/process_loss.py
python scripts/generate_tool_manifest.py --check
```

Raw local outputs: `/tmp/spark-p09-replay-gates.log`,
`/tmp/spark-p09-replay-projections.log`, `/tmp/spark-p09-replay-defects.log`,
`/tmp/spark-p09-replay-final.log`. The broad gate preceded the final event-count
assertion; the final replay module was rerun after that assertion was corrected.
These are local evidence, not committed artifacts. Earlier fixture-development
failures were corrected: `working` versus the web callback's normalized `running`,
an over-specific summary-prompt assertion, and assuming unsupported-stream fallback
already worked. A final durable-event audit initially filtered only top-level
run_id, omitting the atomic acceptance-created event; it now uses the canonical
subagent_run.id and checks one-to-one event IDs/counts across DB reopen. The
stream fallback assumption became the independently verified defect below.

## Reproduced defects for the parent

1. **Unsupported streaming aborts the current request.**
   `test_stream_unsupported_http_response_falls_back_in_same_explicit_turn`
   gets real SDK BadRequestError from HTTP 400 `stream is not supported`.
   `provider_transport.py` sets `_disable_streaming=True`, but `turn_loop.py`'s
   non-retryable client-error branch aborts; final response is None and no JSON
   request is attempted. Fix the narrow pre-delivery capability negotiation path
   to retry non-streaming within the same explicit turn, with a bounded retry and
   unchanged messages/tool schemas. Preserve errors after any delivered output.

2. **Lost dispatch acceptance is not idempotent across legacy compression.**
   `test_lost_dispatch_ack_retry_after_real_compression_reuses_original_receipt`
   dispatches/finishes two actual children, really compresses into a new session,
   and repeats the identical request ID/payload. New handles/attempts and two extra
   jobs are created. `delegate_tool.py`'s early lookup and
   `dispatch_async_children` use the current session, despite controls/delivery
   resolving the compression family. Resolve the original authorized owning
   session's receipt before accepting a new command; retain payload-conflict and
   profile isolation checks, including the concurrent acceptance path.

Both are strict expected failures so a fix yields XPASS and requires removing the
marker. `--runxfail` independently confirmed the intended failed assertions;
they remain release objections, not passing coverage. Their introduction date
was not established; they are findings against the requested base.

## Remaining acceptance boundaries

Parent must integrate fixes and the regenerated manifest, remove the relevant
xfail marks and rerun the gates against the integrated commit. No browser/UI
journey, TypeScript reducer, actual gateway restart/external messaging, real
provider performance, multi-backend browser isolation, installed macOS/Windows
package or release evidence was produced. Existing browser/performance and
baseline objections remain separate. P04 integration and CI wiring stay with
the parent. Terminal test completion does not accept P09.

## Parent integration follow-up

Integrated replay contribution in `f48d7974`. Parent fixed dispatch receipt
lookup across the authorized compression family, retaining the original receipt
owner and acceptance. New dispatches use the compression root; the transaction
rechecks family receipts under `BEGIN IMMEDIATE`. Earlier leaf-owned receipts
remain discoverable. Forks and child transcripts do not join the parent scope;
payload conflicts still fail and profiles retain separate databases.

The compression defect's strict xfail marker was removed. An unrelated replay
payload audit was updated to include P04's additive `isolation: null` field,
matching the real tool's recorded payload rather than weakening hash checks.
Integrated runtime/delegation/worktree/receipt checks: **133 passed, 1 xfailed**,
exit 0, 18.16 seconds. The remaining strict xfail is the unsupported-stream defect;
a separate isolated implementation task owns that fix. This is not P09 acceptance.
