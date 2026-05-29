---
name: release-mac
description: >
  Publish the Spark macOS DMG to GitHub Releases as a release asset.
  Use when the user types /release-mac or asks to release, publish, or ship
  the desktop app or DMG.
---

# Release Spark macOS Desktop App

Publish `Spark.dmg` from the **repository root** to GitHub Releases with tag prefix `desktop-v*`.

## Step 1 — Verify the DMG

```bash
cd "$(git rev-parse --show-toplevel)"
ls -lh Spark.dmg
```

If missing, tell the user to run `/build-mac` first and stop.

## Step 2 — Read the version

```bash
python3 -c "
import json, pathlib
conf = json.loads(pathlib.Path('src/spark_cli/web/src-tauri/tauri.conf.json').read_text())
print(conf.get('version', '0.1.0'))
"
```

Set `VERSION` from the printed value and `TAG=desktop-v${VERSION}`.

## Step 3 — Confirm with the user

Before tagging or releasing, tell the user:

- Version (e.g. `0.1.0`)
- Tag (e.g. `desktop-v0.1.0`)
- DMG file size from `ls -lh`

Ask: **"Should I create GitHub Release `desktop-v<VERSION>` and upload Spark.dmg?"**

Wait for confirmation.

## Step 4 — Tag (if needed)

```bash
git status --short
git tag "$TAG" 2>/dev/null || true
git push origin "$TAG"
```

If the working tree is dirty, warn the user and ask whether to tag anyway or commit first. If the tag already exists on the remote, skip creating it.

## Step 5 — Create release or upload asset

**New release:**

```bash
gh release create "$TAG" \
  "Spark.dmg#Spark.dmg" \
  --title "Spark Desktop v${VERSION}" \
  --notes "## Spark Desktop v${VERSION}

### Install
1. Download **Spark.dmg**, drag Spark to Applications
2. **Right-click → Open** on first launch (unsigned build)
3. If blocked: System Settings → Privacy & Security → Open Anyway
4. For silent Gatekeeper: run `scripts/notarize_mac.sh` before release (Apple Developer ID required)

### Requirements
- macOS 13+
- Apple Silicon

### Notes
- Unsigned build: macOS warns on first open. Right-click → Open to bypass.
"
```

**Release already exists:**

```bash
gh release upload "$TAG" "Spark.dmg#Spark.dmg" --clobber
```

## Step 6 — Report

Print the release URL from `gh` output.

## Notes

- `desktop-v*` tags keep desktop releases separate from CLI/library tags.
- DMG is ~400MB; GitHub allows up to 2GB per asset.
- Requires `gh auth status` to succeed.
- Add code signing/notarization in `scripts/build_desktop.sh` before wide public distribution.
- **`Spark.dmg` is in `.gitignore`** — publish to GitHub Releases only; never `git add` the DMG. Commit `Cargo.lock` after version bumps if it changed.
