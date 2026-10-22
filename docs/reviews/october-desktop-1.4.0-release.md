# Spark Desktop 1.4.0 release evidence

Release: https://github.com/automatedigital/spark/releases/tag/desktop-v1.4.0

Source/tag target: 824ea1e4e17444e34fe1c14b6581d29d54d205e9 (main merge of #185).
Accepted review head: 98e393d4085a763189019d19fb99fcdfd4474047, all eight hosted checks successful.
All twenty original code PRs, tracker #144 and integration #185 are merged; all twenty outcome issues are closed. Final source/native/browser evidence was posted on each outcome issue.

## macOS artifact
- Built using scripts/build_desktop.sh, Node 22.22.1 and isolated Python packaging environment.
- Frozen resource audit and actual frozen backend startup smoke passed.
- Developer ID hardened runtime signing; Apple notary submission e479af5b-03ae-4fa4-8567-d74e5e8b224d accepted; DMG ticket stapled and validated.
- Authoritative verification is the app copied from the final DMG into a temporary installation: deep/strict signature valid, Gatekeeper accepted as Notarized Developer ID, CFBundleShortVersionString 1.4.0.
- Native LaunchServices app ran with isolated HOME/USERPROFILE/CFFIXED_USER_HOME/SPARK_HOME, with Foundation home/application-support paths confirmed isolated. Provider-free fake stream and loopback fixture model only.
- Packaged API acceptance: 14 prepare checks, 13 after-wake checks, four after-relaunch checks. Includes files, native terminal marker, preview start/status/stop, chat/tool SSE delivery/resume/hydration and persisted file recovery.
- Three-second owned app/sidecar process suspension retained server instance; clean Cmd+Q stopped the sidecar; relaunch used a new server instance and preserved data. This is process suspend/resume, not a physical machine power-sleep test.
- CUA native AX and screenshot verified the selected packaged chat response and project file explorer with persisted and terminal marker files.
- Initial direct-executable harness failed Tauri resource lookup; normal macOS LaunchServices launch passed. The pre-DMG staging app was not the notarized copy: DMG packaging re-signs a staged copy. Only the actual distributed DMG's installed copy is claimed Gatekeeper-approved.
- All owned QA app/sidecar processes stopped. No live profile/provider was used.

## Windows artifact
- Workflow https://github.com/automatedigital/spark/actions/runs/39817219208 succeeded at the exact source/tag target.
- Unsigned x64 NSIS beta installer built; native worktree ownership/locking and packaged executable lifecycle steps passed.
- Actual packaged spark.exe ran prepare, process suspend/resume, prepare after wake and quit/relaunch/resume acceptance. Launch-to-ready 5.568s, relaunch 3.080s.
- Installer build/artifact bytes are verified; interactive NSIS installation UI was not exercised here. Native bundle lifecycle is a separate supported claim.
- Windows saved scheduled output remains capability-disabled where safe directory-relative/no-follow access is unavailable. No insecure fallback.
- Windows is an unsigned beta; macOS is signed/notarized.

## Artifact hashes
- Spark.dmg: 52864896 bytes; SHA-256 3158593766843d12d4617b31cd8a50300ce56a3a2bc4ba4a857102f287fe3757
- Spark_1.4.0_x64-setup.exe: 45158332 bytes; SHA-256 6d8db53b3fc960742944ef049e44fd9b9ee971ec8188a44be2a1302d9c83f3d6

SHA256SUMS.txt is attached to the release. GitHub draft upload reported matching server-side SHA-256 digests and sizes for all three assets before publication. Final unauthenticated public-download verification is recorded separately in october-release-public-verification.json.

## Validation boundaries
The 562 frontend tests, 12,692 parallel-safe and 182 serial Python tests, exact-head native Windows persistence (210 passed / 32 platform skips), 505 hosted backend lifecycle/cache/discovery tests, all feature browser flows and all inspector/sidebar/recovery/navigation/three-attempt longthread gates passed. Full Ruff retains 298 baseline findings outside the enforced clean families; no gate was waived. Physical audio and real provider calls are not release test claims.
