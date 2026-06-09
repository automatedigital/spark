# PLAN — Hermes-style Web/Desktop UI + Simplified Skills & Tools

Goal: re-skin the Spark web UI and desktop app to match the **Hermes Agent Desktop**
layout in `screenshots/`, and rebuild Skills & Tools so that connecting external
apps (MCPs, CLIs, connectors, messaging) is effectively **1-click** for non-technical users.

Reference screenshots live in `screenshots/` (note: lowercase). Target layout:
- **Sidebar (top→bottom):** New session · Skills & Tools · Messaging · Artifacts · Search sessions… · Pinned · Sessions (grouped by project workspace) · **Settings pinned to bottom**.
- New-session screen = centered "HERMES AGENT" wordmark + a single "Start with a goal" composer.
- Skills & Tools = flat searchable list grouped by category, each row a one-line toggle.
- Messaging = left list of ~25 platforms, right detail pane with Required/Recommended/Advanced fields + Save.
- Artifacts = All / Images / Files / Links tabs with empty-state.

Current state (for reference):
- Global nav is an icon rail in `src/spark_cli/web/src/App.tsx` (`NAV_ITEMS`: chat, files, canvas, kanban, cron, skills, connectors). Settings is a **modal** (`SettingsPanel.tsx`), already bottom-anchored.
- Session list / search / pinned currently live **inside** `pages/ChatPage.tsx`'s own left sidebar — needs to be hoisted to the global sidebar.
- Skills: `pages/SkillsPage.tsx` (+ `/api/skills`). Connectors: `pages/ConnectorsPage.tsx` (+ `/api/connectors`, `gateway/connectors_routes.py`, `google_connector.py`, `oauth_connectors.py`).
- Messaging platforms exist in `src/gateway/platforms/` (telegram, discord, slack, matrix, whatsapp, signal, bluebubbles, homeassistant, email, sms, dingtalk, feishu, wecom, weixin, qqbot, webhook, api_server) but have **no dedicated web page** yet (configured via gateway config).

---

## Phase 0 — Reference & scaffolding

- [ ] Clone Hermes Agent for reference into a scratch dir: `git clone https://github.com/nousresearch/hermes-agent /tmp/hermes-agent-ref` (read-only; do not vendor wholesale).
- [ ] Document in this file which Hermes components/layouts/styles we mirror vs. reimplement (license check before copying any code).
- [ ] Capture baseline screenshots of the current Spark web UI (chat, skills, connectors, settings) for before/after comparison.
- [ ] Confirm `npm run dev` works in `src/spark_cli/web/` and the dev server renders against the local gateway.

## Phase 1 — Global sidebar restructure (`App.tsx`)

- [ ] Replace `NAV_ITEMS` icon rail with the Hermes section order: New session, Skills & Tools, Messaging, Artifacts.
- [ ] Add **New session** action button at the top (resets chat to a fresh thread; reuse existing `spark-new-chat` CustomEvent path).
- [ ] Add **Search sessions…** input directly into the global sidebar (hoist search logic out of `ChatPage`).
- [ ] Add **Pinned** section header + pinned-session list to the global sidebar.
- [ ] Add **Sessions** section grouped by **project workspace** (use existing `WorkspaceProject` / `SessionInfo` from `lib/api.ts`); show "No workspace" group for ungrouped sessions.
- [ ] Keep **Settings** pinned to the bottom of the sidebar (retain modal trigger via `setSettingsOpen`).
- [ ] Preserve collapse/expand + hover-expand behavior already in `App.tsx`.
- [ ] Wire sidebar session click → navigate to chat + load that session (replace ChatPage-internal selection).
- [ ] Remove the now-duplicated session list/search/pinned UI from `ChatPage.tsx` (ChatPage becomes the thread view only).
- [ ] Move `chat`, `files`, `canvas`, `kanban`, `cron` out of the primary rail into a secondary location (command palette + a "More" menu or workspace tabs) so the primary sidebar matches Hermes exactly.
- [ ] Update mobile nav in `App.tsx` header to mirror the new sections.
- [ ] Update `i18n/en.ts` + `i18n/types.ts` nav labels (newSession, skillsAndTools, messaging, artifacts) and any other locales.

## Phase 2 — New-session screen

- [ ] Build centered hero: large serif "SPARK" (or "HERMES AGENT"-equivalent) wordmark + subtitle ("Type a task, question, or snippet…").
- [ ] Bottom-centered composer "Start with a goal" with mic + send affordances (reuse `components/chat/PromptBar.tsx`).
- [ ] Show this hero when no active session is selected; on first send, create a session and transition to the thread view.
- [ ] Match dark background + subtle texture from screenshots (reuse existing `noise-overlay` / `warm-glow`).

## Phase 3 — Skills & Tools (merged page)

- [ ] Create a unified **Skills & Tools** page with two top tabs: **Skills** and **Toolsets** (matches `skills-and-tools.png`).
- [ ] Render skills as a flat, searchable, category-grouped list; each row = name + one-line description + a right-aligned toggle (`ui/switch.tsx`).
- [ ] Top category filter chips with counts (Apple, Autonomous-AI-Agents, Creative, … Software-Development), like the screenshot.
- [ ] Add `Search skills…` input + refresh control top-right.
- [ ] Fold **Connectors** into this page reworded as **Tools** (plugins + connectors to external apps). Connectors are tools that "connect" to other apps.
- [ ] Each connectable tool shows a **Connect** / **Connected** state; connecting auto-enables the related skills/toolset.
- [ ] Keep existing `/api/skills` + `/api/connectors` data sources; add a combined view-model in `lib/api.ts` if needed.

## Phase 4 — 1-click connections (the core UX goal)

- [ ] Audit existing connect flows in `gateway/connectors_routes.py`, `google_connector.py`, `oauth_connectors.py` (OAuth device-flow + token paste already exist).
- [ ] Design a single **"Connect"** affordance per app: OAuth where available (Google, GitHub, Slack, Notion, etc.), device-flow fallback, token-paste last resort — all behind one button with progressive disclosure.
- [ ] On successful connect, **auto-enable** the matching skill(s)/toolset and surface a toast ("Gmail connected — email skills enabled").
- [ ] Add a connectors→skills mapping (which skills/toolsets light up per connector) and persist enablement.
- [ ] Add MCP servers as connectable tools: surface MCP registry / one-click add (leverage existing MCP settings tab) inside Skills & Tools.
- [ ] Add CLI-backed tools (claude-code, codex, opencode) as toggle rows with a "detected/not detected" state and an install hint.
- [ ] Ensure disconnect/revoke is one click and disables dependent skills (with confirmation).
- [ ] Add empty/needs-setup states with clear copy aimed at non-technical users.

## Phase 5 — Messaging page

- [ ] Create `pages/MessagingPage.tsx`: left scrollable list of platforms with icon + name + connected dot; right detail pane.
- [ ] Source the platform list from `src/gateway/platforms/` (telegram, discord, slack, mattermost, matrix, whatsapp, signal, bluebubbles, homeassistant, email, sms/twilio, dingtalk, feishu/lark, wecom, wechat, qqbot, api_server, webhooks, irc, line, etc.).
- [ ] Detail pane sections: status chips (Disabled / Needs setup / gateway state), "Get your credentials" help + setup-guide link, **Required** fields, **Recommended** fields, collapsible **Advanced**, enable toggle, **Save changes**.
- [ ] Add `/api/messaging` (or extend gateway config endpoints) to read/write per-platform credentials + enabled state; reuse existing gateway config plumbing (`gateway/config.py`, `display_config.py`).
- [ ] Wire Save → restart/refresh the relevant gateway channel (`gateway/restart.py`).
- [ ] Add `Search messaging…` filter for the platform list.

## Phase 6 — Artifacts page

- [ ] Create `pages/ArtifactsPage.tsx` with tabs **All / Images / Files / Links** (each with a live count).
- [ ] Aggregate artifacts produced by sessions (generated images, file outputs, links) — define/extend an `/api/artifacts` endpoint backed by workspace files + session outputs.
- [ ] Empty state: "No artifacts found — Generated images and file outputs will appear here as sessions produce them."
- [ ] Grid/list rendering with type filtering; click opens the artifact (image preview, file download, link out).

## Phase 7 — Settings panel parity

- [ ] Verify the existing `SettingsPanel.tsx` sections match the reference (Model, Chat, Appearance, Workspace, Safety, Memory & Context, Voice, Advanced, Providers, Gateway, Tools & Keys, MCP, Archived Chats, About).
- [ ] Adjust labels/grouping/ordering to match `settings-*.png` screenshots where they differ.
- [ ] Keep Settings reachable from the sidebar bottom; confirm modal styling matches dark minimal aesthetic.

## Phase 8 — Visual polish / theme

- [ ] Tune spacing, type scale, and muted palette to match Hermes minimal/sleek look across all new pages.
- [ ] Confirm status bar at bottom (Gateway ready · Agents · Cron · model · version) matches screenshots.
- [ ] Verify dark mode + responsive (use `preview_resize`) for sidebar collapse, messaging split, artifacts grid.

## Phase 9 — Desktop app parity

- [ ] Verify Tauri shell (`isTauri()` paths in `App.tsx`) renders the new layout identically.
- [ ] Confirm tray "new chat" + `spark://` deep links still route correctly after sidebar refactor.
- [ ] Rebuild the macOS app via `/build-mac` and smoke-test the new UI in the packaged app.

## Phase 10 — Verification & ship

- [ ] Run the dev server and verify each page via preview tools (snapshot + screenshot): new-session, skills & tools, messaging, artifacts, settings.
- [ ] `ruff check src/` and `mypy src/agent/ src/spark_cli/` clean for any backend additions.
- [ ] `python -m pytest tests/ -m "not slow" -q` green (add tests for new `/api/messaging` + `/api/artifacts` routes).
- [ ] Build the web bundle and confirm `web_dist/` is regenerated.
- [ ] Before/after screenshots attached; open a PR from a feature branch (never push to main).

---

### Decisions (locked)
- **Demoted pages:** `chat/files/canvas/kanban/cron` stay reachable but move off the primary sidebar → command palette (Cmd+K) + a secondary "More" menu. Primary sidebar matches Hermes exactly.
- **Branding:** keep **Spark** identity (wordmark + name), but use the Hermes centered-serif + bottom-composer layout from the screenshots.

### Open questions (resolve while building)
- [ ] Artifacts backing store: derive from workspace files only, or add a dedicated artifact index? — default: derive first, index later if needed.
