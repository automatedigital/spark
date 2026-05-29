#!/usr/bin/env bash
# install_desktop.sh — Install Spark Desktop on macOS without manual quarantine steps.
#
# Downloads the release DMG, copies Spark.app to /Applications, clears quarantine,
# and launches. Intended to be run from Terminal (same pattern as install.sh):
#
#   curl -fsSL https://raw.githubusercontent.com/automatedigital/spark/main/scripts/install_desktop.sh | bash
#
set -euo pipefail

SPARK_DESKTOP_VERSION="${SPARK_DESKTOP_VERSION:-1.0.0}"
TAG="desktop-v${SPARK_DESKTOP_VERSION}"
DMG_URL="https://github.com/automatedigital/spark/releases/download/${TAG}/Spark.dmg"
DEST="/Applications/Spark.app"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "error: Spark Desktop is macOS only" >&2
  exit 1
fi

if [[ "$(uname -m)" != "arm64" ]]; then
  echo "error: Spark Desktop requires Apple Silicon (arm64)" >&2
  exit 1
fi

WORK="$(mktemp -d)"
MOUNT="$WORK/mnt"
DMG="$WORK/Spark.dmg"

cleanup() {
  hdiutil detach "$MOUNT" -quiet 2>/dev/null || true
  rm -rf "$WORK"
}
trap cleanup EXIT

echo "==> Downloading Spark Desktop ${SPARK_DESKTOP_VERSION}"
curl -fL# "$DMG_URL" -o "$DMG"

mkdir -p "$MOUNT"
hdiutil attach "$DMG" -mountpoint "$MOUNT" -nobrowse -quiet

SRC="$MOUNT/Spark.app"
[[ -d "$SRC" ]] || { echo "error: Spark.app not found in DMG" >&2; exit 1; }

echo "==> Installing to $DEST"
xattr -cr "$SRC"
rm -rf "$DEST"
ditto "$SRC" "$DEST"
xattr -cr "$DEST"

hdiutil detach "$MOUNT" -quiet

echo "==> Launching Spark"
open "$DEST"
