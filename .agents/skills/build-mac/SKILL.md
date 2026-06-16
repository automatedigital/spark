---
name: build-mac
description: >
  Rebuild the Spark macOS desktop app (.app + .dmg) after web UI or backend changes.
  Use when the user types /build-mac or asks to rebuild, compile, or package the
  desktop app, Tauri app, or DMG.
---

# Build Spark macOS Desktop App

Run the full 5-stage desktop build pipeline from the **repository root** (the directory that contains `scripts/build_desktop.sh`).

## Step 1 — Run the build

```bash
cd "$(git rev-parse --show-toplevel)"
bash scripts/build_desktop.sh
```

Stream output. Stages:

| Stage | What | Typical failure |
|-------|------|-----------------|
| 1 | `npm run build` — Vite frontend | TS/Vite errors in `src/spark_cli/web/src/` |
| 2 | PyInstaller → `dist/spark-server/` | Import errors; check `spark-server.spec` excludes |
| 3 | `tauri build` — Rust + `.app` | Run `cargo check` in `src/spark_cli/web/src-tauri/` |
| 4 | Inject sidecar into `.app` | Ensure `dist/spark-server/` exists |
| 4b | `sign_mac_app.sh` on `.app` (Developer ID or ad-hoc) | Required after injection or macOS reports "damaged" |
| 5 | `make_dmg.sh` — drag-to-install DMG | Requires macOS `hdiutil` |
| 6 | `notarize_mac.sh` — notarize + staple DMG | No-op unless notarization env vars set |

## Step 2 — Report success

On success, report:

- **App:** `src/spark_cli/web/src-tauri/target/release/bundle/macos/Spark.app`
- **DMG:** `Spark.dmg` at the repo root

Tell the user they can run `/release-mac` to publish to GitHub Releases.

## Step 3 — Handle failures

If a stage fails, show the relevant log lines and the fix hint from the table above. Do not guess — use the actual error output.

## Signing & notarization (Developer ID)

By default the build **ad-hoc signs** (`codesign --sign -`) and **skips
notarization** — local dev builds need no Apple certs and behave exactly as
before. To produce a Gatekeeper-approved, distributable DMG, set environment
variables before running `scripts/build_desktop.sh`. Signing and notarization
are driven entirely by env vars; nothing is hardcoded and no secret is committed.

### Required env vars

**Signing** (enables hardened-runtime Developer ID signing in `sign_mac_app.sh`):

| Var | Description |
|-----|-------------|
| `APPLE_SIGNING_IDENTITY` | Developer ID Application identity, e.g. `"Developer ID Application: Acme Inc (TEAM123456)"` or its SHA-1 hash. The cert must be in a keychain. If unset → ad-hoc `--sign -` (current behaviour). |

When set, the app is signed with `--options runtime` (hardened runtime) and the
entitlements at `scripts/entitlements.mac.plist` (minimal: WebKit JIT only).

**Notarization** (enables `notarize_mac.sh`; pick ONE mode):

| Mode | Vars |
|------|------|
| Keychain profile | `APPLE_KEYCHAIN_PROFILE` (created via `xcrun notarytool store-credentials`) |
| Inline | `APPLE_ID` + `APPLE_PASSWORD` (app-specific password) + `APPLE_TEAM_ID` |

If none are set, notarization is skipped with a log message and the build still
succeeds (ad-hoc DMG).

### Example (full signed + notarized build)

```bash
export APPLE_SIGNING_IDENTITY="Developer ID Application: Acme Inc (TEAM123456)"
export APPLE_TEAM_ID="TEAM123456"
export APPLE_ID="you@example.com"
export APPLE_PASSWORD="abcd-efgh-ijkl-mnop"   # app-specific password
bash scripts/build_desktop.sh
```

### Verify the result

```bash
# Bundle signature is valid and deep:
codesign --verify --deep --strict --verbose=2 \
  src/spark_cli/web/src-tauri/target/release/bundle/macos/Spark.app

# Gatekeeper accepts the app (look for "accepted" + "Notarized Developer ID"):
spctl -a -vvv \
  src/spark_cli/web/src-tauri/target/release/bundle/macos/Spark.app

# Notarization ticket is stapled to the DMG:
stapler validate src/spark_cli/web/src-tauri/target/release/bundle/dmg/Spark.dmg
```

### Why Tauri config is not used for signing

`tauri.conf.json` is left without a `macOS.signingIdentity`. Tauri does not
interpolate env vars into the config file, and the sidecar is injected into the
`.app` *after* `tauri build` (see step 4) — so any signature Tauri applied would
be invalidated. All signing is therefore done post-build by `sign_mac_app.sh`,
which signs the bundle in its final state.

## Notes

- Build takes ~10–15 minutes (PyInstaller + Rust are slow).
- Must run on **Apple Silicon** Mac (frozen sidecar is aarch64).
- `scripts/build_desktop.sh` activates the venv; no manual `source venv` needed.
- **Do not commit** `Spark.dmg` (or copy it to repo root for release). It is listed in `.gitignore`; ship binaries only via `/release-mac` → GitHub Releases.
