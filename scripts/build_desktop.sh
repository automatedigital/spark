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

# 1. Build web assets ------------------------------------------------------
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

# 5. Package a styled drag-to-install .dmg ---------------------------------
echo "==> Packaging DMG"
mkdir -p "$DMG_DIR"
DMG="$DMG_DIR/Spark.dmg"
"$REPO_ROOT/scripts/make_dmg.sh" "$APP" "$DMG"

echo ""
echo "App: $APP"
echo "DMG: $DMG"
