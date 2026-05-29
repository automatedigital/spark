#!/usr/bin/env bash
#
# make_dmg.sh — Build a styled drag-to-install macOS .dmg.
#
# Produces a compressed disk image containing the app and an /Applications
# symlink, laid out side-by-side in a Finder window (icon view) so the user
# can drag the app onto Applications. No external tooling required — uses a
# read-write image + AppleScript to set the window/icon layout, then converts
# to a compressed read-only image.
#
# Usage: make_dmg.sh <path/to/App.app> <path/to/output.dmg>
set -euo pipefail

APP="${1:?usage: make_dmg.sh <App.app> <output.dmg>}"
OUT="${2:?usage: make_dmg.sh <App.app> <output.dmg>}"

VOL_NAME="Spark"
APP_NAME="$(basename "$APP")"

[ -d "$APP" ] || { echo "error: app not found: $APP" >&2; exit 1; }

WORK="$(mktemp -d)"
STAGE="$WORK/stage"
RW_DMG="$WORK/rw.dmg"
MOUNT="/Volumes/$VOL_NAME"
trap 'hdiutil detach "$MOUNT" -quiet 2>/dev/null || true; rm -rf "$WORK"' EXIT

# Stage contents: the app + an Applications symlink.
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/$APP_NAME"
ln -s /Applications "$STAGE/Applications"

# Size the read-write image with headroom over the staged payload.
SIZE_MB=$(( $(du -sm "$STAGE" | cut -f1) + 80 ))
hdiutil create -srcfolder "$STAGE" -volname "$VOL_NAME" -fs APFS \
  -format UDRW -size "${SIZE_MB}m" "$RW_DMG" >/dev/null

# Mount and lay out the Finder window.
hdiutil detach "$MOUNT" -quiet 2>/dev/null || true
hdiutil attach "$RW_DMG" -readwrite -noverify -noautoopen -mountpoint "$MOUNT" >/dev/null

osascript <<APPLESCRIPT >/dev/null 2>&1 || echo "  (icon layout skipped — non-fatal)"
tell application "Finder"
  tell disk "$VOL_NAME"
    open
    set current view of container window to icon view
    set toolbar visible of container window to false
    set statusbar visible of container window to false
    set the bounds of container window to {200, 120, 800, 480}
    set theViewOptions to the icon view options of container window
    set arrangement of theViewOptions to not arranged
    set icon size of theViewOptions to 120
    set position of item "$APP_NAME" of container window to {150, 180}
    set position of item "Applications" of container window to {450, 180}
    update without registering applications
    delay 1
    close
  end tell
end tell
APPLESCRIPT

sync
hdiutil detach "$MOUNT" -quiet

# Convert to a compressed, read-only distributable image.
rm -f "$OUT"
hdiutil convert "$RW_DMG" -format UDZO -imagekey zlib-level=9 -o "$OUT" >/dev/null

echo "  DMG written: $OUT"
