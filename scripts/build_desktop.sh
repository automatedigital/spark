#!/usr/bin/env bash
#
# build_desktop.sh — Build the Spark macOS desktop app (.app + .dmg).
#
# Pipeline:
#   1. Build the web frontend (Vite) into src/spark_cli/web_dist/.
#   2. Freeze the Python backend with PyInstaller (--onedir) → dist/spark-server/.
#   3. Smoke-test the frozen backend in an isolated Spark home.
#   4. Build the Tauri .app bundle (without the sidecar).
#   5. Inject the frozen --onedir tree into the .app's Contents/Resources/.
#   6. Package the .app into a .dmg.
#
# Why inject in step 5 instead of using Tauri's `resources` config: the
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
DESKTOP_VENV="${SPARK_DESKTOP_VENV:-$REPO_ROOT/.venv-desktop}"
DESKTOP_PYTHON="${SPARK_DESKTOP_PYTHON:-python3.11}"

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

# 1. Prepare an isolated Python packaging environment ---------------------
# PyInstaller inspects the active interpreter and can pull in unrelated
# optional packages found there. In particular, building from a developer's
# Anaconda environment made the desktop sidecar include pandas, SciPy,
# PyArrow, LLVM, and other packages Spark does not need. Keep packaging in a
# dedicated venv whose contents are explicit and reproducible.
if [ ! -x "$DESKTOP_VENV/bin/python" ]; then
  echo "==> Creating isolated desktop Python environment at $DESKTOP_VENV"
  if command -v uv >/dev/null 2>&1; then
    uv venv --python "$DESKTOP_PYTHON" "$DESKTOP_VENV"
  else
    "$DESKTOP_PYTHON" -m venv "$DESKTOP_VENV"
  fi
fi

echo "==> Installing desktop Python dependencies"
if command -v uv >/dev/null 2>&1; then
  uv pip install --python "$DESKTOP_VENV/bin/python" \
    -e "$REPO_ROOT[web,pty]" "pyinstaller>=6.0,<7"
else
  "$DESKTOP_VENV/bin/python" -m pip install \
    -e "$REPO_ROOT[web,pty]" "pyinstaller>=6.0,<7"
fi
echo "==> Desktop Python: $($DESKTOP_VENV/bin/python -c 'import sys; print(sys.executable)')"

# 2. Build web assets ------------------------------------------------------
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

# 3. Freeze Python sidecar (--onedir) --------------------------------------
echo "==> Freezing Python backend with PyInstaller"
(cd "$REPO_ROOT" && "$DESKTOP_VENV/bin/python" -m PyInstaller spark-server.spec --noconfirm)

# 4. Smoke-test the frozen sidecar -----------------------------------------
# Run the artifact rather than the source interpreter. This catches runtime
# dependencies that PyInstaller or the desktop dependency extra omitted before
# we spend time signing and notarizing an unusable app.
echo "==> Smoke-testing frozen Python backend"
(
  SMOKE_HOME="$(mktemp -d)"
  SMOKE_LOG="$SMOKE_HOME/spark-server.log"
  SMOKE_PORT="$($DESKTOP_VENV/bin/python -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"
  SMOKE_PID=""

  cleanup_smoke_test() {
    if [ -n "$SMOKE_PID" ] && kill -0 "$SMOKE_PID" 2>/dev/null; then
      kill "$SMOKE_PID" 2>/dev/null || true
      wait "$SMOKE_PID" 2>/dev/null || true
    fi
    rm -rf "$SMOKE_HOME"
  }
  trap cleanup_smoke_test EXIT

  SPARK_HOME="$SMOKE_HOME" "$REPO_ROOT/dist/spark-server/spark-server" \
    "$SMOKE_PORT" >"$SMOKE_LOG" 2>&1 &
  SMOKE_PID=$!

  for _ in {1..60}; do
    if curl --fail --silent --show-error \
      "http://127.0.0.1:$SMOKE_PORT/" >/dev/null 2>&1; then
      echo "  Frozen backend started successfully on port $SMOKE_PORT"
      exit 0
    fi
    if ! kill -0 "$SMOKE_PID" 2>/dev/null; then
      break
    fi
    sleep 0.5
  done

  echo "Frozen backend failed its startup smoke test" >&2
  sed -n '1,200p' "$SMOKE_LOG" >&2
  exit 1
)

# 5. Build the Tauri .app (sidecar injected afterwards) --------------------
echo "==> Building Tauri desktop app"
(cd "$WEB_DIR" && npm run desktop:build)

# 6. Inject the sidecar into the built bundle ------------------------------
echo "==> Injecting sidecar into $APP"
rm -rf "$APP/Contents/Resources/spark-server"
cp -R "$REPO_ROOT/dist/spark-server" "$APP/Contents/Resources/spark-server"
chmod +x "$APP/Contents/Resources/spark-server/spark-server"

# Bundled skills live outside the PyInstaller sidecar tree. Ship them as app
# resources and point the sidecar at this copy on launch so first-run/repair
# skill sync works in packaged desktop builds without a source checkout.
echo "==> Injecting bundled skills into $APP"
rm -rf "$APP/Contents/Resources/skills"
cp -R "$REPO_ROOT/skills" "$APP/Contents/Resources/skills"

# 6b. Re-sign after sidecar injection (DMG staging will sign again after cp -R).
#     sign_mac_app.sh uses Developer ID + hardened runtime when
#     APPLE_SIGNING_IDENTITY is set, otherwise falls back to ad-hoc `--sign -`.
echo "==> Signing app bundle"
"$REPO_ROOT/scripts/sign_mac_app.sh" "$APP"

# 7. Package a styled drag-to-install .dmg ---------------------------------
echo "==> Packaging DMG"
mkdir -p "$DMG_DIR"
DMG="$DMG_DIR/Spark.dmg"
"$REPO_ROOT/scripts/make_dmg.sh" "$APP" "$DMG"

# 8. Notarize + staple the DMG ---------------------------------------------
#    No-op (logs + exits 0) unless notarization credentials are in the env:
#    APPLE_KEYCHAIN_PROFILE, or APPLE_ID + APPLE_PASSWORD + APPLE_TEAM_ID.
echo "==> Notarizing DMG"
"$REPO_ROOT/scripts/notarize_mac.sh" "$DMG"

echo ""
echo "App: $APP"
echo "DMG: $DMG"
