# PLAN — Connectors / Plugins / Skills / MCPs

A unified **Connectors** tab that lets users link external platforms ("click → grant in popup → done")
so the agent can act on them. First target: **Google Workspace**.

---

## Distribution model: arbitrary self-hosted VPS hosts (the redirect-URI problem)

Spark is distributed: end users self-host on VPS hosts whose IP/hostname is **unknowable in advance**. Google
requires every OAuth `redirect_uri` to be **pre-registered exactly** (no wildcards), which breaks any single
shared redirect for unknown hosts.

- **Device flow (no redirect at all) is ruled out:** verified Google only allows it for a tiny scope list
  (openid/email/profile, drive.file, YouTube). **Gmail and Calendar are not supported.** Dead end for us.

### FINAL decision (2026-06-05): Public + Free (send-only); desktop bundled client + VPS BYO; relay shelved

Product constraint: **must be public** (no 100-test-user invite cap). With Gmail, you can pick only two of
{public, gmail-read, free}. Public is required and CASA cost is rejected → so **Gmail is send-only** (sensitive
scopes only; no restricted scopes → free Google verification, no CASA). Calendar/Docs/Sheets/Slides full;
Drive = drive.file.

- **Desktop app → one-click.** Ship one shared **Desktop-type** OAuth client bundled in the app
  (`spark_cli/bundled_oauth.py`; injected at build via `SPARK_DESKTOP_GOOGLE_CLIENT_ID/SECRET`). Used only on
  local/desktop (gated by `is_server_environment()`), as a fallback under any env/config client. Localhost loopback
  → no domain/relay. Desktop secret is non-confidential by Google's design, so the **gws bridge works fully**.
  Sensitive-only scopes mean the shared client can pass **free verification and be published publicly — no user
  cap, no CASA.**
- **VPS → BYO client.** On a server the bundled client is ignored → the in-app **setup helper** guides the operator
  to register their own host. (A BYO operator MAY add restricted scopes via `connectors.google.scopes` if they do
  their own CASA — but the shipped default stays send-only.)
- **Relay → SHELVED (built, tested, not deployed).** `src/spark_relay/` remains for a future "VPS one-click" option.

**Default scopes (sensitive/free):** openid, email, profile, gmail.send, drive.file, calendar, documents,
spreadsheets, presentations. Overridable via `connectors.google.scopes`.

**Maintainer actions to finish:**
1. Create the shared **Desktop** OAuth client; add the scopes above; bake id/secret into the desktop build env.
2. Submit the OAuth consent screen for **verification** (free — privacy policy, app homepage, demo video, domain)
   so it can be **Published** to the public without the unverified warning or 100-user cap.

Two (now historical) models considered:

- **A. BYO client (no infra, $0):** each self-hoster creates their own Google OAuth client and registers their
  OWN host's redirect URI (they know it). Spark auto-detects its public URL and **displays the exact redirect URI
  to paste** (in-app setup helper). Full read/write free. ~5 min one-time setup per user. → *Ship as fallback now.*
  - [x] **DONE:** `GET /api/connectors/google/setup` exposes the detected redirect URI + scopes + config status;
        ConnectorsPage shows a collapsible setup helper (copy-the-redirect-URI + config.yaml snippet), auto-expanded
        when no client is configured. tsc clean.
- **B. Shared client + hosted relay (one-click):** the Spark project hosts a small callback **relay** with ONE
  registered redirect URI; the relay brokers the flow back to the user's instance. → *Chosen as the primary path.*
  - [x] **Relay service BUILT** (`src/spark_relay/`): FastAPI app (`/session`, `/callback`, `/claim`, `/healthz`),
        HMAC-signed `state` (`crypto.py`), TTL store (`store.py`), Dockerfile + README. Security: shared
        `client_secret` stays on the relay (it does the token exchange), PKCE verifier held relay-side keyed by
        signed state, tokens delivered to the instance via a one-time short-lived ticket (not via the browser).
        Configurable scopes (defaults send-only/sensitive — no CASA). **16 tests, ruff-clean.**
  - [x] **Instance-side relay mode DONE:** `connectors.google.relay_url` (or `GOOGLE_OAUTH_RELAY_URL`) switches the
        connect flow to the relay — `/connect` calls relay `/session`; `/oauth/google/callback` handles `?ticket=`
        via `claim_relay_tokens()`. Token refresh proxies through the relay `/refresh` (the instance has no secret).
        `is_configured()` is true with a relay alone. Relay `/refresh` endpoint added. Tests cover all of it.
  - [ ] **gws bridge in relay mode** (follow-up): the bridge needs the client_secret to write gws's authorized_user
        creds, which relay mode keeps server-side — so the bridge is inactive there and the agent falls back to the
        direct-API Google tools (which DO refresh via the relay). Options to restore gws under relay: a refresh-on-
        demand `GOOGLE_WORKSPACE_CLI_TOKEN` wrapper, or have the relay vend short-lived gws creds.
  - [ ] **Infra (yours):** deploy the relay container behind TLS on a small VPS/droplet at a domain; register the
        shared Google client with `https://<domain>/callback`.
  - [ ] **CASA** for Gmail read on the shared client is deferred (decide later); relay defaults to send-only.

**Reality to hold:** zero-setup one-click + arbitrary VPS + Gmail scopes **requires both a hosted relay and Google
verification**. No trick removes both (device flow was the only loophole; Google blocks Gmail there).

## TL;DR answer to the design question

**Q: Can the first connector work as a one-click "Connect to Google" button, with no Google Cloud account / no
client-ID setup by the user?**

**Yes — but only if *Spark* (not the user) owns the OAuth client.** This is the single most important decision
in this plan and it shapes everything below.

The `gws` CLI ([googleworkspace/cli](https://github.com/googleworkspace/cli)) does **not** ship with built-in
OAuth credentials. Out of the box every user must create their own Google Cloud project + desktop OAuth client and
drop a `client_secret.json` at `~/.config/gws/`. That is exactly the friction we want to eliminate. But the CLI
*does* read whatever `client_secret.json` we hand it — so we can **ship our own OAuth client** and the user just
sees a normal Google consent screen.

So the real work is **not** wiring the CLI — it's becoming a verified Google OAuth app:

- We register **one** OAuth client in **Spark's** Google Cloud project (Desktop or "Loopback" client type).
- Spark ships/points the `gws` CLI at *our* `client_secret.json`.
- User clicks "Connect Google" → browser opens Google's consent screen for **Spark** → user approves → token
  lands in their local `~/.spark/connectors/google/`. No GCP account, no client ID, ever.
- **The catch:** Gmail/Drive/Calendar read-write are **restricted/sensitive scopes**. To offer them to the
  general public, Spark's OAuth app must pass **Google's OAuth verification + (for restricted scopes) the annual
  CASA security assessment**. Until verified we're capped at **100 test users** and users see an
  "unverified app" warning. See "Google verification" below — this is the long-pole item.

**Decision needed up front (see Open Questions):** do we ship a *shared* Spark OAuth client (best UX, requires
verification + CASA, ongoing compliance cost), or a *bring-your-own-client* fallback for power users, or both?
Recommendation: **both** — ship BYO-client now (unblocks dev + power users immediately), pursue verification in
parallel for the one-click public experience.

---

## What already exists in the repo (build on this, don't rebuild)

- **OAuth UI**: `OAuthProvidersCard.tsx`, `OAuthLoginModal.tsx`, `OnboardingWizard.tsx` (web UI).
- **OAuth backend**: `src/tools/mcp_oauth.py` — full OAuth 2.1 + PKCE loopback flow, `SparkTokenStorage`
  (token persistence to disk), ephemeral localhost callback server, `webbrowser` launch. **This is ~80% of the
  Google flow already.** Generalize it from "MCP servers" to "named connectors".
- **MCP**: `src/tools/mcp_tool.py`, MCP server config in `config.yaml` (`mcp_servers:` block).
- **Skills**: `src/tools/skills_hub.py`, `skills_sync.py`, `skill_usage.py`, `SkillsPage.tsx`, `/skills` command.
  Google Workspace already has **gws-\* skills** installed (gmail, calendar, drive, docs, sheets, slides, etc.) —
  these are the *consumption* layer once auth works.
- **Web pages** live in `src/spark_cli/web/src/pages/`; slash commands in `src/spark_cli/commands.py`;
  gateway handlers in `src/gateway/run.py`.

**Implication:** A "Connectors" feature = (1) a new web page/tab, (2) a connector registry + auth backend that
generalizes `mcp_oauth.py`, (3) per-connector "provider" definitions, and (4) reuse of existing skills as the
action layer. The skill/MCP machinery already exists.

---

## Connector model (the abstraction)

Define a `Connector` as data, not code, so adding platforms is low-effort (mirrors the skin/command-registry
pattern in this codebase).

```
Connector:
  id:            "google"
  name:          "Google Workspace"
  transport:     "cli" | "mcp" | "skill"     # prefer "cli" per the brief
  cli:           { binary: "gws", install: {...}, auth_cmd: "gws auth login" }
  auth:          "oauth2" | "apikey" | "none"
  scopes:        [gmail.modify, calendar, drive, ...]
  skills:        [gws-gmail, gws-calendar, ...]   # surfaced to agent on connect
  status_probe:  how to check "am I connected?" (e.g. `gws auth status`)
```

**Transport priority (per the brief): CLI > MCP > raw API.** CLIs are more context-efficient and easier to set
up. MCP is the fallback for platforms with no good CLI. A connector can also just *enable a set of skills*.

State lives at `~/.spark/connectors/<id>/` (token + metadata), via `get_spark_home()` — **never hardcode**.

---

## Phase 1 — Google Workspace connector (the hard one, done first)

### 1a. Foundations
- [x] Create `src/tools/connectors/` package: `registry.py` (data-driven `CONNECTOR_REGISTRY`), `base.py`
      (`Connector` ABC + `ConnectorState`/`ConnectorStatus` + per-profile `state_dir()`). Tests in
      `tests/test_connectors.py` (18 passing).
- [x] ~~Generalize `mcp_oauth.py`'s loopback flow~~ → **Decided: delegate OAuth to the `gws` CLI itself** (it
      already runs the loopback+PKCE flow). No need to reimplement OAuth for Google; revisit only for connectors
      that have no CLI. `mcp_oauth.py` stays MCP-only.
- [ ] `gws` CLI bootstrap: detect binary (done — `is_installed()`); **install** via npm/Homebrew/binary download
      still TODO. Wire into `spark doctor`.
- [x] **Verified gws command surface against the real binary (gws 0.13.2):**
      - Client identity via env: `GOOGLE_WORKSPACE_CLI_CLIENT_ID` + `_CLIENT_SECRET` (parsed from the stored
        client_secret.json), NOT a single file env var.
      - `GOOGLE_WORKSPACE_CLI_CONFIG_DIR` + keyring backend `file` → **per-profile token isolation** (no shared
        `~/.config/gws`). Big win for Spark profiles.
      - `gws auth login --scopes <csv>` requests exactly our free-tier set.
      - **Gotcha caught: `gws auth status` exits 0 even when logged OUT** — real state is in JSON
        (`auth_method`/`storage` == `"none"`). Status parsing now reads the JSON, not the exit code.

### 1b. Auth — two modes
- [x] **BYO-client mode (connector layer):** `install_client_secret()` stores the user's `client_secret.json`
      (0600, per-profile); `connect()` points `gws` at it via env + runs `gws auth login`. UI wiring pending (1c).
- [ ] **Shared-client mode (the one-click goal):** ship Spark's `client_secret.json`; `gws auth login` uses it;
      consent screen says "Spark". Gate behind the Google verification milestone (below).
- [x] **Token storage: delegated to `gws`** (decided). Spark stores only the client secret + meta under
      `SPARK_HOME/connectors/google/`; `gws` owns token refresh. Verify `gws` honors a per-profile config dir.
- [x] **Verified `gws` command surface** against the real binary (see 1a) — constants in `google.py` corrected.

### 1c. UI
- [x] Backend HTTP endpoints **already exist**: `connectors_routes.py` (`/api/connectors`, `/connect`, `/status`,
      `/oauth/google/callback`, disconnect), mounted in `web_server.py`; `api.ts` already has the client methods.
      Now scope-corrected to free-tier + gws bridge on the backend.
- [x] New **Connectors** page (`ConnectorsPage.tsx`) + nav tab (plug icon) consuming those endpoints: status badge,
      Connect (popup + status polling) / Disconnect, capabilities list, not-configured guidance, and the free-tier
      "Gmail is send-only" note. Registered in `App.tsx` (NAV_ITEMS + PAGE_COMPONENTS); i18n label present.
      tsc clean; verified rendering in the browser preview.
- [x] **Free-tier guard on `gmail_search`** (`google_tools.py`): detects 401/403 insufficient-scope and returns a
      clear "Gmail is send-only on the free tier" message instead of a raw error; schema description updated.
- [x] `/connectors`, `/connect <id>`, `/disconnect <id>` slash commands (`commands.py` CommandDef +
      `_handle_connectors_command` in `commands_mixin.py` + dispatch in `cli/__init__.py`). Gateway/web handler TODO.
- [x] **Agent tool `connectors`** (`tools/connectors_tool.py`): list/status/connect/disconnect, returns JSON.
      Registered in `_discover_tools()` + added to `_SPARK_CORE_TOOLS`. Connect is interactive-only (returns
      guidance in headless/gateway instead of hanging on a browser). 9 tests in `tests/test_connectors_tool.py`.

### 1d. Agent integration
- [ ] On connect, surface the gws-\* skills to the agent (they already exist) — verify no prompt-cache break
      (toolset changes mid-conversation are forbidden per CLAUDE.md; apply on next turn / session boundary).
- [ ] Smoke test: "summarize my unread email", "what's on my calendar today" end-to-end through `gws`.

### 1e. Google verification — **FREE TIER ONLY for v1** (long-pole, start in parallel — owner: project lead, not code)
- [ ] Create/own a dedicated Google Cloud project + OAuth consent screen for "Spark".
- [ ] **Lock v1 to the free "sensitive-only" scope set (no CASA, no fees):**
      - `gmail.send` — send/compose email on the user's behalf (NOT `gmail.readonly`/`modify` — those are restricted/paid).
      - `drive.file` — files the app creates + files the user explicitly picks via a file-picker (NOT full `drive`/`drive.readonly`).
      - `calendar`, `documents`, `spreadsheets`, `presentations` — all "sensitive" (free verification).
- [ ] Submit for **OAuth verification only** (free): privacy policy + homepage + demo video for the consent screen.
      Until approved: 100-test-user cap + "unverified app" warning (functional, just gated).
- [ ] **Restricted scopes (full inbox read / full Drive read) = DEFERRED, paid, opt-in.** Requires the annual
      third-party **CASA** assessment (~$500–$2,700/yr). Do NOT pursue for v1. Power users who need it can use
      BYO-client mode (their own verification responsibility).

---

## Phase 2 — Generalize & add more connectors

Once Google proves the pattern, the registry makes the rest cheap. Prefer CLI transport.

- [ ] **GitHub** — `gh` CLI, already device-flow OAuth, trivially one-click. (Good *second* connector; arguably
      easier than Google and validates the abstraction.)
- [ ] **Slack** — official CLI exists; or MCP fallback.
- [ ] **Linear / Notion / Stripe** — MCP transport (remote MCP servers, already supported via `mcp_tool.py`).
- [ ] Generic **"Add MCP server"** connector (URL + auth) surfaced in the same tab — unifies MCP/connector UX.
- [ ] Generic **"Add Skill"** entry point linking to the existing Skills Hub.

---

## Phase 3 — Polish

- [ ] Connector health/status dashboard (token expiry, last used, re-auth prompts).
- [ ] Per-connector scope/permission editing & revoke.
- [ ] Secrets handling: ensure tokens/secrets respect profile isolation and never leak into session history/logs.
- [ ] Docs + `spark doctor` checks per connector.
- [ ] Tests: connector registry, auth flow (mocked), status probes — with `_isolate_spark_home` fixture; mock
      `Path.home()` + `SPARK_HOME`.

---

## Unified architecture (reconciled with the pre-existing connector stack)

There was already a Google connector in the repo (`spark_cli/google_connector.py` web-OAuth engine +
`spark_cli/connectors_routes.py` HTTP routes + `tools/google_tools.py` direct-API tools). Rather than ship a
second competing stack, **the two are now collapsed into one**:

```
CONNECT  →  web-OAuth + PKCE with a SERVER-SIDE callback (connectors_routes.py).
            Works across ALL deployments the user needs:
              - VPS install, web UI        → public callback (get_public_base_url)
              - local install, web UI      → http://localhost:<port>/oauth/google/callback
              - desktop app                → embedded web UI, same localhost callback
            ↓ yields a refresh_token (google_connector.save_token)
BRIDGE   →  write a gws "authorized_user" creds file + export
            GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE into the process env
            (google_connector.build_gws_credentials / write_gws_credentials_file / apply_process_env).
EXECUTE  →  agent drives Google via the **gws CLI + gws-* skills**, which self-refresh from that file.
```

**On "no relay":** the *Spark web server itself* is the OAuth callback — there is still **no separate/3rd-party
relay to host**. Pure `gws auth login` loopback was rejected because it can't work on a VPS (the loopback would hit
the server's localhost, not the user's remote browser); the server-side callback is the portable choice.

**Why the bridge (not direct API):** the user wants gws-cli for agent use (more capable + context-efficient than
the two direct-API tools). The bridge gives a single connect that powers gws everywhere. Verified `gws` reads the
`authorized_user` JSON shape via `GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE` (confirmed with `gws auth export`).

**Free-tier scope reality:** reading email requires the *restricted* `gmail.readonly` scope (paid CASA) regardless
of transport — so the free tier is **send-only for Gmail**. The old `gmail_search` (read) tool won't function on
free-tier scopes; Calendar/Docs/Sheets/Slides/Drive-file all work.

## Cost model (why v1 is $0 to operate)

- Google Workspace APIs (Gmail, Drive, Calendar, Docs, Sheets) have **no per-call billing** — free at any number
  of users. Quota is **per-end-user**, so one heavy user can't run up a shared bill (there is no bill).
- Hosting the Cloud project + issuing OAuth tokens/logins = **free**.
- The **only** thing that costs money is the annual **CASA** assessment, and that is required **only for restricted
  scopes** (full Gmail read / full Drive read). **v1 avoids restricted scopes entirely**, so v1 = **$0**.

## Decisions made

- **Scope set for v1: free "sensitive-only" tier — no CASA, no fees.** `gmail.send`, `drive.file`, `calendar`,
  `documents`, `spreadsheets`, `presentations`. Full-inbox / full-Drive *read* (restricted, paid) is deferred and
  opt-in via BYO-client. (Phase 1e.)
- **OAuth client strategy for Google: BOTH — ship BYO-client first.** Bring-your-own `client_secret.json` lands
  in v1 (no verification needed); pursue Spark's verified shared client (verification + CASA) in parallel for the
  one-click public experience. (Phase 1b.)
- **Second connector: GitHub (`gh` CLI).** Lowest-risk validation of the connector abstraction — device-flow OAuth
  already built in, no Google-style verification. (Phase 2, first item.)

## Open questions (still need a decision)

1. **Who owns/pays for the Google Cloud project + annual CASA assessment** (~weeks + recurring cost)?
2. **Scope minimization:** which Google scopes do we actually need for v1? (Narrower = faster verification.)
3. **Token security model:** delegate to each CLI's own store, or centralize in `~/.spark/connectors/` encrypted?

---

## Notes / constraints (from CLAUDE.md)
- Use `get_spark_home()` / `display_spark_home()` — never hardcode `~/.spark`.
- Don't break prompt caching: no mid-conversation toolset/system-prompt changes; apply connector tool changes at
  a turn/session boundary.
- Optional/heavy deps imported inside functions with clear `ImportError` messages.
- Tests must not write to real `~/.spark/`.
- Follow PR workflow: feature branch + PR, never push to main.
