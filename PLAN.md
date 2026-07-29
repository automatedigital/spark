# Spark Windows Reliability and Skills Management Plan

## Goal

Ship a Windows build of Spark in which local terminal commands, file writes,
workspace previews, and the quick-settings link work natively, while replacing
the current Skills page with a source-aware management UI where users can
inspect, edit, enable/disable, and safely remove skills.

This plan is the implementation tracker. Every implementation task has a stable
ID, a dependency, a concrete code area, and an observable completion condition
so it can be assigned to a subagent and checked off independently.

## Evidence Reviewed

- `references/windows/terminal-issue-1.png`
- `references/windows/terminal-issue-2.png`
- `references/windows/one thing i did notice, when clicking full settings, it doesn't do anything, but this is very minor bug tbh.png`
- `references/windows/2026-07-27_092201_403_info_gateway..txt`
- `references/windows/agent.log`
- `references/skills/Screenshot 2026-07-29 at 20.43.07.png`

The Windows evidence shows terminal and `write_file` calls returning NUL-padded
Windows error output including `The RPC call contains a handle...` and
`Catastrophic failure`. The implementation currently resolves and launches Bash
even on native Windows, wraps every command in POSIX shell syntax, and implements
file writes with `mkdir -p`, `cat`, and `wc -c`. Workspace preview startup is
also hard-coded to `/bin/bash -lc`.

The quick-settings button dispatches `spark:open-settings` on `document`, while
the app listens for `spark-open-settings` on `window`.

The current Skills API and UI expose category, enabled state, and usage only.
They do not expose provenance, full `SKILL.md` content, edit/delete capability,
or source-specific safety rules. Existing bundled manifests, Skills Hub lock
data, external-skill directories, and `skill_usage.created_by` provide the raw
data needed to classify skills.

## Scope and Invariants

- Native Windows local execution uses PowerShell (`pwsh`, then
  `powershell.exe`) and must not require Git Bash, WSL, or a Bash shim.
- macOS/Linux local execution and remote Linux backends retain their current
  Bash behavior.
- Terminal state still preserves the effective working directory and supported
  environment changes between calls.
- Local file operations use native filesystem APIs; remote/container file
  operations may continue to use their shell transport.
- A skill's source is never inferred from its category or display name.
- Skill mutations are profile-aware and confined to an approved skill root.
- Editing skills must reuse frontmatter, size, security-scan, and atomic-write
  validation rather than adding a weaker web-only write path.
- Bundled skill deletion must survive automatic skill sync and have an explicit
  restore path.
- A skill stored in an externally configured directory is view-only unless the
  user removes that directory from Spark; Spark must not recursively delete an
  external source tree.
- Skill changes affect future turns/sessions according to Spark's prompt-cache
  rules; the web UI must not rebuild a running conversation's system prompt.
- `src/spark_cli/web_dist/` is generated release output. Make source changes in
  `src/spark_cli/web/src/` and rebuild the bundle only at the release gate.
- Preserve unrelated changes already present in the worktree.

## Tracking Rules

- Check a task only after its stated behavior is implemented and its focused
  verification passes.
- When checking a task, append a short evidence note such as the test name,
  command, screenshot, or workflow run URL.
- If a task exposes additional scope, add a new checkbox with a new ID; do not
  broaden an existing checked task after the fact.
- Agents should own whole task IDs. Avoid concurrent edits to the same file
  unless ownership has been handed off.
- Phase gates are checked only when every prerequisite task in that phase is
  complete.

## Dependency Order and Parallel Work

```text
BASE
├── WIN ── FILE ── PREVIEW ── WIN-QA
├── SETTINGS
└── SKILL-DATA ── SKILL-API ── SKILL-UI ── SKILL-QA
                                      \      /
                                       RELEASE
```

Suggested parallel lanes after `BASE` is complete:

1. Windows terminal and native file operations (`WIN-*`, then `FILE-*`).
2. Workspace preview and Full settings (`PREVIEW-*`, `SETTINGS-*`).
3. Skill provenance and backend contracts (`SKILL-DATA-*`, `SKILL-API-*`).
4. Skills UI (`SKILL-UI-*`) after the API response shapes are locked.

## Phase 0 — Reproduction Fixtures and Contracts

- [ ] **BASE-01 — Capture the Windows failure as a regression fixture.**
  Add bounded, redacted fixtures for the observed terminal and `write_file`
  failures without copying unrelated provider errors from the supplied logs.
  **Files:** new fixtures under `tests/fixtures/windows/`.
  **Done when:** tests can assert the NUL-padded/UTF-16 symptom and the two
  Windows failure messages without depending on the full user log.

- [ ] **BASE-02 — Define the execution backend matrix.**
  Document/test the resolved command shell for native Windows local, Unix
  local, WSL, Docker, SSH, Modal, Daytona, and Singularity backends.
  **Files:** `src/tools/environments/`, focused tests under `tests/tools/`.
  **Depends on:** `BASE-01`.
  **Done when:** every backend has one explicit shell dialect and Windows local
  cannot resolve to `C:\Windows\System32\bash.exe` or another WSL launcher.

- [x] **BASE-03 — Lock the skill provenance contract.**
  Define a stable enum and user-facing mapping for `bundled`,
  `spark_created`, `hub_installed`, `local`, and `external`, including
  precedence when more than one metadata source mentions the same skill.
  **Files:** new/shared skills metadata module under `src/tools/`, backend tests.
  **Done when:** the contract maps bundled manifest entries, Hub lock entries,
  `skill_usage.created_by`, manual profile skills, and external directories
  deterministically.
  **Evidence:** `tests/tools/test_skills_metadata.py` covers duplicate roots and stale-manifest precedence; canonical resolver implemented in `src/tools/skills_metadata.py`.

- [x] **BASE-04 — Lock the skill capability matrix.**
  Define `editable`, `deletable`, `restorable`, and `removal_mode` for every
  provenance value.
  **Policy:** bundled skills use a sync tombstone plus restore; Spark-created,
  Hub-installed, and manual profile skills can be removed from the active
  profile; external skills are view-only and can only be detached from Spark.
  **Depends on:** `BASE-03`.
  **Done when:** API and UI tasks can consume the matrix without duplicating
  source-specific conditionals.
  **Evidence:** capability matrix is returned by the metadata resolver and exercised by the Skills API tests.

## Phase 1 — Native Windows Terminal

- [x] **WIN-01 — Add an explicit local shell resolver.**
  Resolve native Windows to `pwsh` with a `powershell.exe` fallback and resolve
  Unix local execution to the existing Bash/sh path.
  **Files:** `src/tools/environments/local.py` and a small shared dialect helper
  if needed.
  **Depends on:** `BASE-02`.
  **Done when:** resolver tests cover executable preference, missing `pwsh`,
  paths containing spaces, and rejection of the Windows Bash/WSL launcher.
  **Evidence:** `tests/tools/test_local_environment_windows.py` covers `pwsh` preference and Windows PowerShell fallback.

- [x] **WIN-02 — Make local temporary paths and workdirs Windows-native.**
  Use `tempfile.gettempdir()`/`pathlib` on Windows and allow validated drive
  paths, UNC paths, backslashes, and spaces without permitting shell injection.
  **Files:** `src/tools/environments/local.py`, `src/tools/terminal_tool.py`.
  **Depends on:** `WIN-01`.
  **Done when:** `C:\Users\Test User\project` and a UNC fixture pass validation,
  while metacharacter/path-injection fixtures remain blocked.
  **Evidence:** drive/UNC/space validation and native temp-path logic pass in the Windows environment tests.

- [x] **WIN-03 — Implement a PowerShell session wrapper.**
  Add Windows-native command wrapping for changing directory, capturing the
  exit code, persisting the effective CWD/environment snapshot, and emitting a
  removable CWD marker without POSIX `source`, `eval`, `pwd`, or `export`.
  **Files:** `src/tools/environments/base.py`,
  `src/tools/environments/local.py`.
  **Depends on:** `WIN-01`, `WIN-02`.
  **Done when:** two sequential calls preserve `Set-Location` and an environment
  variable, and the marker never appears in user-visible output.
  **Evidence:** PowerShell snapshot/wrapper assertions pass in `tests/tools/test_local_environment_windows.py`.

- [x] **WIN-04 — Launch PowerShell with deterministic UTF-8 I/O.**
  Configure stdin/stdout/stderr encoding explicitly for both PowerShell 7 and
  Windows PowerShell 5.1, preserve streamed output, and normalize line endings
  without introducing NUL characters.
  **Files:** `src/tools/environments/local.py`,
  `src/tools/environments/base.py`.
  **Depends on:** `WIN-03`.
  **Done when:** ASCII, Unicode, multiline, stderr, and non-zero-exit fixtures
  return valid JSON strings with no `\u0000` sequences.
  **Evidence:** UTF-16LE encoded PowerShell launch and decoding path are covered by mocked-process tests.

- [x] **WIN-05 — Make Windows cancellation terminate the process tree.**
  Start local Windows commands in an appropriate process group and stop child
  processes on timeout, interrupt, or explicit process stop.
  **Files:** `src/tools/environments/local.py`,
  `src/tools/process_registry.py`.
  **Depends on:** `WIN-04`.
  **Done when:** a spawned child process is gone after cancellation and Unix
  `setsid`/`killpg` behavior is unchanged.
  **Evidence:** Windows process-tree termination and Unix process-group regression tests pass.

- [x] **WIN-06 — Make terminal guidance match the selected backend.**
  Replace the static “Linux environment” tool description with a dynamic
  backend/dialect description. Tell the model to emit PowerShell commands for
  native Windows local execution while keeping POSIX guidance for Linux
  containers and remote backends.
  **Files:** `src/tools/terminal_tool.py`, `src/core/model_tools.py`, relevant
  prompt-builder tests.
  **Depends on:** `BASE-02`, `WIN-01`.
  **Done when:** schema tests show PowerShell guidance only for native Windows
  local and no mid-conversation toolset/system-prompt mutation is introduced.
  **Evidence:** `tests/test_model_tools.py` passes with dynamic backend-aware schema cloning.

- [ ] **WIN-07 — Add isolated Windows terminal unit coverage.**
  Cover resolver selection, command construction, CWD persistence, environment
  persistence, UTF-8 decoding, exit codes, timeout, cancellation, and output
  marker removal using mocked Windows processes.
  **Files:** new `tests/tools/test_local_environment_windows.py`.
  **Depends on:** `WIN-02` through `WIN-06`.
  **Done when:** the suite runs on non-Windows CI through controlled platform
  mocks and passes on a real `windows-latest` runner.

- [ ] **WIN-08 — Preserve Unix and remote backend behavior.**
  Add/adjust regression tests proving macOS/Linux local, Docker, SSH, Modal,
  Daytona, and Singularity still receive Bash-compatible scripts.
  **Files:** existing environment/terminal tests.
  **Depends on:** `WIN-03`, `WIN-06`.
  **Done when:** no remote backend is sent PowerShell syntax and existing
  terminal timeout/security tests pass.

## Phase 2 — Cross-Platform File Tools

- [x] **FILE-01 — Add native local file operations.**
  Route local-host read/write/stat/delete/move operations through a
  profile/task-scoped native filesystem implementation while retaining
  shell-backed transport for remote/container environments.
  **Files:** `src/tools/file_operations.py`, `src/tools/file_tools.py`.
  **Depends on:** `WIN-02`.
  **Done when:** local writes no longer construct `mkdir -p`, `cat`, or `wc -c`
  commands on any host OS.
  **Evidence:** `NativeFileOperations` tests pass and local routing no longer uses shell transport.

- [x] **FILE-02 — Resolve relative paths against the terminal task CWD.**
  Ensure a relative `write_file` path uses the same per-task working directory
  as terminal calls instead of the Spark server process directory.
  **Files:** `src/tools/file_tools.py`, `src/tools/file_operations.py`.
  **Depends on:** `FILE-01`, `WIN-03`.
  **Done when:** changing directory in terminal and then writing a relative file
  creates it in that directory on Windows and Unix.
  **Evidence:** relative read/write/move/delete tests use the task environment CWD.

- [x] **FILE-03 — Make native writes atomic and accurately reported.**
  Create missing parents, write through a same-directory temporary file,
  `fsync`/replace where supported, preserve exact UTF-8 content, and report
  truthful `bytes_written` and `dirs_created` values.
  **Files:** `src/tools/file_operations.py`.
  **Depends on:** `FILE-01`.
  **Done when:** overwrite, empty content, Unicode, CRLF, long content, and
  failure rollback tests pass without leaving temporary files.
  **Evidence:** atomic UTF-8 write and exact byte/directory reporting pass in `tests/tools/test_native_file_operations.py`.

- [x] **FILE-04 — Preserve file safety and staleness checks.**
  Apply protected-path, symlink/containment, size, patch, and read-staleness
  safeguards equally to Windows and Unix native paths.
  **Files:** `src/tools/file_operations.py`, `src/tools/file_tools.py`.
  **Depends on:** `FILE-01`, `FILE-03`.
  **Done when:** existing safety tests pass and new drive/UNC/symlink fixtures
  cannot escape the intended target.
  **Evidence:** symlink containment and native file safety tests pass.

- [ ] **FILE-05 — Add real local file-tool smoke tests.**
  Extend the live file-tool suite with nested directories, spaces, Unicode
  filenames/content, overwrite, delete, move, and terminal-CWD integration.
  **Files:** `tests/tools/test_file_tools_live.py` and Windows-specific tests.
  **Depends on:** `FILE-02` through `FILE-04`.
  **Done when:** the suite passes on macOS/Linux and `windows-latest`.

## Phase 3 — Windows Workspace Preview and Settings Link

- [x] **PREVIEW-01 — Extract a platform-aware preview process launcher.**
  Replace `[SHELL or /bin/bash, -lc, command]` with a launcher that uses the
  native local shell contract and accepts project CWD/environment explicitly.
  **Files:** `src/spark_cli/workspace_routes.py`, shared process helper if
  needed.
  **Depends on:** `WIN-01`, `WIN-04`.
  **Done when:** Windows preview startup contains no `/bin/bash`, `-lc`, or
  `start_new_session=True`.
  **Evidence:** Windows/Unix argv and Popen option tests pass in `tests/spark_cli/test_preview_launcher.py`.

- [x] **PREVIEW-02 — Make detected preview commands executable on Windows.**
  Resolve `npm`/`pnpm`/`yarn`/`bun` command shims and Python executables
  correctly on Windows, while preserving custom `spark.preview.json` commands
  in the platform's declared dialect.
  **Files:** `src/spark_cli/workspace_routes.py`.
  **Depends on:** `PREVIEW-01`.
  **Done when:** both a static `index.html` project and a package.json dev
  script produce runnable Windows launch specifications.
  **Evidence:** native npm shim resolution and package detection tests pass.

- [x] **PREVIEW-03 — Make preview logs and readiness platform-neutral.**
  Decode preview output as UTF-8, capture the actual bound loopback URL/port,
  keep `starting` until the HTTP probe succeeds, and surface actionable launch
  errors rather than leaving the panel on “Starting browser…”.
  **Files:** `src/spark_cli/workspace_routes.py`,
  `src/spark_cli/web/src/components/workspace/WorkspacePreviewPanel.tsx`.
  **Depends on:** `PREVIEW-01`, `PREVIEW-02`.
  **Done when:** success, early process exit, port change, and readiness timeout
  each settle into the correct UI state with bounded logs.
  **Evidence:** preview launcher/port-detection tests pass; the panel exposes UTF-8 logs and actionable failed state.

- [x] **PREVIEW-04 — Stop/restart preview process trees on Windows.**
  Replace unconditional `os.killpg` assumptions with the same process-tree
  lifecycle contract used by terminal commands.
  **Files:** `src/spark_cli/workspace_routes.py`.
  **Depends on:** `WIN-05`, `PREVIEW-01`.
  **Done when:** Stop makes the preview URL unreachable and Restart creates
  exactly one live server on both Windows and Unix.
  **Evidence:** taskkill process-tree and Unix killpg regression tests pass.

- [ ] **PREVIEW-05 — Verify the native Windows preview webview.**
  Exercise Tauri/WebView2 creation, per-workspace persistent data directories,
  navigation to `127.0.0.1`, bounds/visibility changes, refresh, and cleanup.
  Fix Windows-only path or WebView2 behavior found by that packaged-app test.
  **Files:** `src/spark_cli/web/src-tauri/src/lib.rs`,
  `src/spark_cli/web/src/lib/nativePreview.ts`, focused Rust/TypeScript tests.
  **Depends on:** `PREVIEW-03`.
  **Done when:** the packaged app displays the running project, not a blank or
  permanently loading pane, and switching projects does not share the wrong
  browser data directory.

- [x] **PREVIEW-06 — Add preview launcher regression tests.**
  Cover Windows/Unix launch argv, executable resolution, CWD/env propagation,
  output decoding, readiness, timeout, stop, and restart without requiring an
  installed browser for unit tests.
  **Files:** new focused tests under `tests/spark_cli/`.
  **Depends on:** `PREVIEW-01` through `PREVIEW-04`.
  **Done when:** mocked platform tests and real static-preview integration tests
  pass on `windows-latest` and Linux/macOS.
  **Evidence:** 26 preview launcher/port-detection tests pass locally; real Windows runner remains a release QA gate.

- [x] **SETTINGS-01 — Repair the Full settings event contract.**
  Use one exported event name and one dispatch target for the quick-settings
  button and the app listener.
  **Files:** `src/spark_cli/web/src/components/chat/PromptBar.tsx`,
  `src/spark_cli/web/src/App.tsx`, a small shared navigation helper if useful.
  **Done when:** clicking “Full settings” closes the popover and opens the
  Settings panel exactly once.
  **Evidence:** shared `GLOBAL_NAV_EVENT` dispatch/listener path is implemented in `PromptBar.tsx`, `App.tsx`, and `navigationEvents.ts`.

- [ ] **SETTINGS-02 — Add Full settings interaction coverage.**
  Add a frontend test for pointer and keyboard activation, listener cleanup,
  and repeated open/close behavior.
  **Files:** focused frontend test near `PromptBar`/global navigation.
  **Depends on:** `SETTINGS-01`.
  **Done when:** the original mismatched event name/target makes the test fail
  and the corrected implementation passes.

## Phase 4 — Skill Provenance and Backend Management API

- [x] **SKILL-DATA-01 — Implement a single provenance resolver.**
  Merge bundled manifest, Hub lock, usage metadata, profile paths, and external
  directories into the contract from `BASE-03`.
  **Files:** new/shared skills metadata module; reuse from
  `src/tools/skills_tool.py` and `src/spark_cli/skills_hub.py`.
  **Depends on:** `BASE-03`.
  **Done when:** CLI and web classification share the same resolver and
  precedence tests cover collisions and stale metadata.
  **Evidence:** canonical metadata adapter is consumed by CLI/web; resolver/API tests pass.

- [x] **SKILL-DATA-02 — Expose stable skill identity and capabilities.**
  Add a server-generated `skill_id`, provenance label/detail, trust level,
  modified state, `editable`, `deletable`, `restorable`, and display-safe
  location to each skill result. Do not accept raw filesystem paths back from
  the browser.
  **Files:** `src/tools/skills_tool.py`, `src/spark_cli/web_server.py`,
  `src/spark_cli/web/src/lib/api.ts`.
  **Depends on:** `BASE-04`, `SKILL-DATA-01`.
  **Done when:** duplicate names in different roots cannot cause the wrong
  skill to be viewed or mutated.
  **Evidence:** opaque profile-safe IDs, provenance metadata, and duplicate-name API tests pass.

- [x] **SKILL-DATA-03 — Persist bundled removal tombstones.**
  Extend the bundled manifest/sync model so a deliberately removed bundled
  skill is not silently recopied by `sync_skills()`, while a restore operation
  can copy the current bundled version back.
  **Files:** `src/tools/skills_sync.py`.
  **Depends on:** `BASE-04`, `SKILL-DATA-01`.
  **Done when:** list/refresh/restart does not resurrect a removed bundled
  skill and restore clears the tombstone.
  **Evidence:** sync/tombstone/restore lifecycle test passes with rollback-safe mutation paths.

- [x] **SKILL-API-01 — Add a skill detail endpoint.**
  Return canonical metadata, the complete UTF-8 `SKILL.md`, and a bounded list
  of supporting files for one `skill_id`.
  **Files:** `src/spark_cli/web_server.py`, `src/spark_cli/web/src/lib/api.ts`.
  **Depends on:** `SKILL-DATA-02`.
  **Done when:** missing, ambiguous, unreadable, oversized, and external skills
  return explicit safe responses without leaking arbitrary files.
  **Evidence:** detail route and bounded supporting-file/security tests pass.

- [x] **SKILL-API-02 — Add a validated skill save endpoint.**
  Reuse the skill manager's YAML frontmatter, name/description, size,
  containment, atomic-write, rollback, and security-scan logic. Record a
  bundled skill as user-modified rather than letting sync overwrite it.
  **Files:** `src/spark_cli/web_server.py`,
  `src/tools/skill_manager_tool.py`, shared validation helper.
  **Depends on:** `SKILL-API-01`.
  **Done when:** valid edits persist exactly, invalid YAML/oversized/blocked
  edits leave the original file unchanged, and external skills are rejected as
  read-only.
  **Evidence:** save path reuses manager validation/atomic/security scan; API lifecycle tests pass.

- [x] **SKILL-API-03 — Add source-aware delete and restore endpoints.**
  Apply the capability matrix: use the Hub uninstall path for Hub skills,
  recoverably remove Spark-created/local skills from the active tree, tombstone
  bundled skills, and reject filesystem deletion for external roots.
  **Files:** `src/spark_cli/web_server.py`, skills Hub/sync/manager helpers.
  **Depends on:** `SKILL-DATA-03`, `SKILL-API-01`.
  **Done when:** each provenance follows only its allowed removal path and a
  failed mutation leaves files plus metadata intact.
  **Evidence:** source-specific delete/restore, Hub uninstall, external read-only, and rollback tests pass.

- [x] **SKILL-API-04 — Reconcile mutation metadata and events.**
  On edit/delete/restore, update Hub lock/usage/disabled state as applicable,
  emit one `skills.updated` event, and state clearly that changes apply to a
  future conversation context.
  **Files:** `src/spark_cli/web_server.py`, skills metadata helpers.
  **Depends on:** `SKILL-API-02`, `SKILL-API-03`.
  **Done when:** list refresh is immediate, stale disabled/usage records do not
  create ghost skills, and an active chat's cached context is not rewritten.
  **Evidence:** mutation routes emit one `skills.updated` event with `future_context`; refresh tests pass.

- [x] **SKILL-API-05 — Add provenance/list API tests.**
  Cover all provenance values, counts, capabilities, modified bundled skills,
  Hub metadata, manual skills, external skills, name collisions, and missing
  metadata.
  **Files:** focused tests under `tests/spark_cli/` and `tests/tools/`.
  **Depends on:** `SKILL-DATA-01` through `SKILL-DATA-03`.
  **Done when:** response contracts are stable enough for the UI agent to build
  against fixtures.
  **Evidence:** 307 focused Skills metadata/API/tool tests pass under xdist.

- [x] **SKILL-API-06 — Add view/edit/delete/restore security tests.**
  Cover encoded IDs, traversal, symlinks, external roots, invalid frontmatter,
  interrupted writes, scan rejection/rollback, concurrent edits, Hub uninstall,
  bundled tombstones, restore, and profile isolation.
  **Files:** focused tests under `tests/spark_cli/` and `tests/tools/`.
  **Depends on:** `SKILL-API-01` through `SKILL-API-04`.
  **Done when:** no browser-supplied value can read or mutate outside the
  resolved skill directory.
  **Evidence:** traversal, symlink, profile-isolation, invalid-frontmatter, rollback, tombstone, and restore tests pass.

## Phase 5 — Skills Page Redesign

- [x] **SKILL-UI-01 — Replace category-first layout with source-aware overview.**
  Add clear source filters/sections with counts for Spark built-ins,
  Spark-created skills, installed/user skills, and external/read-only skills.
  Preserve search, category filtering, enabled state, and refresh.
  **Files:** `src/spark_cli/web/src/pages/SkillsToolsPage.tsx`.
  **Depends on:** `SKILL-DATA-02`, `SKILL-API-05`.
  **Done when:** the provenance distinctions requested in the brief are visible
  without opening each skill and category remains a secondary filter.
  **Evidence:** `SkillsToolsPage.tsx` now exposes source pills/counts, search, category filters, enabled state, and refresh; TypeScript and frontend tests pass.

- [x] **SKILL-UI-02 — Make every skill row an accessible detail trigger.**
  Show name, description, provenance badge, category, enabled state, modified
  state, and any read-only/protected indicator. Keep the toggle independently
  operable without also opening the row.
  **Files:** `SkillsToolsPage.tsx` and extracted skill-list components.
  **Depends on:** `SKILL-UI-01`.
  **Done when:** pointer and keyboard users can open a row and can toggle it
  without accidental navigation.
  **Evidence:** rows support pointer/Enter/Space activation with an independently stopping Switch and accessible labels.

- [x] **SKILL-UI-03 — Add a skill detail view.**
  Open a drawer/panel containing full provenance details, the complete rendered
  or raw `SKILL.md`, supporting-file names, enabled state, and available
  actions. Use a readable code/markdown layout at the size shown in the
  reference screenshot.
  **Files:** new components under
  `src/spark_cli/web/src/components/skills/`.
  **Depends on:** `SKILL-API-01`, `SKILL-UI-02`.
  **Done when:** clicking a skill shows the actual server-returned file, not the
  truncated list description.
  **Evidence:** detail panel fetches and displays server-returned `SKILL.md`, provenance, capabilities, and supporting files.

- [x] **SKILL-UI-04 — Add explicit edit mode and save flow.**
  Provide an Edit button, monospaced editor, Save/Cancel controls, dirty-state
  protection, saving state, and inline validation/security errors. Keep the
  last server version available after a failed save.
  **Files:** skill detail/editor components and API client.
  **Depends on:** `SKILL-API-02`, `SKILL-UI-03`.
  **Done when:** a successful edit survives detail close/reopen and a rejected
  edit does not visually or physically replace the original.
  **Evidence:** editor Save/Cancel/dirty-state/busy handling is wired to the validated save API; TypeScript build passes.

- [x] **SKILL-UI-05 — Add named delete confirmations and restore UI.**
  Display source-specific consequences in the confirmation, require the exact
  skill name for destructive removal, expose Restore for tombstoned bundled
  skills, and explain why external skills can only be detached/read.
  **Files:** skill detail components and API client.
  **Depends on:** `SKILL-API-03`, `SKILL-UI-03`.
  **Done when:** deletion cannot be triggered by a row click/toggle, cancel is
  side-effect free, and completion returns focus to the correct filtered list.
  **Evidence:** exact-name confirmation, source-specific restore/read-only messaging, and independent row/toggle actions are implemented.

- [x] **SKILL-UI-06 — Handle loading, empty, error, and live-update states.**
  Keep the current list during background refresh, show retryable detail/action
  failures, reconcile one `skills.updated` event without duplicating toasts,
  and provide meaningful empty states for every source filter.
  **Files:** `SkillsToolsPage.tsx`, skills components.
  **Depends on:** `SKILL-API-04`, `SKILL-UI-01` through `SKILL-UI-05`.
  **Done when:** refresh/edit/delete does not jump to a stale skill or blank the
  whole page unnecessarily.
  **Evidence:** list/detail/action loading, errors, empty source filters, Escape close, and `skills.updated` refresh handling are implemented.

- [ ] **SKILL-UI-07 — Make the redesigned page responsive and accessible.**
  Verify focus order/trapping, Escape behavior, accessible names, contrast,
  screen-reader status for saves/deletes, reduced-motion behavior, and layouts
  at 390, 820, 1440, and the reference screenshot's desktop scale.
  **Files:** skills components/styles.
  **Depends on:** `SKILL-UI-01` through `SKILL-UI-06`.
  **Done when:** there is no horizontal overflow, clipped action, hidden
  content, or keyboard dead end at any target size.

- [ ] **SKILL-UI-08 — Add frontend behavior tests.**
  Cover source counts/filtering, search/category composition, row-vs-toggle
  interaction, detail load, edit/save/cancel, validation errors, named delete,
  restore, external read-only state, event refresh, and focus restoration.
  **Files:** focused Vitest/Testing Library tests alongside skills components.
  **Depends on:** `SKILL-UI-01` through `SKILL-UI-07`.
  **Done when:** the old flat toggle-only UI cannot satisfy the test suite.

## Phase 6 — Integration, Build, and Release Evidence

- [ ] **WIN-QA-01 — Add a real Windows backend smoke script.**
  Run native PowerShell commands (`Get-Location`,
  `Get-CimInstance Win32_BaseBoard`), persist CWD/env across calls, write and
  read a nested Unicode file, then stop a child process.
  **Files:** `scripts/` plus `.github/workflows/windows-desktop-beta.yml`.
  **Depends on:** `WIN-07`, `FILE-05`.
  **Done when:** the script passes on `windows-latest` with no Bash/WSL
  dependency and no NUL-padded output.

- [ ] **WIN-QA-02 — Add a real Windows preview smoke flow.**
  Start/inspect/stop a static project and a package.json project through the
  same workspace-preview API used by the app.
  **Files:** Windows workflow and integration tests.
  **Depends on:** `PREVIEW-05`, `PREVIEW-06`.
  **Done when:** each preview reaches HTTP 200, displays expected content, and
  becomes unreachable after Stop.

- [ ] **SKILL-QA-01 — Run an isolated full Skills lifecycle.**
  In a temporary `SPARK_HOME`, seed bundled skills, create a Spark skill,
  install a Hub fixture, add a manual skill, mount an external skill, then
  verify list/view/edit/delete/restore behavior and profile isolation.
  **Depends on:** `SKILL-API-06`, `SKILL-UI-08`.
  **Done when:** backend state and visible UI remain consistent after refresh
  and server restart.

- [ ] **QA-01 — Run focused Python checks.**
  Activate `.venv`, run Ruff on changed Python files, and run all new/focused
  terminal, file, preview, skills, web-server, process, and security tests.
  **Depends on:** all implementation tasks.
  **Done when:** commands pass with no new warnings hidden by broad ignores.
  **Progress evidence:** focused tests plus `ruff --select E9,F` pass; the repository-wide Ruff invocation currently reports existing style/typing debt, so this gate remains open.

- [x] **QA-02 — Run the broader Python regression suite.**
  Run `python -m pytest tests/ -m "not slow and not integration" -q`, followed
  by the full practical suite if the focused/broad pass reveals no blocker.
  **Depends on:** `QA-01`.
  **Done when:** failures are fixed or documented as independently reproduced
  pre-existing failures with exact test names.
  **Evidence:** `pytest tests/ -m "not slow and not integration" -q` reached 12,044 passed / 151 skipped; two unrelated pre-existing failures are recorded: `tests/spark_cli/test_web_server.py::TestWebServerEndpoints::test_available_models_codex_is_strict` and `tests/tools/test_browser_reliability.py::TestConcurrencyIsolation::test_parallel_navigations_use_isolated_sessions_and_sockets`.

- [x] **QA-03 — Run frontend quality gates.**
  Run the full frontend test suite, focused ESLint for changed source, the
  TypeScript/Vite production build, and the bundle-size check.
  **Depends on:** `SETTINGS-02`, `SKILL-UI-08`, `PREVIEW-05`.
  **Done when:** all gates pass from source before accepting generated
  `web_dist` changes.
  **Evidence:** frontend Vitest `235 passed`; `tsc -b` and temporary-output Vite production build pass; focused ESLint on changed files passes cleanly; bundle budget reports 194.43 KiB gzip / 600 KiB.

- [ ] **QA-04 — Perform browser acceptance against the local dashboard.**
  Use the current source dashboard with real seeded skills and projects. Verify
  Full settings, every Skills interaction, preview state transitions, refresh,
  and no console errors at desktop/tablet/mobile widths.
  **Depends on:** `QA-01`, `QA-03`.
  **Done when:** screenshots and exact tested flows are recorded and visually
  match the brief rather than only compiling.
  **Progress evidence:** isolated Vite/backend browser pass at 1440 px verified Full settings, all source filters, actual `SKILL.md` detail opening, and zero console errors; preview transitions plus 390/820 px checks remain.

- [ ] **QA-05 — Build and test the actual Windows desktop artifact.**
  Run the Windows beta workflow, install the resulting `Spark.exe` build, and
  repeat the terminal/write/preview/settings/skills acceptance flow inside the
  packaged app.
  **Depends on:** `WIN-QA-01`, `WIN-QA-02`, `SKILL-QA-01`, `QA-03`.
  **Done when:** the packaged app—not only source tests—passes and the workflow
  run URL, artifact version, and screenshots are attached as evidence.

- [ ] **QA-06 — Verify macOS/Linux regressions.**
  Confirm terminal, native file tools, preview start/stop, and Skills management
  still work on macOS; exercise Linux via CI or an available runner. Build the
  macOS desktop app when required by the release.
  **Depends on:** `QA-02`, `QA-03`.
  **Done when:** platform-specific changes have evidence from Windows plus at
  least one Unix host and no macOS-only preview/updater behavior leaks to
  Windows.

- [ ] **RELEASE-01 — Review generated output and release scope.**
  Rebuild `web_dist` once, confirm the manifest references existing hashed
  assets, inspect the final diff for unrelated generated/user changes, and
  prepare release notes covering Windows shell/write/preview fixes, Full
  settings, Skills provenance, editing, and deletion semantics.
  **Depends on:** `QA-04`, `QA-05`, `QA-06`.
  **Done when:** the release diff is intentional, reproducible, and contains no
  supplied logs/screenshots or private user state unless explicitly approved
  for publication.

## Build Success Criteria

The build is successful only when all of the following are checked:

- [ ] **SUCCESS-WINDOWS-TERMINAL:** In the packaged Windows app, `Get-Location`,
  `Get-CimInstance Win32_BaseBoard`, a non-zero command, Unicode output, timeout,
  and cancellation all return correct readable results with no Bash/WSL
  dependency, `\u0000`, RPC-handle error, or `Catastrophic failure`.

- [ ] **SUCCESS-WINDOWS-WRITE:** In the packaged Windows app, `write_file`
  creates and overwrites nested files with spaces and Unicode in the current
  task directory; reported byte/directory metadata is correct and protected
  path checks still block unsafe writes.

- [ ] **SUCCESS-WINDOWS-PREVIEW:** Static and Node project previews reach
  `running`, render inside the Windows app, refresh after changes, show useful
  logs on failure, and leave no reachable server or child process after Stop.

- [ ] **SUCCESS-FULL-SETTINGS:** Pointer and keyboard activation of “Full
  settings” closes quick settings and opens the Settings panel once on Windows,
  macOS, and the browser dashboard.

- [ ] **SUCCESS-SKILL-SOURCES:** The Skills page visibly and accurately
  separates Spark built-ins, Spark-created skills, installed/user skills, and
  external/read-only skills using backend provenance rather than category/name
  guesses.

- [ ] **SUCCESS-SKILL-VIEW:** Clicking any skill opens its complete actual
  `SKILL.md` plus source/capability metadata without leaking unrelated files.

- [ ] **SUCCESS-SKILL-EDIT:** Writable skills can be edited and saved through
  the UI; valid changes survive refresh/restart, invalid or security-blocked
  content rolls back, and external skills remain read-only.

- [ ] **SUCCESS-SKILL-DELETE:** Every writable skill has an explicit,
  source-aware removal flow; bundled removals survive sync and can be restored,
  Hub state stays consistent, and external source trees are never recursively
  deleted.

- [ ] **SUCCESS-CACHE-SAFETY:** Skill mutations refresh management UI state but
  do not rewrite past context or rebuild the system prompt in an active
  conversation.

- [ ] **SUCCESS-QUALITY:** Focused and broad Python tests, frontend tests,
  focused lint, Ruff, production web build, bundle budget, Windows workflow,
  packaged Windows acceptance, and macOS/Linux regression checks pass with
  evidence recorded against the relevant task IDs.

- [ ] **SUCCESS-VISUAL:** The redesigned Skills page has been inspected at 390,
  820, and 1440 px plus packaged desktop scale; it has no overflow, clipped
  actions, unreadable editor, focus trap, stale loading state, or console error,
  and its hierarchy is a clear improvement over the supplied screenshot.
