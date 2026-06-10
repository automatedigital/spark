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

- [x] Clone Hermes Agent for reference into a scratch dir: `git clone https://github.com/nousresearch/hermes-agent /tmp/hermes-agent-ref` (read-only; do not vendor wholesale).
- [x] Document in this file which Hermes components/layouts/styles we mirror vs. reimplement (license check before copying any code).
- [x] Capture baseline screenshots of the current Spark web UI (chat, skills, connectors, settings) for before/after comparison.
- [x] Confirm `npm run dev` works in `src/spark_cli/web/` and the dev server renders against the local gateway.

**Phase 0 notes:**
- Hermes Agent is MIT-licensed (Nous Research, 2025) — copying code is permitted with license attribution; we still reimplement rather than vendor.
- Reference UI lives at `/tmp/hermes-agent-ref/apps/desktop/src` (pages, `components/pane-shell`, chat) and `/tmp/hermes-agent-ref/web/src`.
- Decision: **mirror layout/IA only** (sidebar section order, new-session hero composer, skills toggle list, messaging master-detail, artifacts tabs); **reimplement** all components in Spark's existing stack (shadcn/Tailwind 4, `ui/*` primitives, lucide icons, Spark theme tokens). No Hermes code is vendored.
- Baseline screenshots: `screenshots/baseline/{chat,skills,connectors,settings}.png` (dev server `npm run dev` on :5173 proxying gateway on :9119 — both verified working).

## Phase 1 — Global sidebar restructure (`App.tsx`)

- [x] Replace `NAV_ITEMS` icon rail with the Hermes section order: New session, Skills & Tools, Messaging, Artifacts.
- [x] Add **New session** action button at the top (resets chat to a fresh thread; reuse existing `spark-new-chat` CustomEvent path).
- [x] Add **Search sessions…** input directly into the global sidebar (hoist search logic out of `ChatPage`).
- [x] Add **Pinned** section header + pinned-session list to the global sidebar.
- [x] Add **Sessions** section grouped by **project workspace** (use existing `WorkspaceProject` / `SessionInfo` from `lib/api.ts`); show "No workspace" group for ungrouped sessions.
- [x] Keep **Settings** pinned to the bottom of the sidebar (retain modal trigger via `setSettingsOpen`).
- [x] Preserve collapse/expand + hover-expand behavior already in `App.tsx`.
- [x] Wire sidebar session click → navigate to chat + load that session (replace ChatPage-internal selection).
- [x] Remove the now-duplicated session list/search/pinned UI from `ChatPage.tsx` (ChatPage becomes the thread view only).
- [x] Move `chat`, `files`, `canvas`, `kanban`, `cron` out of the primary rail into a secondary location (command palette + a "More" menu or workspace tabs) so the primary sidebar matches Hermes exactly.
- [x] Update mobile nav in `App.tsx` header to mirror the new sections.
- [x] Update `i18n/en.ts` + `i18n/types.ts` nav labels (newSession, skillsAndTools, messaging, artifacts) and any other locales.

## Phase 2 — New-session screen

- [x] Build centered hero: large serif "SPARK" (or "HERMES AGENT"-equivalent) wordmark + subtitle ("Type a task, question, or snippet…").
- [x] Bottom-centered composer "Start with a goal" with mic + send affordances (reuse `components/chat/PromptBar.tsx`).
- [x] Show this hero when no active session is selected; on first send, create a session and transition to the thread view.
- [x] Match dark background + subtle texture from screenshots (reuse existing `noise-overlay` / `warm-glow`).

## Phase 3 — Skills & Tools (merged page)

- [x] Create a unified **Skills & Tools** page with two top tabs: **Skills** and **Toolsets** (matches `skills-and-tools.png`).
- [x] Render skills as a flat, searchable, category-grouped list; each row = name + one-line description + a right-aligned toggle (`ui/switch.tsx`).
- [x] Top category filter chips with counts (Apple, Autonomous-AI-Agents, Creative, … Software-Development), like the screenshot.
- [x] Add `Search skills…` input + refresh control top-right.
- [x] Fold **Connectors** into this page reworded as **Tools** (plugins + connectors to external apps). Connectors are tools that "connect" to other apps. (Third **Tools** tab embeds the connectors view.)
- [x] Each connectable tool shows a **Connect** / **Connected** state; connecting auto-enables the related skills/toolset.
- [x] Keep existing `/api/skills` + `/api/connectors` data sources; add a combined view-model in `lib/api.ts` if needed. (Not needed — page composes both APIs directly.)

## Phase 4 — 1-click connections (the core UX goal)

- [x] Audit existing connect flows in `gateway/connectors_routes.py`, `google_connector.py`, `oauth_connectors.py` (OAuth device-flow + token paste already exist).
- [x] Design a single **"Connect"** affordance per app: OAuth where available (Google, GitHub, Slack, Notion, etc.), device-flow fallback, token-paste last resort — all behind one button with progressive disclosure.
- [x] On successful connect, **auto-enable** the matching skill(s)/toolset and surface a toast ("Gmail connected — email skills enabled").
- [x] Add a connectors→skills mapping (which skills/toolsets light up per connector) and persist enablement.
- [x] Add MCP servers as connectable tools: surface MCP registry / one-click add (leverage existing MCP settings tab) inside Skills & Tools.
- [x] Add CLI-backed tools (claude-code, codex, opencode) as toggle rows with a "detected/not detected" state and an install hint.
- [x] Ensure disconnect/revoke is one click and disables dependent skills (with confirmation).
- [x] Add empty/needs-setup states with clear copy aimed at non-technical users.


**Phase 4 notes:**
- Connect flows audited: Google OAuth popup + status polling, GitHub device flow, token-paste modal for api_key connectors — all already behind a single per-connector Connect button in `ConnectorsPage.tsx`.
- Auto-enable: `ConnectorsPage` now watches disconnected→connected transitions and enables each connector's mapped skills (`ConnectorStatus.skills`), with a toast ("X connected — N skills enabled"). Disconnects disable the same skills.
- Mapping lives in the existing connector registry (`src/tools/connectors/base.py` `skills=`); no new persistence needed (skill toggles persist via `/api/skills`).
- CLI agents added as catalog connectors in `src/tools/connectors/generic.py`: `claude-code`, `codex`, `opencode` — detected via CLI on PATH + auth config files (`~/.claude.json`, `~/.codex/auth.json`, `~/.local/share/opencode/auth.json`).
- MCP: "MCP servers" entry card at the top of the Tools tab → "Manage MCP" opens Settings (full one-click MCP registry install is future work).

## Phase 5 — Messaging page

- [x] Create `pages/MessagingPage.tsx`: left scrollable list of platforms with icon + name + connected dot; right detail pane.
- [x] Source the platform list from `src/gateway/platforms/` (telegram, discord, slack, mattermost, matrix, whatsapp, signal, bluebubbles, homeassistant, email, sms/twilio, dingtalk, feishu/lark, wecom, wechat, qqbot, api_server, webhooks, irc, line, etc.).
- [x] Detail pane sections: status chips (Disabled / Needs setup / gateway state), "Get your credentials" help + setup-guide link, **Required** fields, **Recommended** fields, collapsible **Advanced**, enable toggle, **Save changes**.
- [x] Add `/api/messaging` (or extend gateway config endpoints) to read/write per-platform credentials + enabled state; reuse existing gateway config plumbing (`gateway/config.py`, `display_config.py`).
- [x] Wire Save → restart/refresh the relevant gateway channel (`gateway/restart.py`).
- [x] Add `Search messaging…` filter for the platform list.

## Phase 6 — Artifacts page

- [x] Create `pages/ArtifactsPage.tsx` with tabs **All / Images / Files / Links** (each with a live count).
- [x] Aggregate artifacts produced by sessions (generated images, file outputs, links) — define/extend an `/api/artifacts` endpoint backed by workspace files + session outputs.
- [x] Empty state: "No artifacts found — Generated images and file outputs will appear here as sessions produce them."
- [x] Grid/list rendering with type filtering; click opens the artifact (image preview, file download, link out).

## Phase 7 — Settings panel parity

- [x] Verify the existing `SettingsPanel.tsx` sections match the reference (Model, Chat, Appearance, Workspace, Safety, Memory & Context, Voice, Advanced, Providers, Gateway, Tools & Keys, MCP, Archived Chats, About).
- [x] Adjust labels/grouping/ordering to match `settings-*.png` screenshots where they differ.
- [x] Keep Settings reachable from the sidebar bottom; confirm modal styling matches dark minimal aesthetic.

## Phase 8 — Visual polish / theme

- [x] Tune spacing, type scale, and muted palette to match Hermes minimal/sleek look across all new pages.
- [x] Confirm status bar at bottom (Gateway ready · Agents · Cron · model · version) matches screenshots.
- [x] Verify dark mode + responsive (use `preview_resize`) for sidebar collapse, messaging split, artifacts grid.

## Phase 9 — Desktop app parity

- [x] Verify Tauri shell (`isTauri()` paths in `App.tsx`) compiles and bundles the new layout successfully.
- [x] Confirm tray "new chat" + `spark://` deep links still route correctly after sidebar refactor.
- [x] Rebuild the macOS app via `/build-mac` and smoke-test the new UI in the packaged app. (`Spark.app` launches with its bundled server; code signature and DMG checksum verified.)

## Phase 10 — Verification & ship

- [x] Run the dev server and verify each page via preview tools (snapshot + screenshot): new-session, skills & tools, messaging, artifacts, settings.
- [x] `ruff check src/` and `mypy src/agent/ src/spark_cli/` clean for any backend additions. (Changed backend files pass focused Ruff and mypy checks; repository-wide checks retain pre-existing baseline findings.)
- [x] `python -m pytest tests/ -m "not slow" -q` green (add tests for new `/api/messaging` + `/api/artifacts` routes). (`11566 passed, 150 skipped`.)
- [x] Build the web bundle and confirm `web_dist/` is regenerated.
- [x] Before/after screenshots attached; open a PR from a feature branch (never push to main). (PR #25.)

---

### Decisions (locked)
- **Demoted pages:** `chat/files/canvas/kanban/cron` stay reachable but move off the primary sidebar → command palette (Cmd+K) + a secondary "More" menu. Primary sidebar matches Hermes exactly.
- **Branding:** keep **Spark** identity (wordmark + name), but use the Hermes centered-serif + bottom-composer layout from the screenshots.

### Open questions (resolve while building)
- [x] Artifacts backing store: derive from workspace files only, or add a dedicated artifact index? — default: derive first, index later if needed. → derived from workspace files
