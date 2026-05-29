#!/usr/bin/env bash
# sign_mac_app.sh — Ad-hoc sign a macOS .app bundle (all Mach-O binaries + deep sign).
#
# Usage: sign_mac_app.sh <path/to/App.app>
#
# Required after copying a bundle (e.g. into a DMG stage folder) because cp -R
# breaks the previous signature and macOS reports the app as "damaged".
set -euo pipefail

APP="${1:?usage: sign_mac_app.sh <App.app>}"

[ -d "$APP" ] || { echo "error: not a directory: $APP" >&2; exit 1; }

echo "==> Signing Mach-O binaries in $APP"
find "$APP" -type f | while read -r f; do
  if file -b "$f" 2>/dev/null | grep -q 'Mach-O'; then
    codesign --force --sign - "$f" 2>/dev/null || true
  fi
done

echo "==> Deep-signing $APP"
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"
