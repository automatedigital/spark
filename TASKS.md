# Tasks

## Chat Tab Performance & Token Efficiency

---

### 1. Verify and surface caching for Codex and OpenRouter providers

**Background:** Two separate caching paths already exist in `run_agent.py`:
- **Codex (OpenAI Responses API):** `prompt_cache_key = self.session_id` is set at line 6219 — OpenAI handles server-side KV caching automatically. No `cache_control` markers are needed.
- **OpenRouter + Claude models:** `_use_prompt_caching = True` when URL contains `openrouter` and model contains `claude` (line 795). `apply_anthropic_cache_control` injects breakpoints before each API call (line 8339–8340).

**Gaps to close:**
- OpenRouter + non-Claude models (DeepSeek, Qwen, etc.): `_use_prompt_caching` is `False` so the cache stats readback at line 8999 (gated on `_use_prompt_caching`) is skipped even though OpenRouter caches these server-side.
- Codex sessions never surface cache stats to the frontend: `input_tokens_details.cached_tokens` is not read from the Codex response and not included in the `chat.turn_done` payload.

- [x] In `run_agent.py` around line 8999, decouple cache stats readback from `_use_prompt_caching` for OpenRouter: if `_is_openrouter_url()` is true, always attempt to read `prompt_tokens_details.cached_tokens` from the response and log it.
- [x] In the Codex response path (`_normalize_codex_response` / usage parsing), read `input_tokens_details.cached_tokens` and store it alongside the other token counts.
- [x] Ensure the gateway's `turn_done` event emission includes `tokens.cache_read` for both Codex and OpenRouter non-Claude sessions so `SessionInfoBar` can display it.
- [ ] Manually test: send two turns on a Codex session and confirm `SessionInfoBar` shows a non-zero `cache_read` count on the second turn.

---

### 2. Move the post-turn `getSessionMessages` re-fetch to a smarter diff approach

**Background:** In `ChatPanel.tsx:733`, after every `chat.turn_done` event there is a `setTimeout(() => api.getSessionMessages(...), 500)` call that fetches the entire message list to sync `sessionIdx` values. For long sessions this fetches hundreds of messages when only the last few changed.

- [x] Change the post-`turn_done` re-fetch in `ChatPanel.tsx` to call `api.getSessionMessages(cur, 20)` (last 20 messages) instead of the full history.
- [x] Update the merge logic in `mergeSyncedMessages` (or replace the tail sync) so it only patches the tail of `chatMessages` with the returned slice rather than replacing the full list.
- [x] Verify in DevTools Network tab that the request after a turn is `?limit=20` and the payload is significantly smaller than a full session fetch.

---

### 3. Add `cache_write_tokens` to the `SessionInfoBar` display

**Background:** `run_agent.py` tracks `session_cache_read_tokens` and `session_cache_write_tokens` but only `cache_read` appears to be sent in `chat.turn_done`. `SessionInfoBar` has no write-token display.

- [x] Audit the gateway's `turn_done` event emission and confirm `tokens.cache_write` is included; add it if missing.
- [x] Update `SessionInfoBar.tsx` to display both cache read and cache write counts (e.g. `↗ 1,240 cached · ↘ 180 written`).
- [x] Optionally add a rough savings estimate: `cache_read_tokens × 0.9 × input_price_per_token`.
- [x] Confirm the info bar updates correctly after a multi-turn chat session.

---

### 4. Virtualise the message list for long conversations

**Background:** `ChatPanel.tsx:1173` renders all `chatMessages` as a flat `<div>` with no windowing. A 300-message session creates 300+ DOM nodes with heavy `<Markdown>` renders, causing layout thrash on every streaming token.

- [x] Add `@tanstack/react-virtual` to the web package if not already present.
- [x] Replace the flat message list in `ChatPanel.tsx` with a virtualised list using `useVirtualizer`, using dynamic item measurement so variable-height rows (tool bubbles, reasoning blocks) are handled correctly.
- [x] Ensure streaming append still works: the virtualiser should scroll to bottom on new items during streaming.
- [x] Ensure "Load earlier messages" (prepend) still works with the virtual list.
- [ ] Smoke test: open a session with 200+ messages and confirm scrolling is smooth and no messages are visually missing.

---

### 5. Debounce the `searchMatches` recompute during streaming

**Background:** `ChatPanel.tsx:996` — `searchMatches` is a `useMemo` depending on `[chatMessages, searchQuery]`. During streaming, `chatMessages` updates every animation frame. With the search bar open this triggers a full linear scan at ~60fps.

- [x] Replace the `useMemo` for `searchMatches` with a debounced state update (300 ms) that only recomputes when `chatMessages` has been stable or when `searchQuery` changes.
- [x] Confirm the `if (!q) return []` short-circuit still exits immediately when search is closed (no perf regression in the common case).
- [ ] Test: open search, start a streaming response, confirm no visible jank and the match count updates shortly after streaming completes.

---

### 6. Reduce tool result payload stored in chat state

**Background:** `ChatPanel.tsx:612` stores the full `data.result` string in React state on `chat.tool_end`. File reads and terminal output can be 10–100 KB, bloating every subsequent `setChatMessages` diff and inflating `localTurnCache`.

- [x] Add a `MAX_RESULT_DISPLAY = 8000` char constant. When storing tool result in state, truncate to this limit and set a `resultTruncated: boolean` flag on the message.
- [x] Update `ToolCallBubble` to show a "Show full output" affordance when `resultTruncated` is true (expand in place or link to a modal).
- [x] Confirm `localTurnCache` (line 117) no longer holds multi-KB tool results for typical file-reading sessions.

---

### 7. Consolidate context compression config in dashboard UI

**Background:** `run_agent.py` supports `agent.compression.enabled`, `threshold`, `target_ratio`, and `protect_last_n` in `config.yaml` (line ~1258). No dashboard UI exists for these. Users must edit YAML to change compression behaviour.

- [x] Add a "Context Management" card to `ConfigPage.tsx` with controls for `enabled` (toggle), `threshold` (slider 0.2–0.8), `target_ratio` (slider 0.1–0.5), and `protect_last_n` (number input).
- [x] Each control should include a short inline explanation of the token cost impact.
- [x] Wire the form to the existing `/api/config` PATCH endpoint so changes persist to `config.yaml`.
- [ ] Confirm changes take effect on the next agent turn (no server restart needed).

---

### 8. Add SSE reconnect jitter to prevent thundering herd on server restart

**Background:** `useEventBus.ts:32` uses `1000 * 2 ** reconnectAttempt` with no jitter. When the server restarts, all open tabs reconnect at exactly `t=1s` simultaneously.

- [x] In `useEventBus.ts`, modify `scheduleReconnect` to apply ±20% random jitter to the computed delay: `delay * (0.8 + Math.random() * 0.4)`.
- [x] Confirm the fix is a one-line change and does not alter the cap (30 s max) or the backoff progression.

---

### 9. Add `ETag` caching to the session messages endpoint

**Background:** The `/api/sessions/:id/messages` endpoint sends no HTTP cache headers. The post-`turn_done` re-fetch and fork/retry flows all get full `200` responses even for unchanged sessions.

- [x] In the gateway route handler for `/api/sessions/:id/messages`, compute an ETag (e.g. hash of message count + last message ID or timestamp).
- [x] Send `ETag` and `Cache-Control: no-cache` headers on the response.
- [x] Handle `If-None-Match` request headers and return `304 Not Modified` when the ETag matches.
- [x] Verify in DevTools: a second fetch for an unchanged session returns `304` with no body.

---

### 10. Pre-warm the agent cache on dashboard load

**Background:** `run.py` `_agent_cache` is populated lazily on first message. The first message of a resumed session must re-build the system prompt, reload memory, and re-scan skills — adding 1–3 s of latency before the model even receives the request.

- [x] Add a lightweight `/api/sessions/:id/warm` (or `/api/agent/warm`) POST endpoint in the gateway that retrieves (or creates) the cached `AIAgent` for the given session without sending a message.
- [x] Call this endpoint from `ChatPanel.tsx` when a session is loaded (after `getSessionMessages` resolves), fire-and-forget.
- [x] Confirm the warm-up does not trigger a new agent turn or emit any `chat.*` SSE events.
- [x] Benchmark: compare Time-To-First-Token on first message of a resumed session before and after this change.
