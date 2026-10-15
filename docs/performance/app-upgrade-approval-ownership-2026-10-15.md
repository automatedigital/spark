# Gateway approval ownership — 2026-10-15

Scope: approved P03/P09 P1 follow-up to the gateway claim repair. Implementation
base: `3097f32b` (includes `efb585d9`). Root owns canonical checks, CI and final
acceptance. No PLAN checklist, browser, package or release claim is made here.

## Independent proof before this repair

`/tmp/spark-gateway-ownership-review/test_approval_overlap.py` ran against
unchanged production source: **1 passed in 11.21s**, asserting the bug. Its
`repro-output.txt` recorded:

```json
{"before_old_exit":{"callback_present":true,"blocking_approval":true,"decision":{}},"after_old_exit":{"callback_is_replacement":false,"callback_present":false,"blocking_approval":false,"decision":{"approved":false,"description":"delete in root path","message":"BLOCKED: Command denied by user. Do NOT retry this command.","pattern_key":"delete in root path"},"replacement_still_inside_hook":true}}
```

The real base adapter, runner, AIAgent, plugin `pre_llm_call` boundary and real
`check_all_command_guards` were exercised. Old execution paused in its hook;
Stop/reconnection started a replacement and queued its dangerous-command
approval. Releasing the old hook ran unconditional session-key cleanup, removing
the replacement callback and waking its waiter without a user choice. HTTP and
platform sends were synthetic, external sockets blocked, SPARK_HOME temporary,
and the dangerous command was never executed.

## Ownership repair

- Registration returns a unique opaque owner token. Gateway cleanup passes its
  token, removing only that callback and its waiters. The existing one-argument
  unregister remains an explicit whole-session cancellation API.
- Replacement registration cancels previous waiters under the existing lock.
  Callback capture and queue insertion now share that same lock. Choice/result
  publication also occurs under it, so cancellation and approval have a defined
  order. Callback I/O stays outside the lock. A callback already sending during
  cancellation can finish its send; its waiter cannot become a successor's
  waiter, and stale send failure/cleanup removes only its own entry.
- Gateway session binding explicitly carries its registration in context-local
  state. Late calls retain their retired owner and fail closed with a cancellation
  explanation; they cannot fall back to a replacement callback or a fresh pending
  approval. Existing one-argument CLI/web session bindings and no-callback batch
  fallback remain supported. Owned legacy pending requests are removed with their
  registration.
- Explicit gateway Stop cancels the current registration before acknowledging.
  A registration checks the claim's cancellation latch under the approval lock,
  covering Stop between ownership inspection and registration. The worker binds
  the returned token explicitly, even if it was already retired.
- Audit found raw batch-child pool submissions and both sandbox RPC thread starts
  without context propagation. With explicit scope approval, these now run in a
  copied caller context. Shared async-runtime workers already copy context.
  No tool restrictions, provider choices, approval UX or schemas are redesigned.

Normal parent completion only ends its notification registration. It does not
revoke authorized background children. A weak owner index allows explicit Stop
and superseding registration to revoke an owner still held by a copied child
context, without retaining finished contexts. Safe child guards continue after
normal parent return; a dangerous request without its original notification
callback fails closed without enqueueing or borrowing a new callback. Existing
one-argument CLI/web APIs retain their session-only behavior.

## Regression coverage

`tests/gateway/test_approval_ownership.py` preserves the independent overlap
ordering, requires the replacement callback/queue to survive old exit, then sends
actual authorized inbound `/approve` and checks once-only resolution. It also
covers Stop with no replacement through both gateway dispatch paths, and real
sync-batch/async delegated child approvals alongside Stop and replacement. Old
pending waiters cancel; late child calls cannot borrow the new registration.

`tests/tools/test_approval_ownership.py` covers superseding registrations, captured
callbacks still sending (success/failure), three competing owners, Stop before
registration, whole-session cancellation, legacy pending fallback/ownership and
both RPC thread paths. Local RPC runs harmless Python calling a read-file stub;
synthetic dispatch invokes the real guard without executing the dangerous
command. Remote process/filesystem I/O is synthetic while polling stays real.

## Validation

No validation started during the performance hold. Root explicitly cleared the
window at **18:57 UTC**. Every Python run activated
`/Users/joe/Developer/github/spark/.venv/bin/activate`, used this worktree's `src`
via `PYTHONPATH` (except the explicit baseline-source check), and set a fresh
temporary `SPARK_HOME` before collection. All pytest runs used `-n 0` and
`-m 'not integration'`. These are test wall times with other correctness work
permitted, not controlled performance samples. No Node, browser, build, install,
push, PR or release command ran here.

Exact invocation arguments and results, including unsuccessful attempts, are in
the companion JSON. Important retained attempts:

- Initial ownership regressions: **18 passed in 44.13s**. This interim source was
  superseded after parent review identified a background-child lifetime issue.
- A new real gateway regression proved that issue before correcting it:
  `tests/gateway/test_approval_ownership.py::test_async_child_guard_after_normal_parent_completion[normal]`
  **1 failed in 7.25s**. Safe `pwd` guard calls in two actual async children were
  cancelled after ordinary parent return. The weak lifetime distinction above
  repairs this; explicit Stop/replacement still revoke those children.
- Expanded ownership/lifetime suite: **24 passed in 64.82s**. It includes normal
  completion versus Stop versus replacement, and weak-index release after the
  last context disappears. A subsequent compatibility case preserves legacy
  CLI/web binding; final combined coverage is recorded below.
- An initial mixed neighbor batch: **9 failed, 459 passed in 307.53s**. Each failure
  reported `Async execution is disabled`: collecting the CLI approval tests
  imports process-global `CLI_CONFIG` before the gateway fixture creates its
  temporary profile. Delegation's real loader prefers this populated default
  config over the fixture's YAML. The same ordering against archived untouched
  **3097f32b source** reproduced **1 failed, 5 passed in 11.44s**. This is independent
  of ownership changes. The synthetic gateway fixture now binds its runtime
  config as well as writing its YAML; no production config loader was changed.
- CLI collection plus gateway delivery and all three lifetime cases after that
  fixture correction: **9 passed in 44.75s**. The normal case also checks that both
  actual children reach durable `completed` status.

Neighbor checks after the lifetime repair:

- Approval, guards, YOLO, delegation, sandbox, CLI and platform approval neighbors:
  **376 passed in 132.78s**.
- Gateway Stop/async delivery/cache/restart/session races/inactivity, cache goldens,
  lazy manifest and minimal startup: **92 passed in 213.01s**.
- Focused web approval/requested-input check: **6 passed, 105 deselected in 3.00s**.

Final combined approval/web coverage on the completed source: **312 passed in
113.35s**. This includes all **25** ownership/lifetime/compatibility cases,
existing approval/guard/YOLO/gateway decision tests and the full web events suite.
The command's `-k 'not requested_input or requested_input'` expression is a
tautology; it selected every test in the listed files, not a narrower subset.

Other checks:

```text
ruff check tests/tools/test_approval_ownership.py tests/gateway/test_approval_ownership.py tests/gateway/test_async_delegation_delivery.py
All checks passed!
ruff check src/ --select UP015,F,B,I,W,UP028,UP031,UP035,UP037,UP042 --ignore B027
All checks passed!
PYTHONPATH=$PWD/src python scripts/generate_tool_manifest.py --check
Tool manifest valid: 70 tools across 28 isolated modules; 4 optional guards
git diff --check
exit 0
```

Full `ruff check src/ --output-format concise` remains **exit 1, 299 violations**.
All 15 in touched source files are baseline debt: gateway has 14 (`E402`/`E702`),
delegate has one (`E402`), and approval/sandbox have none. `git show
3097f32b:<path> | ruff check --stdin-filename <path> - --output-format concise`
confirmed the same 14/1 diagnostics at their original line numbers. No baseline
lint debt was repaired or hidden here. Root retains canonical mypy/CI/full-suite
and final acceptance ownership.

Not established here: live messaging network/authentication, live remote sandbox,
browser recovery, installed packages, full root suite, canonical CI or P03/P09
acceptance. Stop remains cooperative for a hook or callback already in progress.
