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
- Replacement of an active registration cancels its execution and previous
  waiters under the existing lock. A normal next turn preserves the authorization
  of earlier children after their parent's callback cleanup.
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
revoke authorized background children. A session index of weak owner sets allows
explicit Stop to revoke every generation still held by copied child contexts,
without retaining finished contexts. Only replacing a still-active registration
revokes the overlapping root's owner. Safe child guards continue after normal
parent return and subsequent ordinary turns; a dangerous request without its original notification
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

## Sequential-parent follow-up from `873573b0`

Parent review of unintegrated `873573b0` found another lifetime boundary: its
single weak owner index revokes an earlier background child when an ordinary
next parent turn registers, even though the preceding root completed normally.
The previous normal-return test did not cross a complete subsequent parent turn.
Its `replace` comparison also conflated replacement of an active root with a
normal new turn after the root had returned. Earlier results above remain
historical evidence and do not establish this additional behavior.

A new real gateway regression is prepared: two ordinary explicit parent turns
each dispatch an async child, finish normally, and leave both generations gated
before safe `pwd` and dangerous-command guard calls. Releasing the children must
allow safe guards and preserve once-only delivery on later explicit input.
Explicit Stop must instead revoke both generations. Separate callback-ownership
checks must prevent an earlier child from borrowing a later turn's notification
callback. No shell command is executed by these guard probes.

All retained-context/proof/memory windows were held until root explicitly cleared
the correctness window. Before production changes, the first attempt failed in
**11.69s** on an overstrict test assumption: the runner created a fresh AIAgent for
the second root while preserving its durable session. The corrected fixture
tracks both actual agents' live children. The same regression then failed on the
intended safe-guard assertion: **1 failed in 11.35s** against unchanged `873573b0`.
The earlier child's `pwd` guard was cancelled while the later child's guard was
approved, after both parent turns had returned. Both attempts are retained in JSON.

The follow-up changes only `approval.py`, its two focused test modules and these
evidence files. The weak session index now refers to a WeakSet of all live owner
generations; each owner holds that set alive, but the set holds owners weakly.
Once no context retains any owner, the set and its weak session entry disappear.
Registration supersedes only the currently registered callback owner. An older
normally completed root's child retains authorization, but callback identity must
match that child's bound owner before either blocking enqueue or legacy pending
submission. Whole-session Stop/clear revokes every live generation.

The earlier normal-return test's `replace` case is now `next_turn`, with safe
guards expected to continue and dangerous guards denied without borrowing its
active callback. Separate existing overlap cases still require cancellation of
actively superseded roots. The guard-collection Stop race now explicitly uses
whole-session cancellation, keeping that race distinct from normal cleanup.

Focused validation passed: **31 passed in 105.11s** using:

```text
source /Users/joe/Developer/github/spark/.venv/bin/activate
validation_home=$(mktemp -d /tmp/spark-approval-sequential-focused.XXXXXX)
SPARK_HOME="$validation_home" PYTHONPATH=$PWD/src python -m pytest tests/tools/test_approval_ownership.py tests/gateway/test_approval_ownership.py -q -n 0 -m 'not integration' --tb=short --durations=8
```

The ordinary sequential-turn and Stop cases passed in **20.82s** and **20.74s**.
Both hold two owner generations until two ordinary parent turns have returned,
then verify their guard decisions and once-only result delivery. The normal
next-turn case with an actively registered later responder passed in **10.62s**;
the earlier child's dangerous guard cannot enqueue through that responder.
Existing overlap, old cleanup, parallel child, RPC, Stop and CLI/web compatibility
cases still pass. GC coverage holds three generations in each of 16 sessions,
drops all 48 execution contexts, and checks that owner references, callback owners,
queues and session-index entries are gone after collection. Zero session entries
remain for those finished contexts.
A first focused lint check reported one import-order violation (`I001`) in the
new gateway test import; Ruff corrected that import and the rerun passed.

All focused commands exited and that boundary was reported to root before any
new broad neighbor batch. Further heavy validation is held for root's next
observation window. Earlier 312/376/92 results above apply to the preceding
implementation; this follow-up does not claim they were rerun against the owner-set
change. Root retains canonical/full-suite and final acceptance ownership.

Not established here: live messaging network/authentication, live remote sandbox,
browser recovery, installed packages, full root suite, canonical CI or P03/P09
acceptance. Stop remains cooperative for a hook or callback already in progress.
