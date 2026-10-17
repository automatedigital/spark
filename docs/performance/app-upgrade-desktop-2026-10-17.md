# macOS package and native acceptance — 17 October 2026

The standard `scripts/build_desktop.sh` produced Spark.app and Spark.dmg from the
consolidated application code in `99be7b43` (build started at `f048473c`; later
commits changed only acceptance fixtures and documentation). Actual Node was
22.22.1. Frontend compilation, frozen resource audit (208 sidecar files, 47 web
assets, zero problems), frozen-backend startup, Rust compilation, app signing and
DMG creation passed. The canonical tracked bundle remained byte-identical.

**Distribution is blocked.** The script exited 1 when Apple's notary service
returned HTTP 403: “A required agreement is missing or has expired.” Deep/strict
codesign verification passes; Gatekeeper reports `Unnotarized Developer ID` and
stapler reports no ticket. The Apple account holder must resolve the agreement
before notarization can be retried. No release or production deployment occurred.

Artifacts:

- App: `src/spark_cli/web/src-tauri/target/release/bundle/macos/Spark.app`
- DMG: `src/spark_cli/web/src-tauri/target/release/bundle/dmg/Spark.dmg`
- DMG SHA-256: `10287bfb9b0366960b85bc103cda1502ff3c7bac01f704d66c3a23859c057ab0`
- Native executable SHA-256: `c4fb335ad4f289a2e018c1737f2bcbe090637dc61cca27630540db140d2db065`

## Native and packaged checks

Mounted the actual DMG read-only and copied its app into an isolated test
Applications directory, preserving the user's installed app. Launched the
canonical `/private/tmp/spark-desktop-qa-20261017/Applications/Spark.app` executable
with an isolated SPARK_HOME, empty PYTHONPATH and loopback synthetic streams.
Verified `/api/status` reported the expected home before subsequent acceptance
writes. No model-provider request or external message was sent.

`scripts/desktop_runtime_acceptance.py --phase prepare --platform macos` passed
14 checks through the packaged HTTP backend: frontend/status, project creation,
file read/write, native terminal, preview start/stop, synthetic first token,
resumed SSE tool/terminal events and snapshot hydration. `--phase resume` passed
after clean quit/relaunch and again after forced test-sidecar loss and relaunch.
These are functional timings, not repeated latency benchmarks.

Native CUA observations confirmed:

- Parent transcript and persisted child transcript/result render in the actual
  WKWebView. Completed-child Stop is disabled with “No live owned child”; Retry
  is disabled with “Async execution is disabled.” No native live-child Stop or
  Retry execution is claimed.
- An unsent draft survives two invocations of Cmd+Shift+Space and clean native
  quit/relaunch, alongside selected-child restoration. CUA observation can raise
  the window, so independent global focus/hide behavior is not established.
- Forced loss of the owned test sidecar displays “Reconnecting,” “Load failed,”
  last-loaded child state and stale-capability control reasons. Draft remains.
  Relaunch restores the same draft/child and persisted file.
- Quit via the native app menu closes the shell and owned sidecar. Final process
  inventory has no test app or listener on 9119.

Real machine sleep/wake and Windows execution were not tested. These limitations,
live-child native controls and global Quick Ask focus prevent closing the whole
installed-platform checklist item. No synthetic suspend is labelled real sleep.

## Preserved harness failures and cleanup

The first direct launch used the `/tmp` symlink and crashed with Tauri setup
`unknown path`. CUA then automatically relaunched the test copy through Launch
Services without its isolated environment. Before the incorrect profile was
noticed, the acceptance script created `native-acceptance-20261017` in the real
workspace, wrote its two synthetic marker files, ran the local marker terminal
and preview, then failed at the disabled fake-stream endpoint. No provider prompt
was submitted. The app was stopped and that exact test project was moved out of
the user's workspace into the QA artifact directory; it was not deleted. No
unrelated project was changed. Subsequent runs used canonical paths and an explicit
status-home precondition before writes.

After the first clean quit, requesting CUA state automatically relaunched the
copy without the isolated environment again. It was stopped before further
acceptance writes. Final quits deliberately omit post-quit CUA observation and
verify closure through process/port inventory instead. Future native fixtures
must account for this automation behavior rather than assume a UI binding
preserves a subprocess environment.

Raw evidence: `/tmp/spark-desktop-build-20261017.log`, codesign/Gatekeeper/stapler
logs with the same date, and `/tmp/spark-desktop-qa-20261017/` launch logs,
isolated prepare/resume reports and recovered wrong-profile test project.
Adjacent JSON pins the artifacts and receipts. This is partial native acceptance,
not a notarized release or full P10 completion.
