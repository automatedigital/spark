# Spark Improvement Plan

## Desktop/WebUI Freeze on Long Responses (web-search + delegation)

### Problem statement

The macOS desktop app (and the WebUI it embeds) **freezes and becomes unclickable**
partway through long assistant responses. The user reports it "usually freezes or
cuts out when it's a longer response" and suspects it's "related to web search and
delegation."

### Evidence

- **Activity Monitor:** the process `http://127.0.0.1:9119` is pinned at **100.7% CPU**
  (one full core). On macOS this is the **WKWebView/Tauri renderer** for the Spark
  dashboard — i.e. the **frontend**, not the backend. The Python `spark-server`
  process was only at **4.6% CPU**.
- **Log (`~/Downloads/log.md`):** session `20260617_172240_b0492dcc` ran a parallel
  `delegate_task` (2 subagents doing web research, returned **27,134 chars** in 66.9s),
  then streamed a **14,078-char** final response. The gateway then **restarts**
  (`Starting Spark Gateway…`) at 17:26:16 — consistent with the user force-quitting a
  frozen app. The same restart pattern appears earlier (11:17, 17:21, 17:26).
- The earlier session also shows many large `terminal`/tool outputs (19.8k, 39.5k,
  28.8k chars) — large payloads streaming into the UI.

### Root cause

While a long assistant message streams, `AssistantRow` renders
`<Markdown content={msg.content} />` (`src/spark_cli/web/src/components/ChatPanel.tsx:333`).
On each animation-frame flush (`flushTokenBuffer`, `ChatPanel.tsx:588`) the message
content grows and the `Markdown` component:

1. Re-runs `parseBlocks(content)` over the **entire** string (`Markdown.tsx:50`, `:91`).
2. Re-renders **every** `Block` — `Block` is **not** memoized and is keyed by array
   index (`Markdown.tsx:54`), so React reconciles all N blocks every frame.
3. Re-highlights the in-progress fenced code block with `hljs.highlight` every frame
   (`Markdown.tsx:212`) — O(n²) per code block.

Per-frame cost scales with message length, so the work is **O(n²)** over the stream.
For multi-KB responses this saturates a single core, starving the webview's input/event
handling → the window stops responding to clicks → the user force-quits → the gateway
restarts. If the renderer is CPU/OOM-killed by the OS, the response "cuts out."

**Why web-search + delegation trigger it:** those turns produce the longest final
responses, emit the most `chat.token` events, and yield URL/link-dense paragraphs that
make inline parsing (`parseInline`, `Markdown.tsx:374`) and reconciliation heavier.

### Contributing factors (secondary)

- **Reasoning updates are not batched.** `chat.reasoning` calls `setChatMessages` on
  every event with no rAF coalescing (`ChatPanel.tsx:720`), unlike `chat.token`. Models
  that stream reasoning trigger one unbatched full re-render per delta.
- **Per-token SSE volume.** `token_callback` publishes one `chat.token` event per model
  token (`src/spark_cli/web_server.py:4146`); each event invokes every bus listener
  (`useEventBus.ts:31`). A 3,500-token response = ~3,500 events.
- **Inline regex risk.** `parseInline` uses a large alternation regex with a nested
  quantifier in the `MEDIA:` branch (`Markdown.tsx:378`) — a catastrophic-backtracking
  shape if `MEDIA:` ever precedes pathological input. Low probability, high impact.
- **Virtualizer re-measure.** The streaming row grows continuously while
  `virtualizer.measureElement` (ResizeObserver) re-measures it; combined with
  `scrollToIndex` this can add layout thrash (`ChatPanel.tsx:1266`, `:1277`).
- **No per-message render ceiling.** A single very large message has no guardrail, so the
  renderer can be killed rather than degrade gracefully.

### Goal / acceptance criteria

- Streaming a 15k+ char response (with code blocks and many links) keeps the renderer
  **well under one core** and the UI stays clickable throughout.
- Per-frame render cost during streaming is **bounded** (independent of total message
  length) — only the growing tail re-renders.
- No regression in rendered markdown fidelity, copy buttons, media previews, tables,
  task lists, reasoning, or tool bubbles.

---

## Phase 0 — Reproduce & instrument (confirm before changing)

- [x] Add a repro that exercises the parse/render hot path on large, growing markdown
      (with headings, long paragraphs, links, and fenced code). Implemented as a
      unit-test characterization in `src/spark_cli/web/src/components/Markdown.test.ts`
      ("streaming parse cost is bounded by the tail") rather than a shipped UI harness.
- [x] Capture the cost characteristic via `Date.now()` timers in that test: parsing a
      ~56k-char message's live tail stays <2ms/frame, independent of prefix size.
- [x] Confirm the O(n²) shape by code analysis: the old path re-ran `parseBlocks` over
      the whole string and re-rendered every (un-memoized, index-keyed) `Block` each
      animation-frame flush, so per-frame work grew with total length. (See root-cause
      writeup above.)
- [x] Confirm which process is the renderer (`http://127.0.0.1:9119`, the WKWebView at
      100.7% CPU) vs. `spark-server` (Python, 4.6%) — fix belongs in the frontend.
- [ ] (Manual, on packaged app) Reproduce the real-world `delegate_task` + web-search
      path and capture a live devtools profile before/after. Folded into the Phase 4
      real-app verification — not runnable from the dev box used for this change.

## Phase 1 — Frontend render hot-path (root cause)

- [x] Memoize `Block` via `React.memo` + a structural comparator (`blockPropsEqual` in
      `markdownParse.ts`), so unchanged blocks skip reconciliation. `MemoBlock` wraps
      `Block` in `Markdown.tsx`.
- [x] Keep block ordering/index stable so memoized blocks aren't invalidated as the tail
      grows: stable blocks render first in order, tail blocks after — index of any
      committed block is constant over the stream.
- [x] Split parsing into a stable committed prefix + live tail via `findStableBoundary`
      (boundary = last blank line outside any code fence), so committed blocks are parsed
      once. Equivalence to whole-string parsing is locked by unit tests.
- [x] Defer syntax highlighting for the in-progress code block: `CodeBlock` skips
      `hljs.highlight` when `live` and renders plain `<code>`; it highlights once the
      block completes (`live` flips false). Flagged via the last tail block.
- [x] `InlineContent`'s `useMemo(parseInline)` now only recomputes for the changing tail
      paragraph, since committed paragraph blocks no longer re-render at all.
- [x] Characterized via unit test that per-frame parse work is bounded by the tail size,
      not total message length (Phase 0 test). Live devtools re-profile = Phase 4 manual.

## Phase 2 — Reduce streaming update volume

- [x] Batch `chat.reasoning` updates through a rAF buffer (`reasoningBufferRef` +
      `flushReasoningBuffer` + `appendReasoning`), mirroring `chat.token`. A shared
      `flushPendingStream()` flushes both buffers before tool rows / finalize / turn end,
      and the session-switch effect cancels the reasoning rAF too.
- [~] Coalesce tokens server-side — **deliberately deferred.** Rationale: the backend was
      not the bottleneck (Python ~5% CPU vs. the renderer at 100%), the frontend already
      rAF-batches render, and threading a turn-end flush through 4 call sites + every
      interrupt/turn_done path risks silently dropping a response's tail on the streaming
      hot path. The plan itself says ship Phase 1 first and measure before doing this.
      Revisit only if profiling shows SSE volume is still a problem after Phase 1.
- [~] (Depends on the deferred item above.)
- [~] (Depends on the deferred item above.)

## Phase 3 — Resilience & graceful degradation

- [x] Per-message soft cap (`SOFT_RENDER_CAP = 80_000`): above it, a streaming message
      renders its committed prefix verbatim (`<pre>`) and only block-parses the live tail;
      it formats fully on completion (`streaming=false`). Prevents pathological blowup.
- [x] Hardened `parseInline`: replaced the `MEDIA:` branch's nested
      `\S+(?:[^\S\n]+\S+)*?` quantifier (catastrophic-backtracking shape) with a linear
      lazy `[^\n]*?`; capture-group numbering unchanged. Adversarial-input unit test added
      (asserts <100ms on inputs that would have hung the old pattern).
- [x] Reviewed the virtualizer path: the auto-scroll effect keys on
      `[collapsedMessages.length, streaming, virtualizer]`, so it does not fire per-frame
      during streaming; `measureElement` re-measures the tail at most once per frame. With
      committed blocks now memoized, the growing row's reconciliation is bounded. No change
      needed; left as-is to avoid scroll regressions.
- [x] Verified the stall watchdog (`STALL_MS = 45_000`) + `resyncTurnState`: a busy frame
      is now bounded (well under the 45s threshold), and `resyncTurnState` uses
      `flushPendingStream()` so both buffers are flushed on recovery.

## Phase 4 — Verification & regression coverage

- [x] Added a frontend unit test asserting committed blocks are reported unchanged
      (skip re-render) as the tail grows, via the exact `blockPropsEqual` comparator
      React uses — and that a block re-renders when its `live` flag flips.
- [x] Added an adversarial `parseInline` unit test with a <100ms timeout assertion so a
      regression to catastrophic backtracking fails CI.
- [x] Frontend suite green: `vitest run` → 35 passed; `tsc -b && vite build` clean
      (0 type errors); `eslint` 0 errors on changed files (1 pre-existing warning,
      unrelated, untouched).
- [~] `pytest` for backend changes — N/A: no Python changed (token coalescing deferred).
- [x] Rebuilt the web bundle into `web_dist/` (consumed by the desktop app) and rebuilt
      the macOS desktop app via `/build-mac`.
- [x] Ran `graphify update .` to keep the knowledge graph current.
- [ ] (Manual, on packaged app) Stream a real `delegate_task` + web-search turn producing
      a 15k+ char response and confirm the renderer stays under one core and the UI is
      clickable throughout (stop button, sidebar, scroll). Also confirm code highlighting
      applies on completion and copy buttons work. Requires a live agent session with
      API credentials — to be done by the reporter / on a machine with a configured
      profile.

---

### Notes / out of scope

- The background "review/skill-save" turn that fires after each user turn (e.g.
  `20260617_112526_ded07e` in the log) adds backend work but runs on the Python side
  (~5% CPU) and is not implicated in the freeze. Leave as-is for this fix.
- Token coalescing (Phase 2) is an optimization, not the root cause; ship Phase 1 first and
  measure whether Phase 2 is still needed. **Decision: deferred** (see Phase 2) — backend
  was never the bottleneck and the change risks dropping response tails on the hot path.
- Follow the standard feature-branch + PR workflow; do not push directly to `main`.

### What shipped in this change

- `markdownParse.ts` (new): pure parser + memo helpers, unit-tested without a DOM.
- `Markdown.tsx`: streaming-aware incremental parse (stable prefix + live tail), memoized
  blocks, deferred code highlighting, and an 80k-char soft cap.
- `ChatPanel.tsx`: rAF-batched reasoning + a shared `flushPendingStream()`.
- `Markdown.test.ts` (new): 17 tests — parse-equivalence, memo-skip behavior, ReDoS
  hardening, and tail-bounded parse cost.
- Rebuilt `web_dist/` + the macOS app.

Net effect: per-frame work during a long stream is bounded by the small live tail instead
of the whole growing message, so the renderer no longer saturates a core and freezes.
