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
permitted, not controlled performance samples. No Node command ran for the initial
ownership validation; the later transport/Web follow-up below records a focused
Node check. No browser, build, install, push, PR or release command ran here.

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
new broad neighbor batch. Further heavy validation was held for root's next
observation window. Earlier 312/376/92 results above apply to the preceding
implementation; this follow-up does not claim they were rerun against the owner-set
change. Root retains canonical/full-suite and final acceptance ownership.

## Transport decision identity follow-up from `d044b79a`

Independent source review found a pre-existing transport hole after finding no
remaining weak-lifetime blocker: gateway notifications sent only the session key,
and interactive responses resolved the oldest current waiter. A sent A prompt
could survive Stop, B could queue a different command, and A's button could
authorize B. Slack, Telegram, Discord and Feishu had the same session-only path.
Their UI also published approval labels before confirming that a waiter resolved.

The bounded regression ran before production edits, after root cleared the browser
measurement window: **1 failed in 6.12s** against unchanged `d044b79a`, on the
intended assertion `A's stale button resolved B's different command`. Raw proof:

```json
{"old_prompt_label":"✅ Approved once by synthetic owner","replacement_decision":{"approved":true,"description":"world/other-writable permissions","message":null,"user_approved":true},"replacement_still_waiting":false}
```

This uses the real authorized gateway runner, AIAgent, plugin hook and command
guard; the existing local Telegram-source inbound fixture bridges the gateway's
unchanged notification arguments to the real Slack sender/click handler. Only
Slack SDK sends/edits and provider HTTP responses are synthetic. Internet sockets
are forbidden, SPARK_HOME is temporary, and neither dangerous command executes.
This proves the application button boundary, not live Slack inbound/auth/network.
The failure was reported and its command had exited before broader validation.

The repair adds a UUID action ID when creating each approval entry and forwards
that same ID from actual gateway notification to all four button transports.
Slack encodes session plus entry ID in its button value; Telegram callback data
uses the opaque entry identity and stores its session binding, avoiding counter
reuse after adapter reconstruction. Discord's view and Feishu's card state retain
the original entry ID. Every response resolves only that ID and publishes an
approved/denied label only when the resolver returns a nonzero count. Missing,
old-format or cancelled IDs fail closed; expired Feishu cards use a neutral
expiry state. Late notifications retain their cancelled entry identity.

Execution owners, weak lifetime sets, Stop and normal sequential-parent behavior
are unchanged by this transport fix. Entry identity is a decision identity, not
an execution owner. Omitting an ID in the core resolver intentionally preserves
FIFO and resolve-all behavior for `/approve`, `/approve all`, `/deny` and legacy
backend APIs. An explicit empty/unknown ID resolves zero and cannot fall back.
Old direct platform sender calls remain callable without a new required argument,
but resulting ID-less interactive responses cannot authorize anything.

The Web route already validates durable action/session identity and targets that
waiter, so no production route change was needed. Its legacy API still accepts
current-queue requests. The audit found a historical timeline button could omit
its ID; with explicit scope approval, both built-in Web button paths now use the
strict submission helper, which refuses missing/blank identities before any API
request. Valid action IDs remain intact. Added backend regression confirms an old
durable action cannot resolve a newer waiter in the same session.

Validation (exact commands and environment details are in JSON):

- Real gateway/Slack stale-click and delayed-send regressions, 12 four-platform
  scenarios (cancelled/missing ID/reverse-order parallel decisions), and existing
  Slack/Telegram/Feishu button neighbors: **58 passed in 11.84s**.
- Web submission helper: **5 passed**, Vitest **362ms**, with live-verified Node
  **v22.22.1** at `/Users/joe/.nvm/versions/node/v22.22.1/bin/node`. An isolated
  temporary Vitest config reused existing root node_modules and a temporary cache;
  no dependency installation, lockfile, source config or bundle change.
- Approval/guards/YOLO, all ownership/lifetime/GC/sequential-parent cases, gateway
  text decisions and full Web events: **322 passed in 149.39s**. The roughly
  three-minute estimate was reported before this neighbor batch began.
- Cache goldens, lazy manifest and minimal startup: **13 passed in 9.84s**.
- Focused test lint and selected source CI lint: **passed**. Ruff corrected one
  import-order issue in a new test before the final check.
- Manifest: **70 tools / 28 isolated modules / 4 optional guards**, valid.
- `git diff --check`: **exit 0**.

Discord tests execute actual adapter/view source against a local optional-SDK UI
shim; Feishu uses local SDK send/profile/card-update boundaries. Telegram/Slack
also use local SDK I/O. These do not establish installed SDK or live messaging
behavior. Root owns canonical frontend lint/type/build/browser gates and final
integration. All validation commands exited; no further broad batch is planned.

Not established here: live messaging network/authentication, live remote sandbox,
browser recovery, installed packages, full root suite, canonical CI or P03/P09
acceptance. Stop remains cooperative for a hook or callback already in progress.

## Caller authorization follow-up from `9741a7d1`

Independent v3 review found no introduced identity/lifetime defect, but identified
two pre-existing P1 caller-policy holes. Feishu approval cards bypassed both the
gateway's user authorization and the adapter's group policy. Slack, Telegram and
Discord checked only populated platform allowlists, so an empty platform list
allowed a button caller that the global gateway allowlist rejected.

Before production edits, actual sender/click handlers and the real approval queue
reproduced all five intended failures: **5 failed in 0.23s**. Each adapter resolved
a stranger's click despite the existing gateway policy rejecting that caller;
Feishu also resolved a caller excluded by its group helper. The first attempt
reported **5 failed in 0.28s**: four intended failures plus a Telegram local
ParseMode mock setup failure. Correcting only that mock produced the complete
intended proof. Both attempts and exact commands remain in JSON.

The repair installs the bound `GatewayRunner._is_user_authorized` callback on
adapters during initial connection and reconnect. No second allowlist/pairing
policy is introduced. Gateway notifications forward their actual SessionSource;
each transport retains a copy of that trusted prompt route. Before consuming
button/view state, the adapter checks the actual caller, platform, destination
and thread/topic, then supplies that caller in the trusted source to the existing
runner policy. Missing caller, source, route or installed policy fails closed.
Old direct sender signatures remain callable; their fallback routing is treated
as a group, conservatively, and still requires an installed authorizer.

Feishu additionally reuses `_allow_group_message` for non-DMs, including per-group
rules and admin overrides. Its concrete callback message ID binds a card to its
original message/thread; callbacks do not expose a separate thread identity.
Unauthorized clicks leave approval state and dedup tokens available and do not
fetch display names. Discord validates the actual interaction destination against
the channel/thread where its view was sent. Telegram checks forum and direct-message
topics, and Slack checks channel/thread. Rejected clicks do not prevent a later
authorized user resolving the original request.

The policy matrix compares real button outcomes with the real inbound policy for
platform/global membership and exclusions, wildcards, per-platform allow-all,
global allow-all, pairing and default deny. It explicitly preserves the existing
rule that global allow-all does not override populated restrictive allowlists,
while per-platform allow-all does. All four choices (once/session/always/deny),
unauthorized-then-authorized retry, missing/wrong caller/routing/source/policy,
Feishu group/DM policies and per-group blacklist overrides are covered. Startup
and reconnect tests assert that the runner installs the callback.

The existing real runner/AIAgent/guard plus Slack sender/click regressions still
pass for stale buttons and delayed sends. Their reusable Telegram-source inbound
fixture now explicitly translates only the source platform at its local Slack
bridge so the actual Slack caller check receives a Slack source. This remains
application-boundary proof, not live Slack inbound/network authentication.

Validation, always with the root .venv active, temporary SPARK_HOME before
collection, PYTHONPATH pointing to this worktree's src, serial execution and
`not integration` (exact commands in JSON):

- Initial policy/identity checks: **17 passed in 0.90s**.
- Expanded matrix and button neighbors: **156 passed in 1.39s**.
- Matrix plus real gateway regressions: **162 passed in 12.15s**.
- First bounded neighbor batch: **488 passed, 3 failed in 25.93s**. All failures
  were existing Feishu SDK-only reaction/contact fixtures. Their collection-time
  MagicMock makes an absent optional SDK appear installed.
- Loading unchanged `9741a7d1` Feishu source into a temporary test-only overlay
  reproduced those same assertions: **3 failed, 119 deselected in 0.28s**. No
  repository production file was overwritten for that proof.
- Final bounded batch explicitly deselected only those three demonstrated SDK
  failures: **488 passed, 3 deselected in 26.11s**. Includes inbound authorization,
  pairing, Feishu/Slack/Discord neighbors, startup/reconnect, text approvals and
  cache-golden/lazy-manifest/minimal-startup guards. Existing AsyncMock and
  deprecation warnings remain (17 warnings).
- Focused test lint, selected source CI lint and `git diff --check`: **passed**.
  Initial test lint fixed one import-order issue and reported three lambda
  assignment violations; local functions replaced those assignments before rerun.

All heavy commands exited and this was reported before committing. No further
heavy batch is planned. Execution-owner lifetimes, decision identities, legacy
text/backend APIs and Web/ChatPanel code are unchanged in this follow-up. No real
SDK sends, external provider calls, shell effects, browser, installation or build
was used. Root's separate cleanup/fixture changes and canonical acceptance remain
root-owned; this worktree did not overwrite them. SDK compatibility, live network
authentication and full root-suite success are not established here.

## Telegram private-topic follow-up from `6a88765b`

Independent v4 caller-policy review found one P2 regression, with no additional
policy bypass or owner-lifetime defect: private inbound messages store
`direct_messages_topic.topic_id` as both `source.thread_id` and
`source.direct_messages_topic_id`. The callback passed only its raw
`message_thread_id` to the route guard, so a matching direct-topic callback with
no raw message thread was rejected. The earlier fixture manually constructed a
source without `thread_id`, missing this actual inbound contract.

The replacement regression builds its source through the real
`TelegramAdapter._build_message_event` and forwards real source metadata into the
sender. Before production edits, unchanged `6a88765b` gave **8 failed, 8 passed,
103 deselected in 0.63s**. All four choices failed for each private direct-topic
case (raw message thread absent, or differing from the direct topic). Legacy
private-thread and group forum cases passed. Wrong-topic clicks leave the waiter
pending before the matching authorized retry.

The narrow callback fix normalizes IDs using existing `_telegram_id_to_str` and
uses the same precedence as the inbound builder: private direct topic first,
otherwise the raw message thread. Group/forum routes retain their message-thread
identity. Caller allowlist/pairing/group policies and base route checks are
unchanged. No execution-owner, transport decision-ID or Web changes are included.

Focused validation, with the root .venv active, fresh temporary SPARK_HOME and
this worktree's src on PYTHONPATH:

```text
python -m pytest tests/gateway/test_approval_button_authorization.py tests/gateway/test_telegram_approval_buttons.py tests/gateway/test_telegram_thread_fallback.py tests/gateway/test_telegram_reply_mode.py tests/gateway/test_telegram_group_gating.py -q -n 0 -m 'not integration' --tb=short --durations=5
```

Result: **173 passed in 8.12s**. Covers every choice, correct/wrong actual-builder
private direct-topic and forum routes, private precedence when both IDs exist,
legacy private threads, authorized retry/once-only resolution, existing caller
authorization cases and private-topic send/fallback/reply/group neighbors.
Focused test lint, selected Telegram CI lint and whitespace checks passed. Exact
commands, setup and the failed proof are retained in JSON.

All commands exited; no broad suite was run. SDK sends and topic lookup were
local fixtures, with Internet sockets forbidden. No shell execution, provider
calls, installs, browser or builds occurred. Root's frozen full-suite source was
not changed; canonical integration and final acceptance remain root-owned.
