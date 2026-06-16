#!/usr/bin/env bash
# notarize_mac.sh — Submit a .dmg (or .app) to Apple notarization and staple it.
#
# Usage: notarize_mac.sh <path/to/output.dmg>
#
# Notarization is GATED on credentials being present in the environment. If they
# are not set, this script skips notarization with a clear log message and exits
# 0 so local/ad-hoc dev builds keep working.
#
# Two credential modes (checked in this order):
#
#   1. Keychain profile — set APPLE_KEYCHAIN_PROFILE to the name of a profile
#      previously stored with:
#        xcrun notarytool store-credentials "<profile>" \
#          --apple-id "<you@example.com>" \
#          --team-id "<TEAMID>" \
#          --password "<app-specific-password>"
#
#   2. Inline credentials — set ALL of:
#        APPLE_ID        — Apple Developer account email
#        APPLE_PASSWORD  — app-specific password (NOT your Apple ID password)
#        APPLE_TEAM_ID   — 10-char Team ID
#
# NEVER hardcode credentials here — all values come from env.
set -euo pipefail

TARGET="${1:?usage: notarize_mac.sh <output.dmg>}"
[ -e "$TARGET" ] || { echo "error: not found: $TARGET" >&2; exit 1; }

NOTARY_ARGS=()
if [ -n "${APPLE_KEYCHAIN_PROFILE:-}" ]; then
  echo "==> Notarizing via keychain profile: $APPLE_KEYCHAIN_PROFILE"
  NOTARY_ARGS=(--keychain-profile "$APPLE_KEYCHAIN_PROFILE")
elif [ -n "${APPLE_ID:-}" ] && [ -n "${APPLE_PASSWORD:-}" ] && [ -n "${APPLE_TEAM_ID:-}" ]; then
  echo "==> Notarizing via Apple ID: $APPLE_ID (team $APPLE_TEAM_ID)"
  NOTARY_ARGS=(--apple-id "$APPLE_ID" --password "$APPLE_PASSWORD" --team-id "$APPLE_TEAM_ID")
else
  echo "==> Notarization skipped — no credentials in environment."
  echo "    Set APPLE_KEYCHAIN_PROFILE, or APPLE_ID + APPLE_PASSWORD + APPLE_TEAM_ID,"
  echo "    to enable notarization. (Local/ad-hoc builds do not need this.)"
  exit 0
fi

echo "==> Submitting $TARGET to Apple notary service (this can take minutes)"
xcrun notarytool submit "$TARGET" "${NOTARY_ARGS[@]}" --wait

echo "==> Stapling notarization ticket to $TARGET"
xcrun stapler staple "$TARGET"
xcrun stapler validate "$TARGET"

echo "  Notarized + stapled: $TARGET"
