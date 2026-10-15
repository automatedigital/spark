# P09 provider HTTP replay v1

`transport-v1.json` is authored synthetic protocol data, based on Spark commit
`bed0d01007b47e78e6a90c8f8f5db0a754bf2ac0`. It is not an actual provider recording.
No credentials, user messages, local paths or live inference outputs are captured.
The API key used by the harness is the literal `synthetic-no-credentials`.

The schema discriminator is `spark.test.provider-transport-replay.v1`:

- `provenance`: origin, date, source commit, protocol and evidence limitations.
- `model` / `origin`: synthetic model and reserved `.invalid` HTTP origin.
- `root_prompt` / `dispatch`: the first provider response calls the real
  `delegate_task` with this JSON payload; its actual receipt becomes the next
  provider request's tool result.
- `children`: goal-to-final-answer mapping. Each child's first HTTP response
  requests the real `read_file`; its second response waits at a test-owned gate.
- `root_result`: final text returned after the root's gate opens. The optional
  decision scenario first requests the real `clarify` tool and web callback.
- `provider_error`: HTTP status/body for a synthetic external provider rejection.
- `file_content`: materialized only inside pytest's temporary filesystem.

The harness serializes these messages as Chat Completions JSON or SSE and
replaces only `httpx.HTTPTransport.handle_request`. The real SDK parses those
responses. Cancellation additionally holds one HTTP transport's `close` boundary
to prove receipt acceptance precedes terminal acknowledgement. SQLite triggers
inject a real transaction abort. No AIAgent, provider-loop, child constructor,
delegate handler, lifecycle callback, DB write or projection function is mocked.
Provider capability flags and durable initial root identity/projection are test
setup; child lifecycle data always comes from real execution.

`process_loss.py` starts the same real agent and workers in a separate Python
process, waits for actual dispatch receipt and both child HTTP requests, then
uses `os._exit(73)`. The next process must reconcile durable work as uncertain,
without reexecuting it. This is process-loss evidence, not gateway restart proof.

The tests run serially because the profile environment and web journal are
process-global. Each test gets temporary SPARK_HOME/CODEX_HOME from conftest.
Two-profile coverage uses distinct real databases, same session/request IDs and
real agents; it does not claim concurrent multi-backend browser coverage.

Strict xfail tests identify independently reproduced defects. Their failures are
release objections; XPASS is an error so a parent fix requires removing the mark.
No P09 acceptance, live provider latency, messaging gateway, browser, frontend
TypeScript reducer, package or installed-platform claim follows from this suite.
