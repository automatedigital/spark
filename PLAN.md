# Spark Improvement Plan

Living plan for the next round of Spark fixes and features. Tasks are written as
atomic markdown checkboxes so **multiple agents can work in parallel** and check
items off as they land. Each task names the primary file(s) to touch.

## How to use this plan (for async agents)

- Pick an **unchecked** task. Check it off **in this file immediately after the
  change lands and is verified** — do not batch check-offs to the end.
- Each task is sized to a single focused PR. Prefer one feature area per branch.
- Follow repo rules: feature branch + PR (never push to `main`), use `.venv`
  (not anaconda), run `graphify update .` after code changes.
- Tests: `python -m pytest tests/ -q`. Lint: `ruff check src/`. Types:
  `mypy src/agent/ src/spark_cli/`. Web: `cd src/spark_cli/web && npm run lint && npm run build`.
- Profile safety: never hardcode `~/.spark`; use `get_spark_home()`.
- Dependencies between areas are called out per-phase. Phase 0 (bugs) is
  parallelizable immediately and unblocks confidence in the rest.

## Architecture map (where things live)

| Area | Location |
|------|----------|
| Desktop shell (Tauri) | `src/spark_cli/web/src-tauri/` (`tauri.conf.json`, Rust sidecar launcher) |
| Web UI (React) | `src/spark_cli/web/src/` — `App.tsx` (nav + status footer), `pages/`, `components/` |
| Onboarding | `src/spark_cli/web/src/components/OnboardingWizard.tsx` |
| Sidebar / sessions / projects | `src/spark_cli/web/src/components/sidebar/SidebarSessions.tsx`, `lib/sessionStore` |
| Chat composer | `src/spark_cli/web/src/components/ChatPanel.tsx` |
| Backend HTTP API | `src/spark_cli/web_server.py`, `src/spark_cli/workspace_routes.py` |
| Gateway (background service) | `src/gateway/` (`run.py`, `status.py`, `config.py`, `platforms/`) |
| Browser tools | `src/tools/browser_tool.py`, `src/tools/browser_camofox.py` |
| Toolsets / skills | `src/core/toolsets.py`, `src/core/toolset_distributions.py`, `src/tools/skills_*.py` |
| Desktop build/sign | `scripts/build_desktop.sh`, `scripts/sign_mac_app.sh`, `scripts/make_dmg.sh` |

---

## Phase 0 — Bugs & reliability (do first, parallelizable)

These are independent fixes surfaced during code review and from Pete's VPS
logs. None depend on the feature work below.

### 0.1 Status bar is not live (also see §6)

`App.tsx` fetches status/model/cron **once on mount** (`useEffect` at
`src/spark_cli/web/src/App.tsx:456`) and never refreshes. `gatewayReady`,
`activeModel`, and `scheduledJobCount` go stale; the footer dot is frozen.

- [x] Extract the status fetch in `App.tsx` into a polling effect (~8s) so
      `gatewayReady`, `activeModel`, `scheduledJobCount` refresh in realtime. (PR #38)
- [x] Pause polling when the window/tab is hidden (`document.visibilityState`),
      resume on `visibilitychange`. (PR #38)
- [ ] Ensure the footer status (`App.tsx:890`) and `StatusPage.tsx` share one
      source of truth for gateway state. _(Not done: PR #38 agent missed that
      `StatusPage.tsx` exists; StatusPage still fetches independently. Reconcile
      in the desktop follow-up pass.)_

### 0.2 Browser tools time out and burn the whole API budget on headless VPS

From `petes-logs.txt`: `browser_navigate`, `browser_snapshot`, `browser_console`,
and `browser_open` repeatedly time out (30s/60s) on an Ubuntu VPS. One turn hit
`max_iterations_reached(20/20)` retrying timed-out navigations; a `delegate_task`
ran **936s**. One nav also returned `Non-JSON output from agent-browser for 'open'`
(daemon returned `about:blank` then malformed trailing output) — a sign that
agent-browser / Chromium is not fully installed or cannot launch headless
(missing system libs from `agent-browser install --with-deps`, or no usable
sandbox on the VPS).

- [x] `_browser_backend_healthy()` preflight (`agent-browser --version`, 8s,
      cached per process, reset on cleanup); checked before first navigation. (PR #43)
- [x] Unhealthy → fast actionable error (`_browser_install_hint()` + headless
      guidance) instead of hanging. (PR #43)
- [x] Circuit breaker: trips after 3 consecutive timeouts (`error_type:
      circuit_open`), resets on success/cleanup. (PR #43)
- [x] Malformed daemon response → distinct `error_type: malformed_response`; raw
      blob moved to `raw_output`. (PR #43)
- [x] `spark doctor` check: Linux + no `$DISPLAY` probes Chromium libs, suggests
      `agent-browser install --with-deps` (advisory). (PR #43)
- [x] Documented `command_timeout` (docstrings + `docs/configuration.md`); default
      30s kept — new guards cover the unhealthy case. (PR #43)

### 0.3 Concurrent sub-agents contend on the shared browser daemon

The logs show 3 delegated sub-agents (`443f27`, `037cb9`, `10002e`) driving the
browser at the same time, compounding the timeouts.

- [x] Audited: each agent run gets a unique `task_id`, sessions/sockets keyed
      per task_id → concurrent agents already isolated (isolation, not
      serialization, is the safer design). (PR #43)
- [x] Regression test: two parallel navigations assert distinct socket dirs. (PR #43)

### 0.4 Telegram fallback IP failures on VPS

Log: `[Telegram] Fallback IP 149.154.167.220 failed`. The seed fallback list is
hardcoded to a single IP (`src/gateway/platforms/telegram_network.py:43`).

- [x] Configurable multi-IP seed (`TELEGRAM_FALLBACK_IPS` / config) with 4
      in-range `149.154.160.0/20` IPs; backward compatible. (PR #40)
- [x] Log fix via `_describe_exc()` — always emits exception type + cause (root
      cause: httpx `ConnectError` has empty `str()`). (PR #40)
- [x] Bounded retry/backoff per IP before exhausting fallbacks. (PR #40)

---

## Phase 1 — Desktop: gateway-always-on + live status

Goal: on the macOS desktop app the gateway should **always be running in the
background** (so messaging platforms can reach Spark even when the user is just
using the app), and the status menu must reflect live state.

Context: `gateway_running` is `get_running_pid() is not None`
(`web_server.py:1052`). The desktop sidecar runs `web_server` but does **not**
start the gateway process, so the PID file is absent and the footer shows
"Gateway offline" (`App.tsx:898`).

- [x] Auto-start gateway in background on desktop launch — in-process
      `DesktopGatewaySupervisor` (`desktop_gateway.py`), wired into web_server
      `_lifespan`; `SPARK_DESKTOP=1` already set by the Rust sidecar. (PR #44)
- [x] On shutdown, stop only the gateway we started (ownership tracking; never
      touches an external/user-managed gateway). (PR #44)
- [x] Footer shows "Gateway ready" on desktop (PID file present → §0.1 footer
      poll + StatusPage poll reflect it). (PR #44)
- [x] Status fields live-refresh — both footer (8s, PR #38) and `StatusPage.tsx`
      (5s) poll canonical `/api/status`. _(Shared-hook refactor intentionally
      skipped — no functional gap, avoids an unneeded abstraction.)_ (PR #44)
- [x] Config opt-out `desktop.gateway_autostart` (default true) + migration
      (v24→25) + test. (PR #44)

---

## Phase 2 — Onboarding: local Mac vs. existing VPS instance

Goal: during onboarding the user chooses to **run Spark locally** or **connect
to an existing remote instance** (VPS). For remote, prompt for **dashboard URL +
dashboard token**. Allow switching later in Settings.

Context: `OnboardingWizard.tsx` currently only does provider/model selection
(steps at `OnboardingWizard.tsx:443`+). The dashboard-token auth wall already
exists in `App.tsx:828` and `getDashboardToken/setDashboardToken` in `lib/api.ts`;
remote connect should reuse that token plumbing.

- [x] Desktop-only onboarding step (`isTauri()`): "Run locally" vs "Connect to an
      existing Spark instance". (PR #45)
- [x] Remote path: URL+token validated by probing `${url}/api/config`; `lib/api.ts`
      routes through dynamic `getApiBase()` (pure logic in `lib/connection.ts`). (PR #45)
- [x] Persist mode + base URL across restarts (`spark-connection-mode`,
      `spark-remote-base-url`; reuses `spark_dashboard_token`). (PR #45)
- [x] Settings "Connection" section: switch Local↔Remote, edit/validate, clear. (PR #45)
- [x] Footer shows "Local" / "Remote @ host". (PR #45)
- [x] Vitest tests for URL/token validation + persistence (18/18); added minimal
      Vitest infra to the web package. (PR #45)

---

## Phase 3 — Project starter templates

Goal: creating a new project shows a template picker. Selecting a template
scaffolds starter files into the project.

Templates:
- Start from scratch (current behaviour)
- Static website (HTML, CSS, JS, Tailwind CSS)
- Web app: Vite + TypeScript + React + TanStack Router & Query + Tailwind + shadcn/ui + Vitest
- Productivity (basic project with helpful skills enabled for general work)

Context: `ProjectCreate` (`workspace_routes.py:128`) currently only accepts
`name`; `POST /projects` (`:238`) just creates the dir. Project creation UI lives
in `SidebarSessions.tsx` (`ProjectGroup`/`ProjectCreate`).

- [x] Template registry `src/spark_cli/project_templates.py` (scratch/static/webapp/
      productivity) with `list/get/is_valid/materialize`. (PR #41)
- [x] `ProjectCreate.template` + `create_project` validation (400 on unknown) +
      scaffolding; `GET /api/workspace/project-templates`. (PR #41)
- [x] Template-picker cards on "new project" in `SidebarSessions.tsx` + api wiring. (PR #41)
- [ ] "Productivity" template enables a curated skill set for the project.
      _(Partial: scaffolded as README guidance + Phase 4 TODO, not wired to skill
      enablement. Finish once skill-enablement-per-project exists.)_
- [x] Backend tests: scaffolding per template + unknown-id rejection (11 passed). (PR #41)
- [ ] (Optional) Add more templates if useful (e.g. Node API, Python script).

---

## Phase 4 — Skills: add "Taste" to Creative

Goal: add the Taste skill (`npx skills add Leonxlnx/taste-skill`) to the Creative
base skill set so creative projects/profiles get it by default.

Context: `creative` is defined as a toolset distribution
(`toolset_distributions.py:148`). "Base skills" seeding lives around
`src/tools/skills_*.py`. Confirm whether "Creative base skills" means a default
skill bundle vs. the toolset distribution before wiring.

- [x] Located the bundle: `skills/creative/` (synced by `skills_sync.py`), not the
      toolset distribution. Vendored Taste at `skills/creative/taste/`. (PR #39)
- [x] Sync is a pure file copy (bundled, no network) → inherently offline-safe. (PR #39)
- [x] Documented (README + provenance); test `test_taste_is_in_creative_base_skill_set`. (PR #39)

> Note: Taste was **vendored** into the bundled skill set rather than fetched live via
> `npx skills add`. No auto-install registry exists; vendoring matches the "base skills"
> intent and is offline-safe. Revisit if a live-fetch mechanism is preferred.

---

## Phase 5 — Replace "Artifacts" tab with "Files"

Goal: the Artifacts tab looks buggy; remove it from primary nav and rely on the
existing Files tab / preview panel.

Context: `artifacts` is in `PRIMARY_NAV` (`App.tsx:51`); `files` is demoted to the
"More" menu (`App.tsx:57`). `ArtifactsPage.tsx` is the buggy view; `FilesPage.tsx`
already exists and is full-featured.

- [ ] Promote **Files** into `PRIMARY_NAV` and remove **Artifacts** from it
      (`App.tsx:48–61`).
- [ ] Remove `ArtifactsPage` from `PAGE_COMPONENTS`, `PAGE_LABEL_KEYS`,
      `FULL_WIDTH_PAGES`, and the command palette; delete `ArtifactsPage.tsx`
      (and the `artifacts` i18n label if now unused).
- [ ] Verify nothing else links to the artifacts route (deep links, i18n,
      `CommandPalette.tsx`).
- [ ] Confirm the preview panel covers the artifact-viewing use case Files users
      expect (images, file outputs); note any gap as a follow-up task.

---

## Phase 6 — New session: optional project selection in composer

Goal: when starting a new session, the prompt bar lets the user optionally pick a
project. Blank = plain chat thread. Picking a project adds the thread to that
project's sessions in the sidebar.

Context: `newProjectThread(slug)` already exists in the session store and is wired
via `openProjectCompose` (`App.tsx:378`). The composer is `ChatPanel.tsx`. This is
mostly surfacing existing plumbing in the new-session UI.

- [x] Add a project picker (dropdown/combobox) to the new-session composer
      (`ChatPage.tsx` `NewSessionHero`), defaulting to "No project (just chat)". (PR #37)
- [x] On submit with a project selected, create the thread under that project
      (via `api.startWorkspaceConversation`) so it appears in the project's sidebar group. (PR #37)
- [x] Persist/restore the last-used selection sensibly (localStorage
      `spark-hero-last-project`; stale slugs dropped). (PR #37)
- [ ] Tests for thread→project association. _(Unblocked: PR #45 added Vitest infra
      to the web package — a follow-up can now add this test.)_

---

## Phase 7 — Apple Developer signing & notarization

Goal: ship a properly **signed + notarized** macOS build (paid Apple Developer
account now available). Today the build only **ad-hoc signs** (`codesign --sign -`
in `sign_mac_app.sh`); `tauri.conf.json` has no signing identity.

- [x] Developer ID + hardened runtime signing in `sign_mac_app.sh` (gated on
      `APPLE_SIGNING_IDENTITY`; ad-hoc fallback preserved) + `entitlements.mac.plist`. (PR #42)
- [x] Gated notarization + stapling (`notarize_mac.sh` via `notarytool`/`stapler`),
      wired into `build_desktop.sh`; skips cleanly without creds. (PR #42)
- [x] All values sourced from env (`APPLE_SIGNING_IDENTITY`, `APPLE_TEAM_ID`,
      `APPLE_ID`+`APPLE_PASSWORD` or `APPLE_KEYCHAIN_PROFILE`); documented. (PR #42)
- [x] Verified end-to-end with real Developer ID certs: signed (hardened
      runtime) → Apple notary **Accepted** → stapled DMG. `spctl -a -vvv` on the
      in-DMG app → "accepted, source=Notarized Developer ID". (Also fixed an
      entitlements-plist XML-comment parse bug, PR #49.)
- [x] Updated `build-mac/SKILL.md` with the signing/notarization flow + verification. (PR #42)

> Note: PR #42 replaced a pre-existing `notarize_mac.sh` that used `SPARK_*` env vars
> with the new `APPLE_*` scheme. Update any external CI/scripts that referenced the old vars.

---

## Suggested parallelization

- **Immediately, independently:** Phase 0 (0.1–0.4), Phase 5, Phase 6, Phase 4.
- **Desktop-focused track:** Phase 1 → Phase 2 (share the desktop/gateway/remote
  plumbing; 0.1 polling unblocks the status pieces of both).
- **Backend track:** Phase 3 (templates) is self-contained.
- **Release track:** Phase 7 can proceed any time; coordinate with whoever cuts
  the next desktop build.
