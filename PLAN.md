# Sub-Agents First-Class UI Plan

## References

- [Floating sidebar, full window](screenshots/260626/01_Sub-Agent_FloatingSidebar_Screenshot%202026-06-25%20at%2021.07.27.png)
- [Floating sidebar, close crop](screenshots/260626/02_Sub-Agent_FloatingSidebar_Screenshot%202026-06-25%20at%2021.07.34.png)
- [Expanded sub-agent sidebar](screenshots/260626/03_Sub-Agent_ExpandedSidebar_Screenshot%202026-06-25%20at%2021.07.41.png)

## Goal

Make sub-agents a visible, inspectable part of Spark. When the main agent calls `delegate_task`, each child agent should appear in a Codex-style "Subagents" at-a-glance area in the right-hand sidebar. Clicking a sub-agent should expand the right side into that sub-agent's transcript, status, task, and controls while keeping the main thread visible.

## Current State

- `src/tools/delegate_tool.py` already creates child `AIAgent` instances, runs them in parallel, blocks the parent until they complete, and returns structured summaries.
- `src/tools/delegate_tool.py` has `_build_child_progress_callback()` for CLI/gateway progress, but the callback mostly batches tool names and does not expose first-class sub-agent entities.
- `src/core/run_agent/__init__.py` already supports `tool_progress_callback`, `stream_delta_callback`, `thinking_callback`, child interrupt tracking, and a delegation depth guard.
- `src/spark_cli/web_server.py` already has a shared `/api/events` SSE bus with `chat.*` topics, per-conversation token streams, turn snapshots, and tool/reasoning event callbacks.
- `src/spark_cli/web/src/pages/ChatPage.tsx` already owns the chat layout and workspace right panel; this is the natural place to add the Codex-like floating and expanded sub-agent panel.
- `src/spark_cli/web/src/components/ChatPanel.tsx` already renders chat, tool, reasoning, approval, status, and prompt controls; reuse these patterns for the sub-agent transcript instead of building a separate visual language.

## Product Behavior

- [x] A delegated child appears immediately in the right sidebar as soon as it is created.
- [x] Each sub-agent row shows a stable glyph/color, display name, and live status text such as `is working`, `done`, `failed`, or `stopped`.
- [x] The compact right sidebar keeps the existing Environment/Changes/Local/Branch/Commit/Create PR area, then adds a `Subagents` section matching the screenshot.
- [x] If no sub-agents exist, the sidebar does not show an empty sub-agent section unless a turn is actively delegating.
- [x] Clicking a sub-agent opens the selected child transcript inside the right-hand `Subagents` sidebar tab while the main thread remains visible.
- [x] The expanded pane header shows the selected sub-agent glyph/name, status, elapsed time, and close/collapse controls.
- [x] The expanded pane begins with the delegated task/context card and supports `Show more` for long prompts.
- [x] The expanded pane streams child commentary, reasoning summaries, tool activity, and final summary while the child runs.
- [x] The parent thread still receives only the existing delegation result summary in its own context; exposing child transcripts in UI must not alter parent prompt caching or parent conversation history.
- [x] Interrupting the parent turn stops running sub-agents and updates their statuses in the UI.
- [x] Reloading the web UI during an active or completed delegated turn restores the sub-agent list and the latest available transcript snapshot.

## Phase 1: Backend Sub-Agent Lifecycle Contract

- [x] Define a canonical sub-agent run model with fields: `id`, `parent_session_id`, `child_session_id`, `task_index`, `name`, `glyph`, `color`, `status`, `task`, `context_preview`, `model`, `provider`, `toolsets`, `started_at`, `last_event_at`, `ended_at`, `duration_seconds`, `exit_reason`, `summary`, `error`, `tokens`, and `tool_trace`.
- [x] Add a small lifecycle helper module, likely `src/agent/subagents.py` or `src/core/run_agent/subagents.py`, so `delegate_tool.py` does not become the state/event dumping ground.
- [x] Generate stable display identities for each parent turn: use deterministic names/glyphs/colors in creation order, then persist them so reloads do not reshuffle rows.
- [x] Ensure each child gets a stable `child_session_id` before it starts running, and store that id on the lifecycle record.
- [x] Emit lifecycle events for `created`, `started`, `thinking`, `tool_started`, `tool_output`, `tool_completed`, `status`, `completed`, `failed`, and `interrupted`.
- [x] Keep lifecycle event payloads JSON-safe, bounded, and free of secrets; truncate args/results at web-preview limits and keep full tool results in existing message/tool result storage.
- [x] Preserve existing `delegate_task` return shape for backwards compatibility.
- [x] Preserve existing `DELEGATE_BLOCKED_TOOLS`, `MAX_DEPTH`, `max_concurrent_children`, config routing, credential-pool leasing, and heartbeat behavior.
- [x] Add unit tests for lifecycle creation, event ordering, status transitions, deterministic identities, truncation, and interrupt/failure handling.

## Phase 2: Persistence And Snapshots

- [x] Add persistence for sub-agent runs without polluting top-level session lists. Preferred shape: a new `subagent_runs` table keyed by `id`, linked to parent and child sessions.
- [x] Add migration for the new table in `src/core/spark_state.py` and bump `SCHEMA_VERSION`.
- [x] Store transcript events either as child `messages` in `SessionDB` plus lightweight event metadata, or as a bounded `subagent_events` table if child messages are not sufficient for live replay.
- [x] Ensure `SessionDB.list_sessions_rich()` continues hiding child sessions by default.
- [x] Add `SessionDB` helpers such as `create_subagent_run`, `update_subagent_run`, `append_subagent_event`, `list_subagent_runs(parent_session_id)`, and `get_subagent_transcript(subagent_id)`.
- [x] Include compression/session migration behavior: when a parent session migrates, active sub-agent records should remain discoverable from the latest session id and the original requested session id.
- [x] Add tests for schema migration from an older DB, cascade/delete behavior, child-session hiding, and snapshot recovery after process restart.

## Phase 3: Web Server Events And API

- [x] Extend `_make_web_chat_callbacks()` or introduce a sibling callback factory so web turns pass a `subagent_event_callback` into `AIAgent`/`delegate_task`.
- [x] Publish sub-agent lifecycle changes on `/api/events` using topics under `chat.subagent.*`, reusing the existing `chat` topic subscription.
- [x] Add `GET /api/conversations/{session_id}/subagents` returning the current snapshot list for reload/reconnect.
- [x] Add `GET /api/conversations/{session_id}/subagents/{subagent_id}` returning detail plus recent transcript events.
- [x] Add `GET /api/conversations/{session_id}/subagents/{subagent_id}/messages` if the expanded pane will render from child `SessionDB` messages rather than event records.
- [x] Add optional `POST /api/conversations/{session_id}/subagents/{subagent_id}/interrupt` for stopping one child without stopping the parent, if safe with current child tracking.
- [x] Make reconnect recovery call the snapshot endpoint when the event bus emits `bus.reconnected`.
- [x] Add FastAPI tests in `tests/spark_cli/test_web_server_events.py` for event publication, snapshots, reconnect recovery, migration handling, and authorization.

## Phase 4: Frontend State And API Types

- [x] Add TypeScript types for `SubagentRun`, `SubagentEvent`, and snapshot responses in `src/spark_cli/web/src/lib/api.ts`.
- [x] Add API helpers for listing sub-agents, fetching detail/transcripts, and interrupting a sub-agent.
- [x] Add a small state hook, likely `useSubagents(sessionId)`, that merges initial snapshot data with live `chat.subagent.*` events.
- [x] Handle session migration by following `chat.session_migrated` and reloading sub-agent snapshots for the new session id.
- [x] Handle `bus.reconnected` by refetching snapshots and reconciling statuses without duplicating events.
- [x] Keep updates coalesced enough that parallel sub-agents with busy tool loops do not cause chat list jank.
- [x] Add frontend tests for event merge behavior, duplicate suppression, status ordering, reconnect recovery, and selected-subagent preservation.

## Phase 5: Codex-Style Right Sidebar UI

- [x] Refactor `ChatPage.tsx` so the right-hand area exposes sub-agents as a first-class sidebar tab alongside Files, Terminal, Preview, and Changes.
- [x] Build `SubagentsAtGlance` with the screenshot's row density, section label, divider, glyph, name, muted status text, and hover/click states.
- [x] Build `SubagentGlyph` with deterministic color/glyph variants matching the screenshot direction: yellow, purple, orange, red, then additional accessible variants.
- [x] Add compact empty/hidden rules: hide the section when there are no sub-agents; show a small pending state when delegation is starting but no child id exists yet.
- [x] Build `SubagentDetailPanel` for expanded mode with header tab, close button, elapsed timer, task card, transcript, and status footer.
- [x] Reuse `Markdown`, `ToolCallBubble`, `ReasoningBubble`, `StatusPill`, and `PromptBar` visual patterns where possible.
- [x] Decide and implement v1 interactivity: read-only transcript plus stop button, or direct follow-up prompt routed to the child. If follow-up is included, add backend routing and tests in Phase 3 before enabling the prompt.
- [x] Make the expanded panel resizable with the existing `ResizeDivider` behavior and persist the width separately from workspace panel width.
- [x] Ensure workspace tabs (`Files`, `Terminal`, `Preview`, `Changes`) and sub-agent expanded view do not fight for the same right-panel state.
- [x] On mobile/tablet widths, replace the split view with a full-screen drawer or modal sheet that preserves the main chat route.
- [x] Match the screenshot's dark, quiet UI: compact typography, muted dividers, 8px or smaller radii, no nested cards, no decorative gradients.
- [x] Add loading, no transcript, failed, interrupted, and completed states.
- [x] Add accessibility labels, keyboard navigation for sub-agent rows, Escape-to-close, and focus restoration.

## Phase 6: Main Thread Integration

- [x] Add a subtle inline chat event when the parent creates a child, similar to `Created an agent`, without duplicating all child transcript content in the main thread.
- [x] When `delegate_task` runs multiple tasks, make each row show the delegated task title rather than only `Worker 1`.
- [x] Show parent-level aggregate progress in the compact sidebar: number working, completed, failed.
- [x] Add a `Subagents` badge/count to the chat header when the compact sidebar is closed.
- [x] Make parent interrupt/redirect clearly update child rows to `stopping` then `stopped` or `interrupted`.
- [x] Verify context compression does not lose active sub-agent UI state.

## Phase 7: CLI, Gateway, And ACP Compatibility

- [x] Keep existing CLI spinner tree output working while adding lifecycle callbacks.
- [x] Keep gateway text progress concise; do not flood messaging platforms with full child transcripts unless explicitly requested later.
- [x] Decide whether ACP should receive structured sub-agent events; if yes, extend `src/acp_adapter/events.py` with compatible notifications.
- [x] Update docs in `docs/building/agent-loop.md`, `docs/building/tools-runtime.md`, and `docs/configuration.md` to describe first-class sub-agent lifecycle and limits.
- [x] Add a short user-facing docs section describing how to ask Spark to delegate work and where to inspect sub-agents in the web UI.

## Phase 8: Testing And Verification

- [x] Run targeted Python tests for delegation: `source venv/bin/activate` then `python -m pytest tests/tools/test_delegate.py tests/agent/test_subagent_progress.py -q`.
- [x] Run targeted web-server tests: `source venv/bin/activate` then `python -m pytest tests/spark_cli/test_web_server_events.py -q`.
- [x] Run chat/frontend tests from `src/spark_cli/web`: `npm test -- --run` or the repo's existing focused test command.
- [x] Run `npm run build` in `src/spark_cli/web` to catch TypeScript and Vite integration issues.
- [x] Manually test a single delegated task and a parallel batch from the web UI.
- [x] Manually test reload during delegation, event-bus reconnect, parent stop, child failure, and completed transcript restore.
- [x] Use Playwright screenshots for desktop compact, desktop expanded, and mobile drawer states, comparing against the three reference screenshots.
- [x] Run `graphify update .` after implementation so the project graph stays current.

## Rollout Notes

- [x] Gate the UI behind a config flag such as `dashboard.subagents_sidebar` until backend snapshots and reload behavior are stable.
- [x] Keep all new API payloads additive so old clients ignore them.
- [x] Avoid changing the parent prompt/system prompt after a conversation starts; sub-agent visibility is UI state, not parent context mutation.
- [x] Bound transcript event retention for noisy tool output, and rely on existing full tool-result retrieval for deep inspection.
- [x] Add logging around lifecycle creation/update failures, but never let UI event persistence failure fail the actual delegated task.

## Definition Of Done

- [x] Asking Spark to delegate one or more tasks creates visible sub-agent rows in the compact right sidebar.
- [x] Clicking a sub-agent opens an expanded right pane with its task, live transcript, tool activity, status, and final summary.
- [x] The UI recovers correctly after reload or SSE reconnect.
- [x] Parent interrupt stops active children and updates the UI.
- [x] Existing CLI/gateway delegation behavior remains compatible.
- [x] Targeted backend, web-server, and frontend tests pass.
