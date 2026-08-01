# Async runtime inventory

Last audited: 2026-08-01. Scope: Python under `src/`.

The repeatable audit command is:

```bash
rg -n 'asyncio\.run\(|new_event_loop\(|ThreadPoolExecutor\(max_workers=1\)|requests\.(get|post|request)\(|httpx\.(Client|AsyncClient)\(|time\.sleep\(' src --glob '*.py'
```

The raw scan found 28 `asyncio.run`, 6 `new_event_loop`, 5 one-worker
executors, 24 direct `requests.get/post`, 42 explicit `httpx` clients, and 65
blocking `time.sleep` calls. These totals intentionally include CLI entry points, examples,
retry backoff, and dedicated subprocess environments; a raw count is not a
migration target.

## Classification and disposition

| Process / owner | Call-site family | Classification | Disposition |
| --- | --- | --- | --- |
| Agent tool registry | async handlers including web extraction, vision, Google, RL, MoA and session summaries | hot request path | `core.async_runtime` is now the only sync bridge; no per-call or per-worker loops |
| MCP manager | former `mcp-event-loop` | long-lived network/process path | attached to the process runtime; MCP shutdown closes server tasks but never the shared loop |
| Home Assistant | sync handler bridge | hot network path | moved to the process runtime; handler API remains synchronous |
| Gateway `run.py` | compression, agent runs, MCP reload, TTS, transcription, dream and persistence helpers | live event-loop blocking risk | all blocking work routed through the runtime's bounded worker pool |
| Web server | update checks, persistence, OAuth helpers, agent construction/turns and diagnostics | live event-loop blocking risk | default and dedicated ad-hoc executor calls routed through the bounded runtime worker pool |
| Web/vision/image/MoA tool clients | async provider calls | hot network path | share one loop, allowing existing provider client caches and connection pools to remain reusable |
| Skills Hub/connectors | primarily synchronous `requests` implementations | incremental migration | safely offloaded at the registry/gateway boundary; retained until response/error compatibility fixtures exist |
| `core/cli`, `spark_cli/main`, `gateway/run` module entry points | top-level `asyncio.run` | process ownership | retained: these own a process loop rather than creating one per request |
| modal/computer-use environment adapters | dedicated loop bound to a remote sandbox object | isolated subsystem ownership | retained: lifetime and thread affinity differ from Spark's process transports |
| trajectory compressor and RL CLI | batch/command entry points | offline process ownership | retained; not on interactive request hot paths |
| retry and poll sleeps | terminal/process polling, provider retry backoff | intentional blocking worker behavior | retained only where already outside an event loop or isolated in the bounded pool |
| UI/display sleeps | animation pacing | user-visible timing | retained; never execute on the gateway/web event loop |

## Isolation contract

Reusable HTTP transports are keyed by family, profile, base URL, a one-way
credential fingerprint, proxy, and TLS policy. A client is never selected by
host alone. Individual tools may close their own `TransportKey`, but only the
process shutdown hook may close the runtime. Telemetry exposes aggregate
counts only and never includes credentials, headers, or complete URLs.

## Follow-up rule

New request-path code must use `get_async_runtime().run_blocking(...)` for
unavoidable synchronous work, `_run_async` at the legacy tool boundary, or a
pooled client acquired with a complete `TransportKey`. New per-call event loops
and one-worker coroutine bridges fail the runtime contract tests.
