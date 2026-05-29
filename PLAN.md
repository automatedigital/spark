# Tauri macOS Desktop App (Fully Bundled)

Bundle the React/Vite frontend **and** the Python FastAPI backend into a single native macOS `.app`. Tauri wraps the web UI; the Python server (`spark dashboard`) runs as a Tauri sidecar process. The webapp source and Python source remain unchanged.

**Architecture at runtime:**
```
Spark.app
  └── Tauri shell (window → http://127.0.0.1:9119)
        └── sidecar: spark-server  ← PyInstaller-frozen Python binary
              └── FastAPI/uvicorn on 127.0.0.1:9119
```

---

## Prerequisites

- [ ] Verify Rust toolchain installed (`rustc --version`); install via `rustup` if missing
- [ ] Verify Xcode Command Line Tools installed (`xcode-select -p`)
- [ ] Verify PyInstaller available: `pip install pyinstaller` (add to `dev` extras in `pyproject.toml`)
- [ ] Node/npm available in `src/spark_cli/web/`

---

## Phase 1 — Freeze Python Backend with PyInstaller

Goal: produce a single self-contained binary `spark-server` that runs `spark dashboard --port 9119 --no-browser`.

- [ ] Create `scripts/build_sidecar.py` — a PyInstaller spec helper that:
  - Entry point: `src/spark_cli/main.py` (or a thin wrapper `scripts/sidecar_entry.py` that calls `start_server()` directly)
  - Includes all `src/` packages: `core`, `agent`, `spark_cli`, `tools`, `gateway`, `cron`, `acp_adapter`, `plugins`
  - Bundles `src/spark_cli/web_dist/` as data (so the server can serve the pre-built frontend as fallback)
  - Output binary name: `spark-server`
- [ ] Create `scripts/sidecar_entry.py` — minimal entrypoint:
  ```python
  import sys
  from spark_cli.web_server import start_server
  port = int(sys.argv[1]) if len(sys.argv) > 1 else 9119
  start_server(host="127.0.0.1", port=port, open_browser=False)
  ```
- [ ] Create `spark-server.spec` PyInstaller spec at repo root (use `--onefile` or `--onedir`; `--onedir` is faster cold-start)
- [ ] Run `pyinstaller spark-server.spec` and verify the binary starts and serves on port 9119
- [ ] Add `dist/`, `build/`, `*.spec` output dirs to `.gitignore`

---

## Phase 2 — Scaffold Tauri App

- [ ] `cd src/spark_cli/web && npm install -D @tauri-apps/cli`
- [ ] Run `npx tauri init` with:
  - App name: `Spark`
  - Window title: `Spark`
  - Web assets: `../../web_dist` (pre-built frontend; Tauri will also load from URL at runtime)
  - Dev server URL: `http://127.0.0.1:9119` (points at running Python server)
  - Front-end dev command: *(leave blank — we drive the Python server directly)*
  - Front-end build command: `npm run build`
- [ ] Commit the scaffolded `src-tauri/` directory

---

## Phase 3 — Wire Sidecar into Tauri

Tauri sidecars are binaries placed in `src-tauri/binaries/` and declared in `tauri.conf.json`.

- [ ] Copy (or symlink for dev) the frozen `spark-server` binary into:
  ```
  src/spark_cli/web/src-tauri/binaries/spark-server-aarch64-apple-darwin
  ```
  *(Tauri requires the target-triple suffix; use `rustc -vV | grep host` to confirm the triple)*
- [ ] Edit `src/spark_cli/web/src-tauri/tauri.conf.json`:
  ```json
  {
    "bundle": {
      "externalBin": ["binaries/spark-server"]
    }
  }
  ```
- [ ] Add sidecar allowlist in `capabilities` (Tauri v2) or `tauri.allowlist` (Tauri v1):
  ```json
  "shell": {
    "sidecar": true,
    "scope": [{ "name": "binaries/spark-server", "sidecar": true }]
  }
  ```
- [ ] Write `src/spark_cli/web/src/sidecar.ts` — Tauri frontend helper that:
  1. Spawns the sidecar on app launch via `@tauri-apps/api/shell` `Command.sidecar()`
  2. Waits for the server to be ready (poll `http://127.0.0.1:9119/health` or listen for stdout line)
  3. Once ready, navigates the window to `http://127.0.0.1:9119`
  4. Kills the sidecar on window close via Tauri's `onCloseRequested` hook

---

## Phase 4 — App Window Configuration

- [ ] Edit `tauri.conf.json` window settings:
  ```json
  "windows": [{
    "url": "http://127.0.0.1:9119",
    "title": "Spark",
    "width": 1280,
    "height": 800,
    "minWidth": 960,
    "minHeight": 600,
    "decorations": true
  }]
  ```
- [ ] Show a loading screen (simple HTML in `web_dist/` or inline) while the sidecar starts up
- [ ] Set `bundle.identifier` to `studio.fromtheroot.spark`

---

## Phase 5 — App Icons

- [ ] Source or create a 1024×1024 PNG icon
- [ ] Run `npx tauri icon <path>.png` — generates all sizes into `src-tauri/icons/`
- [ ] Verify `bundle.icon` in `tauri.conf.json` includes the `.icns` path

---

## Phase 6 — Build Scripts

- [ ] Add to `src/spark_cli/web/package.json`:
  ```json
  "tauri":          "tauri",
  "desktop:dev":    "tauri dev",
  "desktop:build":  "tauri build"
  ```
- [ ] Create top-level `scripts/build_desktop.sh`:
  ```bash
  #!/usr/bin/env bash
  set -e
  # 1. Build web assets
  cd src/spark_cli/web && npm run build && cd -
  # 2. Freeze Python sidecar
  pyinstaller spark-server.spec --noconfirm
  # 3. Copy binary into Tauri binaries dir
  cp dist/spark-server src/spark_cli/web/src-tauri/binaries/spark-server-$(rustc -vV | grep host | cut -d' ' -f2)
  # 4. Build Tauri app
  cd src/spark_cli/web && npm run desktop:build
  echo "✅  App: src/spark_cli/web/src-tauri/target/release/bundle/macos/Spark.app"
  echo "✅  DMG: src/spark_cli/web/src-tauri/target/release/bundle/dmg/"
  ```
- [ ] Make it executable: `chmod +x scripts/build_desktop.sh`
- [ ] Add the following to `.gitignore` (build artifacts — never commit these):
  ```
  # Tauri / desktop build artifacts
  src/spark_cli/web/src-tauri/target/
  src/spark_cli/web/src-tauri/binaries/

  # PyInstaller artifacts
  dist/
  build/
  *.spec.bak
  ```
  *The frozen `spark-server` binary in `binaries/` is regenerated by `build_desktop.sh` — committing it would add 150–300 MB of binary that changes every build.*

### Distribution — GitHub Releases (not the repo)

Built `.app` and `.dmg` files are distributed via GitHub Releases, not stored in git:

- [ ] Tag releases with the Spark version (e.g. `git tag desktop-v1.3.5`)
- [ ] Upload the `.dmg` from `src-tauri/target/release/bundle/dmg/` as a GitHub Release asset
- [ ] (Optional later) Add a GitHub Actions workflow `desktop-release.yml` that triggers on `desktop-v*` tags, runs `build_desktop.sh` on a macOS runner, and attaches the `.dmg` to the release automatically

---

## Phase 7 — First-Run Onboarding Flow

Goal: when the desktop app launches for the first time (no `~/.spark/config.yaml` or no model configured), show a friendly multi-step onboarding wizard before the main dashboard. Mirrors the TUI `_run_first_time_quick_setup` flow but designed for the GUI.

The existing APIs (`PUT /api/config`, `PUT /api/env`, `PUT /api/model/smart`) handle all persistence — no new backend endpoints are needed.

### Detection

- [ ] Add `GET /api/onboarding/status` endpoint to `web_server.py`:
  - Returns `{ "needs_onboarding": bool, "has_model": bool, "has_api_key": bool }`
  - `needs_onboarding` is true when `~/.spark/config.yaml` doesn't exist **or** `model.provider` is unset/empty
- [ ] In `App.tsx`, call this endpoint before rendering — if `needs_onboarding: true`, render `<OnboardingWizard>` instead of the main app

### Wizard structure: 4 steps, one question each

**Step 1 — Welcome**
- Spark logo, headline: *"Let's get Spark set up"*
- Two sentences explaining what it does
- Single "Get started" button — no questions yet

**Step 2 — Choose your AI provider**
- Headline: *"Which AI provider do you use?"*
- Visual card picker (icon + name + tagline) for the most common options:
  - Anthropic (Claude) — *Best for coding and reasoning*
  - OpenAI Codex — *Log in with your ChatGPT account*
  - OpenAI — *GPT-4o, o3 via API key*
  - Google — *Gemini 2.5 Pro/Flash*
  - OpenRouter — *Access 200+ models with one key*
  - Ollama — *Run models locally, no API key needed*
  - Other / Custom — *Any OpenAI-compatible endpoint*
- Selecting a card advances to Step 3

**Step 3 — Authenticate** *(varies by provider)*

Three sub-variants of this step:

*3a — API key entry* (OpenAI, Google, OpenRouter, Custom)
- Headline: *"Paste your [Provider] API key"*
- Single password input field, placeholder: `sk-…` (or provider-appropriate hint)
- Link to provider's key page shown below the field
- "Continue" button — calls `PUT /api/env` with the correct env var key, then `PUT /api/config`

*3b — OAuth / device-code login* (OpenAI Codex, Anthropic)
- Headline: *"Log in with your [ChatGPT / Claude] account"*
- Reuses the existing `OAuthLoginModal` component (already handles both PKCE and device-code flows via `POST /api/providers/oauth/{provider}/start` + polling)
- Instead of rendering it as a modal overlay, embed its inner content inline in the wizard step — same logic, same API calls, just no backdrop/close-button chrome
- On `onSuccess`, wizard auto-advances to Step 4
- Codex flow: shows the device user-code + "Open chatgpt.com" button, then polls `/api/providers/oauth/openai-codex/poll/{session_id}` every 2 s
- Anthropic flow: opens claude.ai in a browser tab, user pastes back the code

*3c — No key needed* (Ollama)
- Headline: *"Ollama runs locally — no key required"*
- Single text field for the Ollama base URL, pre-filled with `http://localhost:11434`
- "Continue" saves `model.provider = ollama` and `model.base_url` via `PUT /api/config`

**Step 4 — Done**
- Headline: *"You're all set"*
- Short confirmation of what was saved (provider + masked key)
- Single "Open Spark" button — sets a `localStorage` flag `spark-onboarding-complete` and re-renders `<App>`

### Files to create/modify

- [ ] `src/spark_cli/web/src/components/OnboardingWizard.tsx` — the 4-step wizard component
  - Uses the same design tokens (card backgrounds, border colors, primary button) as the rest of the app — no new CSS variables needed
  - Step indicator: small numbered dots at the top (1–4)
  - Animated step transitions (CSS `fade-in` already defined in `index.css`)
  - Full-screen centered layout (replaces entire viewport, not a modal)
- [ ] `src/spark_cli/web/src/App.tsx` — add onboarding gate logic:
  ```tsx
  const [needsOnboarding, setNeedsOnboarding] = useState<boolean | null>(null);
  // fetch /api/onboarding/status on mount
  // if needs_onboarding && !localStorage.getItem('spark-onboarding-complete')
  //   render <OnboardingWizard onComplete={() => setNeedsOnboarding(false)} />
  ```
- [ ] `src/spark_cli/web_server.py` — add `GET /api/onboarding/status` (≈15 lines)

### Provider → env var + default model mapping (used in Step 3)

| Provider | Auth method | Env var / credential | Default model |
|---|---|---|---|
| anthropic | PKCE OAuth (`OAuthLoginModal`) | saved to `~/.spark/.anthropic_oauth.json` | `claude-sonnet-4-6` |
| openai-codex | Device-code OAuth (`OAuthLoginModal`) | saved by `_codex_full_login_worker` | `gpt-5.4` |
| openai | API key | `OPENAI_API_KEY` | `gpt-4o` |
| google | API key | `GOOGLE_API_KEY` | `gemini-2.5-flash` |
| openrouter | API key | `OPENROUTER_API_KEY` | `anthropic/claude-sonnet-4-6` |
| ollama | Base URL only | `model.base_url` in config | `llama3.3` |
| custom | Base URL + optional key | `OPENAI_API_KEY` + `model.base_url` | *(user-entered)* |

### What onboarding does NOT cover (available later in Settings)

- Fast/smart model routing
- Terminal backend
- Agent iteration limits
- Messaging platforms (Telegram, Discord, etc.)
- Tool permissions

---

## Phase 9 — Test Dev Mode

- [ ] Start Python server manually: `spark dashboard --port 9119`
- [ ] Run `npm run desktop:dev` from `src/spark_cli/web/`
- [ ] Confirm Tauri window opens and loads the dashboard from `http://127.0.0.1:9119`
- [ ] Clear `spark-onboarding-complete` from localStorage and reload — confirm onboarding wizard appears
- [ ] Walk through all 4 steps and confirm config is saved to `~/.spark/config.yaml` and `.env`

---

## Phase 10 — Full Build & Smoke Test

- [ ] Run `./scripts/build_desktop.sh` from repo root
- [ ] Open `Spark.app` from Finder — sidecar should auto-start, window should load dashboard
- [ ] Verify API calls work (sessions, config, tools)
- [ ] Quit the app — confirm the Python sidecar process is killed (check `ps aux | grep spark-server`)
- [ ] Test the `.dmg` installer on a clean path

---

## Notes

- **User data** — `~/.spark/` is still the data dir; the bundled app reads/writes it normally.
- **API keys** — Users still configure `~/.spark/.env`; the sidecar inherits the user's environment.
- **Port conflicts** — If 9119 is taken, the sidecar entry can pick a random free port and pass it back to Tauri via stdout. Defer until needed.
- **Code signing** — For distribution, you need an Apple Developer ID certificate. For personal use, right-click → Open bypasses Gatekeeper.
- **PyInstaller size** — The `--onedir` bundle will be 150–300 MB. Use `--exclude-module` to trim unused heavy deps (e.g. `torch`, `modal`) if size is a concern.
- **Auto-updates** — Tauri's built-in updater can serve signed `.tar.gz` updates; out of scope for now.
