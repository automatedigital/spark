# TASKS

This file tracks the progress of current tasks for the project.

## Summary

The Spark Web Dashboard has strong foundations—including streamed chat, workspace sessions, file upload and preview, `@file` autocomplete, session search, and more. However, its main weakness is context management: context is spread across prompts, uploads, files, and tool outputs, but users lack clear visibility and control over what becomes model context. Pre-send token feedback is also missing.

## Key Problems

- Context selection is implicit; `@file` and uploads go into prompt text, not visible structured context.
- No project manifest, reusable brief, or pinned files in workspace chats.
- Important decisions/outputs cannot be promoted into durable project context.
- Token usage feedback only comes after a turn, not before.
- File management and context attachment are fragmented across multiple places with no unified view.

## Current Priorities

1. **Context Tray & API**: Show users attached files, excerpts, notes, etc., with explicit inclusion modes (e.g., path-only, excerpt, summary, full-content, searchable).
2. **Preflight Token Budgeting**: Estimate and warn about token usage _before_ sending, broken down by prompt, context, pinned, and history.
3. **Thread Briefs & Manifests**: Let users promote important content into a durable, compact, reusable project/session state.
4. **Summaries, Excerpts, Retrieval**: Add file/folder summaries, selected lines, diff-only and bounded search snippets as context.
5. **Tool Output & Polish**: Make persisted tool outputs manageable and referenced; improve performance in autocomplete, long lists, UI states.

## Best Near & Long-term Improvements

- **Context Tray with Structured Items**: Makes prompt mentions explicit choices and reduces accidental full-inclusion.
- **Durable Briefs and File Summaries**: For long-running sessions, compresses repeated context into compact, reusable state.

## Task Checklist

Mark items only after implementation and verification.

---

### Phase 0: Baseline

These tasks are read-only exploration and design work. No code should be written until all six are done. The goal is to understand exactly what exists today before adding anything, so we don't build on wrong assumptions.

- [x] **Review chat send flow** (`ChatPanel.tsx`, `PromptBar.tsx`, `api.ts`, `web_server.py`)
  _What_: Trace the full lifecycle of a chat message — from the user pressing Send to the model response arriving in the UI. Note where files/prompt text are assembled, how streaming is handled, where messages are persisted, and any existing context-passing hooks.
  _Why_: We need to know the exact insertion points for context items before we design the ContextItem API. Missing this step risks building context support in the wrong layer.

- [x] **Review file/workspace flow** (`FilesPage.tsx`, `WorkspacePage.tsx`, `AtFileMenu.tsx`, `workspace_routes.py`)
  _What_: Understand how files are listed, uploaded, previewed, and referenced via `@file`. Map which frontend components own file state, which routes serve file metadata, and how workspace isolation is enforced today.
  _Why_: The Context Tray will integrate directly with `@file` mentions and file uploads. We must know the existing data shapes and ownership before designing the attach/detach API.

- [x] **Confirm how `@file` is handled by agent**
  _What_: Follow an `@file` mention from the autocomplete selection through to what the agent actually receives. Determine whether file content is inlined into the prompt string, sent as a separate message block, or passed as a tool input — and where that transformation happens.
  _Why_: The inclusion-mode system (path-only, excerpt, full) depends on intercepting this transformation. We can't redesign it without knowing where it happens and what format the agent expects.

- [x] **Define minimal `ContextItem` schema**
  _What_: Write the canonical shape of a `ContextItem` — the object that represents one attached piece of context (file, excerpt, note, tool output, etc.). Must include: `id`, `type`, `source_path` (optional), `inclusion_mode`, `content` or `content_ref`, `scope` (one-turn vs. pinned), and `size_bytes`.
  _Why_: Every subsequent task — backend models, frontend types, tray UI, token estimation — depends on a stable, agreed-upon shape. Locking this down early prevents multiple incompatible representations from diverging across the stack.

  **Canonical schema (locked):**
  ```
  ContextItem:
    id: str                    # UUID, client-generated
    type: "file" | "excerpt" | "note" | "tool_output" | "url"
    source_path: str | None    # Relative path within workspace root (None for notes/URLs)
    inclusion_mode: "path_only" | "excerpt" | "summary" | "full" | "search"
    content: str | None        # Inline content (for notes, or eagerly-loaded small files)
    content_ref: str | None    # Path to cached content on disk (for large files)
    scope: "one_turn" | "pinned"
    size_bytes: int            # 0 for path_only; actual bytes for other modes
    excerpt_range: [int, int] | None   # [start_line, end_line] for excerpt mode
    search_query: str | None   # Query string for search mode
    label: str | None          # User-visible display name (defaults to filename)
  ```

- [x] **Decide storage for session context & manifests**
  _What_: Choose where structured context is persisted: options include the existing SQLite session DB (new table), a sidecar JSON file per session, or a separate context DB. Document the decision with rationale.
  _Why_: Pinned context and session briefs must survive page refresh and browser close. The storage choice affects migration complexity, query patterns for token estimation, and profile isolation. This decision gates all persistence work in Phases 1–3.

  **Decision: new tables in the existing SQLite session DB (`spark_state.py`).**
  - Add `context_items` table: `(id TEXT PK, session_id TEXT FK, type TEXT, source_path TEXT, inclusion_mode TEXT, scope TEXT, content TEXT, content_ref TEXT, size_bytes INT, excerpt_range TEXT, search_query TEXT, label TEXT, created_at REAL)` — indexed on `session_id`.
  - Add `session_briefs` table: `(session_id TEXT PK FK, text TEXT, updated_at REAL)`.
  - Add `workspace_manifests` table: `(workspace_slug TEXT PK, data_json TEXT, updated_at REAL)` — stored in the same SQLite DB, isolated per profile via `get_spark_home()`.
  - **Rationale**: same WAL journal, existing migration pattern, profile-isolated by `get_spark_home()`, already used for all other session state. Sidecar JSON would add file management complexity and lose ACID guarantees. A separate DB adds another file to manage.

- [x] **Ensure new persistent paths use correct helpers**
  _What_: Confirm that every new file or DB path introduced by this feature goes through `get_spark_home()` (never hardcoded `~/.spark`). Add a grep-based check or linter note if helpful.
  _Why_: Profile safety is a hard rule in this codebase. Using hardcoded paths silently breaks `--profile` isolation, which is a regression that is hard to detect until a user loses data across profiles.

  **Verified**: existing codebase has no `~/.spark` hardcodes in core workspace/session paths. Only comments, docs, and the intentional container path (`/root/.spark`) use the literal string. New tables go into the existing `SessionDB` (which uses `DEFAULT_DB_PATH = get_spark_home() / "sessions.db"`), so they inherit the safety automatically.

---

### Phase 1: Context Tray

The Context Tray is the central UI surface where users see and manage everything attached to the current turn. The goal is to make context explicit, controllable, and visible _before_ sending.

- [x] **Backend models for `ContextItem`, `ContextScope`, `ContextEstimate`**
  _What_: Create Python dataclasses (or Pydantic models) matching the schema defined in Phase 0. `ContextItem` holds a single attachment. `ContextScope` is an enum: `one_turn | pinned | session_brief`. `ContextEstimate` is a lightweight object returned by the token estimation endpoint (Phase 2) — define the shape here so both phases share a contract.
  _Why_: Centralising these models prevents the frontend and backend from inventing divergent types. Defining `ContextEstimate` now means Phase 2 won't need a breaking schema change.

- [x] **Add context fields to chat/workspace create/message**
  _What_: Extend the existing request bodies for chat creation, workspace creation, and message send to accept an optional `context_items: list[ContextItem]` field. Store received items alongside the message in the session DB.
  _Why_: Context items need to travel from the frontend tray to the backend on every send. Without this wire-up, the tray is purely cosmetic.

- [x] **Validate path safety, workspace, count, size**
  _What_: On the backend, for every incoming `ContextItem` that references a file path: (1) resolve and check it doesn't escape the workspace root (no `../` traversal), (2) confirm it belongs to the active workspace, (3) enforce a per-message item count cap (suggest 20), and (4) enforce a per-item size cap for full-content mode (suggest 500 KB).
  _Why_: File path inputs are an injection vector. Without validation, a malicious or misconfigured client could read arbitrary host files or exhaust memory with huge attachments.

- [x] **Render structured context compactly**
  _What_: In the chat message history, show a compact, read-only summary of context items that were sent with each turn — e.g., a small chip row showing file names and inclusion modes. Clicking a chip shows the content that was actually sent.
  _Why_: Users need an audit trail of what context the model saw per turn. Without this, debugging unexpected model behavior is guesswork.

- [x] **Frontend API/types for structured context**
  _What_: Add TypeScript types matching the backend `ContextItem` / `ContextScope` models. Add API client functions for: attach item, remove item, update inclusion mode, list current tray items. Keep these in a dedicated `context.ts` (or similar) rather than scattered across components.
  _Why_: A clean frontend API boundary makes the tray UI composable and testable. Mixing API calls into UI components leads to duplicated fetch logic and brittle state.

- [x] **Reusable `ContextTray` UI**
  _What_: Build a `ContextTray` component that renders the list of current context items. Each item shows: file name / type icon, inclusion mode badge, size indicator, and action buttons (remove, change mode, pin). The tray sits below or beside the prompt bar and collapses when empty.
  _Why_: The tray is the primary user-facing surface for the entire context management system. It must be reusable across chat and workspace views, and should be pleasant and fast to interact with.

- [x] **Attach actions from `@file`, upload, file picker**
  _What_: When a user selects a file via `@file` autocomplete, uploads a file, or picks one from the file browser, route the selection into the context tray rather than (or in addition to) inlining it as plain text in the prompt. Show the item in the tray immediately, not embedded in the prompt box.
  _Why_: Today, `@file` mentions become raw text in the prompt, making them invisible to the inclusion-mode system. Routing through the tray makes attachment explicit and controllable.

- [x] **Remove/pin/one-turn/inclusion-mode controls**
  _What_: Each tray item needs interactive controls: (1) a remove/detach button, (2) a scope toggle (one-turn vs. pinned — pinned items persist across multiple turns), and (3) an inclusion-mode selector (see next task). These should be accessible via a small dropdown or popover per item.
  _Why_: Without controls, the tray is read-only decoration. The whole point is giving users agency over what the model sees.

- [x] **Support path-only, excerpt, summary, full, search inclusion modes**
  _What_: Implement five inclusion modes for file items:
  - `path-only`: send only the file path string; the model knows the file exists but can't read it.
  - `excerpt`: send a user-selected line range from the file.
  - `summary`: send a cached AI-generated summary of the file (see Phase 4).
  - `full`: send the entire file content.
  - `search`: send the top-N matching lines for a query (see Phase 4).
  The backend must apply the correct transformation when building the message sent to the model.
  _Why_: Different files warrant different levels of inclusion. A 50-line config file is fine as `full`; a 10,000-line codebase file should default to `summary` or `search`. Giving users this control is the core value proposition of the tray.

- [x] **Warn/block full-content on large files**
  _What_: If a user selects `full` inclusion mode for a file larger than a configurable threshold (suggest 100 KB or ~25K tokens), show an inline warning in the tray and suggest switching to `summary` or `excerpt`. Block sending if the file is over a hard cap (suggest 500 KB).
  _Why_: Accidentally including a large file as full content wastes tokens, slows responses, and can hit model context limits silently. Users need guardrails, not just controls.

- [x] **Ensure normal chat still works**
  _What_: After implementing the tray, verify that a user who never touches it — typing a message and pressing Send — gets exactly the same behavior as before. No regressions in streamed responses, history, or session persistence.
  _Why_: The tray is additive. Existing workflows must be unaffected. This is a non-negotiable backward-compatibility checkpoint.

- [x] **Context reaches backend**
  _What_: End-to-end test: attach a file via the tray with `full` mode, send a message, and confirm the file content appears in the actual API call payload logged on the backend. Do the same for `path-only` (content absent, path present) and `excerpt`.
  _Why_: The frontend can look correct while context silently fails to reach the model. This test closes the loop.

- [x] **Reject traversal/cross-workspace**
  _What_: Write a backend test that sends a `ContextItem` with `source_path = "../../etc/passwd"` and confirms the server returns a 400 or 403, not the file content. Also test a path from a different workspace.
  _Why_: Path traversal is a real attack vector. Tests that prove rejection are the only reliable proof the validation works.

- [x] **Backend tests**
  _What_: pytest tests covering: valid item attach/detach round-trip, inclusion mode transformations (path-only / excerpt / full each produce the correct backend payload), count and size cap enforcement, and storage isolation per profile.
  _Why_: Context logic is subtle and stateful. Tests protect against regressions as token budgeting, briefs, and summaries are layered on top.

---

### Phase 2: Token Budgeting

Users should know before they send a message whether they're about to blow the context window or incur a large token cost. This phase adds a preflight estimate so they can make informed decisions.

- [ ] **Preflight token estimate endpoint**
  _What_: Add a `POST /api/estimate-tokens` endpoint that accepts: the current prompt text, the list of `ContextItem`s (with their inclusion modes), any pinned brief text, and the message history count. Returns a `ContextEstimate` with a breakdown by component and a total.
  _Why_: Token counting must happen server-side to match the exact tokenizer the model uses. A client-side approximation would give misleading numbers.

- [ ] **Use existing token helpers where possible**
  _What_: Before writing new tokenization code, audit the codebase for existing helpers (`count_tokens`, tiktoken usage, etc.) in `src/core/` or the web server. Reuse them in the estimate endpoint rather than duplicating logic.
  _Why_: Duplicate token-counting implementations will diverge over time, producing inconsistent numbers. Using one source of truth is simpler and cheaper to maintain.

- [ ] **Estimate: prompt, attached, pinned, history**
  _What_: The `ContextEstimate` response must break down token counts into four labeled buckets: (1) current prompt text, (2) attached context items (per item and total), (3) pinned brief, (4) conversation history included in the next turn. Surface each bucket in the UI so users know which component is costing the most.
  _Why_: A total token count with no breakdown is hard to act on. When a user sees they're over budget, they need to know whether to trim the prompt, remove an attachment, or clear history — not just that the total is too high.

- [ ] **Warn for likely compression or costly attachments**
  _What_: If the total estimate exceeds 80% of the model's context window, show a yellow warning in the tray ("Context may be compressed"). If it exceeds 95%, show a red warning ("Likely to hit context limit"). Also flag any single attachment that accounts for more than 50% of the total.
  _Why_: Context compression silently degrades response quality. Warning users before they send — and telling them what's expensive — gives them a chance to fix it rather than just experiencing a worse reply.

- [ ] **Debounce/cancel estimate during typing**
  _What_: The estimate should re-trigger whenever the prompt text changes, a context item is added/removed, or an inclusion mode changes. Debounce the request by 400–600 ms after the last change. Cancel any in-flight estimate request when a new one starts (use `AbortController`).
  _Why_: Without debouncing, every keystroke fires a request, creating noisy network activity and flickering UI. Without cancellation, slow responses arrive out of order.

- [ ] **Budget indicator near send; expanded details in tray**
  _What_: Add a compact token budget indicator in the prompt bar footer (e.g., "4,200 / 200K tokens") that turns yellow/red when thresholds are hit. Clicking it (or expanding the tray) shows the full breakdown by bucket.
  _Why_: The indicator should be glanceable without being intrusive. The expanded view is for users who want to dig into what's using their budget.

- [ ] **Quick actions to remove/switch mode**
  _What_: When the budget indicator shows a warning, surface direct action buttons in the expanded view: e.g., "Switch [file.py] to summary" or "Remove pinned brief". These should apply the action and re-trigger the estimate immediately.
  _Why_: A warning without an escape hatch is frustrating. Offering a one-click fix closes the loop and makes the budgeting feature feel helpful rather than just alarming.

- [ ] **Live updates as prompt/context change**
  _What_: Ensure the estimate display updates in real time as the user types, adds/removes context items, and changes inclusion modes. The UI state should reflect the current pending request clearly (e.g., a spinner or subtle "updating…" label while the estimate loads).
  _Why_: Stale numbers are worse than no numbers — they create false confidence. The indicator must always reflect the current state, not a cached one from 30 seconds ago.

- [ ] **Graceful UI for estimate failures**
  _What_: If the estimate endpoint returns an error or times out, hide the indicator or show "—" rather than a stale or incorrect number. Do not block the user from sending. Log the error for debugging.
  _Why_: Token estimation is a convenience feature, not a safety gate. Failing closed (blocking send) when the estimate is unavailable would be worse than showing nothing.

- [ ] **Estimate boundary tests**
  _What_: Backend tests that verify: (1) a prompt with no context returns a non-zero estimate, (2) adding a 10KB full-content file increases the estimate by approximately the right amount, (3) a request near the model limit triggers the warning threshold fields in the response, and (4) an empty request doesn't error.
  _Why_: Estimation logic has subtle edge cases (empty context, very large files, history truncation). Tests catch regressions before they reach users who rely on the numbers to make decisions.

---

### Phase 3: Briefs & Manifests

Long-running sessions accumulate context that gets re-sent in every turn. Briefs and manifests give users a durable, compact summary layer they can curate and reuse, reducing repeated token cost.

- [ ] **Storage for briefs & manifests (profile-scoped)**
  _What_: Add a storage layer for two distinct object types: (1) a **session brief** — a short user-editable text block attached to one chat session, summarising key decisions, constraints, or background; (2) a **workspace manifest** — a set of pinned files, notes, and brief text that applies to all chats in a workspace. Both must be stored per-profile (under `get_spark_home()`), not globally.
  _Why_: Briefs and manifests need to persist across page reloads and sessions. Mixing them into the main session table would couple unrelated concerns; separate storage makes CRUD simpler and isolation testable.

- [ ] **CRUD endpoints for session briefs and workspace manifests**
  _What_: Implement REST endpoints: `GET/PUT /api/sessions/{id}/brief` for session briefs; `GET/PUT /api/workspaces/{id}/manifest` for manifests. Support partial updates (don't require sending the full object to change one field). Return 404 if the session/workspace doesn't exist.
  _Why_: The frontend needs to read the current brief on page load, save edits on change, and reset it. Clean CRUD endpoints are easier to cache and test than embedding brief state in message or session objects.

- [ ] **Editable brief panel in chat**
  _What_: Add a collapsible "Brief" panel in the chat sidebar or above the prompt bar. It shows the current session brief text in an editable textarea. Changes auto-save after a short debounce (1–2 seconds). An empty brief hides the panel or shows a "Add a brief…" placeholder.
  _Why_: The brief needs to be instantly editable without leaving the chat flow. A separate settings page would add too much friction. The panel should feel like a sticky note attached to the chat.

- [ ] **"Promote to brief" actions**
  _What_: Add a "Promote to brief" action to: (1) any assistant message (promotes the message text or a user-selected portion), (2) any context item in the tray (promotes its content or summary). The action opens a small editor pre-filled with the selected content and lets the user edit before saving.
  _Why_: The most valuable things to put in a brief are the outputs and decisions the model already produced. Making it easy to pull those up into the brief, rather than forcing users to copy-paste, encourages use.

- [ ] **Current brief included as context on next turn**
  _What_: When building the message payload for any turn in a chat that has a non-empty brief, prepend the brief as a system or user context block — clearly labelled so the model treats it as persistent context, not user input. For workspace manifests, include pinned files/notes similarly.
  _Why_: The brief only has value if the model can actually see it. This is the payload-level wire-up that makes the brief part of every turn without the user having to copy-paste it into the prompt.

- [ ] **Brief edits survive streaming/reload**
  _What_: Verify that edits made to a brief while a streamed response is in progress are not lost when the response completes and the UI updates. Also verify edits survive a browser reload (i.e., they were persisted server-side, not only in React state).
  _Why_: Briefs are meant to be living documents that users edit mid-session. Losing an edit during a stream would be a trust-destroying bug.

- [ ] **Brief not duplicated in prompt**
  _What_: Confirm that the brief content is injected by the backend as a separate context block — not by the frontend appending it to the prompt string. If the user also quotes brief content in their prompt manually, that should not cause double-inclusion.
  _Why_: Duplicate content wastes tokens and can confuse the model (conflicting signals if the user edited the brief after quoting it). The backend must own the canonical inclusion, not the frontend.

- [ ] **Persistence/profile-isolation tests**
  _What_: Tests covering: (1) brief survives a session reload, (2) brief for session A does not appear in session B, (3) workspace manifest for workspace X does not bleed into workspace Y, (4) brief is cleared when a session is deleted.
  _Why_: Profile and session isolation failures are silent data leaks. These tests are the proof that the storage layer enforces the boundaries it claims to enforce.

---

### Phase 4: Summaries & Retrieval

Large files are impractical to include in full. This phase adds AI-generated summaries and bounded search so users can attach useful slices of big files without blowing the context window.

- [ ] **Metadata storage for summaries**
  _What_: Create a storage table or JSON sidecar (outside user files, under `get_spark_home()`) that maps a file's path + size + mtime to its cached summary text. Each record stores: path, size_bytes, mtime, summary_text, model_used, created_at.
  _Why_: Generating a summary is expensive (requires an LLM call). Caching by path+size+mtime means we only regenerate when the file actually changes. Storing summaries outside user files keeps the workspace clean.

- [ ] **File/folder summary endpoints with size/binary checks**
  _What_: Add `POST /api/summarize-file` and `POST /api/summarize-folder` endpoints. Both must: (1) check the file is within the workspace (path safety), (2) reject binary files (detect by extension or MIME sniff), (3) reject files over a configurable size cap (suggest 2 MB), and (4) return the cached summary if fresh, otherwise generate and cache a new one.
  _Why_: Without size and binary checks, a user trying to summarize a 500MB video file would trigger an enormous LLM call. The endpoint must be defensive because users will try unusual inputs.

- [ ] **Track summary freshness (path, size, mtime)**
  _What_: Before returning a cached summary, check the file's current size and mtime against the cached values. If either has changed, mark the summary stale and regenerate. Surface a "stale" flag in the tray UI so users can see when a summary might be out of date.
  _Why_: A cached summary of a file that has since been edited is misleading. Freshness tracking prevents the model from receiving outdated information while still benefiting from caching for unchanged files.

- [ ] **UI actions: summarize file/folder, select lines/excerpts**
  _What_: In the context tray and file browser, add: (1) a "Summarize" button for any attached file that triggers generation and switches its inclusion mode to `summary`; (2) a "Select lines" action that opens a simple line-range picker and switches mode to `excerpt` with the chosen range.
  _Why_: Summaries and excerpts are only useful if they're easy to trigger. Hiding the controls in a settings panel would mean almost no one uses them. The actions need to be discoverable at the point of attachment.

- [ ] **Diff-only context where baseline exists**
  _What_: For files that have a known baseline (e.g., the git HEAD version), add a `diff` inclusion mode that sends only the lines that changed, with a small surrounding context window (e.g., ±3 lines). Surface this option in the inclusion-mode selector when the file is in a git repo.
  _Why_: When reviewing recent edits, sending a 2000-line file in full is wasteful. A diff is typically under 100 lines and tells the model exactly what changed, which is usually what matters.

- [ ] **Bounded search snippets as context**
  _What_: For `search` inclusion mode, implement a backend that runs a grep/ripgrep-style search within the file for a user-provided query string, returns the top-N matching line ranges (e.g., 5 matches × 10 surrounding lines each), and sends only those snippets. The tray should show a query input for `search`-mode items.
  _Why_: When a user wants the model to focus on how a specific function or keyword is used in a large file, sending the whole file is overkill. Bounded snippets give surgical precision without blowing the budget.

- [ ] **Summaries stored outside user files by default**
  _What_: Confirm that summary files are written to a path under `get_spark_home()/summaries/` (or equivalent), never inside the workspace file tree. Add a test that creates a summary and asserts the file does not exist inside the workspace directory.
  _Why_: Writing AI-generated content into the user's project directory would pollute their workspace and could interfere with version control. The spark home is the right place for all generated metadata.

- [ ] **Path safety, freshness, binary-skip tests**
  _What_: Tests covering: (1) a path-traversal attempt returns 400, (2) a binary file returns a clear error, (3) an oversized file returns a clear error, (4) requesting a summary twice for the same unchanged file returns the cached version (no second LLM call), (5) after modifying the file, the next request regenerates the summary.
  _Why_: Caching + security logic is easy to get subtly wrong. These tests are the specification and the regression net.

---

### Phase 5: Tool Outputs

When the model produces outputs that were written to disk (files, reports, generated code), users should be able to attach and reference those outputs in subsequent turns without re-running the tool or copy-pasting paths.

- [ ] **Detect persisted-output in tool bubbles**
  _What_: Parse tool result bubbles in the chat UI to detect whether the output references a local file path (e.g., `Saved to /path/to/output.py`). Flag these tool results as "has persisted output" and store the detected paths alongside the message record.
  _Why_: Tool outputs that write files are the most natural candidates for follow-up context. Today, users must manually type or copy the path. Detecting it automatically is the first step to surface-level integration.

- [ ] **Surface safe output paths as references**
  _What_: For tool results with detected output paths, show a small "Attach to tray" chip below the tool bubble. Clicking it adds the file to the context tray with a default inclusion mode (e.g., `path-only` or `summary`). Only surface paths that pass the workspace safety check (no traversal, within workspace root).
  _Why_: The chip closes the loop between "model produced this file" and "user can reference it in the next turn." Without it, the output sits in the chat as a string and the user has no obvious path to re-attach it.

- [ ] **Pin/summarize/attach-excerpt actions for outputs**
  _What_: Once a tool output is in the tray, it should support the same inclusion-mode controls as any other attachment: pin across turns, switch to summary (trigger on-demand summary generation), select an excerpt. The "Summarize" action is especially useful here since tool outputs are often large generated files.
  _Why_: Tool outputs can be very large (generated codebases, CSV reports, etc.). Without inclusion-mode controls, attaching them in full would always be expensive. The same controls that apply to user-added files should apply equally here.

- [ ] **Avoid raw links to unsafe/non-local paths**
  _What_: If a tool output references a path outside the workspace root (e.g., `/tmp/something`), do not surface an "Attach" chip. Show the path as plain text only. Do not create a clickable link or tray attachment for it.
  _Why_: Tool outputs could theoretically reference sensitive system paths. We must not silently allow out-of-workspace files to enter the context tray through a trusted-looking chip.

- [ ] **Large outputs can be summarized/attached without full dump**
  _What_: If the detected output file is larger than the full-content threshold (from Phase 1), default the chip to `summary` mode rather than `full`. Show a tooltip explaining why and let the user override.
  _Why_: A tool that generates a 50KB file should not silently push 50KB of tokens into the next turn. Defaulting to summary mode for large outputs prevents the most common accidental over-inclusion scenario.

- [ ] **Parsing & safe-path tests**
  _What_: Tests for: (1) a tool result with a valid workspace path is detected and surfaced, (2) a tool result with no path produces no chip, (3) a path outside the workspace is detected but not surfaced as an attachment option, (4) a path-traversal string in the tool result does not create an attachment.
  _Why_: Path detection from unstructured text is fragile. Tests lock in the parser behavior and prevent security regressions if the detection logic is refactored.

---

### Phase 6: Polish & Verification

Final quality pass: performance, accessibility, mobile, and the test suite needed before shipping.

- [ ] **Debounce/cancel directory requests**
  _What_: Any file browser or autocomplete component that fires requests on every keystroke (e.g., `AtFileMenu`) must debounce by at least 200 ms and cancel in-flight requests when a new one starts. Audit all such components and apply `AbortController` consistently.
  _Why_: Fast typing currently generates a flood of requests in the `@file` menu. This wastes server resources and can cause out-of-order responses that produce confusing autocomplete results.

- [ ] **Virtualize long lists as needed**
  _What_: If the file browser, tray, or any list component can render hundreds of items, switch to a windowed/virtual list (e.g., `react-window` or `react-virtual`). Profile first — only virtualize lists that actually have performance problems.
  _Why_: Rendering 500 file chips in the DOM causes noticeable lag on mid-range hardware. Virtualization keeps the UI responsive without visible change to the user.

- [ ] **Incremental long history loading**
  _What_: For chat sessions with many turns, load history in pages (e.g., 50 turns at a time) and prepend earlier turns on scroll-up. Do not load the entire history on mount. Show a "Load earlier messages" button or auto-trigger on scroll.
  _Why_: Long sessions today can cause slow initial loads and large DOM trees. Incremental loading keeps the initial render fast regardless of session length.

- [ ] **Consolidate file helpers**
  _What_: Audit the codebase for duplicate file-path utilities, workspace-root helpers, and path-safety functions across the frontend and backend. Merge duplicates into single canonical helpers. Document where each lives.
  _Why_: Phase 1–4 added several new path-handling code paths. Without consolidation, future changes will need to update multiple copies, and the safety logic can drift between them.

- [ ] **Clear empty/error states for tray, estimates, summaries, manifests**
  _What_: Every new UI surface needs a designed empty state and an error state: the tray when nothing is attached, the budget indicator when estimation fails, the brief panel when no brief exists, the summary when generation fails. None should show a blank space or a raw error message.
  _Why_: Empty and error states are the most common UX a new user sees. Blank spaces feel broken; raw errors feel hostile. Good empty states guide users toward the first action.

- [ ] **Keyboard navigation for menus, tray, send, stop**
  _What_: Audit all new interactive surfaces for keyboard accessibility: (1) tray items navigable by arrow keys, (2) inclusion-mode dropdowns openable and navigable by keyboard, (3) Tab/Shift-Tab cycles through tray → prompt → send without focus traps, (4) Escape closes any open popover.
  _Why_: Power users and screen-reader users rely on keyboard navigation. A tray that requires mouse clicks is inaccessible. This is also a baseline requirement for any production UI.

- [ ] **Mobile layout works for chat & tray**
  _What_: Test the chat + tray layout on viewport widths of 375px and 430px. The tray should either collapse into a bottom sheet / drawer on mobile or be accessible via a dedicated icon. Context chips in the tray must be scrollable if they overflow.
  _Why_: Mobile users exist. The tray is a new persistent UI element that could easily obscure the prompt bar or overflow off-screen on small viewports without explicit mobile testing.

- [ ] **Code checks: `ruff`, `mypy`, targeted backend tests, frontend build**
  _What_: Before marking Phase 6 complete: run `ruff check src/` with zero errors, run `mypy src/agent/ src/spark_cli/` with zero errors in new code, confirm the frontend builds without TypeScript errors, and run targeted backend tests for all new endpoints.
  _Why_: These checks catch real bugs and type mismatches that slip through manual testing. They are the minimum bar for code quality and match the project's existing lint/type standards.

- [ ] **Full test suite**
  _What_: Run `python -m pytest tests/ -q` and confirm it passes. Fix any tests that break due to new features (don't skip them). Add any integration tests needed to cover critical paths not covered by unit tests.
  _Why_: The full suite is the final regression check. Shipping without it risks breaking existing features that were not touched intentionally.

---

## Success Criteria

- All attached context is visible before sending
- Large files default to summary/excerpt/search, not full
- Warn before likely context compression
- Less repeated file/history for long sessions
- Fewer prompt tokens per continued session
