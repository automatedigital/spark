---
name: build-mac
description: Rebuild the Spark macOS desktop app (.app + .dmg) after web UI or backend changes
---

Rebuild the Spark macOS desktop app by running the full build pipeline.

## Steps

1. Run the build script:

```bash
cd /Users/joe/Developer/github/spark
bash scripts/build_desktop.sh
```

2. Watch the output for errors. The pipeline has 5 stages:
   - **Stage 1**: `npm run build` — Vite frontend compile
   - **Stage 2**: PyInstaller freeze → `dist/spark-server/`
   - **Stage 3**: `tauri build` — Rust compile + .app bundle
   - **Stage 4**: Post-build inject — `cp -R dist/spark-server Spark.app/Contents/Resources/spark-server`
   - **Stage 5**: `make_dmg.sh` — styled drag-to-install DMG

3. On success, report the output paths:
   - App: `src/spark_cli/web/src-tauri/target/release/bundle/macos/Spark.app`
   - DMG: `Spark.dmg` (repo root)

4. If any stage fails, show the error output and suggest a fix:
   - Stage 1 failures: TypeScript/Vite errors in `src/spark_cli/web/src/`
   - Stage 2 failures: Python import errors or missing deps — check `spark-server.spec` excludes
   - Stage 3 failures: Rust compile errors — run `cargo check` in `src/spark_cli/web/src-tauri/`
   - Stage 4: Verify `dist/spark-server/` exists before injecting
   - Stage 5: Requires `hdiutil` (macOS only)

## Notes

- Build takes ~10–15 min (PyInstaller + Rust are the slow parts)
- Must be run on Apple Silicon Mac (the frozen sidecar is aarch64)
- The Python venv must exist: `source venv/bin/activate` is handled inside the script
- After building, run `/release-mac` to publish to GitHub
