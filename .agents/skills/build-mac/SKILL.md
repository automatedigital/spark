---
name: build-mac
description: >
  Rebuild the Spark macOS desktop app (.app + .dmg) after web UI or backend changes.
  Use when the user types /build-mac or asks to rebuild, compile, or package the
  desktop app, Tauri app, or DMG.
---

# Build Spark macOS Desktop App

Run the full 5-stage desktop build pipeline from the **repository root** (the directory that contains `scripts/build_desktop.sh`).

## Step 1 — Run the build

```bash
cd "$(git rev-parse --show-toplevel)"
bash scripts/build_desktop.sh
```

Stream output. Stages:

| Stage | What | Typical failure |
|-------|------|-----------------|
| 1 | `npm run build` — Vite frontend | TS/Vite errors in `src/spark_cli/web/src/` |
| 2 | PyInstaller → `dist/spark-server/` | Import errors; check `spark-server.spec` excludes |
| 3 | `tauri build` — Rust + `.app` | Run `cargo check` in `src/spark_cli/web/src-tauri/` |
| 4 | Inject sidecar into `.app` | Ensure `dist/spark-server/` exists |
| 5 | `make_dmg.sh` — drag-to-install DMG | Requires macOS `hdiutil` |

## Step 2 — Report success

On success, report:

- **App:** `src/spark_cli/web/src-tauri/target/release/bundle/macos/Spark.app`
- **DMG:** `Spark.dmg` at the repo root

Tell the user they can run `/release-mac` to publish to GitHub Releases.

## Step 3 — Handle failures

If a stage fails, show the relevant log lines and the fix hint from the table above. Do not guess — use the actual error output.

## Notes

- Build takes ~10–15 minutes (PyInstaller + Rust are slow).
- Must run on **Apple Silicon** Mac (frozen sidecar is aarch64).
- `scripts/build_desktop.sh` activates the venv; no manual `source venv` needed.
