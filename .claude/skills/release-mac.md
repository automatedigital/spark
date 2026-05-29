---
name: release-mac
description: Publish the Spark macOS DMG to GitHub Releases and upload as a release asset
---

Publish the built Spark macOS app to GitHub Releases.

## Steps

### 1. Verify the DMG exists

```bash
ls -lh /Users/joe/Developer/github/spark/Spark.dmg
```

If missing, tell the user to run `/build-mac` first.

### 2. Determine the version

Read the version from tauri.conf.json:

```bash
python3 -c "
import json, pathlib
conf = json.loads(pathlib.Path('src/spark_cli/web/src-tauri/tauri.conf.json').read_text())
print(conf.get('version', '0.1.0'))
"
```

### 3. Confirm with the user

Before proceeding, tell the user:
- The version you found (e.g., `0.1.0`)
- The tag that will be created (e.g., `desktop-v0.1.0`)
- The DMG file size
- Ask: "Should I create release `desktop-v0.1.0` and upload Spark.dmg?"

Wait for confirmation.

### 4. Commit any pending changes and tag

```bash
# Only tag if working tree is clean
git status --short
git tag desktop-v<VERSION>
git push origin desktop-v<VERSION>
```

If the working tree has uncommitted changes, warn the user and ask whether to tag anyway or commit first.

### 5. Create the GitHub Release and upload the DMG

```bash
gh release create "desktop-v<VERSION>" \
  "/Users/joe/Developer/github/spark/Spark.dmg#Spark.dmg" \
  --title "Spark Desktop v<VERSION>" \
  --notes "## Spark Desktop v<VERSION>

### Install
1. Download **Spark.dmg**
2. Open the DMG and drag Spark to Applications
3. On first launch: right-click → Open (required because this build is unsigned)

### Requirements
- macOS 13+ (Apple Silicon)

### Notes
- Unsigned build — macOS will warn on first open. Right-click → Open to bypass.
"
```

If a release for this tag already exists, use `gh release upload` to add/replace the asset:

```bash
gh release upload "desktop-v<VERSION>" \
  "/Users/joe/Developer/github/spark/Spark.dmg#Spark.dmg" \
  --clobber
```

### 6. Report success

Print the release URL returned by `gh release create` so the user can share it.

## Notes

- Tag prefix `desktop-v*` keeps desktop releases separate from any future library/CLI tags
- The DMG is ~400MB — GitHub Releases supports up to 2GB per asset
- Requires `gh` CLI authenticated: `gh auth status`
- Once you have Apple Developer ID, add signing/notarization to `scripts/build_desktop.sh` before releasing publicly
