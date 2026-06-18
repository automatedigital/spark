#!/usr/bin/env bash
#
# build_desktop.sh — Build the Spark macOS desktop app (.app + .dmg).
#
# Pipeline:
#   1. Build the web frontend (Vite) into src/spark_cli/web_dist/.
#   2. Freeze the Python backend with PyInstaller (--onedir) → dist/spark-server/.
#   3. Build the Tauri .app bundle (without the sidecar).
#   4. Inject the frozen --onedir tree into the .app's Contents/Resources/.
#   5. Package the .app into a .dmg.
#
# Why inject in step 4 instead of using Tauri's `resources` config: the
# PyInstaller --onedir tree contains versioned dylib symlinks (sqlite, ffmpeg,
# etc.) that Tauri's resource walker cannot traverse ("Not a directory"). A
# plain `cp -R` into the built bundle copies symlinks faithfully. Rust resolves
# the sidecar via resource_dir() == Contents/Resources/, so the runtime path
# (Contents/Resources/spark-server/spark-server) is unchanged.
#
# Run from anywhere; paths are resolved relative to the repo root.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB_DIR="$REPO_ROOT/src/spark_cli/web"
BUNDLE_DIR="$WEB_DIR/src-tauri/target/release/bundle"
APP="$BUNDLE_DIR/macos/Spark.app"
DMG_DIR="$BUNDLE_DIR/dmg"

# 0. Load local release-signing config so every build is Developer ID signed +
#    Apple-notarized by default (no manual `export` needed before each build).
#    scripts/release.env is gitignored and holds only non-secret config:
#    APPLE_SIGNING_IDENTITY (cert name), APPLE_KEYCHAIN_PROFILE (notary profile
#    name), APPLE_TEAM_ID. The notarization password lives in the macOS keychain
#    under the profile — never in this file. See scripts/release.env.example.
#    (Gitignored, so CI checkouts won't have it and can set the env vars directly.)
RELEASE_ENV="$REPO_ROOT/scripts/release.env"
if [ -f "$RELEASE_ENV" ]; then
  echo "==> Loading release-signing config from scripts/release.env"
  set -a
  # shellcheck disable=SC1090
  . "$RELEASE_ENV"
  set +a
fi

# 1. Build web assets ------------------------------------------------------
# Install deps first so the build never fails on a newly-added/changed
# dependency (e.g. a stale node_modules missing a devDependency). Use `npm ci`
# when a lockfile is present for a clean, reproducible install; fall back to
# `npm install` otherwise.
echo "==> Installing web frontend dependencies"
if [ -f "$WEB_DIR/package-lock.json" ]; then
  (cd "$WEB_DIR" && npm ci)
else
  (cd "$WEB_DIR" && npm install)
fi
echo "==> Building web frontend"
(cd "$WEB_DIR" && npm run build)

# 2. Freeze Python sidecar (--onedir) --------------------------------------
echo "==> Freezing Python backend with PyInstaller"
(cd "$REPO_ROOT" && pyinstaller spark-server.spec --noconfirm)

# 3. Build the Tauri .app (sidecar injected afterwards) --------------------
echo "==> Building Tauri desktop app"
(cd "$WEB_DIR" && npm run desktop:build)

# 4. Inject the sidecar into the built bundle ------------------------------
echo "==> Injecting sidecar into $APP"
rm -rf "$APP/Contents/Resources/spark-server"
cp -R "$REPO_ROOT/dist/spark-server" "$APP/Contents/Resources/spark-server"
chmod +x "$APP/Contents/Resources/spark-server/spark-server"

# 4b. Re-sign after sidecar injection (DMG staging will sign again after cp -R).
#     sign_mac_app.sh uses Developer ID + hardened runtime when
#     APPLE_SIGNING_IDENTITY is set, otherwise falls back to ad-hoc `--sign -`.
echo "==> Signing app bundle"
"$REPO_ROOT/scripts/sign_mac_app.sh" "$APP"

# 5. Package a styled drag-to-install .dmg ---------------------------------
echo "==> Packaging DMG"
mkdir -p "$DMG_DIR"
DMG="$DMG_DIR/Spark.dmg"
"$REPO_ROOT/scripts/make_dmg.sh" "$APP" "$DMG"

# 6. Notarize + staple the DMG ---------------------------------------------
#    No-op (logs + exits 0) unless notarization credentials are in the env:
#    APPLE_KEYCHAIN_PROFILE, or APPLE_ID + APPLE_PASSWORD + APPLE_TEAM_ID.
echo "==> Notarizing DMG"
"$REPO_ROOT/scripts/notarize_mac.sh" "$DMG"

echo ""
echo "App: $APP"
echo "DMG: $DMG"
