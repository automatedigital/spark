# P03 gateway transport acceptance — 2026-10-15

Base: `fb52fe7c8d47730ed0d1932b32b558e8348c544f`.

**P03 remains open.** Deterministic actual gateway-boundary coverage establishes
stored-result delivery at the next explicit inbound parent turn, deduplication,
chat/session ownership, disconnected retention, runner reconstruction and crash
recovery. Actual gateway `/stop` exposes two source defects. This change contains
only new tests, authored fixtures and this evidence; it changes no production
code, existing tests, plan, manifests, bundles or configuration.

## Exercised boundary

`LocalPlatform.inbound_text()` → production `BasePlatformAdapter.handle_message()`
→ background adapter processing → `GatewayRunner._handle_message()` → real
authorization, session store, agent cache and `_run_agent()` → real `AIAgent` →
OpenAI SDK → synthetic `httpx.HTTPTransport.handle_request()` responses → real
`delegate_task`, child workers, `read_file`, lifecycle/receipts and SQLite → actual
adapter response/retry pipeline → captured local `send()`.

The only substitutions are external platform I/O, provider HTTP I/O, the optional
security-binary installer, and profile-path rebinding for legacy cached module
constants. Internet socket connects are blocked. Every send requires a
`fixture-*` recipient. Config and credentials are synthetic under temporary
`SPARK_HOME`/`CODEX_HOME`; the provider is `gateway-replay.invalid`. No user state,
external messages, real inference, server, package, publication or deployment is
involved. The fake adapter inherits the production inbound/response pipeline;
`AIAgent(platform="telegram")` alone is not the acceptance evidence.

## Flows and exact assertions

| Flow | Evidence |
| --- | --- |
| Busy parent; alpha/beta finish in either order; another chat runs | Two parameterized cases. Both children run real file tools. Parent remains the running gateway owner; other chat has a distinct session. No child completion starts a parent turn or platform send. Cached system prompt, tool definitions and captured historical prefix remain unchanged. |
| Next explicit parent inbound; subsequent inbound | Exactly two durable result messages with distinct delivery-message IDs. Later explicit inbound adds no delivery. Four explicit inbound turns produce four platform replies and five parent SDK requests (one extra request for the delegate tool round trip). Exactly four child SDK requests and two real file reads. |
| Idle and disconnected completion; reconstructed gateway | Root finishes before children. Disconnect local adapter, release children, observe no sends/inference/delivery. Fresh runner/cache/session store/DB connections load the same session. Explicit reconnect delivers twice once; a second reconstructed runner and explicit turn do not redeliver or rerun children. Three explicit parent turns, four parent SDK requests, four child SDK requests. |
| Stop one child | Production `delegate_task(mode="cancel")` targets the parent actually owned by the gateway; there is no child-stop gateway slash command. Duplicate cancel request returns the original acknowledgement. Alpha becomes interrupted, beta remains working then completes, and root remains running. Late alpha HTTP success cannot regress terminal state. Explicit follow-up receives the two stored outcomes once. Two inbound turns, two replies, three parent SDK requests, four child SDK requests. |
| Authorization and ownership | Unauthorized inbound never calls provider or sends. Another authorized chat cannot inspect/cancel the first chat's child via the production control tool and cannot consume its pending results. Accepted turns total three parent SDK requests (including delegate round trip), four child requests. |
| Actual process loss | A subprocess constructs the real runner/adapter, accepts one inbound, dispatches two children through provider tool calls and runs their file tools. It exits with `os._exit(73)` while root/children await HTTP responses: one inbound, zero sends, four child SDK requests. Reconstruct runner on the persisted session. No automatic inference/send occurs. Explicit recovery reconciles both children as uncertain and delivers two outcomes once. Retried dispatch returns original acceptance; retry of uncertain effects is rejected. Two recovery inbounds produce two SDK requests and two replies, zero child requests. |

Child control uses the real domain tool rather than a fabricated gateway command.
Gateway session creation, authorization, root command dispatch and reply delivery
remain production code. Child state is never reconstructed manually or written
by fixture setup. The process-loss script uses the same authored HTTP transport;
it does not depend on the web-server module or callback imports.

## Blocking source defects for the lead

1. **Busy parent `/stop` starts an implicit follow-up.**
   `src/gateway/run.py:2730` and `:4401` pass `"Stop requested"` to
   `AIAgent.interrupt()`. After interruption, `_run_agent()` at `:9359` treats
   `result["interrupt_message"]` as pending user input when no pending event
   exists. This reason lacks a slash-command prefix, so the command filter does
   not discard it. Production `run_conversation()` runs again with user text
   `"Stop requested"`, without an explicit inbound parent prompt. The new test
   observes an extra persisted user message and provider request. Depending on
   child completion timing, that implicit turn could also consume child results.
   Fix command-driven cancellation so a stop reason cannot become queued input;
   preserve genuine inbound follow-up queue behavior. Cover both stop paths.

2. **Idle parent `/stop` misses active background children.**
   `_handle_stop_command()` (`src/gateway/run.py:4378`) looks up only
   `_running_agents`. After root completion, the parent is still in
   `_agent_cache` with live child workers but absent from `_running_agents`.
   Actual inbound `/stop` responds `"No active task to stop."` while the two
   owned children continue running. Resolve the same session's cached parent/live
   owned children when applying Stop, with existing ownership restrictions and
   terminal acknowledgement preserved. Do not treat an unrelated cached chat as
   the stop target.

Both regressions are **strict xfails**, not accepted product behavior. Remove
those marks after source fixes; an unexpected pass fails the suite. Scope forbids
this test agent from editing production source. The busy-stop assertion is
reached only after both children converge to interrupted and late HTTP replies
cannot regress them. The idle-stop assertion reports the actual wrong command
response before waiting for expected cancellation.

## Meaning of idle/disconnected/stopped

The implementation, `CONTEXT.md`, capabilities and ADR-0013 support delivery at
the **next explicit parent turn**. An idle parent does not wake automatically;
child results remain durable. Disconnection creates no send or new root turn;
a later authorized explicit inbound can consume results. A stopped run must
converge without inventing a follow-up; stored terminal outcomes are intended to
wait for an explicit resume. The busy-stop bug violates that contract.

The approved P03 checkbox says “safe subsequent parent boundary,” which can
express the explicit-turn contract, but the PLAN execution ledger separately
calls out the lack of autonomous wake-up as unresolved. This report does not
silently reinterpret that approval or check off the plan. The lead must reconcile
that wording explicitly, and both `/stop` defects block closure regardless.

## Verification

All Python commands activated `/Users/joe/Developer/github/spark/.venv` and used
`PYTHONPATH=$PWD/src` from this T3 worktree. Tests ran serially with external
integration tests excluded. Exact commands, results and durations are in the
companion JSON.

- New gateway suite: **6 passed, 2 strict xfailed** in 105.50 seconds. Both
  xfails reproduce the stop defects above; no unexpected test failures.
- Neighboring gateway, cache-golden, lazy-manifest and minimal-startup suites:
  **65 passed** in 44.84 seconds.
- Existing async/runtime HTTP replay suites: **38 passed** in 14.41 seconds.
  `--runxfail` deliberately exercises the stale stream-unsupported xfail at this
  committed base as a normal assertion; no existing test file was changed.
- Manifest check: **70 tools, 28 isolated modules, 4 optional guards**.
- CI production Ruff rule-family gate: **passed**.
- New-file Ruff: **passed**.
- Broad `ruff check src/`: **299 pre-existing diagnostics** in untouched source.
  This is separate from the passing CI rule-family gate and new-file lint.

Timing here is test wall time, not a latency/performance baseline. The gateway
currently waits up to five seconds for an absent stream consumer with streaming
disabled; these tests retain that production behavior instead of mocking it.

Not established by this report: live Telegram SDK authentication, external
messaging/reconnect delivery, daemon startup/scheduler integration, browser/chat
switch UI, actual interactive CLI command entry, installed macOS/Windows behavior,
autonomous idle-parent wake-up, complete P03/P09 acceptance or the full root suite.
Existing runtime replay checks exercise CLI/web runtime modes and real web
callbacks; they are not browser proof.

## Parent integration follow-up

Integrated original contribution in `69878d48`. Parent fix `f7f03b4` removes
replacement text from command-driven interruption and resolves idle background
children only through their owning session's cached parent. Both strict xfail
markers are removed. Actual gateway replay and command/race/shutdown neighbors:
**48 passed**, exit 0, 132.67s. Added direct fallback-command and foreign-chat
idle Stop assertions: **2 passed**, exit 0, 11.79s. CI Ruff and mypy (131 source
files) pass. These are ordinary regressions rather than expected failures now.

Delivery remains the next explicit authorized parent input, with no autonomous
inference/send on completion. Parent has separately verified the integrated
canonical browser bundle. P03 remains open for a fresh ownership audit of Stop
during pre-agent preparation and late cleanup of a replaced session owner; source
inspection alone is not yet a reproduced failure. Performance/platform/release
gates remain separate.
