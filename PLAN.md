# Spark UI Improvement Plan

Date: 2026-06-19

This plan has been audited against the current codebase. It lists only new work
or missing deltas; features that already exist have been removed from the action
items.

## Product Constraints

- Chat remains the default home surface.
- Keep the current split between standalone Chat threads and Project threads.
- Project work stays inside Chat through the project right panel; do not revive a
  separate Workspace page.
- Keep Skills, Tools, Messaging, and Connectors as separate user-facing areas.
- Keep Files in both places: the Chat/project panel for context, and the top-level
  Files page for broader storage management.
- Treat Canvas and Tasks as artifacts of Chat/project work. A focused Canvas can
  replace the main Chat view, but users must have an easy Chat/Canvas toggle for
  the originating thread. Tasks should live in the right sidebar and expand only
  when needed.
- Treat Subagents as contextual child threads. Show them in the same right-side
  task/sidebar pattern, and let users inspect a subagent thread there while the
  parent Chat thread remains visible in the main center pane.
- Browser and macOS desktop should use the same React UI and visual tokens; the
  desktop app should differ only through native affordances such as tray, global
  shortcut, notifications, native preview, and diagnostics.
- Preserve prompt caching: do not change active toolsets, memories, or system
  prompt structure mid-conversation.

## Phase 0 - Shared UI Contract

Goal: give TUI, Web UI, and macOS one vocabulary for agent runs without changing
the agent prompt contract.

Actions:

1. Add a UI architecture note defining shared run-state terms: active turn, phase,
   tool timeline item, pending approval, background job, artifact, project, task,
   subagent, notification, diagnostic event.
2. Map those terms onto the existing surfaces:
   - TUI callbacks, status bar, and future retained transcript store.
   - Web SSE topics, `ChatPanel`, project panel, and session store.
   - Desktop tray, notifications, deep links, and sidecar diagnostics.
3. Define which state may be persisted locally per profile, per project, per
   thread, or per browser window.
4. Refresh docs and screenshots after the first implementation slice so the docs
   stop describing older dashboard shapes.

High-impact files:

- `docs/web-dashboard.md`
- `docs/desktop-webview-diagnostics.md`
- `src/spark_cli/web/README.md`
- `src/spark_cli/web/src/hooks/useEventBus.ts`
- `src/core/cli/callbacks_mixin.py`

## Phase 1 - Navigation And Information Architecture

Goal: make the current app structure visible and intentional.

Actions:

1. Rework `App.tsx` navigation groups so expanded desktop and mobile navigation
   no longer bury core work surfaces in `More`:
   - Work: Chat, Files, Canvas, Tasks.
   - Capabilities: Skills, Tools, Messaging, Connectors.
   - Operations: Schedule, Logs/Analytics, Settings.
2. Keep the collapsed sidebar compact, but make `More` a collapsed/overflow
   behavior rather than the default home for Chat, Canvas, Tasks, and Schedule.
3. Rename remaining reader-facing "Workspace" labels that actually mean Project
   or Chat project panel. Keep "workspace" only for filesystem/project storage.
4. Extend the existing command palette only where coverage is missing:
   - file and canvas targets
   - settings-section deep links
   - common actions such as connect provider, start preview, open logs, toggle
     skill, and copy diagnostics
5. Add a page-level empty-state standard for primary pages:
   - one primary action
   - recent relevant items
   - one setup or health warning when applicable
   - no generic marketing copy

High-impact files:

- `src/spark_cli/web/src/App.tsx`
- `src/spark_cli/web/src/components/CommandPalette.tsx`
- `src/spark_cli/web/src/lib/globalNavigation.ts`
- `src/spark_cli/web/src/i18n/en.ts`
- `src/spark_cli/web/src/components/chat/FeedbackForm.tsx`

## Phase 2 - Web Chat Workbench Deltas

Goal: finish the missing workbench pieces around Chat's project panel.

Actions:

1. Extract the inline Chat page pieces into focused modules:
   - `NewSessionHero`
   - `ProjectThreadCompose`
   - `WorkspaceRightPanel`
   - `RightPanelSwitcher`
   - `SimpleFileViewer`
   - project-panel persistence hooks
2. Extend the existing right panel with Activity and Artifacts tabs:
   - Activity groups live/contextual work: Tasks, Subagents, approvals, and key
     run events.
   - For Project threads, Activity is always visible.
   - For standalone Chat threads, Activity appears only after the thread has a
     task, subagent, approval, or artifact-linked event.
   - Tasks always appear inside Activity for Project threads with a lightweight
     empty state.
   - Standalone Chat threads show Activity task rows only after task artifacts
     exist.
   - Subagents appear inside Activity as running/completed child work spawned by
     the active thread.
   - Each subagent Activity row shows compact live status by default: name,
     status, model, duration, and current tool.
   - Expanding a subagent row shows the latest child message/tool activity inline.
   - Clicking a subagent opens its child chat thread in the right panel, so the
     parent Chat thread remains visible in the center pane.
   - Artifacts holds durable outputs such as canvases, generated files, and other
     reusable work products.
   - Persist selected activity/artifact state per project/thread, in addition to
     the existing tab and width persistence.
3. Harden project terminals:
   - reconnect to an existing project shell when returning to Chat
   - avoid killing a useful shell on brief navigation away from the page
   - retain enough run identity for dev servers and shell history to survive UI
     remounts where possible
4. Add a collapsed run timeline rail to `ChatPanel`:
   - tool call sequence
   - approvals
   - errors
   - files changed
   - agent-triggered terminal commands
   - previews started
   - subagent start/progress/completion events
5. Add artifact actions for generated outputs beyond brief promotion:
   - save as file
   - open in Canvas
   - create Task
   - attach result to next turn
6. Make Canvas artifact focus mode replace the main Chat view when active, with
   an obvious toggle back to the source Chat thread.
7. Add stale attached-file detection in the context tray so users can refresh or
   remove file context that changed after attachment.
8. Improve render diagnostics:
   - explain why safe mode enabled and what it disabled
   - expose markdown render time, token batching, and long-task counters
   - add a copy diagnostic bundle button for stuck turns
   - include subagent lineage, child thread IDs, and child tool traces when a
     delegated run fails or stalls

High-impact files:

- `src/spark_cli/web/src/pages/ChatPage.tsx`
- `src/spark_cli/web/src/components/ChatPanel.tsx`
- `src/spark_cli/web/src/components/chat/*`
- `src/spark_cli/web/src/components/workspace/*`
- `src/spark_cli/web/src/lib/context.ts`
- `src/spark_cli/web/src/lib/renderHealth.ts`
- `src/spark_cli/web/src/lib/sessionStore.tsx`
- `src/tools/delegate_tool.py`
- `src/tools/session_search_tool.py`
- `src/spark_cli/workspace_routes.py`

Verification gates:

- `npm run test`
- `npm run lint`
- `npm run build`
- Add mocked Playwright smoke tests for Chat, project panel tabs, prompt send,
  SSE reconnect, and long-history virtualization.

## Phase 3 - TUI Retained Mode

Goal: make the terminal experience a real retained interface while keeping the
current scrollback renderer as the default until the new mode is proven.

Actions:

1. Introduce a `TuiTranscriptStore` fed by existing streaming/tool callbacks:
   - user messages
   - assistant deltas
   - reasoning previews
   - tool start/end
   - approvals/clarifications
   - background process updates
2. Add an opt-in retained transcript viewport above the existing input/status
   region:
   - scrollable current-session history
   - compact tool timeline rows
   - collapsible reasoning and tool result blocks
   - search within current session
   - jumps to last user message, last tool error, and last approval
3. Preserve the current scrollback renderer as compatibility mode.
4. Extend the status bar beyond the existing model/context/cost basics:
   - active tool or active phase
   - queued/interrupt mode
   - background jobs
5. Add a TUI command palette overlay for models, skills, toolsets, sessions, and
   common config toggles.
6. Make approval, clarify, sudo, and secret prompts share one modal panel renderer
   with consistent keyboard behavior.
7. Add narrow-terminal layout personas:
   - under 52 columns: one-line status, no decorative chrome
   - 52-80 columns: compact transcript rows
   - 80+ columns: full transcript plus side metadata

High-impact files:

- `src/core/cli/__init__.py`
- `src/core/cli/tui_mixin.py`
- `src/core/cli/status_bar_mixin.py`
- `src/core/cli/streaming_mixin.py`
- `src/core/cli/callbacks_mixin.py`
- `src/agent/display.py`

Verification gates:

- Unit tests for transcript store ordering.
- Golden-frame tests for 48, 80, and 120 column layouts.
- Regression tests for resize ghosting, image paste badges, busy input mode,
  approvals, and model picker.
- Manual SSH/tmux smoke test.

## Phase 4 - macOS Native Layer Deltas

Goal: make the desktop app useful while the main window is hidden, without
forking the browser UI.

Actions:

1. Replace the global shortcut's main-window toggle with a Quick Ask flow:
   - small always-on-top composer
   - choose project/thread
   - paste screenshot/file
   - submit in background or expand to full Chat
2. Upgrade the tray/menu-bar companion from a status tooltip/menu into an activity
   center:
   - active turn count
   - current running tool
   - background jobs
   - last completed thread
   - quick actions: New Chat, Quick Ask, Open Tasks, Pause Gateway, Copy
     Diagnostics, Quit
3. Make native notifications deep-link to exact UI targets:
   - thread completion -> source thread
   - task review -> task artifact
   - preview ready -> project preview
   - approval requested -> active approval card
4. Add sidecar recovery UI:
   - detect port conflict on 9119 and show a recovery screen
   - offer restart sidecar
   - expose sidecar logs in the app
   - surface `/api/diagnostics/webview` from Settings
5. Add an "ask agent about current preview" primary control to the preview panel.
6. Improve desktop onboarding:
   - explain the local sidecar and dashboard token briefly
   - request notification permission at the moment it becomes useful
   - explain the global shortcut
   - explain desktop-use permissions only when enabling computer-use
7. Raise release quality:
   - signing/notarization plan
   - update channel clarity
   - crash/diagnostics bundle
   - DMG install friction review

High-impact files:

- `src/spark_cli/web/src-tauri/src/lib.rs`
- `src/spark_cli/web/src/lib/desktop.ts`
- `src/spark_cli/web/src/lib/nativePreview.ts`
- `src/spark_cli/web/src/components/workspace/WorkspacePreviewPanel.tsx`
- `src/spark_cli/web/src/components/NotificationBell.tsx`
- `src/spark_cli/web/src/components/OnboardingWizard.tsx`
- `src/spark_cli/web_server.py`
- `src/spark_cli/desktop_gateway.py`
- `scripts/build_desktop.sh`

Verification gates:

- `npm run desktop:build` from `src/spark_cli/web`
- `scripts/build_desktop.sh`
- Launch app and confirm sidecar start, `/api/status`, gateway autostart, app
  exit sidecar cleanup, tray actions, global shortcut, deep links, native
  notifications, and diagnostics visibility.

## Phase 5 - Guided Health And Diagnostics

Goal: connect the existing Admin, Status, setup, and diagnostics pieces into one
actionable health path.

Actions:

1. Add a Settings health summary that routes to the existing detailed pages:
   - model/provider
   - dashboard auth
   - gateway
   - memory
   - desktop app
   - MCP/connectors
   - preview backend
2. Turn health warnings into direct repair actions or guided wizards where the
   detailed page has the required controls.
3. Add test-connection buttons only for credential surfaces that still lack one.
4. Standardize local UI diagnostics:
   - active turn started/ended
   - first token latency
   - SSE reconnect count
   - dropped event count
   - markdown long-task count
   - sidecar startup time
   - preview startup time
5. Add copy diagnostic bundle entry points in Web UI, macOS tray, and TUI status.
6. Make terminal `/status` and Web Settings Status report the same health
   concepts.

High-impact files:

- `src/spark_cli/web/src/components/SettingsPanel.tsx`
- `src/spark_cli/web/src/pages/AdminPage.tsx`
- `src/spark_cli/web/src/pages/StatusPage.tsx`
- `src/spark_cli/web/src/pages/ConfigPage.tsx`
- `src/spark_cli/web/src/pages/EnvPage.tsx`
- `src/core/cli/info_mixin.py`
- `src/spark_cli/doctor.py`
- `src/spark_cli/web_server.py`

## Phase 6 - Shared Design Tokens And Accessibility

Goal: make TUI, browser, and macOS feel like siblings without creating a separate
desktop theme.

Actions:

1. Define a compact Spark UI token map:
   - surface colors
   - accent colors
   - semantic colors
   - spacing
   - radius
   - typography scale
   - terminal equivalents
2. Document or generate mappings between:
   - Web CSS variables in `src/spark_cli/web/src/index.css`
   - CLI skin fields in `src/spark_cli/skin_engine.py`
   - Tauri loading screen styles in `src/spark_cli/web/src-tauri/loading/*`
3. Add a performance/focus setting for the cursor-following glow so it can be
   reduced or disabled without changing the product theme.
4. Standardize labels and icons across surfaces for Chat/thread, Project/files,
   Tasks, Schedule, Capabilities, Messaging, and Settings.
5. Add accessibility checks for:
   - visible focus states
   - keyboard navigation
   - reduced motion
   - sufficient contrast
   - no hover-only access to critical actions

High-impact files:

- `src/spark_cli/web/src/index.css`
- `src/spark_cli/skin_engine.py`
- `src/core/cli/tui_mixin.py`
- `src/core/cli/status_bar_mixin.py`
- `src/spark_cli/web/src/components/ui/*`
- `src/spark_cli/web/src-tauri/loading/*`

## Phase 7 - Documentation And Release Verification

Goal: ship the UI work as a coherent product upgrade, not a hidden refactor.

Actions:

1. Update docs to match the current product model:
   - `docs/cli/index.md`
   - `docs/integrations/web-dashboard.md`
   - `docs/web-dashboard.md`
   - `docs/desktop-webview-diagnostics.md`
   - `src/spark_cli/web/README.md`
2. Add a UI architecture doc covering shared run state, Web SSE bus, TUI
   callbacks, desktop bridge, and the Project/Chat relationship.
3. Add a small screenshot smoke harness with mocked API data before refreshing
   baseline screenshots.
4. Add visual screenshots for desktop and mobile widths after Phase 1 and Phase 2.
5. Write a migration note if navigation labels or placement change.
6. Keep ADRs sparse. Add one only if the shared run-state contract becomes a
   cross-surface API that affects CLI, Web UI, desktop, and gateway.

## Suggested Execution Order

1. Navigation and terminology cleanup.
2. Chat workbench deltas: extracted modules, Activity/Artifacts tabs,
   right-panel child-thread viewer, run timeline, Canvas toggle, terminal
   hardening.
3. macOS native deltas: Quick Ask, tray activity center, notification deep links,
   sidecar recovery.
4. TUI retained mode behind config.
5. Health summary, diagnostics bundle, shared design tokens, docs, and screenshot
   smoke tests.

## Success Metrics

- Expanded navigation makes Chat, Files, Canvas, and Tasks directly reachable.
- Returning users can resume the right thread/project in under 10 seconds.
- Active Canvas can replace Chat while preserving an obvious return path.
- Project tasks are visible from Project threads without leaving Chat.
- Running and completed subagents are visible in the right sidebar, and a user can
  expand recent child activity or inspect a full child subagent thread without
  losing the parent Chat thread in the center pane.
- Project terminal survives ordinary tab switches and brief navigation away.
- First token latency, SSE reconnects, long tasks, sidecar startup, and preview
  startup are visible in diagnostics.
- TUI retained mode remains readable at 48, 80, and 120 columns.
- Desktop global shortcut opens Quick Ask without requiring the main window first.
- Every background completion or approval notification can deep-link to the exact
  UI target.
- Docs and screenshots match the shipped navigation.
