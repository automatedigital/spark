#!/usr/bin/env bash
# sign_mac_app.sh — Sign a macOS .app bundle (all Mach-O binaries + deep sign).
#
# Usage: sign_mac_app.sh <path/to/App.app>
#
# Required after copying a bundle (e.g. into a DMG stage folder) because cp -R
# breaks the previous signature and macOS reports the app as "damaged".
#
# Two modes, selected by the APPLE_SIGNING_IDENTITY environment variable:
#
#   * Developer ID mode (APPLE_SIGNING_IDENTITY set) — signs with that identity,
#     enables the hardened runtime (--options runtime) and applies the
#     entitlements at scripts/entitlements.mac.plist. This is required for
#     Apple notarization. Set APPLE_SIGNING_IDENTITY to a Developer ID
#     Application identity, e.g. "Developer ID Application: Acme Inc (TEAMID123)"
#     (or its SHA-1 hash). The identity/cert must already be in a keychain.
#
#   * Ad-hoc mode (APPLE_SIGNING_IDENTITY unset/empty) — falls back to the
#     original `--sign -` ad-hoc signing. Local dev builds work with no certs.
#
# NEVER hardcode an identity, Team ID, or secret here — all values come from env.
set -euo pipefail

APP="${1:?usage: sign_mac_app.sh <App.app>}"

[ -d "$APP" ] || { echo "error: not a directory: $APP" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENTITLEMENTS="$SCRIPT_DIR/entitlements.mac.plist"

IDENTITY="${APPLE_SIGNING_IDENTITY:-}"

if [ -n "$IDENTITY" ]; then
  # ---- Developer ID signing (hardened runtime + entitlements) -------------
  echo "==> Signing with Developer ID identity (hardened runtime): $IDENTITY"
  [ -f "$ENTITLEMENTS" ] || { echo "error: entitlements not found: $ENTITLEMENTS" >&2; exit 1; }

  SIGN_ARGS=(--force --timestamp --options runtime --sign "$IDENTITY")

  # Sign every nested Mach-O binary first (inside-out), then the bundle.
  find "$APP" -type f | while read -r f; do
    if file -b "$f" 2>/dev/null | grep -q 'Mach-O'; then
      codesign "${SIGN_ARGS[@]}" "$f"
    fi
  done

  echo "==> Deep-signing $APP with entitlements"
  codesign "${SIGN_ARGS[@]}" --entitlements "$ENTITLEMENTS" "$APP"
  codesign --verify --deep --strict --verbose=2 "$APP"
else
  # ---- Ad-hoc signing (original behaviour — no certs required) ------------
  echo "==> APPLE_SIGNING_IDENTITY unset — ad-hoc signing (local dev build)"
  echo "==> Signing Mach-O binaries in $APP"
  find "$APP" -type f | while read -r f; do
    if file -b "$f" 2>/dev/null | grep -q 'Mach-O'; then
      codesign --force --sign - "$f" 2>/dev/null || true
    fi
  done

  echo "==> Deep-signing $APP"
  codesign --force --deep --sign - "$APP"
  codesign --verify --deep --strict "$APP"
fi
