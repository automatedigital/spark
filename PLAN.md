# PLAN - 120626

Source: `screenshots/120626/` — four screenshots covering 2 bugs and 2 UI changes in the web UI / agent core.

## Execution notes (for agents working this plan)

- One feature branch + PR per numbered item — never push to main. Check off boxes in this file as you complete them.
- **Parallel-safe:** items 1, 3, 4 are independent of each other and of item 2.
- **Sequencing:** item 2 must complete (through "agent tools" + "graceful error state") before any 2b work starts — 2b builds on the agent-browser backend, not the Playwright one. Within 2b, "Streaming quality" and "Agent efficiency" come first; collaboration/chrome polish after.
- Item 2's first checkbox is a **spike with a decision**: write up the chosen integration approach (see below) at the top of the item before implementing the rest.
- Env: use `.venv` (not anaconda) for pytest/ruff. Frontend lives in `src/spark_cli/web/` (Vite/React); rebuild `web_dist` to verify built-app behavior.

## 1. Loop guard: recover instead of abandoning the task

**Screenshot:** `bug_Detected 3 consecutive identical 'process' calls...png`

Investigated: the guard (`src/core/run_agent/__init__.py:~9750`) already compares tool name **and** JSON-serialized arguments, so it only fires on three truly identical calls — the detection itself is fine. The real problem is the recovery: when it trips, the turn hard-breaks (`_turn_exit_reason = "tool_loop_detected"`) and the task is silently left incomplete.

- [ ] Change the guard's behavior from "stop the turn" to "intervene": on detection, inject a tool-result/system note telling the model its last N calls were identical and to change approach, and let the conversation continue. Only hard-stop if it trips a second time in the same turn.
- [ ] Make sure the stop (if it still happens) is clearly surfaced as an incomplete task in the UI, not just an inline warning line.
- [ ] Tests: identical-call loop gets one recovery nudge then continues; double-trip still terminates.

## 2. Browser backend: migrate preview tab to agent-browser (shared with the agent)

**Screenshot:** `preview_error_501...png` (current Playwright backend errors with 501 "Playwright is not installed" + broken-image placeholder)

Goal: one browser instance that (a) renders/streams into the WebUI Preview tab and (b) the agent can drive directly (navigate, click, fill, read) so it can browse the web and operate web apps. Replace the current Playwright sync-API streamer in `src/spark_cli/preview_browser.py` with [vercel-labs/agent-browser](https://github.com/vercel-labs/agent-browser).

- [ ] **Spike (decide before implementing):** agent-browser is a Node-based CLI/daemon driving Chromium over CDP, while Spark's backend is Python. Choose the integration mechanism — (a) Python shells out to the `agent-browser` CLI per command, (b) Python talks to the agent-browser daemon directly, or (c) Python attaches to the same Chromium over CDP for streaming while agent tools use the CLI. Must support: screenshot streaming + input forwarding for the preview pane (`workspace_routes.py` endpoints), and agent tool calls against the same session. Document the decision + rationale here before proceeding.
- [ ] Keep per-workspace persistent profiles (`SPARK_HOME/browser/<slug>`) so logins survive restarts — map onto agent-browser sessions/profiles.
- [ ] Add agent tools (`src/tools/`, registered per CLAUDE.md 3-file pattern) that drive the *same* browser session: navigate, click, type, snapshot/read page, screenshot — so what the agent does is visible live in the Preview tab.
- [ ] Installation/bootstrap: detect missing agent-browser/Chromium and offer install (one-click in UI + `spark doctor` check) instead of a raw 501 JSON blob and broken `<img>`.
- [ ] Graceful error state in the preview pane when the backend is unavailable (hide the `<img>`, show message + install action).
- [ ] Remove/deprecate the Playwright dependency path once parity is confirmed (or keep as fallback behind a config flag).

### 2b. Preview tab "top-tier" upgrades

**Depends on item 2 being merged** — all of this targets the agent-browser backend. Do not build against the Playwright streamer.

**Streaming quality**
- [ ] Replace polled screenshot frames with CDP screencast (push frames) — lower latency, smoother scrolling; consider WebRTC later if needed.
- [ ] Proper input parity: keyboard shortcuts, scroll momentum, right-click, file upload dialogs, clipboard in/out.

**Browser chrome**
- [ ] URL bar with back/forward/reload, multiple tabs, pop-out to a larger window/fullscreen.
- [ ] Responsive presets (mobile/tablet/desktop) + dark-mode emulation toggle for testing.
- [ ] Download handling (files land in the workspace, surfaced in Files tab).

**Agent ⇄ user collaboration**
- [ ] "Follow agent" mode: when the agent drives, show a visible cursor + highlight on elements it clicks/types into, so the user can watch.
- [ ] Take-over/pause: user can grab control mid-task (e.g. to solve a login/CAPTCHA), then hand back to the agent.
- [ ] Element picker: user clicks an element in the preview → a structured reference (selector + screenshot crop) is inserted into chat ("fix this button").
- [ ] One-click "send screenshot to chat" and short GIF/flow recording for bug reports.

**Dev-loop integration**
- [ ] Console + network errors from the previewed page auto-available to the agent (and a visible console drawer for the user) — closes the edit→reload→check loop.
- [ ] Auto-detect running dev servers (common ports / process scan) and offer them in the URL bar; auto-reload on HMR where possible.

**Agent efficiency & safety**
- [ ] Give the agent an accessibility-tree / DOM snapshot tool, not just screenshots — far cheaper in tokens and more reliable for clicking (agent-browser supports this natively via refs).
- [ ] Action log: every agent browser action recorded and visible in the pane (auditable transcript).
- [ ] Permission gates for sensitive actions: submitting payments, sending messages, logging into new domains — pause and ask the user.

## 3. UI: collapsible Sessions + "No Workspace" chat sections in sidebar

**Screenshot:** `add collapseable option on sessions + old workspace chats...png`

The sidebar's SESSIONS list (workspace folders) and the "NO WORKSPACE" list of old chats are both always fully expanded, making the sidebar very long.

- [x] Component: `src/spark_cli/web/src/components/sidebar/SidebarSessions.tsx` (the "No workspace" section is at ~line 458).
- [x] Rename the "NO WORKSPACE" section label to "CHATS".
- [x] Make the SESSIONS section header and the CHATS section header collapsible (chevron + click-to-toggle), persisting collapsed state (localStorage or existing UI-state store).
- [x] Keep individual workspace folders' existing expand/collapse behavior; this adds collapse at the *section* level.

## 4. UI: empty-state hero logo too dark on dark theme

**Screenshot:** `logo-too-dark_USE-icon_small-dark-png...png`

On the dark theme, the big Spark logo on the empty chat screen is nearly invisible (too dark against the dark background). Confirmed fix: dark themes should use `icon_small-dark.png`.

- [x] Hero logo renders via `BrandLogo` in `src/spark_cli/web/src/pages/ChatPage.tsx:145`; asset selection logic is in `src/spark_cli/web/src/components/BrandLogo.tsx:12`.
- [x] Update `BrandLogo.tsx` so dark themes use `/icon_small-dark.png` (and light themes the other asset). The code comment claims names are inverted — visually verify both PNGs in `src/spark_cli/web/public/` and correct the comment + `LIGHT_THEMES` mapping to match reality.
- [x] Verify in the built app (`web_dist` / desktop build) on dark theme, not just dev.
- [x] Check other BrandLogo / icon usages (`index.html` loading screen, favicon) for the same issue.

## Verification

- [ ] `python -m pytest tests/ -q` (use `.venv`, not anaconda)
- [ ] `ruff check src/` on touched files
- [ ] Visual check of sidebar collapse + logo in dark theme via preview
