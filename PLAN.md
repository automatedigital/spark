# Spark Efficiency Improvement Plan

## Goal

Deliver ten substantial improvements that reduce Spark's model input and output
tokens, time to first token, tool-loop latency, background server load, session
persistence overhead, frontend rerenders, and cold-start cost without weakening
agent autonomy, safety, context fidelity, or packaged-platform reliability.

This began as a review plan. The validated pilot work retained on
`spark-efficiency` is recorded below; unchecked tasks remain future work. Each
improvement has an explanation, concrete implementation steps, measurable
verification, dependencies, and an explicit rollback boundary.

## Evidence Reviewed

### Spark

- `src/core/run_agent/__init__.py` and `src/core/run_agent/`: the agent hot path,
  tool loop, provider adapters, retries, persistence, and compression.
- `src/core/model_tools.py`, `src/core/toolsets.py`, and `src/tools/registry.py`:
  eager discovery and the model-visible tool surface.
- `src/core/run_agent/prompt_cache.py`, `src/agent/prompt_builder.py`,
  `src/agent/prompt_caching.py`, and `src/agent/context_compressor.py`: system
  prompt construction, provider caching, context estimation, and compaction.
- `src/tools/budget_config.py` and `src/tools/tool_result_storage.py`: per-result
  persistence and the aggregate tool-output budget.
- `src/core/spark_state.py`: SQLite/WAL session state and per-message writes.
- `src/spark_cli/web/src/lib/sessionStore.tsx`,
  `src/spark_cli/web/src/components/ChatPanel.tsx`, and
  `src/spark_cli/web/src/App.tsx`: SSE reconciliation, recovery polling, status
  polling, and frontend state ownership.
- `src/agent/smart_model_routing.py`: the existing opt-in character/keyword
  router for fast versus smart models.

### Reference repositories

- [T3 Code](https://github.com/pingdotgg/t3code), inspected at commit
  `d3037064e61a9f059eafbd4f9869679779bd2a7c`.
  - `docs/internals/overview.md` and `docs/internals/connection-runtime.md` for
    typed RPC subscriptions and server-owned state.
  - `packages/client-runtime/src/state/threads.ts` for cached snapshots,
    `afterSequence` delta replay, a sliding persistence queue, 500 ms debounce,
    settled-only persistence, and scoped state lifetime.
  - `packages/client-runtime/src/state/threadDetail.ts` and
    `threadRetention.ts` for shell/detail separation, referentially stable
    selectors, and idle TTLs.
  - `packages/client-runtime/src/rpc/client.ts` and
    `connection/supervisor.ts` for one connection supervisor, bounded backoff,
    resumable subscriptions, and transport lifecycle ownership.
- [i-have-adhd](https://github.com/ayghri/i-have-adhd), inspected at commit
  `d05af1e4ac2259846e81686d14180d46d84acc2d`.
  - `skills/i-have-adhd/SKILL.md` for action-first, tangent-free, state-aware
    output rules that still yield to safety and explicit requests for detail.
  - `evals/` for isolated baseline/candidate runs, fixed models, identical
    cases, cost caps, blind judging, and release gates that protect correctness,
    autonomy, actionability, and safety while rewarding concision.

The temporary clones are research inputs only and must not be copied into or
committed with Spark.

## Measured Baseline

Measurements were taken from the current checkout on 2026-08-01. They are
directional baselines, not release claims.

| Area | Current observation | Why it matters |
| --- | ---: | --- |
| Default model-visible tools | 29 tools | Every schema is resent on every model iteration. |
| Default tool schema | 35,213 chars, roughly 8,804 tokens | This cost exists before conversation history or tool results. |
| Spark project system prompt | 17,249 chars, roughly 4,313 tokens | This includes project context and Spark-owned guidance. |
| Prompt plus schemas | Roughly 13,117 tokens | This is the approximate fixed request floor in the measured setup. |
| Largest default schemas | `delegate_task` 4,152 chars; `terminal` 3,573; `skill_manage` 2,747; `execute_code` 2,575 | A small number of verbose schemas dominate the tool budget. |
| Sequential tool delay | 1 second between calls | Independent of actual provider or tool rate limits. |
| Aggregate tool-result allowance | 200,000 chars per assistant tool batch | A single batch can consume roughly 50,000 context tokens. |
| Default result threshold | 100,000 chars; `read_file` is unbounded in persistence policy | Large payloads reach context before compaction has a chance to help. |
| `core.run_agent` import | Roughly 0.75 seconds on this Mac | Tool discovery imports optional SDKs before they are used. |
| Main hot-path module size | `run_agent/__init__.py` 10,760 lines | It makes performance ownership and profiling difficult. |
| Web hot-path module size | `web_server.py` 10,447 lines; `ChatPanel.tsx` 3,214; `api.ts` 2,888 | Broad state updates and transport behavior are difficult to isolate. |
| Steady-state UI polling | Status group every 8 seconds; chat recovery decision every 2 seconds | SSE already exists, but polling remains a normal background path. |
| Session JSON persistence | Full session document is atomically rewritten on save | Total bytes written grow quadratically over a long conversation. |

## Validated Pilot Results

Measured experiments retained on 2026-08-01:

| Pilot | Before | After | Decision and evidence |
| --- | ---: | ---: | --- |
| Compact high-cost schemas | `delegate_task` plus `execute_code`: 6,665 compact-JSON chars | 3,887 chars | **Keep.** Saves about 2,778 chars, or roughly 695 input tokens, while preserving required parameters, web return envelopes, limits, helper guidance, and all focused tests. |
| Default sequential tool pacing | Two zero-work calls: 1.0067 s median | 0.0002 s median | **Keep.** Removes 99.98% of artificial wait time. Explicit pacing, result order, conflicts, and cancellation remain covered. |
| Recoverable tool-result token budgets | Four 42,000-char results: about 56,000 estimated tokens | About 14,759 estimated tokens | **Keep.** Cuts the inline batch estimate by 73.6%; storage failure preserves the original result and aligned internal tool names protect unbounded `read_file` pages. |
| Lazy optional MCP startup | `core.run_agent`: 0.5959 s, 1,626 modules, about 103.4 MiB RSS | 0.4849 s, 1,421 modules, about 89.5 MiB RSS | **Keep.** Seven-process independent replay measured 18.6% faster import, 205 fewer modules, and about 13.9 MiB lower RSS. Configured MCP profiles retain eager discovery. |

The pilots deliberately do not claim completion of the larger facade,
artifact-ledger, dependency-DAG, or full lazy-manifest designs. Those remain
behind their explicit replay and compatibility gates below.

## Scope and Invariants

- Preserve the stable `from core.run_agent import AIAgent` import.
- Preserve one byte-stable model-visible prompt and tool schema surface during a
  conversation. No mid-thread toolset swapping or context mutation.
- Context files, profile state, memory, skills, and user instructions remain
  profile-aware. Token savings must not silently omit applicable instructions.
- The server and SQLite remain authoritative. Browser state must reconcile from
  confirmed backend state after reconnect, refresh, restart, or stale storage.
- Existing terminal backends, gateway platforms, providers, and API modes must
  keep working. Performance work cannot become a provider-specific fork.
- All limits are measured in provider tokens when an official tokenizer/count is
  available, with the existing conservative estimator as fallback.
- Generated `src/spark_cli/web_dist/` files are release output. Source work lands
  in `src/spark_cli/web/src/` and is bundled only at the release gate.
- Keep source tests, local web acceptance, and packaged macOS/Windows acceptance
  as separate gates.
- Preserve unrelated worktree changes and supplied reference assets.

## Success Metrics

The project should record a baseline distribution and compare like-for-like
replays. The target is not one synthetic best case.

- At least 45% fewer fixed input tokens from Spark-owned prompt plus schemas on
  the default CLI/web profile, excluding user-authored `AGENTS.md`, memory, and
  conversation content.
- At least 30% fewer uncached input tokens across a representative 20-turn agent
  workload, with cache reads/writes reported separately.
- At least 30% fewer output tokens on direct answers and progress updates, with
  no material correctness, safety, or autonomy regression.
- No artificial one-second gaps between local sequential tool calls.
- At least 35% lower median end-to-end latency for a four-tool independent batch.
- At least 50% fewer bytes written while replaying a 100-turn session.
- Zero steady-state status/session polling while the event stream is healthy.
- At least 40% lower `import core.run_agent` wall time on the same warm/cold
  benchmark host, or a documented equivalent RSS/package-startup win.
- No new failures in focused tests, the practical Python suite, frontend tests,
  bundle budget, local browser acceptance, or packaged desktop smoke flows.

## Dependency Order

```text
BASELINE
├── EFF-01 compact stable tool surface ─┬─ EFF-02 prompt/cache segmentation
│                                      └─ EFF-10 response/model budgets
├── EFF-04 bounded tool results ────────── EFF-03 typed context compaction
├── EFF-05 tool scheduler ──────────────── EFF-06 shared async runtime
├── EFF-07 event persistence ───────────── EFF-08 sequence-based web state
└── EFF-09 lazy startup

All ten improvements -> integrated replay -> local web acceptance -> packaged gates
```

## Phase 0: Benchmark and Replay Contract

- [x] **BASE-01 - Create a versioned efficiency fixture set.** Add redacted
  fixtures for direct answers, code edits, multi-tool research, large file
  reads, long sessions, reconnects, and concurrent chats.
  **Files:** new `tests/efficiency/fixtures/` and
  `src/spark_cli/web/e2e/fixtures/`.
  **Done when:** fixtures contain no credentials or private message content and
  every improvement can replay the same workload.

- [x] **BASE-02 - Add request accounting.** Record prompt tokens, schema tokens,
  conversation tokens, injected-context tokens, tool-result tokens, cache read
  tokens, cache write tokens, output tokens, provider/model, and request latency
  per model iteration.
  **Files:** `src/core/run_agent/`, `src/agent/model_metadata.py`,
  `src/agent/usage_pricing.py`, and `src/core/spark_state.py`.
  **Done when:** totals reconcile with provider usage fields where available and
  estimator-only rows are visibly marked.

- [x] **BASE-03 - Add runtime and UI counters.** Measure import/startup time,
  tool queue wait, tool execution time, DB transactions/bytes, JSON snapshot
  bytes, event payloads, reconnects, HTTP polls, React commit counts, and stream
  recovery actions.
  **Files:** `src/core/run_agent/`, `src/core/spark_state.py`,
  `src/spark_cli/web_server.py`, and `src/spark_cli/web/src/lib/`.
  **Done when:** one replay produces a machine-readable JSON report without
  enabling verbose logs or changing model behavior.

- [x] **BASE-04 - Capture the pre-change baseline.** Run at least three trials
  per fixture with pinned model/provider/reasoning settings, preserve raw
  counters, and publish median plus p95 values.
  **Depends on:** `BASE-01` through `BASE-03`.
  **Done when:** future results can be compared without changing cases, models,
  prompts, or judging rules.
  **Evidence for BASE-01 through BASE-04:** seven versioned redacted workloads,
  three trials, raw rows, median/p95 reports, provider-versus-estimator token
  buckets, and runtime/DB/SSE/HTTP/React/recovery JSON counters are committed.

## Improvement 1: Compact, Stable, Task-Scoped Tool Surface

**Priority:** P0. **Primary gain:** input tokens and tool-selection accuracy.
**Risk:** medium. **Depends on:** `BASE-04`.

The default `spark-cli` surface sends roughly 8,804 schema tokens on every
iteration. Spark already proves that related actions can live behind one schema
with `cronjob`; the same approach can collapse verbose families while keeping
the model-visible surface byte-stable for prompt caching.

### Implementation

- [x] **EFF-01-P1 - Compact the two highest-cost default schemas.** Reduce the
  model-visible `delegate_task` and `execute_code` descriptions without
  changing tool names, parameters, limits, helper guidance, or web result
  envelopes.
  **Evidence:** compact JSON fell from 6,665 to 3,887 characters, saving about
  695 estimated input tokens per model request.

- [x] **EFF-01-01 - Define the stable facade contract.** Group related actions
  into compact facades such as `files`, `skills`, `preview`, `canvas`, and
  `web`, each with an `action` discriminator and action-specific validation.
  Keep `terminal`, `todo`, `memory`, `clarify`, and delegation separate where
  distinct names improve safe selection.
  **Files:** `src/core/toolsets.py`, `src/tools/registry.py`, and a new
  `src/tools/facades/` package.

- [x] **EFF-01-02 - Generate compact schemas from typed action definitions.** Do
  not hand-maintain duplicated descriptions, enums, and examples. Share the
  definitions with runtime validation and web/API documentation.
  **Files:** `src/tools/registry.py`, new facade schema helpers, and focused
  registry tests.

- [x] **EFF-01-03 - Keep legacy handlers internally addressable.** Map facade
  actions to existing handlers so integrations and old transcripts remain
  loadable. Do not expose both facade and legacy schemas to a new model request.
  **Files:** `src/core/model_tools.py`, `src/tools/normalize.py`, and facade
  dispatchers.

- [x] **EFF-01-04 - Select profiles only at session creation.** Resolve the
  platform/toolset profile before the first model call and freeze the resulting
  ordered schema list for the full context epoch. Replace the current
  post-`browser_open` schema swap with a stable browser facade.
  **Files:** `src/core/run_agent/prompt_cache.py`,
  `src/core/run_agent/__init__.py`, `src/tools/browser_tool.py`, and session DB
  metadata.

- [x] **EFF-01-05 - Add schema fingerprints.** Store an ordered schema hash with
  the session and reject accidental mid-epoch changes in development/tests.
  **Files:** `src/core/run_agent/`, `src/core/spark_state.py`, and caching golden
  tests.

### Verification

- [x] **EFF-01-PV1 - Lock schema size and execution contracts.** Focused tests
  enforce serialized size ceilings, required delegation guidance, sandbox
  limits/helpers, enabled-tool filtering, and the `web_search`/`web_extract`
  return envelopes.

- [x] **EFF-01-V1 - Meet the schema budget.** The default profile is at most
  18,000 serialized characters or 4,500 estimated tokens, with no lost action.
- [x] **EFF-01-V2 - Run tool-selection evals.** Compare facade versus current
  schemas on every tool family, ambiguous requests, invalid arguments, and
  multi-action batches. Success requires equal or better correct-tool rate.
- [x] **EFF-01-V3 - Prove cache stability.** The schema fingerprint remains
  identical across turns, browser activation, skill use, reconnect, and resume.
- [x] **EFF-01-V4 - Exercise compatibility.** Old tool names in saved sessions,
  skills, and API callers normalize to the new action contract without exposing
  duplicate model schemas.

**Evidence for EFF-01-01 through EFF-01-V4:** typed facades preserve every
legacy action behind deterministic validation and compatibility normalization;
the frozen session schema fingerprint remains stable across resume and browser
activation. The default surface fell from 32,435 to 14,076 serialized
characters (56.6%) while granular API toolsets retain legacy names.

**Rollback boundary:** keep the profile flag able to restore legacy schemas at
new-session creation. Never change an already-running context epoch.

## Improvement 2: Segmented Cross-Session Prompt Caching

**Priority:** P0. **Primary gain:** uncached input cost and first-token latency.
**Risk:** high because prompt ordering is correctness-sensitive.
**Depends on:** `EFF-01-05`.

Spark caches one assembled system string per session, but the string includes
memory, goal state, project context, timestamp, model/provider metadata, and
platform guidance. A new session therefore misses large reusable prefixes.
Separate immutable Spark guidance from project/profile and session metadata so
providers can cache the longest stable prefixes across sessions while keeping
the complete effective instruction set.

### Implementation

- [x] **EFF-02-01 - Replace string concatenation with typed prompt blocks.** Each
  block records `kind`, content hash, stability scope (`release`, `profile`,
  `project`, `session`, or `turn`), token estimate, and required ordering.
  **Files:** `src/core/run_agent/prompt_cache.py` and
  `src/agent/prompt_builder.py`.

- [x] **EFF-02-02 - Create three immutable cache segments.** Use a release-level
  Spark identity/behavior prefix, a profile/project context prefix, and a
  session-specific suffix. Move timestamp and diagnostic identity to the suffix
  or API metadata without removing them from behavior that depends on them.

- [x] **EFF-02-03 - Add provider-specific cache adapters.** Map the same block
  contract to Anthropic content breakpoints, OpenAI prompt-cache keys, and
  cache-stable chat-completion ordering. Fall back to one ordinary system
  message where segmentation is unsupported.
  **Files:** `src/agent/prompt_caching.py`, provider adapters in
  `src/core/run_agent/`, and `src/agent/anthropic_adapter.py`.

- [x] **EFF-02-04 - Add a prompt lint pass.** Detect duplicated guidance,
  unstable timestamps in stable segments, unordered tool descriptions, and
  accidentally repeated context files. Report rather than silently remove
  user-authored instructions.

- [x] **EFF-02-05 - Persist segment fingerprints.** Store hashes and source
  provenance with the session so resume can reproduce the original prompt and
  compression can start a deliberate new context epoch.

### Verification

- [x] **EFF-02-V1 - Extend caching golden tests.** Assert exact block order,
  hashes, provider payload shape, resume behavior, compression invalidation,
  and no mutation within an epoch.
- [x] **EFF-02-V2 - Measure cache reuse.** Two new sessions in the same project
  must reuse the release/project prefix; changing `AGENTS.md` must invalidate
  only the project segment; changing a turn-only hook must not invalidate either.
- [x] **EFF-02-V3 - Meet the uncached-token target.** Reduce uncached input
  tokens by at least 30% on the 20-turn fixture, reporting cache writes and reads
  separately so a larger cache write cannot masquerade as a saving.
- [x] **EFF-02-V4 - Run instruction-adherence evals.** Project rules, profile
  memory, current goal, platform formatting, and user system messages must match
  baseline behavior.

**Evidence for EFF-02-01 through EFF-02-V4:** immutable hashed release,
profile/project, session, and turn blocks pass exact-order, invalidation,
provider-payload, provenance, resume, and instruction-preservation tests. The
pinned 20-turn replay reduced uncached input from 90,000 to 14,000 tokens
(84.4%) without removing applicable guidance.

**Rollback boundary:** provider adapters can fall back to the current single
cached system string without changing prompt content.

## Improvement 3: Typed Context Ledger and Incremental Compaction

**Priority:** P1. **Primary gain:** long-session tokens, compaction latency, and
handoff fidelity. **Risk:** high. **Depends on:** `EFF-04-05`, `EFF-02-05`.

The current compressor prunes old tool text and asks a model to summarize a
middle slice. Repeated compression rewrites a narrative summary and can lose
precise state. Introduce a typed ledger for durable task state, then reserve LLM
summarization for genuinely narrative information.

### Implementation

- [x] **EFF-03-01 - Define a versioned context checkpoint.** Include objective,
  constraints, decisions, completed work, unresolved questions, current plan,
  touched files, commands/tests with outcomes, external artifact handles, and
  the last included message/event sequence.
  **Files:** new `src/agent/context_checkpoint.py`, `src/core/spark_state.py`,
  and schema migration.

- [x] **EFF-03-02 - Capture deterministic state first.** Build checkpoint fields
  from todo/goal stores, tool-call metadata, file/result artifacts, and session
  events without an LLM call. Do not infer success from a tool name alone.

- [x] **EFF-03-03 - Summarize only the narrative delta.** Feed the summarizer
  messages not already represented by typed fields and update the prior
  narrative section incrementally. Preserve exact paths, identifiers, commands,
  errors, and explicit user wording as structured data.

- [x] **EFF-03-04 - Separate recent history from durable state.** Assemble model
  context as stable prompt, compact checkpoint, bounded recent turns, and
  referenced artifacts. Eliminate synthetic todo snapshots masquerading as user
  messages.

- [x] **EFF-03-05 - Shadow the new compressor.** Generate old and new checkpoints
  on fixtures, but use only the old result until automated and human review
  shows equivalent continuation quality.

- [x] **EFF-03-06 - Keep one logical task identity.** Record context epochs and
  checkpoint sequence without forcing the UI to follow a newly created session
  ID every time context is compressed.

### Verification

- [x] **EFF-03-V1 - Add loss tests.** Verify exact preservation of user
  constraints, approved targets, pending blockers, file paths, failed tests,
  tool IDs, and incomplete work across three compactions.
- [x] **EFF-03-V2 - Replay long tasks.** Continue a 100-turn code task from old
  and new compacted contexts using the same model and blind-score completion,
  rework, hallucination, and repeated-tool counts.
- [x] **EFF-03-V3 - Meet the context target.** After compaction, fixed checkpoint
  plus recent tail is at most 20% of the model context window unless one current
  user/tool item alone exceeds the budget.
- [x] **EFF-03-V4 - Fail safely.** If narrative summarization fails, retain typed
  state plus recent turns and mark the missing narrative explicitly. Never drop
  the middle silently.

**Evidence for EFF-03-01 through EFF-03-V4:** a versioned deterministic ledger,
narrative-only delta summary, bounded recent tail, shadow/legacy mode, DB-backed
context epochs, and crash-safe checkpoints pass long-task and resume tests. The
100-turn fixture fell from 76,035 to 16,085 tokens while retaining the latest
20 messages and all typed task state.

**Rollback boundary:** keep the existing `ContextCompressor` selectable per
new session until checkpoint migration and replay gates pass.

## Improvement 4: Adaptive Tool-Result Budgets and Artifact Handles

**Priority:** P0. **Primary gain:** context tokens and fewer emergency
compactions. **Risk:** medium. **Depends on:** `BASE-04`.

Spark can currently admit 200,000 characters from one tool batch, while
`read_file` bypasses result persistence to avoid a read-persist-read loop.
Replace character-only truncation with token-aware paging and durable artifact
handles so the model sees a compact index and requests only relevant slices.

### Implementation

- [x] **EFF-04-P1 - Add recoverable token soft limits.** Apply conservative
  UTF-8 token estimates of 12,000 tokens per result and 24,000 per tool batch
  only when durable environment storage is available. Preserve the complete
  original result if a token-only spill cannot be stored.

- [x] **EFF-04-P2 - Add safe artifact identity and same-turn deduplication.**
  Record SHA-256 content identity and origin metadata in persisted previews,
  collapse repeated persisted content to the first artifact reference, and
  pass aligned tool names internally so pinned `read_file` pages cannot enter
  a persist-read loop.

- [x] **EFF-04-01 - Make every large-producing tool pageable.** Standardize
  `offset`, `limit`, `next_cursor`, `total_size`, `content_hash`, and truncation
  metadata for file reads, searches, terminal output, browser snapshots, web
  extraction, session search, and connector responses.
  **Files:** `src/tools/file_tools.py`, `terminal_tool.py`, browser/web/session
  tools, and shared result models.
  **Evidence:** oversized results from every tool family use one opaque artifact
  contract with bounded paging/search and complete cursor/hash metadata.

- [x] **EFF-04-02 - Add profile/model-aware token budgets.** Allocate a maximum
  tool-result share from remaining context, current task phase, result type, and
  provider tokenizer. Keep conservative hard ceilings for estimator-only paths.
  **Files:** `src/tools/budget_config.py`, `tool_result_storage.py`, and agent
  request accounting.
  **Evidence:** remaining model context, task phase, result kind, and an optional
  provider token counter now derive safe request-specific shares.

- [x] **EFF-04-03 - Replace path-only spillover with artifact records.** Store
  content hash, MIME/type, origin tool, expiry, size, backend locator, and safe
  slice/search operations. The model receives a short preview plus opaque handle,
  not a transport-specific `/tmp` assumption.
  **Evidence:** task-scoped records expose only `artifact://` handles while hash,
  MIME, origin, expiry, size, and backend locator remain recoverable internally.

- [x] **EFF-04-04 - Add semantic previews.** Preserve headings, matching lines,
  errors, exits, and tail summaries instead of always returning the first 1,500
  characters. Keep raw bytes retrievable through bounded pages.
  **Evidence:** previews retain head context, headings/errors/failures/exits and
  tail state; bounded pages reconstruct the exact original.

- [x] **EFF-04-05 - Deduplicate repeated results.** When an unchanged file,
  status response, or tool output is requested again in one context epoch,
  return its prior artifact handle and a compact unchanged marker.
  **Evidence:** task-epoch content identity reuses the first handle and backend
  write across separate results and turns.

### Verification

- [x] **EFF-04-PV1 - Cover token-density and recovery edges.** Tests cover ASCII,
  CJK, lone-surrogate estimation, storage failure, token-budget opt-out,
  duplicate artifacts, aligned-name mismatch safety, and pinned `read_file`
  behavior. A four-result fixture reduced estimated inline tokens from 56,000
  to 14,759, a 73.6% reduction.

- [x] **EFF-04-V1 - Fuzz pagination.** Reassemble Unicode, binary metadata,
  long-line, empty, remote, and concurrent outputs byte-for-byte from pages.
  **Evidence:** concurrent page tests cover Unicode, binary metadata, empty and
  long-line results, private remote locators, searches, expiry, and exact replay.
- [x] **EFF-04-V2 - Prevent loops.** A model can page an artifact repeatedly
  without each page being re-persisted or losing its cursor.
  **Evidence:** `artifact_read` is pinned and repeated cursors advance without
  another persistence pass.
- [x] **EFF-04-V3 - Meet payload budgets.** p95 inline tool-result tokens are at
  least 60% lower on large-output fixtures and no batch exceeds its computed
  share without an explicit user-approved override.
  **Evidence:** the 100-result fixture retains at most 40% of baseline p95 inline
  payload, while adaptive ceilings prevent an unapproved over-share.
- [x] **EFF-04-V4 - Preserve task success.** Code search, debugging, log review,
  and large-file edits complete with no increase in missed evidence or total
  tool iterations.
  **Evidence:** semantic/search fixtures retain matching errors, headings, tail
  state, offsets, and full recovery; pinned large-file reads keep edit flows direct.

**Rollback boundary:** each tool can return its current JSON/string result when
the caller does not support artifact metadata.

## Improvement 5: Zero-Delay Dependency-Aware Tool Scheduler

**Priority:** P0. **Primary gain:** tool-loop wall time. **Risk:** medium.
**Depends on:** `BASE-04`.

Sequential batches sleep one second between tools even when neither tool nor
provider requires pacing. Existing parallelism handles a safe subset, but a
resource/effect graph can safely schedule more work and serialize only real
conflicts.

### Implementation

- [x] **EFF-05-01 - Change the default artificial delay to zero.** Remove
  `tool_delay=1.0` from the generic agent path. Introduce explicit per-tool or
  per-service rate limiters only where measured external limits require them.
  **Files:** `src/core/run_agent/__init__.py`, config migration, and tool metadata.
  **Pilot evidence:** the default is now zero, explicit nonzero pacing remains
  supported, and focused plus full `tests/run_agent/` verification passed.

- [x] **EFF-05-02 - Declare tool effects.** Registry metadata must state
  read/write/network/process/user-interaction effects, resource keys, ordering
  requirements, and concurrency caps.
  **Files:** `src/tools/registry.py` and each registered tool family.

- [x] **EFF-05-03 - Build a conflict DAG per assistant batch.** Run nodes when
  dependencies are satisfied; allow independent paths/services in parallel;
  preserve assistant tool-call order when appending model-visible results.
  **Files:** `src/core/run_agent/parallelism.py` and extracted scheduler module.

- [x] **EFF-05-04 - Add cooperative cancellation and deadlines.** Interrupt
  queued work immediately, propagate deadlines to running tools, and emit a
  result for every skipped/cancelled tool-call ID.

- [x] **EFF-05-05 - Move display callbacks off the scheduling critical path.**
  Batch/debounce progress events while preserving start/complete ordering and
  exact final results.

### Verification

- [x] **EFF-05-PV1 - Verify default and explicit pacing.** Two zero-work calls
  fell from 1.0067 seconds to 0.0002 seconds median. Tests prove the default
  performs no sleep, explicit nonzero pacing still sleeps exactly once between
  calls, tool-result order is stable, and provider-facing tool messages keep
  their standard shape.

- [x] **EFF-05-V1 - Run conflict-table tests.** Cover independent reads,
  overlapping writes, terminal mutations, browser session state, memory/todo
  writes, clarification, remote rate limits, and mixed batches.
- [x] **EFF-05-V2 - Meet the latency target.** Four independent 500 ms tools
  complete in under 1.2 seconds median; four conflicting tools remain ordered
  with no extra one-second sleeps.
- [x] **EFF-05-V3 - Stress cancellation.** No orphan process, missing tool
  result, locked DB transaction, or callback-after-close occurs across 1,000
  randomized batches.
- [x] **EFF-05-V4 - Verify deterministic transcripts.** Replaying identical
  completed results produces the same model-visible message order regardless of
  execution completion order.

**Evidence for EFF-05-02 through EFF-05-V4:** complete effect/resource metadata
drives a deterministic conflict DAG with service caps, cooperative deadlines,
cancellation results for every call ID, and ordered non-blocking progress. One
thousand randomized batches completed without leaks; four independent 500 ms
tools measured 0.5091 s median and 0.5113 s p95 while conflicting calls stayed
ordered.

**Rollback boundary:** a config flag can force the current conservative
sequential executor for a new run.

## Improvement 6: Shared Async Runtime and Pooled Transports

**Priority:** P1. **Primary gain:** network latency, CPU, sockets, and memory.
**Risk:** high. **Depends on:** `EFF-05-04`.

Spark has several local bridges that create event loops or one-worker thread
pools around `asyncio.run`, plus many one-shot `requests` and `httpx` calls.
Create one owned async runtime per process and reuse bounded clients so DNS,
TLS, HTTP/2, SDK pools, and cancellation work consistently.

### Implementation

- [x] **EFF-06-01 - Inventory blocking and loop-owning call sites.** Classify
  each `asyncio.run`, `new_event_loop`, `ThreadPoolExecutor(max_workers=1)`,
  `requests.*`, one-shot `httpx.*`, and blocking sleep by process and thread.
  **Files:** audit artifact under `docs/performance/`.

- [x] **EFF-06-02 - Introduce a process runtime service.** Own the event loop,
  task group, DNS/TLS-aware `httpx.AsyncClient` pools, SDK clients, connection
  limits, and shutdown order. Do not let individual tools close shared clients.
  **Files:** new `src/core/async_runtime.py` and provider/tool adapters.

- [x] **EFF-06-03 - Migrate hot network tools first.** Move web, MCP, skills Hub,
  Home Assistant, connectors, vision/image jobs, and session search to the
  runtime while preserving synchronous handler compatibility at the registry
  boundary.

- [x] **EFF-06-04 - Make gateway handlers non-blocking.** Run unavoidable
  filesystem/subprocess work in bounded worker pools and remove blocking sleeps
  from the gateway event loop.
  **Files:** `src/gateway/run.py`, `src/spark_cli/web_server.py`, and tool
  environment adapters.

- [x] **EFF-06-05 - Add lifecycle telemetry.** Count active/idle connections,
  pool waits, created loops, worker queue depth, open file descriptors, and
  shutdown leaks.

### Verification

- [x] **EFF-06-V1 - Assert one runtime.** Hot paths create no per-call event
  loops and no one-worker executor merely to run one coroutine.
- [x] **EFF-06-V2 - Load test network tools.** Compare 100 sequential and 20
  concurrent requests for latency, CPU, RSS, connections, retries, and failures.
- [x] **EFF-06-V3 - Exercise interrupts/restarts.** Cancel active streams, swap
  credentials, restart the gateway, and close Spark without event-loop-bound
  client errors or leaked sockets.
- [x] **EFF-06-V4 - Preserve provider isolation.** Different credentials,
  profiles, base URLs, proxies, and TLS policies never share an unsafe client.

**Evidence for EFF-06-01 through EFF-06-V4:** the checked-in inventory maps all
loop, blocking, and one-shot transport sites. One process-owned loop, bounded
workers, and credential/profile/base/proxy/TLS-keyed pools now serve migrated
MCP, Home Assistant, model, gateway, and web paths. Load tests measured 20.59x
normalized concurrency, one loop/client per safe key, and zero shutdown leaks.

**Rollback boundary:** unmigrated tools retain the existing sync bridge while
each family moves independently.

## Improvement 7: Append-Only Session Events and Settled Snapshots

**Priority:** P0. **Primary gain:** disk I/O, DB contention, resume speed, and
state correctness. **Risk:** high. **Depends on:** `BASE-04`.

SQLite already stores messages append-only, but every append is a separate
transaction and `_save_session_log` rewrites the complete JSON document. Follow
T3 Code's server-authoritative event/projection pattern selectively: append
ordered events in batches, update projections transactionally, and materialize
large snapshots only when a turn settles or an export is requested.

### Implementation

- [x] **EFF-07-01 - Define ordered session events.** Cover user/assistant/tool
  messages, stream checkpoints, usage, status transitions, compression epochs,
  title/source changes, interrupts, and session end. Every event has a monotonic
  sequence and idempotency key.
  **Files:** `src/core/spark_state.py` or a new `src/core/session_events.py`.

- [x] **EFF-07-02 - Batch one agent iteration per transaction.** Append the
  assistant message, all tool results, counter changes, and event projection in
  one WAL transaction instead of one `BEGIN IMMEDIATE` per message.

- [x] **EFF-07-03 - Make projections authoritative for reads.** Maintain session
  shell rows and message/detail rows transactionally from committed events.
  Publish to subscribers only after commit.

- [x] **EFF-07-04 - Replace hot-path full JSON rewrites.** Write a small
  crash-recovery journal or rely on committed SQLite events during active work.
  Produce the existing full JSON format only on settle, close, explicit export,
  or bounded debounce.

- [x] **EFF-07-05 - Add checkpoint snapshots.** Periodically snapshot projection
  state with its event sequence so startup/replay does not scan an unbounded log.

- [x] **EFF-07-06 - Migrate without breaking old sessions.** Read current SQLite
  and JSON records, backfill event sequence/projection state, and keep export
  format compatibility. Migration is restart-safe and idempotent.
  **Evidence for EFF-07-01 through EFF-07-06:** schema v10 adds monotonic,
  idempotent events and versioned checkpoints; one iteration commits messages,
  usage, status, counters and projections once, publishes after commit, lazily
  backfills legacy rows, and materializes full JSON only for settled turns.

### Verification

- [x] **EFF-07-V1 - Crash at every boundary.** Kill the process before append,
  during transaction, after commit/before publish, during snapshot, and during
  migration. Resume must produce one consistent transcript with no duplicates.
- [x] **EFF-07-V2 - Meet the I/O target.** A 100-turn fixture writes at least 50%
  fewer bytes and performs at least 50% fewer write transactions than baseline.
- [x] **EFF-07-V3 - Stress contention.** Run gateway, CLI, web, and subagent
  writers together with no message loss, deterministic order, or UI-visible
  uncommitted state.
- [x] **EFF-07-V4 - Verify export equivalence.** Materialized JSON contains the
  same user-visible messages, tool calls/results, reasoning metadata, and usage
  as the old format.
  **Evidence for EFF-07-V1 through EFF-07-V4:** rollback tests cover mid-batch,
  checkpoint, post-commit publication, and restartable migration boundaries;
  100 messages use one write transaction and over 50% fewer encoded bytes than
  repeated snapshots; 20 concurrent writers stay ordered; exports are equivalent.

**Rollback boundary:** dual-read old/new storage during migration; never delete
old JSON logs as part of this work.

## Improvement 8: Sequence-Resumable Web State and Granular Subscriptions

**Priority:** P1. **Primary gain:** server load, network payload, frontend CPU,
and reconnect speed. **Risk:** high. **Depends on:** `EFF-07-03`.

Spark already has SSE patches and recovery logic, but it also reconciles session
pages after events, polls three status endpoints every eight seconds, and checks
chat recovery every two seconds. Adopt T3 Code's snapshot-plus-delta contract and
shell/detail split so clients subscribe only to mounted data and resume from a
known sequence.

### Implementation

- [x] **EFF-08-01 - Version one typed event envelope.** Include topic, entity ID,
  committed sequence, projection version, timestamp, and minimal patch payload.
  Generate matching Python and TypeScript contracts or validate from one schema.

- [x] **EFF-08-02 - Split shell and detail projections.** Sidebar session shells
  contain title/project/source/activity/status/counts only. The selected chat
  subscribes separately to messages, reasoning, tools, plans, and subagents.

- [x] **EFF-08-03 - Add snapshot plus `after_sequence` resume.** On first load,
  fetch a bounded snapshot. On reconnect, request only committed deltas after
  the cached sequence; return a new snapshot only when retention has expired or
  the projection version changed.

- [x] **EFF-08-04 - Centralize connection supervision.** One authenticated
  connection owns retry/backoff, visibility/wakeup resubscribe, health probes,
  and offline state. Components consume state and never create transports or
  independent retry loops.

- [x] **EFF-08-05 - Normalize client state.** Store entity maps keyed by ID and
  expose referentially stable selectors for shell, messages, status, usage, and
  project groups. Apply idle TTL to unmounted thread detail.

- [x] **EFF-08-06 - Persist only settled detail.** Debounce cached thread writes
  and skip serialization of rapidly changing active tool payloads until the turn
  settles, while the server remains authoritative.

- [x] **EFF-08-07 - Retire healthy-state polling.** Replace the eight-second
  status/model/cron group and normal two-second recovery loop with events. Keep
  a bounded watchdog probe only after the stream is stale or the app wakes.

### Verification

- [x] **EFF-08-V1 - Run lifecycle acceptance.** Cover long conversations,
  multiple chats, switching during generation, refresh, disconnect, app wake,
  gateway restart, stale browser cache, compression epoch, and deletion.
- [x] **EFF-08-V2 - Prove sequence correctness.** Duplicate, reordered, missing,
  retained-out, and version-mismatched events converge to the authoritative
  snapshot without duplicate messages or stuck Working state.
- [x] **EFF-08-V3 - Meet steady-state targets.** With a healthy stream there are
  zero periodic status/session HTTP calls, unchanged entities do not rerender,
  and an unselected long chat body is not resident indefinitely.
- [x] **EFF-08-V4 - Record browser evidence.** Test 390, 820, and 1440 px with
  exact flows, screenshots, React commit/network traces, and no console errors.

**Evidence for EFF-08-01 through EFF-08-V3:** mirrored validated Python/TypeScript
v1 envelopes drive bounded shell/detail snapshots and retained ordered delta
resume through one supervisor. Normalized stable selectors, 120-second detail
TTL, settled-only cache writes, and stale-only watchdog recovery remove healthy
8-second and 2-second polling. Sequence, restart, retention, 5,000-message TTL,
cache-crash, and 10,000-event tests passed; a 50-event resume stayed below 25 KB.
**Evidence for EFF-08-V4:** `docs/performance/browser-efficiency.md` records the
provider-free production-pipeline flow, 390/820/1440 screenshots, React commit
counts, 177 traced API responses, zero application console/page/HTTP errors,
zero forbidden calls in the settled 12-second window, cold reload hydration,
simultaneous switching, and recovery across a changed backend instance.

**Rollback boundary:** keep the existing SSE envelope and recovery endpoints
available for one compatibility release while new clients negotiate the
projection version.

## Improvement 9: Lazy Startup and Optional Dependency Boundaries

**Priority:** P1. **Primary gain:** cold start, memory, packaging, and test
collection. **Risk:** medium. **Depends on:** `BASE-04`.

Importing `core.run_agent` currently takes roughly 0.75 seconds in this checkout.
`core.model_tools` eagerly imports all tool modules, pulling in SDKs such as MCP,
Firecrawl, OpenAI types, aiohttp, and cron even when the selected profile never
uses them.

### Implementation

- [x] **EFF-09-P1 - Defer optional MCP imports for unconfigured profiles.**
  Inspect raw profile configuration before importing the MCP SDK. Profiles with
  an `mcp_servers` mapping keep the existing eager discovery path, while
  unconfigured profiles avoid loading the optional SDK and its dependencies.

- [x] **EFF-09-01 - Split schema metadata from handlers.** Keep a lightweight,
  declarative manifest importable without optional SDKs. Resolve and import the
  handler module only on its first invocation.
  **Files:** `src/tools/registry.py`, `src/core/model_tools.py`, and generated or
  declarative tool manifests.

- [x] **EFF-09-02 - Generate/validate the manifest in development.** A build/test
  command imports every handler in isolation, compares registered names/schemas
  to the lightweight manifest, and fails on drift or missing optional guards.

- [x] **EFF-09-03 - Lazy-load provider and feature modules.** Move model catalogs,
  voice, browser, MCP, messaging platforms, cron, image/video SDKs, and desktop
  helpers behind their route/tool/command boundaries.

- [x] **EFF-09-04 - Split the run-agent hot path by responsibility.** Extract
  provider payload adapters, response normalization, retry policy, persistence,
  and turn orchestration without changing `core.run_agent.AIAgent`.
  **Files:** modules under `src/core/run_agent/` plus ADR/caching golden updates.

- [x] **EFF-09-05 - Audit packaged resources.** Ensure frozen sidecar internals,
  caches, generated bundles, and optional ML dependencies are excluded from
  source discovery and included in desktop artifacts only when required.

### Verification

- [x] **EFF-09-PV1 - Benchmark and test the lazy MCP boundary.** Seven fresh
  `core.run_agent` processes improved from 0.5959 to 0.4849 seconds median,
  imported 205 fewer modules, and used about 13.9 MiB less RSS. Fresh-process
  tests cover both configured and unconfigured profiles, and MCP/model-tool/ACP
  regression suites preserve discovery behavior.

- [x] **EFF-09-V1 - Import budget.** Measure five fresh processes and meet a
  median `import core.run_agent` target of 0.45 seconds, stretch goal 0.35, on
  the same host while reporting RSS and imported module count.
- [x] **EFF-09-V2 - Minimal install test.** Core CLI help, doctor, and a no-tool
  chat import without browser, MCP, voice, messaging, or ML extras installed.
- [x] **EFF-09-V3 - First-use tests.** Each lazy feature loads once, reports a
  precise missing-extra error, and remains safe under concurrent first calls.
- [ ] **EFF-09-V4 - Package comparison.** Record macOS app, Windows installer,
  sidecar size, startup time, and feature smoke results before and after.

**Evidence for EFF-09-01 through EFF-09-V3:** a generated 70-tool manifest was
validated against 28 isolated handler modules and four blocked optional-SDK
guards. Fourteen lazy-manifest, minimal-install, and responsibility tests passed;
concurrent first use imported its handler exactly once and missing dependencies
named the required extra. Focused Ruff passed. Five fresh processes improved
from 0.5012 s median, 1,428 modules, and 91,504 KiB RSS to 0.1055 s, 415 modules,
and 43,024 KiB: 79.0% lower median latency, 70.9% fewer modules, and 53.0% lower
RSS. Raw trials are in `docs/performance/lazy-startup-benchmark.json`. ADR 0012
records stable `core.run_agent.AIAgent`, cache, and rollback contracts. The
desktop resource audit is enforced by both platform builds and excludes caches
and optional ML runtimes while PyInstaller collects lazy first-party modules.

**Rollback boundary:** keep eager manifest validation in CI even though runtime
imports become lazy.

## Improvement 10: Task-Aware Response, Reasoning, and Model Budgets

**Priority:** P0. **Primary gain:** output tokens, reasoning cost, user steering,
and time to useful answer. **Risk:** medium. **Depends on:** `BASE-04`,
`EFF-01-04`.

Spark's current smart router is opt-in and mainly classifies by message length,
line count, URLs, backticks, and keywords. Build a deterministic request envelope
that selects response shape, output budget, reasoning effort, model tier, and
the already-frozen tool profile. Use the `i-have-adhd` reference as an evaluated
concision model, not as a hard global short-answer rule.

### Implementation

- [x] **EFF-10-01 - Define request classes and risk gates.** At minimum support
  direct answer, status/progress, action/change, diagnosis, explanation,
  comparison/options, plan/review, destructive/high-stakes, and explicit
  user-format contracts. Classification must be local and deterministic so it
  does not add an LLM call.
  **Files:** replace/extend `src/agent/smart_model_routing.py` and add tests.

- [x] **EFF-10-02 - Create a response budget envelope.** Carry recommended
  verbosity, soft output-token range, reasoning effort, model tier, tool-needed
  flag, and required response elements. Explicit user requests for detail or
  exact formats override compact defaults.

- [x] **EFF-10-03 - Add an action-first compact style.** For direct/status/action
  requests, lead with the result or next action, keep steps atomic, suppress
  tangents/preambles/recaps, surface the current state, and end when the answer
  is complete. Safety confirmations, real ambiguity, and detailed explanations
  are explicit exceptions.
  **Files:** prompt blocks in `src/agent/prompt_builder.py` and user-facing config.

- [x] **EFF-10-04 - Route model and reasoning by capability, not length alone.**
  Use the fast model only when the request class, risk, tool need, attachments,
  context state, and provider capabilities allow it. Preserve the smart model
  for coding, ambiguous, high-stakes, long-context, or recovery work.

- [x] **EFF-10-05 - Apply soft output caps safely.** Set provider output limits
  from the envelope, allow the model to exceed the style target when needed,
  and continue a genuinely truncated answer. Never post-truncate a correct
  response or spend another model call merely to shorten it.

- [x] **EFF-10-06 - Build an isolated evaluation harness.** Adapt the reference
  repo's baseline/candidate structure: same cases, pinned models and reasoning,
  equal trials, resumable rows, cost caps, isolated user config, blinded
  condition labels, and exact version reporting.
  **Files:** new `evals/response_efficiency/` and runner tests.

### Verification

- [x] **EFF-10-V1 - Score quality, not length alone.** Judge correctness 35%,
  autonomy 25%, actionability 20%, safety 10%, and concision 10%. Candidate
  release requires zero blockers, correctness/safety within 0.1 of baseline,
  and a higher weighted score.
- [x] **EFF-10-V2 - Cover exceptions.** Include detailed walkthroughs,
  destructive actions, medical/legal/financial boundaries, real ambiguity,
  code-only output, casual messages, partial success, multi-step progress, and
  complex plans.
- [x] **EFF-10-V3 - Meet the token target.** Direct-answer and progress fixtures
  use at least 30% fewer median output tokens and need no more follow-up steering
  turns than baseline.
- [x] **EFF-10-V4 - Validate routing.** Log the non-sensitive routing reason and
  compare cost, latency, tool success, fallback frequency, and user-visible model
  label. No request silently loses a required capability.
  **Evidence for EFF-10-01 through EFF-10-V4:** the deterministic nine-class
  envelope, action-first prompt block, capability/risk router, safe soft caps,
  and blinded resumable harness pass 13 exception cases. Direct/progress median
  output fell 42.5 to 7 tokens (83.53%) with zero steering turns or blockers,
  correctness/safety 5.0, weighted score 4.9692 to 5.0, and 100% tool success.

**Rollback boundary:** response mode and adaptive routing are separately
configurable; explicit user verbosity always wins.

## Integrated Rollout Gates

- [x] **GATE-01 - Complete focused source checks.** Activate `.venv`, run Ruff on
  changed Python, mypy on affected typed packages, and focused pytest suites for
  prompt caching, tools, compaction, persistence, gateway, and web server.
  **Evidence:** 770 focused backend tests passed. Ruff E9/F found zero newly
  introduced critical errors across 74 changed files, full Ruff passed all 43
  new Python files, and scoped mypy passed all 20 new typed source modules.

- [x] **GATE-02 - Complete frontend checks.** Run full Vitest, focused ESLint,
  TypeScript build, production Vite build to temporary output, and the bundle
  budget before accepting generated `web_dist` changes.
  **Evidence:** 235 Vitest tests passed; full ESLint passed with zero errors and
  warnings; TypeScript/Vite production build passed; the initial entry graph is
  194.80 KiB gzip against the 600 KiB budget.

- [x] **GATE-03 - Replay the fixed efficiency suite.** Compare baseline and
  candidate with pinned versions and publish raw measurements, median, p95,
  cache accounting, correctness scores, and any regressions.
  **Evidence:** Five-trial deterministic fixture replay, response-quality
  scoring, cache/token accounting, DB/event telemetry, scheduler, browser, and
  startup/RSS results are published in `docs/performance/efficiency-replay.md`
  with raw candidate rows in `docs/performance/efficiency-candidate-v1.json`.

- [x] **GATE-04 - Run local browser acceptance.** Test multiple simultaneous
  chats, long history, active switching, large tool results, background/foreground,
  refresh, reconnect, gateway restart, responsive widths, and console/network
  traces against the source dashboard.
  **Evidence:** Playwright 1.62/Chromium 151 passed the exact flow at commit
  `27a94d5f`; all widths had no horizontal overflow, the steady-state forbidden
  call set was empty, and only the deliberately forced outage produced a
  transient preview-detector 500. Screenshots and trace summary are in
  `docs/performance/browser-efficiency.md`.

- [x] **GATE-05 - Run full practical regressions.** Execute
  `python -m pytest tests/ -m "not slow and not integration" -q`, then the full
  practical suite if no blocker appears. Document exact independently reproduced
  pre-existing failures rather than hiding them.
  **Evidence:** 12,068 tests passed and 151 skipped. The two failures were
  reproduced unchanged on detached `main`: a stale offline Codex catalog
  expectation and DNS safety rejecting `a.example`/`b.example` in a browser
  concurrency fixture.

- [ ] **GATE-06 - Validate the packaged macOS app.** Measure launch, first token,
  tools, reconnect, persistence, and web state in the actual signed/notarized
  `.app`/DMG, not only source mode.

- [ ] **GATE-07 - Validate the packaged Windows beta.** Repeat the same flows in
  the actual `Spark.exe` build, including native terminal/file/preview behavior
  and sleep/wake/reconnect.

- [x] **GATE-08 - Review generated output and release scope.** Rebuild
  `src/spark_cli/web_dist/` once after source acceptance, verify every manifest
  asset exists, inspect the diff, and exclude temporary clones, eval secrets,
  private fixtures, raw provider payloads, and unrelated worktree changes.
  **Evidence:** Node 22 produced 46 manifest entries; every manifest and
  `index.html` asset reference resolves. The release worktree contains only
  the version bump, generated bundle, PLAN evidence, and no supplied references.

## Recommended Delivery Order

1. **First release:** baseline telemetry, compact stable tool facades, adaptive
   result budgets, zero-delay scheduler, and task-aware response budgets. These
   have the clearest token/latency return with bounded compatibility layers.
2. **Second release:** segmented prompt caching, lazy imports, and pooled async
   transports. These need provider and packaged-platform evidence.
3. **Third release:** append-only session events and sequence-resumable web
   projections. Ship storage first, then negotiate the new client protocol.
4. **Final high-risk release:** typed context ledger and incremental compaction
   after shadow comparison proves it preserves long-task fidelity.

## Final Acceptance Checklist

- [ ] Exactly ten efficiency improvements have implementation and verification
  evidence attached to their task IDs.
- [ ] Fixed prompt/schema tokens, uncached tokens, cache reads/writes, tool-result
  tokens, output tokens, latency, DB I/O, event traffic, startup, RSS, and package
  size are all reported from the same versioned replay set.
- [ ] Token savings do not come from omitting applicable user/project rules,
  truncating necessary answers, hiding tool output, or routing beyond a model's
  capabilities.
- [ ] Runtime and UI state recover from interruption, refresh, reconnect,
  compression, gateway restart, and stale browser cache.
- [ ] Source tests, web acceptance, macOS package acceptance, and Windows package
  acceptance are reported as distinct results.
- [ ] Temporary reference clones and benchmark secrets are absent from the final
  repository and release artifacts.
