# Spark simplicity and performance improvement plan

Prepared 2026-11-06. **25 proposed improvements, in priority order; one implementation PR per item.** All checkboxes start unchecked. This is an implementation brief, not a claim that the changes or performance gains have been verified.

## Research baseline and scope

- Spark reviewed at `13d7f767b056a4e8661c0af4118e3f1ad43c2433`, branch `docs/october-issue-feature-plan`. Working tree was clean before this planning work. Future implementers must inspect their actual committed base: this branch is not evidence of current `main` or installed-app behaviour.
- Hermes Agent reviewed at [`90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`](https://github.com/nousresearch/hermes-agent/tree/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4), fetched 2026-11-06. Reviewed its README, selected feature documentation and runtime sources. References below are pinned to that revision; upstream documentation describes intended behaviour, not independently measured performance.
- Spark analysis covered the domain glossary, structure map, all three accepted ADRs, chat lifecycle/routes, client transport/session loading, timeline projection, navigation/settings, providers, tools, memory and scheduler seams. Findings below are source observations and design recommendations. No new runtime defect reproductions, browser tests, benchmarks or installed-package tests were run for this document.
- The preceding plan is preserved verbatim in [the October delivery archive](docs/plans/issue-feature-plan-2026-10-22.md). The earlier [app upgrade plan](docs/plans/app-upgrade-2026-10-15.md), linked issues and open browser/native gates remain historical obligations. Archiving does not accept or close them.
- Spark already implements lazy tool manifests, bounded async execution, effect-aware tool scheduling, chat/sidebar virtualisation, shared SSE, durable run/child state, drafts, FTS search and context compression. Improve these existing paths; do not rebuild them. The October plan also records separate PRs for prompt history/stash, Markdown export/rendering, sounds, skill edit history and saved cron output. Check those PRs before editing overlapping areas; none is re-proposed here as a new feature.

Priority weighs lost/duplicated work first, then latency and resource use on common paths, then reductions in everyday configuration and navigation effort. Dependencies constrain merge order, not relative product value. Sizes are indicative: S = 1–2 focused days, M = 3–5, L = 5–8 including tests/review; these are planning estimates, not commitments.

Implementation update: the starting checkout was behind current main. Implementation PRs must use current `main` (`679916c4` at dispatch preparation), retaining this plan's research baseline for provenance. Revalidate source observations against the actual base and extend already-merged features rather than duplicating them. The latest main-branch [release ledger](docs/plans/release-ledger-before-2026-11-06.md) is also preserved.

## Pinned Hermes references

| Ref | Inspected feature/source | Relevant lesson for Spark |
| --- | --- | --- |
| H1 | [README](https://github.com/nousresearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/README.md) | Broad provider support, learning, scheduling and delegation are useful only when their controls remain understandable. |
| H2 | [Context compressor](https://github.com/nousresearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/context_compressor.py) | Protected head/tail, tool-output pruning, bounded summarisation and explicit failure handling inform context management. |
| H3 | [Session search tool](https://github.com/nousresearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/session_search_tool.py) | Search and bounded historical recall should retrieve the relevant conversation context. |
| H4 | [Memory guide](https://github.com/nousresearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/user-guide/features/memory.md) | Persistent memory and recall need visible user controls; distinguish memory types and their roles. |
| H5 | [Skills guide](https://github.com/nousresearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/user-guide/features/skills.md) | Progressive disclosure, project-local skills, bundles and setup requirements can reduce repeated instructions. |
| H6 | [Scheduled tasks guide](https://github.com/nousresearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/user-guide/features/cron.md) | Timezone, execution history, admission checks and separate delivery status make unattended work understandable. |
| H7 | [Code execution guide](https://github.com/nousresearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/user-guide/features/code-execution.md) | Bounded output, lifecycle limits and retrieving saved output avoid repeated execution and oversized context. |
| H8 | [MCP implementation](https://github.com/nousresearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/mcp_tool.py) | Connection, discovery, pagination and timeout handling are explicit integration concerns. |
| H9 | [Context files guide](https://github.com/nousresearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/user-guide/features/context-files.md) | Project instructions and their scope should be discoverable without bloating normal chat. |

H references identify inspiration, not missing-feature or parity claims. Spark-specific improvements are explicitly identified below. Adapt concepts to Spark's architecture; preserve notices for any copied code and review the pinned upstream licence.

## Implementation and acceptance contract

Each task below is a separate agent assignment and PR. No implementation agents are being started by this plan.

1. Before dispatch, create/link a GitHub issue using `docs/agents/issue-tracker.md`, record the packet ID, exact committed base, prerequisites, allowed paths and contract fixtures. Recheck whether the capability already landed elsewhere. A dependency means start from its merged commit or an explicitly recorded local stacked base, never assume another worktree includes uncommitted changes.
2. Own only listed paths and focused tests; new helper paths below are proposals. Keep shared-file PRs sequential, even if they modify different functions. One writer owns `spark_state.py` migrations, schemas/config, tool manifests, npm lockfile and production bundle at any time. Do not run several bundle/lockfile writers. No runtime rewrite or new orchestration framework.
3. Keep ADR-0001 cache goldens, ADR-0012 lazy discovery and ADR-0013 identity/ownership intact. No mid-thread system/toolset changes, implicit Dream, silent provider substitution, automatic replay of uncertain work, or child completion closing a root run. Use profile-aware storage and synthetic `SPARK_HOME`.
4. Baseline and candidate must use the same fixture, provider replay, machine, build mode and recorded Node/Python versions. Separate cold startup, warm reuse, acceptance time, first visible event, actual first token, tool time and completion. Capture at least five repeats for latency comparisons and report median/p95, sample size, payload bytes, request/commit counts and relevant memory. Targets below are **acceptance targets**, not measured claims. If missed, record the result and leave the checkbox open; do not weaken a threshold to obtain a pass.
5. Activate `.venv` for Python/server checks; verify Node 22 and its executable for frontend acceptance. Run focused regression tests while iterating, `ruff check src/` plus relevant pytest (`not integration`, `-n 0` for serial/shared state), and affected frontend lint/tests/build. Runtime/tool work also runs cache goldens, `tests/test_minimal_startup.py`, lazy-manifest tests and manifest `--check`. Report existing debt separately. Full suite when practical; disclose omissions. Tests should exercise real persistence at provider/process boundaries with replay fixtures.
6. Every UI/chat/gateway task needs browser evidence of its stated flow, including long conversations, two active chats, switching during generation, refresh/reconnect and isolated-profile state. Preserve project chat grouping and auto-opening its folder. Include keyboard/focus/error states. Web source/build, served bundle, macOS installation and Windows installation are separate gates. Each PR records what was actually verified; bundle regeneration and releases require their own coordinated gate.
7. Completion evidence goes in the issue and PR: exact head, source changes, baseline/candidate results, browser flow, limitations and rollback. Check an item only after its acceptance evidence passes, not when an agent finishes or opens a PR. Normal rollback disables additive behaviour or restores a compatible implementation; never delete newer user data or restore an old database blindly.

## Prioritised improvements

### 01 — Accept each submitted prompt once

- [ ] **SP01 · Backend + composer · L · Dependencies: none**

**Evidence and benefit.** `web_server.py` has durable receipts for child controls, but root create/send follow separate paths; `send_conversation_message` rejects an active turn with 409 rather than returning a previously accepted submission. Network ambiguity should not make users choose between losing a prompt and submitting it twice. This is Spark-specific reliability work, informed by H1's unattended/delegated workflows.

**Implement.** Add an optional client-generated submission ID to new-chat and follow-up bodies. Reuse the existing receipt mechanism, scoped to profile, originating conversation/create request and operation; hash the canonical prompt, attachment/context references and explicit route. Commit acceptance, root turn identity and dispatch intent together. Repeated identical requests return the original IDs; reused IDs with different payloads conflict. Preserve existing clients. On restart expose accepted-but-uncertain execution without redispatch. Composer retains the same ID until acceptance is resolved and only clears the originating acknowledged draft.

**PR boundary.** Own submission handlers/models in `src/spark_cli/web_server.py`, receipt extensions in `src/core/spark_state.py`, `web/src/hooks/useChatComposerActions.ts`, conversation API/types and focused tests. Sole migration writer. Do not change retries or child receipts.

**Accept.** Drop the HTTP response after commit; retry from the same draft and prove one persisted user prompt, one root run and one dispatch in replay. Test simultaneous duplicate requests, mismatched bodies, two profiles, compression aliases and process loss before/after dispatch. Browser retry recovers the accepted turn without duplicate output. Legacy payloads still work.

### 02 — Reconcile chat from one authoritative recovery snapshot

- [ ] **SP02 · Backend + chat UI · L · Dependencies: SP01**

**Evidence and benefit.** `web_server.py` exposes turn status, stream snapshot, outcomes, plan and pending actions separately; `chatRecovery.ts` and the session/stream controllers coordinate multiple responses. Consolidating recovery reduces round trips and inconsistent combinations of statuses. Existing journal recovery remains; this is an extension, not a new replay system.

**Implement.** Introduce a versioned recovery response containing resolved session/lineage, durable run state, pending decisions, bounded stream tail and projection revision. Read related durable fields in one database snapshot; explicitly identify the separate process-epoch stream watermark. Retry a bounded number of times or request re-reconciliation if those sources change during assembly. Adapt controllers to one recovery action while preserving legacy routes. Never combine the two cursor types or reissue work to rebuild the screen.

**PR boundary.** Recovery assembly in `web_server.py`/new helper, read-only SessionDB accessor, API types, `chatRecovery.ts`, session/stream controllers and replay tests. No new lifecycle writer.

**Accept.** Simulate expired retention, server restart, compression during fetch, delayed old replies and unresolved approvals. Browser refresh matches persisted state; an unknown tail is labelled/reconciled. Target one recovery HTTP request in the ordinary reconnect path instead of the measured multi-fetch baseline, with no duplicate prompts/actions and no regression in first restored content time.

### 03 — Keep expensive chat preparation off the API event loop

- [ ] **SP03 · Backend · M · Dependencies: SP01–SP02**

**Evidence and benefit.** The async follow-up handler in `web_server.py` synchronously opens SessionDB, resolves lineage and hydrates `get_messages_as_conversation` before executor dispatch. Warm-session and model preparation have additional blocking seams. Other chats' heartbeats and controls should remain responsive during long-history preparation.

**Implement.** Profile preparation stages, then move demonstrated SQLite/file/provider setup blocking into the existing bounded runtime. Create/use/close each DB connection in its owning worker. Separate preparation from commit/dispatch so SP01 ownership remains atomic; keep locks short and never hold the global turn lock across I/O. Put an explicit bound on queued preparations and return an actionable busy response when saturated. Do not increase thread counts as the default solution.

**PR boundary.** Chat preparation helper extracted from `web_server.py`, narrow `core/async_runtime.py` integration if required, focused concurrency/replay tests. No wholesale server extraction or provider payload edits.

**Accept.** With four concurrent submissions and a synthetic 10,000-message history/slow DB fixture, measure an independent status request and SSE heartbeat. Target p95 control response below 250 ms on the recorded fixture machine and at least 50% lower event-loop delay than baseline. Stop/cancel during preparation must fence dispatch; unchanged single-chat ordering/cache goldens must pass.

### 04 — Cancel obsolete reads across navigation and connection changes

- [ ] **SP04 · UI transport · M · Dependencies: SP02**

**Evidence and benefit.** `apiHelpers.ts` tracks connection generations and some APIs accept signals, but session list/history/search methods in `api_session.ts` do not expose cancellation. Session controllers fence stale responses, yet obsolete network/server work can continue. Cancellation saves resources during rapid navigation; fencing still provides correctness.

**Implement.** Add optional AbortSignals to read-only session/history/search/model calls without changing existing signatures' defaults. Provide a small owner-scoped read controller tied to backend, credential/profile epoch and view generation. Abort on retirement and treat AbortError as expected; continue checking identity on resolve/reject/finally. Never auto-abort an accepted mutation or share an abort controller across independent consumers.

**PR boundary.** `web/src/lib/apiHelpers.ts`, affected `api_*.ts`, small read-owner helper and read consumers/tests. Coordinate session-controller hunks after SP02; leave query deduplication to SP05.

**Accept.** Deferred-response tests cover A→B→A, same-ID different backend, credential replacement and unmount. Browser rapidly switches 20 threads under throttling: no stale messages/loading/errors and obsolete reads are cancelled. Compare completed bytes/requests with baseline and show a reduction; mutation acceptance remains recoverable through SP01.

### 05 — Share reference-data reads and retire redundant polling

- [ ] **SP05 · Backend + UI data layer · M · Dependencies: SP04**

**Evidence and benefit.** `sessionStore.tsx` reloads sidebar metadata on focus/visibility and a 15-second timer; `CronPage.tsx` also polls. Each Memory target card independently calls the all-target memory endpoint. Shared SSE already exists, so adding another transport would increase complexity.

**Implement.** Add a bounded, profile/backend/auth-scoped resource cache for sidebar metadata, cron summaries and memory targets only. Deduplicate in-flight identical reads, expose freshness/error state and invalidate from existing committed events plus successful mutations. Coalesce reconnect/focus refreshes; retain a low-frequency visibility-aware fallback for missing events and disconnected transports. Abort one consumer without cancelling other subscribers. Use ETags/revisions where useful; no generic cache of secrets or mutation responses.

**PR boundary.** New resource-store helper, sidebar metadata read integration, `CronPage.tsx`, `MemoryPage.tsx`, narrow domain ETag/event support and tests. No package dependency required; no broad session-store rewrite.

**Accept.** Two memory cards cause one read; simultaneous focus/reconnect produces one fetch per resource. Test lost events, TTL expiry, failed fetch, offline recovery and two profiles. Target at least 70% fewer idle reference-data requests over a recorded five-minute visible session, with committed changes shown within one second while connected and eventual fallback reconciliation when events are unavailable.

### 06 — Update only the active tail during token streaming

- [ ] **SP06 · Chat UI performance · M · Dependencies: SP02; coordinate ChatPanel edits after SP04**

**Evidence and benefit.** `ChatPanel.tsx` already virtualises turns and passes a previous timeline, but reprojects when `chatMessages` or subagents change. `threadTimelineModel.ts` must still be profiled for historical scan/allocation cost. Virtual DOM limits do not automatically bound projection or Markdown work.

**Implement.** Instrument completed-turn visits and React commits. Reuse immutable settled-turn projections; rebuild the dirty suffix identified by changed message/run IDs, falling back to a full projection for history replacement, edits, forks or compression. Memoise settled turn rows with stable callbacks. Batch active-tail presentation to animation frames without delaying terminal/approval events. Do not mutate persisted content or discard streamed text.

**PR boundary.** `ChatPanel.tsx`, `lib/threadTimelineModel.ts`, `components/chat/MessagesTimeline.tsx`, active assistant rendering and focused performance/property tests. Preserve the existing virtualiser and scroll model.

**Accept.** Full and incremental projections match across append, prepend, tool completion, subagent updates, fork and compression fixtures. On 10,000-message replay, target no settled-turn rebuilds for an ordinary token append and at least 50% lower projection CPU than baseline. Browser selection, exact copy, minimap, scroll anchoring and switching between two streams remain correct; record frame/commit evidence.

### 07 — Retrieve large tool results in bounded chunks

- [ ] **SP07 · Backend + tool-result UI · M · Dependencies: SP04**

**Evidence and benefit.** History already supports compact tool payloads and `getSessionToolResult`; that detail endpoint returns one complete content string. `ToolCallBubble.tsx` limits rich detection for large content, but an expanded result can still fetch/render a very large string. H7's saved-output retrieval motivates extending the existing path.

**Implement.** Add a capped cursor/range read to tool-result detail with total length, truncation and content revision. Keep raw stored output intact. Open collapsed results with a small preview, load further pages explicitly and support an authenticated streaming download for exact full content. Avoid loading the entire result merely to copy a preview. Keep permission/session ownership validation on every read, bound media detection and cancel stale expansions.

**PR boundary.** Tool-result read handler, read-only SessionDB accessor if needed, `api_session.ts`, `ToolCallBubble.tsx` and focused tests. No changes to model-visible truncation, exports or tool execution.

**Accept.** A 10 MB synthetic result opens with at most 64 KiB of initial result content; pagination reconstructs exact bytes, including Unicode boundaries. Test concurrent output revision, missing result, wrong thread/profile and cancellation. Browser expanding/collapsing two results stays responsive; explicit full download matches the stored hash and does not block token streaming.

### 08 — Make warmed-agent retention cost-aware

- [ ] **SP08 · Backend resource use · M · Dependencies: SP03**

**Evidence and benefit.** `web_server.py` already has an LRU/count cap, pending-approval protection and warm deduplication. Its cache is count-based; last-used bookkeeping offers a seam for idle expiry and measuring retained histories. H7's explicit lifecycle limits inform the policy; do not claim Spark lacks caching.

**Implement.** Add configurable idle expiry and a conservative retained-context byte estimate alongside the existing count cap. Evict only idle agents without live root/child ownership or pending decisions; close owned clients/resources using their existing lifecycle contracts. Bound warm bookkeeping and queued warm requests. Avoid rehydrating unchanged full history on warm hits when a verified durable revision matches; invalidate on external writes, route changes and compression. Keep disk history authoritative.

**PR boundary.** Agent-cache/warm helpers in `web_server.py`, optional config metadata and cache tests. No provider cache-key or prompt-content changes. Sole config writer while this PR is active.

**Accept.** Cycle 100 large sessions; demonstrate bounded estimates/cache entries and report measured process memory before/after quiescence. Live turns/approvals/children survive pressure. Eviction/reload produces byte-equivalent requests to baseline. Separate cold/warm first-token measurements; warm-hit preparation should improve without worsening cold preparation p95 by more than 10% on matched fixtures.

### 09 — Load Settings one tab at a time

- [ ] **SP09 · UI loading · S · Dependencies: none**

**Evidence and benefit.** `App.tsx` defers SettingsPanel, but `SettingsPanel.tsx` eagerly imports Analytics, Logs, Admin, Config, Memory, Messaging and SkillsTools pages. Opening Model settings therefore crosses many unrelated module boundaries. Existing route splitting is good; finish the nested boundary.

**Implement.** Lazy-load secondary settings tabs behind `LazyLoadBoundary`, with a cheap tab skeleton and explicit chunk-failure retry. Mount only the active tab. Preserve unsaved edits when switching through a small per-tab draft owner rather than mounting every page; background polling/subscriptions must stop when inactive. Keep Model settings immediately usable.

**PR boundary.** `web/src/components/SettingsPanel.tsx`, tab loader/draft helper and bundle/loading tests. No settings navigation redesign or dependency upgrades; existing package/lockfile unchanged.

**Accept.** Built browser network trace shows no Analytics/Logs/Admin feature chunk or data fetch when opening only Model settings. Compare transferred JavaScript and time to interactive controls with baseline; require a reduction in both on the throttled fixture. Test tab switch with an unsaved draft, close/reopen, chunk error recovery, focus restoration and remote profile changes. Initial Chat bundle must not grow.

### 10 — Use one provider catalogue across settings and chat

- [ ] **SP10 · Backend + model UI · M · Dependencies: none; serialize config/schema edits with SP08**

**Evidence and benefit.** SettingsPanel defines hardcoded provider options, endpoints and env-key mappings, explicitly saying they must mirror the backend schema. `runtime_provider.py` already resolves real routes. H1's provider flexibility is best served by a single trustworthy catalogue.

**Implement.** Expose a lightweight catalogue derived from existing provider definitions/resolution metadata: stable ID, label, credential mechanism, base-URL policy and supported controls. Return configured/available/unknown capability states without exposing credentials or performing network probes on catalogue reads. Consume it in Settings and ModelPicker, retaining typed custom models/endpoints. Keep secrets server-side and distinguish disabled capability from unverified support.

**PR boundary.** Catalogue helper/API in `providers_routes.py`, metadata integration with `runtime_provider.py`, Settings provider form, `ModelPicker.tsx`, API/types and contract tests. Do not replace provider resolution or silently migrate routes.

**Accept.** Parameterised tests cover every registered provider plus custom/local endpoints, missing credentials and unavailable optional SDKs. Browser select/save/reopen agrees with effective runtime configuration. Adding a fixture provider requires no new frontend option list. Catalogue fetch triggers no provider connection; runtime imports/minimal startup/cache goldens remain unchanged.

### 11 — Make model search fast and immune to stale responses

- [ ] **SP11 · Backend + UI · S · Dependencies: SP04, SP10**

**Evidence and benefit.** SettingsPanel's `ModelCombobox.load` updates models/loading after any request resolves; provider/base URL changes can overlap. H1 motivates preserving custom model choice while simplifying discovery. This is a source-observed race candidate, not a reproduced production incident.

**Implement.** Extract the combobox loader with a route/credential generation fence, AbortSignal, short-lived bounded catalogue cache and explicit refresh. Cache by full effective route and auth epoch, not provider name alone. Keep a valid selected custom model visible even if a list call fails. Separate loading, stale cached results, empty provider response and connection failure; never write a late default into config.

**PR boundary.** Model-loading helper, Settings combobox, narrow available-models API cache if server-side dedupe is needed and tests. SP10 owns catalogue semantics; this PR owns live list freshness only.

**Accept.** Resolve A/B provider requests in reverse order, change URL/token mid-request and retry a failure: only current-route results appear. Reopening an unchanged selector within TTL makes no second live list call; explicit refresh does. Browser keyboard selection and custom entry survive offline mode and route switches. No secret, auth token or unbounded list is persisted to browser storage.

### 12 — Open the command palette without bulk-fetching the app

- [ ] **SP12 · UI + search API · M · Dependencies: SP04–SP05**

**Evidence and benefit.** `CommandPalette.tsx` fetches projects, 500 sessions, cron jobs and skills on every open, then separately searches message text. This makes a navigation shortcut pay for data users may never search. H3's targeted recall suggests bounded query-driven lookup.

**Implement.** Show static actions and cached recent items immediately. Fetch a small recent list only when absent; debounce server-backed search by category with bounded results/cursors. Reuse SP05 resources for skills/jobs, never enumerate them solely to open the palette. Fence query/open generations, support cancellation and partial category errors. Preserve explicit project/thread/task destinations and keyboard grouping.

**PR boundary.** CommandPalette, palette search adapter, narrow existing search endpoint extensions and API tests. No new global search database or search-summary LLM call.

**Accept.** Cold open issues at most one bounded recent-items request and never calls `getSessions(500)`. On 10,000 sessions, initial actionable menu target is under 100 ms using cached/static items; record actual query latency separately. Search beyond the first 500 sessions succeeds. Test close/reopen mid-search, offline cached actions, one failed category and keyboard navigation while results arrive.

### 13 — Jump directly to the message found by search

- [ ] **SP13 · Backend + chat navigation · M · Dependencies: SP12**

**Evidence and benefit.** Session search returns message IDs, but CommandPalette currently navigates only to the result's thread. Users must search again inside a long conversation. H3 provides a concrete recall use case; Spark already has FTS and timeline navigation primitives.

**Implement.** Extend the global navigation target with an optional message anchor. Add a bounded history-window read around a validated message ID and resolved lineage, with stable surrounding cursors. Load that window, scroll/highlight the exact turn and allow loading older/newer pages; resume normal live-tail handling independently. For missing/deleted/compacted messages, explain the limitation and open the nearest valid thread context without inventing a match.

**PR boundary.** `globalNavigation.ts`, palette result action, session history API/read accessor, session controller and timeline anchor tests. Coordinate `spark_state.py` read helpers; no index migration or changed FTS semantics.

**Accept.** Search a message in the middle of 10,000 messages and open it with a bounded window, not the entire transcript. Test compression lineage, two equal snippets, deleted messages, query escaping and active-stream arrival. Browser highlight is visible and keyboard focus remains usable; returning to latest follows the current stream without duplicate rows or lost cursors.

### 14 — Explain context pressure and make compaction controllable

- [ ] **SP14 · Runtime + context UI · L · Dependencies: SP02**

**Evidence and benefit.** Spark has `ContextCompressor`, checkpoints, manual compression feedback and a ContextWindowMeter with estimated usage and attachment controls. H2 adds useful design references for pruning first, protecting head/tail and reporting summary failure. Extend those existing mechanisms rather than adding a second compressor.

**Implement.** Show a compact breakdown of history, tools, instructions, memory and attachments, distinguishing estimates from provider counts. Offer a preflight view of the existing compaction policy and an explicit compact action at an idle/safe boundary. Use deterministic tool-output reduction before an LLM summary where compatible with current policy; protect unresolved decisions, tool-call/result pairs, recent instructions and requested attachments. Bound summary time/cost; keep the last valid checkpoint on failure. Record lineage and reduction statistics without rewriting cached history mid-turn.

**PR boundary.** `agent/context_compressor.py`, `context_checkpoint.py`, existing compaction entry point, context estimate/controls and tests. No memory/Dream behaviour changes.

**Accept.** Replay context-overflow fixtures with tools/approvals and verify every protected fact/pair. Failure/timeout preserves resumability. Browser action cannot race an active turn and shows before/after estimated versus actual usage honestly. Report compaction latency/token reduction and answer-quality checks against baseline; reject a cheaper summary that loses required facts.

### 15 — Show where a slow turn spent its time

- [ ] **SP15 · Backend + chat diagnostics · M · Dependencies: SP02–SP03**

**Evidence and benefit.** Spark already records streaming pipeline timings, lock/executor waits and efficiency counters; `SessionInfoBar`/timeline usage and Analytics offer display seams. These measurements should answer why a specific turn is slow without opening logs. H1/H2 motivate separating provider/context overhead from UI delay.

**Implement.** Persist a bounded per-turn timing summary using existing root IDs: accepted, queue/preparation, provider start/first token, tool duration and finish; include provider-reported usage/cache counters where available. Use monotonic server durations and separate browser marks; never subtract unsynchronised clocks. Add an optional details popover with plain-language stages and unknown/estimated labels. Reuse existing diagnostics; no per-token database writes or external telemetry service.

**PR boundary.** Existing pipeline metrics helper/turn summary persistence, `agent/efficiency_metrics.py` if needed, turn-outcome API/types and a small SessionInfoBar/detail component. Coordinate sole migration writer; avoid ChatPanel refactoring.

**Accept.** Deterministic delayed queue/provider/tool replays produce expected nonnegative spans; first status is not mislabelled first token. Two simultaneous chats show their own timings after refresh. UI is quiet by default and works when usage is absent. Added instrumentation target: under 2% local replay wall-time overhead, measured on baseline/candidate; no transcript/secret capture.

### 16 — Make retry waits visible, bounded and cancellable

- [ ] **SP16 · Runtime + status UI · M · Dependencies: SP15**

**Evidence and benefit.** Retry policy, rate-limit tracking and error classification already exist. Waiting is still a different state from generating content; users need to see whether the provider is retrying or the app has stalled. H6's explicit provider-unavailable handling informs this extension.

**Implement.** Consolidate the existing retry decision into a structured status with reason class, attempt, next-attempt delay and a total elapsed retry budget. Respect Retry-After, jitter and current provider-specific policy. Emit sparse countdown/deadline data rather than per-second backend events. Cancellation interrupts backoff promptly. Do not retry uncertain side-effecting tools, replay accepted submissions, change provider/model silently or mutate request prefixes between attempts.

**PR boundary.** `core/run_agent/retry_policy.py`, existing retry/error helpers, status callbacks and `StatusPill.tsx`/status model with tests. No new routing policy.

**Accept.** Replay 429, temporary 5xx, auth failure, timeout and stream failure after partial output. Permanent errors stop; transient retries respect the budget; Stop during backoff prevents another provider request within 250 ms in the fixture. Browser shows retry reason/next delay and restores confirmed state after reconnect. Cache goldens and payload equivalence across retries pass.

### 17 — Preview schedules before they can run

- [ ] **SP17 · Scheduler + Schedule UI · M · Dependencies: SP10; rebase after earlier cron mutation-lock PR if integrated**

**Evidence and benefit.** `cron/jobs.py` parses schedules and computes next times; CronPage edits a schedule string. H6 documents timezone, catch-up and pre-dispatch validation. A readable preview prevents timezone mistakes and unexpectedly frequent work.

**Implement.** Add a side-effect-free validation/preview API returning the next five execution times, explicit timezone and effective model/skills/delivery availability. Reuse the same parser for preview, create, update and dispatch; reject nonpositive intervals and unsupported/invalid values at every boundary. Add an optional per-job IANA timezone with legacy jobs retaining existing semantics. Mark malformed legacy schedules paused/requiring repair rather than hot-looping. Clearly describe missed-run policy; do not execute or contact a provider during preview.

**PR boundary.** Schedule parser/next-run code, cron request models/routes/API, isolated preview component in CronPage and tests. Preserve or integrate existing cross-process mutation locking; no attempt ledger here.

**Accept.** Frozen-clock fixtures cover DST gaps/folds, UTC, local/remote timezones, invalid intervals, one-shots and structured updates. Preview and actual next-run computation agree. Browser shows absolute times/timezone and actionable validation; editing an existing job preserves its ID and unrelated fields. No provider call or job creation occurs from preview.

### 18 — Separate scheduled execution history from delivery history

- [ ] **SP18 · Scheduler persistence + Schedule UI · L · Dependencies: SP17**

**Evidence and benefit.** `scheduler.tick` saves output, delivers and updates aggregate job state; the preceding plan adds saved-output browsing, which is not authoritative attempt history. H6 explicitly distinguishes execution and delivery. Users need to know whether a job failed to run or merely failed to send its result.

**Implement.** Add a small profile-local SQLite attempt ledger owned by a new cron history module, leaving existing job definitions in their current store. Record attempt ID, job ID, scheduled/manual cause, start/finish, execution outcome, delivery outcome and safe output reference. Persist before publishing events. On restart reconcile abandoned attempts to interrupted/unknown; never rerun them silently. Present a paginated history drawer that links saved output when available and displays delivery failure independently. Retain bounded history with explicit pruning rules.

**PR boundary.** New cron history module/schema, narrow scheduler lifecycle hooks, read API and standalone history UI. One writer owns this schema; do not migrate job definitions or duplicate the earlier output browser.

**Accept.** Real SQLite replay covers success+delivery failure, silent suppression, cancellation, crash before/after delivery and repeated callbacks. No duplicate attempt/notification; unknown delivery remains unknown. Browser refresh preserves history and pages without loading outputs. Existing scheduling/mutation-lock tests pass; legacy output remains readable without fabricated historical attempts.

### 19 — Stop terminal sessions whose start acknowledgement arrives too late

- [ ] **SP19 · Terminal UI lifecycle · M · Dependencies: SP04**

**Evidence and benefit.** `WorkspaceTerminalPanel.tsx` has a pending-start/cleanup seam: a retired request can return before its run ID was adopted. The prior reference audit records this candidate outside the selected October packets. Reproduce on the actual base before fixing. H7's explicit process lifetimes inform the intended behaviour.

**Implement.** Bind terminal start, acknowledgement and stream handlers to one owner/generation. If a newly created owned run is acknowledged after retirement, stop that exact run once; never stop a replacement or an intentionally reattached terminal. Define reconnect as reattachment where supported and restart as an explicit new process. Bound retries and show disconnected/reconnecting state without silently launching another shell.

**PR boundary.** `components/workspace/WorkspaceTerminalPanel.tsx`, terminal lifecycle helper/tests; narrow terminal API changes only if needed to identify create versus attach ownership. No generic process manager rewrite.

**Accept.** Deferred start→navigate→late acknowledgement cleans up the old run; replacement survives. Test reversed restart responses, stream loss, reconnect failure and project switch. Browser flow uses a temporary project plus a harmless process marker to verify one surviving terminal and no orphan after close. Record Windows limitations separately; never infer cleanup from a closed UI panel.

### 20 — Fetch project files as users expand folders

- [ ] **SP20 · File API + project UI · M · Dependencies: SP04**

**Evidence and benefit.** `workspace_routes.py` has both recursive tree construction and per-directory list endpoints. FileTreePane should prefer the bounded directory path for large repositories. H9's project-scoped context is useful without enumerating every file when opening Chat.

**Implement.** Trace the live FileTreePane request path and reuse directory listing for expanded nodes only. Add stable sort, bounded page size/cursor and a cancellable filename search using existing filesystem/Git ignore policy. Cache expanded directory results by root/revision and invalidate only affected ancestors on edits/events. Explicitly handle symlinks/cycles and intentionally linked project roots; keep all reads inside the authorised root. Do not replace the file editor or silently hide user files.

**PR boundary.** Tree/list helpers in `workspace_routes.py`, file APIs, FileTreePane and tests. Integrate after any existing upload/Git route PRs; do not touch their handlers.

**Accept.** A synthetic 100,000-entry repo opens with one directory page of at most 200 entries, without recursive traversal. Expand/page/search reaches omitted files; refresh after create/delete updates the correct folder. Test hidden/ignored files, deep paths, external symlinks and project switch. Record p95 tree-ready latency and payload reduction against baseline; streaming remains smooth during expansion.

### 21 — Give memory one coherent, searchable review surface

- [ ] **SP21 · Memory backend + UI · M · Dependencies: SP05**

**Evidence and benefit.** MemoryPage currently shows two Markdown targets; `memory_routes.py` loads MemoryStore for those targets. Spark also has a holographic store/retrieval provider and explicit Dream outputs. H4 motivates making those distinctions visible instead of presenting two lists as the whole memory system.

**Implement.** Keep existing editable Memory/About-you cards, fed by one shared read. Add bounded read-only holographic search/details and a link to explicit Dream review output, labelling source/category/time when actually stored and unknown otherwise. Show whether edits affect the next conversation/compaction rather than promising mid-thread reload. Preserve drafts on read errors; show mutation failures inline. Existing explicit forgetting remains limited to the store it actually updates.

**PR boundary.** `memory_routes.py`, new bounded holographic read adapter, MemoryPage/subcomponents and tests. No retrieval ranking rewrite, new automatic extraction, implicit Dream or fabricated provenance.

**Accept.** Fixtures demonstrate Markdown-only, holographic-only, optional-provider unavailable and empty memory. Search pages without full-store reads; results are profile-isolated and safe to render. Browser can edit an entry, recover from a failed save, find a holographic fact and open a real Dream review when present. Measure initial request count and response size; no LLM invocation on browsing/searching local facts.

### 22 — Make skills easy to choose without loading every instruction

- [ ] **SP22 · Skills metadata + UI · M · Dependencies: SP10, SP21; respect earlier skill-history PR**

**Evidence and benefit.** SkillsToolsPage fetches skills/toolsets together and has a detail panel; Spark already has skill metadata, guards and usage helpers. H5's progressive disclosure/project-local requirements suggest a simpler discovery path, not another skills engine.

**Implement.** Build a lightweight indexed metadata view from existing skill discovery: name, short description, scope, provenance and declared requirements. Cache by discovered-file metadata with explicit refresh/external-change invalidation; load body/supporting files only on selection. Separate available, disabled and missing-requirement states; check presence of required credentials without returning values or running arbitrary setup. Offer explicit project/thread skill selection through existing next-turn user-message injection, never alter the live toolset/system prefix.

**PR boundary.** Skill list metadata/cache helper, skills routes, SkillsToolsPage list/filter/detail integration and tests. Keep skill edit-history ownership intact; no automatic installation, marketplace, bundle format or skill generation in this PR.

**Accept.** With 1,000 skills, initial list omits full instruction bodies and shows scoped search without opening each file. Test user/project name collisions, external edits, missing requirements and unavailable optional dependencies. Browser selection injects the intended skill once into the correct thread, retains unsent input and cannot silently activate untrusted setup. Compare list-ready time/payload with baseline.

### 23 — Show integration readiness and bounded MCP tests

- [ ] **SP23 · MCP backend + Settings UI · M · Dependencies: SP05, SP10**

**Evidence and benefit.** `mcp_routes.py` lists configuration and starts a background admin-run test. Spark already supports MCP timeouts and dynamic discovery. Configuration presence alone is not proof of a usable integration; H8 provides connection/discovery/pagination reference points.

**Implement.** Project a safe readiness summary: configured, testing, ready, failed or unknown, last test time, elapsed time and tool count from an actual completed test. Bound concurrent tests/timeouts, dedupe tests for the same config revision and retire outdated results. Show a single Test/Retry action linked to the existing admin run. Redact env/header/URL secrets in summaries and errors. Do not perform probes on every page open or mutate active-conversation schemas in response to tests.

**PR boundary.** MCP routes/config test adapter, existing admin-run integration, MCP settings component and focused tests. Leave live discovery ownership in `tools/mcp_tool.py`; no new transport.

**Accept.** Fake stdio/HTTP servers cover timeout, malformed schema, pagination, auth error and success. A slow server cannot stall other integrations or exceed the configured test pool. Config edits prevent old success being adopted. Browser distinguishes saved from verified configuration and can inspect a bounded error safely; tests never disclose synthetic secrets and normal startup does not connect to unconfigured servers.

### 24 — Explain Auto model choices before users need logs

- [ ] **SP24 · Routing UI + read API · M · Dependencies: SP10, SP15**

**Evidence and benefit.** `agent/smart_model_routing.py` already returns deterministic decision signals, scores and reasons; response budgets/model-role configuration also exist. H1's broad provider choice reinforces the value of making Spark's existing Auto mode understandable. Do not add another classifier or routing framework.

**Implement.** Expose the effective configured role routes and a concise explanation of the selected route on a turn's details. Let users choose Auto or pin an explicit model through existing controls; provide one settings view for current role mappings and capability/credential gaps. Use existing route validation. Mark estimates and unavailable capabilities honestly. Changing a role applies only at supported future-turn/new-thread boundaries; surface any required new thread rather than silently rebuilding the cached prefix.

**PR boundary.** Routing projection/helper, read API/types, ModelPicker/role-settings panel and tests. Do not tune classifier weights, add provider fallback or change budgets automatically in this PR.

**Accept.** Deterministic fixtures cover direct answer, attachments, high-risk action, missing route credentials and explicit pinned model. Visible explanation matches the route actually used after refresh and reconnect; an explicit model is never overridden. Browser can inspect/change a role without raw YAML and retains custom endpoints. No extra model request is made to explain a decision; cache goldens pass.

### 25 — Replace scattered configuration with a searchable common-settings view

- [ ] **SP25 · UI simplicity · M · Dependencies: SP09–SP11, SP14, SP22–SP24**

**Evidence and benefit.** App navigation, CommandPalette page items, SettingsPanel tabs and schema-driven ConfigPage expose overlapping destinations; some page concepts are settings rather than live top-level routes. H1/H5/H9 demonstrate a broad agent's discoverability challenge. This task simplifies the existing information architecture after the underlying controls stabilise.

**Implement.** Create a small typed destination/settings index shared by navigation, palette and Settings search. Show common controls first: connection/profile, model, memory/context, skills/integrations and notifications; retain advanced fields behind a named disclosure with the same backend validation. Search opens the exact section/field with a breadcrumb. Preserve existing deep links, custom values, translations and unsaved drafts; unknown advanced fields remain reachable. Do not create “Fast” presets with unmeasured performance claims or move project tasks out of Chat.

**PR boundary.** Navigation/settings registry helper, `App.tsx`, SettingsPanel/ConfigPage navigation, CommandPalette destination mapping, relevant translations and accessibility tests. No backend defaults, branding or unrelated layout redesign.

**Accept.** Keyboard-only flows: change model, find memory, test MCP, edit a schedule, return to the originating thread. Each common setting is reachable in at most two explicit navigation selections after opening Settings; search takes users to the exact labelled control. Test old deep links, remote/local profile switch, unsaved changes and small screens. No duplicate destinations/dead palette actions; SP09 lazy chunk/network budgets remain satisfied.

## Scheduling refinement — 2026-11-06

To use all five authorised parallel slots without shared-file writers, SP17,
SP19 and SP20 may implement from green SP01 head `a12205a5` now. Source review
confirms cron already exposes provider resolution/catalogue seams, terminal
ownership can be fixed within its own component, and file browsing can use native
AbortController plus a dedicated domain client. Their original SP10/SP04 links
remain integration ordering/compatibility checks, not hard implementation blockers.
SP17 reuses existing runtime/provider resolution (no new catalogue); SP19/SP20
must not invent a competing generic transport. SP20 owns workspace tree/list routes
and a new file-tree client; SP19 leaves api_workspace unchanged. A real-process
acceptance failure demonstrated that terminal Stop reports stopped while zsh
survives. SP19 is now additionally authorised to own only terminal worker/Stop
functions in workspace_routes plus a separate process-lifecycle helper; SP20
must keep changes to tree/list/search functions. These non-overlapping function
slices require explicit integration/rebase and rerunning workspace neighbours;
neither agent may reformat or extract the whole shared module.
SP17 owns cron modules/routes/page/client. All three leave shared api.ts/apiTypes,
SessionDB, web_server, SettingsPanel, config, manifests, lockfiles and bundles to
their existing owners. SP04/SP10 later retain these domain contracts when integrated.
SP11 may also start after SP10 using native AbortController and the existing
signal-capable fetchJSON, with SP04 retained as a later transport compatibility
check. Its model-search writer must first finish SP10's discovered live PromptBar
integration and remove unintended mount-time model discovery, updating the same
SP10 PR before making a separate SP11 PR. PromptBar is independent of the active
SP02 ChatPanel/controller writer; do not edit those shared files.
SP23 may proceed from SP10's catalogue base using existing MCP config/admin-run
interfaces; SP05 resource-cache adoption is a later integration check, not a
reason to block domain readiness/testing work. SP23 owns MCP routes/helpers/new
readiness UI and only the McpSection function/imports in SettingsPanelContent;
SP11 owns ModelCombobox/provider sections in that file. Keep those slices narrow,
serialize final shared-file integration and rerun Settings neighbours. Do not
replace either with a whole-file rewrite or introduce another generic transport.
SP03 may implement against green SP01 while SP02 finishes rendered recovery:
SP02's committed server edits add recovery assembly/read routes, whereas SP03
owns only create/send/warm preparation handlers and a new preparation helper.
Keep SessionDB schema/receipts and recovery read fields unchanged. These separate
function slices require explicit rebase/integration and shared lifecycle replay
checks before acceptance; SP03 must preserve SP02's eventual recovery response.
SP21 may implement its independent memory routes/review page from corrected
SP10 head `9acb185a` while SP05 is pending. One view-owned parent read feeds both
Markdown cards, using existing signal-capable fetchJSON and native cancellation;
SP05 later adopts that domain read without a competing generic cache. SP12 may
likewise implement its palette-only query owner and bounded search adapter now.
It must not enumerate skills/jobs to open the palette or create a second shared
resource cache. SP04/SP05 remain explicit integration checks for both packets.
SP12 owns CommandPalette/new palette client and narrow search-route functions;
SP21 owns MemoryPage/memory routes/new read adapter. Neither touches SP02/SP03
lifecycle/controller functions, SP23 Settings/MCP functions, shared API barrels,
SessionDB schema, lockfiles or generated bundles. Preserve existing endpoints;
serialize any eventual shared server import/registration integration.
SP07 may implement bounded tool-result reads using existing signal-capable
fetchJSON and a dedicated result client before SP04. SP04 remains an explicit
later transport integration check. SP07 owns only the tool-result detail/download
route functions, a new read helper, api_session tool-result functions and
ToolCallBubble. It must not edit SessionDB or SP02-owned API barrels/types and
controllers; use a worker-owned connection and SQL bounded projection through
an isolated read adapter. Keep lifecycle preparation/recovery functions untouched.
SP03's real ownership probe demonstrated that a cached agent connection crosses
preparation, turn and cleanup threads. SP03 may therefore additionally change
narrow agent creation/disposal and title/runtime DB-lifetime helpers to finish
physical connection ownership. Preserve cache policy, actual SessionDB identity,
child ownership and receipt/schema contracts; no generic proxy or new worker pool.
SP22 may add a stable-ID skill invocation formatter without setup and narrow
context-validation/augmentation integration. Keep selected identity/revision in
the canonical submission payload; no receipt/schema/controller changes or cached
prefix/toolset mutation. This does not give SP22 ownership of SP03's preparation
handlers. Each writer integrates these separate function slices explicitly.
This changes scheduling only; every packet's full behaviour, tests and performance
acceptance remains required. No missing prerequisite is silently counted complete.

## Dispatch and integration map

Priority numbers above are authoritative; this map prevents concurrent writers from turning 25 independent PRs into an integration rewrite.

| Shared area | Required ownership/order |
| --- | --- |
| Root lifecycle/server/SessionDB | SP01 → SP02 → SP03. SP08 follows SP03; SP15 follows SP02/SP03. Serialize any migration/read-helper edits for SP07/SP13/SP15 through one owner. |
| Client transport/cache | SP04 → SP05; SP07 can follow SP04 independently. SP12 follows SP05, then SP13. |
| ChatPanel/session controllers | Merge SP02/SP04 controller changes before SP06; SP13 rebases afterwards. Keep visual seams for SP14/SP15/SP16 minimal and coordinate the same writer. |
| Settings/model selection/config | SP09 is independent loading work. SP10 catalogue precedes SP11; SP24 follows SP10/SP15. Serialize their SettingsPanel hunks. SP25 integrates last. |
| Cron | Recheck October mutation-lock/output/model-fields PRs, then SP17 → SP18. SP05 changes refresh only; rebase before editing the page again. |
| Memory/skills/MCP | SP21 follows SP05; SP22 follows SP21/SP10; SP23 follows SP05/SP10. Separate domain modules, shared settings integration serialized. |
| Files/terminal | SP19/SP20 follow SP04 and can be dispatched separately, with the existing upload/Git/terminal PR state checked first. |
| Dependencies/build artifacts | No packet assumes a new npm package. If necessary, one designated writer updates nested lockfile. Do not commit web_dist in parallel feature PRs; regenerate at the coordinated verified web release gate. |

For each assignment, attach representative fixtures (long thread, parallel chats, temporary Git project, slow provider/integration, two isolated profiles) relevant to that packet. Scope any uncovered prerequisite explicitly; do not silently expand a single PR into several roadmap items. Keep all 25 checkboxes open until their own acceptance record is complete.

## Validation adjustment — user direction, 2026-11-06

Stop repeated full-suite local runs per packet. During implementation, run focused
regressions for changed behavior, relevant lint/type/build checks, and the affected
browser acceptance flow. Reuse passing evidence for unchanged source. Existing CI
runs the full matrix once per published PR; reruns require a specific diagnosed
failure or material new change. Preserve meaningful tests/assertions and required
behavioral acceptance; do not delete tests, skip failures, or weaken thresholds.
This supersedes earlier blanket full-local-matrix delegation requirements.
