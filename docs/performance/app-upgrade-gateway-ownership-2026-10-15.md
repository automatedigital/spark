# Gateway Stop ownership evidence — 2026-10-15

Scope: P03/P09 gateway correctness, with acceptance still open. Baseline commit:
`a9008c5b57dc10c4804abef241faccd678633494`, including the lead's original Stop
repair `f7f03b4d`. The earlier gateway report records its historical **6 pass /
2 strict xfail** result; those markers were already removed before this work.
This note supplements that report rather than rewriting its original evidence.

## Deterministic failures before repair

The three initial tests ran through `BasePlatformAdapter.handle_message`, the
real `GatewayRunner`, real `AIAgent`, real SDK, and temporary SQLite/session
storage. Authored gateway `agent:start` and registered plugin `pre_llm_call`
handlers pause execution at extension boundaries. Reconnection installs a fresh
local adapter on the same runner while the old callback is still returning.
No gateway, runtime, persistence or delegation method is mocked. HTTP responses
and recipient sends use the existing synthetic transport, with external sockets
blocked and temporary `SPARK_HOME`; no real messages, profiles or inference.

Before editing production source:

```text
source /Users/joe/Developer/github/spark/.venv/bin/activate
PYTHONPATH=$PWD/src python -m pytest tests/gateway/test_stop_ownership.py -q -n 0 -m 'not integration' --tb=short --durations=5
3 failed in 26.22s
```

All failures were the intended assertions, without gate/poll timeouts:

1. Stop during preparation followed by genuine queued input issued **two**
   provider requests instead of one. The stopped prompt reached inference and
   persistence after Stop had acknowledged it.
2. After Stop and adapter replacement, finishing the old preparation removed
   the replacement's sentinel: `_running_agents.get(key)` was `None` while the
   replacement was still inside its preparation hook. Old worker tracking and
   unconditional `_run_agent`/outer-handler cleanup could overwrite or remove
   a newer request's agent, sentinel and timestamp.
3. Stop acknowledged an old worker blocked in `pre_llm_call`, then replacement
   preparation reused that **same AIAgent** concurrently. Releasing both gates
   produced two root executions and two SDK requests. Runtime startup's
   `clear_interrupt()` erased the old Stop before inference.

## Repair and ownership choices

- A per-session inbound claim covers preparation, runtime and queued turns.
  A task-local reference carries it through existing handler APIs. Both early
  Stop interception and the normal fallback Stop handler invalidate the claim.
  Stop can find a worker published to its claim before polling has replaced
  the shared pending sentinel.
- After preparation and runtime/hook awaits, a superseded handler exits without
  starting inference, publishing its result, consuming newer queued input or
  appending its gateway transcript fallback. Runtime startup uses the existing
  `_spark_async_cancel_event` latch, so an earlier Stop survives interrupt reset.
  Each runtime turn receives a fresh latch; genuine queued text remains explicit
  input and is processed once.
- Cache selection reserves an agent under the existing cache lock. A live
  worker is ineligible for reuse; an overlapping replacement gets another agent.
  The worker releases this reservation in its own `finally`, after actual sync
  exit, rather than when async timeout/cleanup merely releases the session.
  Normal completed workers remain cacheable with their frozen prompt/tools.
- Tracking and cleanup check claim ownership and agent identity. An old handler
  cannot remove a replacement's sentinel, agent or timestamp. Old completion
  cannot dequeue a replacement's messages or evict its cache as fallback state.
  Stop acknowledgement still precedes terminal worker acknowledgement.

No thread killing, restart framework, schema/config changes or provider policy
changes were introduced. Retired agents are not closed by stale cleanup:
`AIAgent.close()` also kills resources by session ID and could affect the active
replacement that shares that durable conversation.

## Verification

Every Python command used the root virtualenv and worktree `PYTHONPATH` above.
All test runs were serial with external integration tests excluded. Durations
are test wall time, not controlled performance measurements.

Initial repaired cases plus existing session-race guards:

```text
PYTHONPATH=$PWD/src python -m pytest tests/gateway/test_stop_ownership.py tests/gateway/test_session_race_guard.py -q -n 0 -m 'not integration' --tb=short --durations=5
13 passed in 26.54s
```

Four ownership cases (including the direct production fallback Stop handler)
plus gateway delegation, restart, cache and startup neighbors:

```text
PYTHONPATH=$PWD/src python -m pytest tests/gateway/test_stop_ownership.py tests/gateway/test_async_delegation_delivery.py tests/gateway/test_agent_cache.py tests/gateway/test_session_race_guard.py tests/gateway/test_restart_drain.py tests/gateway/test_session_reset_notify.py tests/gateway/test_transcript_offset.py tests/gateway/test_gateway_inactivity_timeout.py tests/gateway/test_flush_memory_stale_guard.py tests/run_agent/test_caching_golden.py tests/tools/test_lazy_manifest.py tests/test_minimal_startup.py -q -n 0 -m 'not integration' --tb=short --durations=8
91 passed in 191.92s
```

An added ordinary busy-followup test first failed its final assertion because it
counted legitimate persisted child-result deliveries as explicit user prompts.
Provider counts, once-only followup and cache identity already passed. The test
now filters the same `Delivery child-result:` marker used by existing fixtures:

```text
PYTHONPATH=$PWD/src python -m pytest tests/gateway/test_stop_ownership.py::test_genuine_busy_followup_runs_once_and_reuses_finished_parent_cache -q -n 0 -m 'not integration' --tb=short
1 passed in 10.56s
```

Final source, including late hook/error-result ownership fences, and all five
ownership cases:

```text
PYTHONPATH=$PWD/src python -m pytest tests/gateway/test_stop_ownership.py -q -n 0 -m 'not integration' --tb=short --durations=5
5 passed in 36.70s
```

Other checks:

```text
ruff check tests/gateway/test_stop_ownership.py
All checks passed!
ruff check src/ --select UP015,F,B,I,W,UP028,UP031,UP035,UP037,UP042 --ignore B027
All checks passed!
PYTHONPATH=$PWD/src python scripts/generate_tool_manifest.py --check
Tool manifest valid: 70 tools across 28 isolated modules; 4 optional guards
git diff --check
exit 0
```

Worktree `mypy src/agent/ src/spark_cli/` followed imports into excluded gateway,
core and tools modules: **2710 errors in 119 files (131 target files)**. The lead
confirmed this worktree import-traversal mismatch against earlier isolated
baseline results and reran the exact root CI invocation without `PYTHONPATH`:
**Success: no issues found in 131 source files**. Root must recheck after
integration. No type configuration or excluded source was changed here.

Not established: live messaging authentication/network reconnect, browser UI,
installed packages, autonomous idle-parent wake, full root suite, P03/P09 closure.
The reconnection race uses the real base adapter and runner with local platform
I/O; it is not a claim about a live Telegram SDK connection. Plugin and provider
gates are bounded; Stop does not forcibly terminate a hung external plugin.
