#!/usr/bin/env bash
# notarize_mac.sh — Sign and notarize Spark.app + DMG for Gatekeeper-approved installs.
#
# Requires Apple Developer Program membership and these env vars:
#   SPARK_CODESIGN_IDENTITY   e.g. "Developer ID Application: Your Name (TEAMID)"
#   SPARK_NOTARY_APPLE_ID      Apple ID email for notarytool
#   SPARK_NOTARY_TEAM_ID       10-character Team ID
#   SPARK_NOTARY_PASSWORD      App-specific password (or keychain profile via --keychain-profile)
#
# Optional:
#   SPARK_NOTARY_KEYCHAIN_PROFILE  if set, passed to notarytool instead of --password
#
# Usage (after build_desktop.sh):
#   export SPARK_CODESIGN_IDENTITY="Developer ID Application: ..."
#   export SPARK_NOTARY_APPLE_ID=...
#   export SPARK_NOTARY_TEAM_ID=...
#   export SPARK_NOTARY_PASSWORD=...
#   bash scripts/notarize_mac.sh
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="${1:-$REPO_ROOT/src/spark_cli/web/src-tauri/target/release/bundle/macos/Spark.app}"
DMG="${2:-$REPO_ROOT/src/spark_cli/web/src-tauri/target/release/bundle/dmg/Spark.dmg}"
IDENTITY="${SPARK_CODESIGN_IDENTITY:?Set SPARK_CODESIGN_IDENTITY (Developer ID Application)}"

sign_app() {
  local target="$1"
  echo "==> Signing $target with $IDENTITY"
  find "$target" -type f | while read -r f; do
    if file -b "$f" 2>/dev/null | grep -q 'Mach-O'; then
      codesign --force --options runtime --timestamp --sign "$IDENTITY" "$f" 2>/dev/null || true
    fi
  done
  codesign --force --deep --options runtime --timestamp --sign "$IDENTITY" "$target"
  codesign --verify --deep --strict --verbose=2 "$target"
}

notarize() {
  local path="$1"
  local name
  name="$(basename "$path")"
  echo "==> Notarizing $name"
  local -a args=(submit "$path" --apple-id "$SPARK_NOTARY_APPLE_ID" --team-id "$SPARK_NOTARY_TEAM_ID" --wait)
  if [[ -n "${SPARK_NOTARY_KEYCHAIN_PROFILE:-}" ]]; then
    args+=(--keychain-profile "$SPARK_NOTARY_KEYCHAIN_PROFILE")
  else
    args+=(--password "$SPARK_NOTARY_PASSWORD")
  fi
  xcrun notarytool "${args[@]}"
  xcrun stapler staple "$path"
  echo "==> Stapled $name"
}

[[ -d "$APP" ]] || { echo "error: app not found: $APP (run build_desktop.sh first)" >&2; exit 1; }
[[ -f "$DMG" ]] || { echo "error: dmg not found: $DMG" >&2; exit 1; }

: "${SPARK_NOTARY_APPLE_ID:?Set SPARK_NOTARY_APPLE_ID}"
: "${SPARK_NOTARY_TEAM_ID:?Set SPARK_NOTARY_TEAM_ID}"
if [[ -z "${SPARK_NOTARY_KEYCHAIN_PROFILE:-}" ]]; then
  : "${SPARK_NOTARY_PASSWORD:?Set SPARK_NOTARY_PASSWORD or SPARK_NOTARY_KEYCHAIN_PROFILE}"
fi

sign_app "$APP"
# Rebuild DMG from signed app if needed
"$REPO_ROOT/scripts/make_dmg.sh" "$APP" "$DMG"
sign_app "$APP"  # staged copy inside DMG pipeline re-signs; for notarized DMG, notarize the dmg
notarize "$DMG"

echo ""
echo "Notarized DMG: $DMG"
echo "Upload with: gh release upload desktop-vX.Y.Z $DMG --clobber"
