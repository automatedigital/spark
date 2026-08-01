# Desktop package acceptance: v1.3.31

Captured on 2026-08-01 from merged `main` commit
`fb52802634355cfccf2592194f7209f624b13a75`. Source, browser, macOS package,
and Windows package results are reported separately below; passing one does not
stand in for another.

## macOS distribution

The release build produced a signed `Spark.app` and a notarized, stapled
`Spark.dmg`. The bundle identifier is `studio.fromtheroot.spark` and both bundle
version fields are `1.3.31`. `codesign --verify --deep --strict` passed. The DMG
passed `hdiutil verify`, `stapler validate`, and Gatekeeper assessment as a
Notarized Developer ID distribution. The app mounted from that DMG also passed
Gatekeeper. The loose build-directory app is signed but does not carry a
separate staple; the supported distribution and release artifact is the DMG.

The v1.3.31 DMG is 49,695,941 bytes with SHA-256
`226336cb95d4d12d00e175a215d22e129fab7c49eb2afc5b2c7955c42305885c`.
The unpacked app is 97,940 KiB and its frozen sidecar is 75,256 KiB. The
v1.3.30 comparison artifacts were 49,523,459 bytes, 97,736 KiB, and 75,104 KiB
respectively. That is a 0.35% DMG increase and roughly 0.2% increases in the app
and sidecar; package size did not improve.

Three comparable cold sidecar launches on the same host produced root/status
times of 0.6674/0.7386, 0.6927/0.7659, and 0.7207/0.7672 seconds. The v1.3.30
trials were 2.70/3.05, 0.842/0.880, and 0.690/0.765 seconds. Medians improved
from 0.842 to 0.6927 seconds for the root (-17.7%) and from 0.880 to 0.7659
seconds for status (-13.0%). This complements the source-level fresh-process
import result; it does not conceal the small package-size regression.

The actual packaged application was launched with an isolated persistent
`SPARK_HOME`. Its status identified desktop version 1.3.31, platform `macos`,
and commit `fb528026`. The prepare phase passed frontend load, backend status,
workspace create/list, native file write/read, POSIX terminal output, preview
start/stop, first streamed token (0.1611 seconds), tool start/end events, SSE
sequence resume, and authoritative web-state hydration. After quitting both the
Tauri process and sidecar, a fresh launch used a new server instance and the
resume phase recovered the session and persisted file marker from the same
`SPARK_HOME`.

The deterministic fake stream used for packaged first-token/tool verification
travels through the production HTTP, event, persistence, and web-state pipeline;
it is not described as a live provider call. The separate same-model live
provider A/B is recorded in `response-live-ab-v1.json`.

## Windows distribution

Native GitHub Actions run
[`30714505055`](https://github.com/automatedigital/spark/actions/runs/30714505055)
completed successfully against exact commit `fb528026`. It produced the
unsigned NSIS installer `Spark_1.3.31_x64-setup.exe`: 42,711,926 bytes, SHA-256
`7a8c95f1ce4dc1d1bbdddd335d6052310c44097ab72b5dce689c2f2232feeac6`.
The v1.3.30 installer was 42,564,153 bytes with SHA-256
`bb43d86a6fc53eccd9e4ab0dae5472b6ba45ff7d947bb567f696272ea91c8dd1`.
The installer grew by 147,773 bytes (0.35%); package size did not improve.

The workflow launched the actual packaged `target/release/spark.exe` with an
isolated `SPARK_HOME`. The first prepare phase passed frontend/backend health,
workspace create/list, Windows-native `cmd` terminal output, file read/write,
preview start/stop, first streamed token (0.1494 seconds), tool start/end events,
SSE sequence resume, and web-state hydration. It then suspended the exact Tauri
and sidecar process tree with `NtSuspendProcess`, waited three seconds, resumed
the same PIDs, required the same `server_instance_id`, and repeated the complete
acceptance flow successfully (first token 0.2440 seconds). This is a CI
process-tree suspend/resume simulation, not a claim of literal hosted-OS sleep.
Finally, the workflow killed and relaunched the process tree, required a changed
server instance, and recovered the persisted workspace and file marker.

## Version-linked acceptance index

“Versioned replay set” means release evidence set `desktop-v1.3.31-2026-08-01`.
The deterministic replay and lazy-startup/RSS capture were rerun from clean
commit `4f380488`. The macOS package commit `fb528026` has the same product
source and desktop version; intervening commits change only this evidence report,
`PLAN.md`, and Windows workflow timing instrumentation. The refreshed Windows
package is built at `4f380488`. Later evidence-only commits do not change the
measured Python, web, Rust, or package inputs. This mapping avoids presenting
measurements from different code revisions as though they were one process run.

| Result class | Versioned evidence |
| --- | --- |
| Source checks | 12,193 passed, 151 skipped at the final source candidate; two failures reproduced unchanged on baseline `main`; 770 focused tests and scoped lint/type checks passed. |
| Source browser | Playwright/Chromium multi-chat, long-result, refresh, reconnect, backend-restart, stale-state, and responsive-width acceptance in `browser-efficiency.md`. |
| macOS package | Signed/notarized v1.3.31 package and lifecycle evidence above. |
| Windows package | Native unsigned v1.3.31 installer and lifecycle passed in run `30714505055` at exact commit `fb528026`. |
| Replay metrics | Fixed/schema/conversation/tool-result token buckets, provider cache read/write counters, output tokens, latency, DB I/O, event traffic, startup and RSS are indexed in `efficiency-replay.md` and its linked raw files. |
| Package metrics | v1.3.30 versus v1.3.31 macOS and Windows artifact comparison in this report. |

Token reductions retain the complete static system and project-rule blocks.
Golden prompt/schema tests, typed-ledger fidelity tests, recoverable artifact
paging, risk/capability routing, explicit verbosity overrides, and the manually
reviewed live same-model A/B guard against savings obtained by omission or
unsafe truncation. Packaged smoke tests independently confirm that the compact
path retains file, terminal, preview, and tool-event capabilities.
