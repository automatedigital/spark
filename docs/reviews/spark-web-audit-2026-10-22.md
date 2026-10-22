# Spark web/API audit — 2026-10-22

Base: `64af0d26976714b747dd4f1cc5b495c47c7f7567` on `main` (verified locally).

Research only. Read AGENTS.md, CONTEXT.md, STRUCTURE.md and accepted ADRs 0001, 0012, 0013. No source edits, issues, PRs, delegation, provider calls, or live Spark state. The unrelated handoff move remains exactly as found: deleted `HANDOFF_100826.md`, untracked `docs/HANDOFF_100826.md`.

Seven current defects follow. Five were reproduced by calling actual route functions against disposable filesystem/Git fixtures under temporary directories, with SPARK_HOME/HOME/USERPROFILE redirected before imports. Two frontend defects are confirmed by source tracing; browser/hook runtime verification remains a proposed implementation acceptance check. These are specific failures, not old PLAN acceptance gates. No claim of a full browser or gateway audit.

## W01 — Context and brief clients ignore the configured remote backend (P1)

- Evidence: `src/spark_cli/web/src/lib/context.ts:51-57` calls `fetch(url, ...)` directly. All context and brief operations use relative `/api/...` URLs at lines 60-102. The shared transport correctly prefixes `getApiBase()` at `src/spark_cli/web/src/lib/apiHelpers.ts:142-147`. Related affected flow: `src/spark_cli/web/src/components/ChatPanel.tsx:1023-1041` sends summarize-file directly to the current origin and omits dashboard authorization.
- Trigger: desktop/dashboard is configured to control a remote Spark instance; load or modify context, promote text to the brief, estimate tokens, or summarize an attachment.
- Impact: requests go to the local origin/sidecar rather than the selected backend. They fail or read/write local state for an unrelated session; summarize also fails on a protected dashboard because it has no auth header.
- Narrow fix: use shared `fetchJSON` from apiHelpers for context/brief and expose summarize-file through the same transport. Preserve existing payloads. Avoid importing the api facade from context.ts when importing the helper suffices.
- Owned paths: `web/src/lib/context.ts`, the summarize handler in `web/src/components/ChatPanel.tsx`, narrowly scoped transport tests (all web paths relative to `src/spark_cli/`). No backend change required.
- Meaningful validation: mock fetch with remote base + token and assert exact URL/header/body for context GET/PUT/DELETE, brief GET/PUT, estimate, summarize; assert same-origin behavior in local mode. Browser acceptance against two isolated fixture backends must prove requests reach only the selected one. Summarize can return a fixture response; no provider call needed.
- Overlap: W02 also edits context.ts; land W01 first or assign one writer. Summarize's missing auth belongs in this transport fix, not a second counted bug.

## W02 — Older token estimates overwrite newer prompt/session estimates (P2)

- Evidence: `src/spark_cli/web/src/hooks/useTokenEstimate.ts:18-34` creates/aborts an AbortController but never passes its signal to estimateTokens. `context.ts:78-90` has no signal argument. Both success and error callbacks update state without a request generation check. Cleanup at hook lines 37-39 clears only the debounce timer.
- Trigger: prompt/session A launches an estimate; change to B; B resolves before A, or A fails after B succeeds.
- Impact: A's token counts/warning overwrite B's estimate, or an old failure clears the current result. The unused controller does not prevent any request or callback.
- Narrow fix: pass AbortSignal through the client and fence callbacks by effect/request generation, retiring the previous generation immediately on input change/unmount, including the debounce interval. Reset old-session estimate as appropriate.
- Owned paths: `web/src/hooks/useTokenEstimate.ts`, `web/src/lib/context.ts`, focused hook test.
- Meaningful validation: fake timers plus controlled deferred responses for A→B with B resolving first; old success/error must not change B or its loading state. Include session switch, unmount, and response arrival during debounce. Verify actual fetch receives the signal. Browser smoke: rapid edit/session switch with delayed fixture responses.
- Overlap/dependency: W01 shared client only; logically independent. Keep cancellation/race assertions separate from URL assertions.

## W03 — Git Changes corrupts quoted/Unicode filenames (P2)

- Evidence: `src/spark_cli/workspace_routes.py:1227-1235` reads line-based porcelain output and only strips double quotes; it never decodes Git's C-style path quoting. Numstat parsing at 1213-1222 has the same line/path-format assumption. `web/src/components/workspace/WorkspaceChangesPanel.tsx:58` and `:76` send the returned path directly to diff/revert.
- Reproduced: an untracked actual `café.txt` was returned as literal `caf\303\251.txt`, with null additions/deletions. The path is not the real filename. Tabs/newlines and names containing literal ` -> ` also invalidate the parsing assumptions.
- Trigger/impact: use such filenames in a project; Changes displays escaped/incorrect names and cannot reliably diff or discard the intended file. For an untracked escaped name, revert can even return success without deleting the actual file because the nonexistent escaped target falls through.
- Narrow fix: parse NUL-delimited porcelain and numstat (`-z`), including rename records and exact path bytes/decoded strings. Do not repair with `strip('"')` or only disable core.quotePath.
- Owned paths: Git-status parsing section of `workspace_routes.py`; route Git tests. Frontend behavior should remain compatible.
- Meaningful validation: disposable real Git repo with Unicode, spaces, tabs, embedded newline, literal arrow, leading/trailing quotes, tracked rename and modifications. Assert exact paths/counts, then diff/revert each returned path. Browser: one Unicode row expands and reverts correctly.
- Overlap: same status call as W04. Land W03 first, then W04, or combine if PR independence is less important than one parser change.

## W04 — Untracked directories produce nonfunctional Changes rows (P2)

- Evidence: `workspace_routes.py:1227` uses default `git status --porcelain`, which collapses wholly untracked directories to `?? newdir/`. Code at 1239-1244 counts only files. Revert at 1298-1302 calls `unlink()` on any existing untracked target, including directories. The UI offers the normal diff/revert actions for every row (`WorkspaceChangesPanel.tsx:46-80`).
- Reproduced: a repo with `newdir/child.txt` returned `newdir/` with null counts. Reverting that returned path raised HTTPException 500 with `Operation not permitted` on macOS. The implementation cannot unlink a directory on other platforms either.
- Trigger/impact: add a new directory containing files; Changes hides individual additions/counts and its discard action fails. Directory diff synthesis also treats a directory as one file.
- Narrow fix: request `--untracked-files=all` and expose individual file rows. Keep revert file-oriented; explicitly reject directory inputs with 400 rather than introducing recursive deletion.
- Owned paths: `workspace_routes.py` status invocation and revert validation; isolated Git route tests.
- Meaningful validation: nested untracked files appear individually with correct line counts; each file diff works and revert deletes only that file; ignored siblings remain untouched; explicit directory revert is rejected without removing contents. Browser: expand/discard one nested row.
- Overlap: W03 parser hunk; apply its -z invocation first, then add -uall. No runtime/orchestration dependency.

## W05 — Upload follows an existing symlink outside the project (P1)

- Evidence: `workspace_routes.py:873` validates only the destination directory. Lines 881-885 append an upload basename and call `write_bytes()` without validating that final destination. `_safe_path` at 253-261 already rejects resolved paths outside the project, but is not applied to this file. Global uploads at 901-905 have the analogous behavior.
- Reproduced: placed `link.txt` in the temporary project pointing at a sibling temporary file. Uploading `link.txt` returned success and changed the sibling's contents from `original` to `overwritten`.
- Trigger/impact: upload a filename matching an existing project symlink that points outside the allowed root. An authenticated upload writes outside the project boundary, potentially overwriting arbitrary files accessible to the process. No claim of unauthenticated exploitation.
- Narrow fix: validate the final destination, reject symlink destinations, and use a no-follow/exclusive or safely atomic write strategy so the check/write boundary cannot follow a replaced symlink. Apply the same policy to global uploads. Do not silently allow the resolved outside target.
- Owned paths: both upload handlers in `workspace_routes.py`, shared upload-path helper if useful, upload route tests.
- Meaningful validation: internal and external symlink destinations, symlinked destination directory, normal upload, nested valid path, malicious filename; assert the outside sentinel is unchanged and rejected writes emit no successful saved entry. Include a controlled swap-at-write boundary if using a precheck.
- Overlap: W06 touches the same upload handlers. Assign one writer and land W05 before the attachment-name change. Unique naming alone does not prove a containment guarantee.

## W06 — Same-name chat uploads silently replace earlier attachments (P1)

- Evidence: `workspace_routes.py:894-911` stores every general-chat upload at the profile-global `workspace/files/<filename>`, overwrites with `write_bytes`, and returns that same path/absolute_path. Project uploads at 879-886 likewise overwrite names; ChatPanel uses that route with directory `files` for project attachments (`web/src/components/ChatPanel.tsx:974-975`). There is no per-upload or per-thread namespace in the route contract.
- Reproduced: uploaded `report.txt` with `first`, then `report.txt` with `second`; both saved responses had the identical absolute path, and reading the first response's path returned `second`.
- Trigger/impact: attach common filenames (screenshot.png, report.txt) twice, including in separate ordinary chats. The earlier attachment now points to different bytes, silently changing the source material users intended to send/retain.
- Narrow fix: preserve the display filename but allocate collision-resistant storage names for attachment uploads and return the real saved path. Preserve deliberate file-manager replace behavior only through an explicit replacement operation/flag; inspect callers before changing project-wide upload semantics.
- Owned paths: upload storage in `workspace_routes.py`, frontend upload response/context mapping if required, isolated upload + draft-attachment tests.
- Meaningful validation: sequential/concurrent same-name uploads retain both byte streams and return distinct paths; separate chats/project attachments work; original display names remain readable; reload a draft and verify it references the original bytes. No provider required.
- Overlap/dependency: W05 same handlers. Land containment fix first. This is a content-identity bug distinct from escaping the root.

## W07 — Canvas expectedRevision check is not atomic with save (P1)

- Evidence: `src/spark_cli/canvas_routes.py:218-226` checks current revision separately from the write/replace at 237-240, without a per-canvas lock/CAS transaction. Thus two requests with the same expectedRevision can both pass. Millisecond temporary names at 237 also collide for concurrent writes to the same canvas. CanvasPage builds requests with lastRevision (`web/src/pages/CanvasPage.tsx:122-123`), so the advertised conflict handling is used by the real UI.
- Reproduced: two threads called the real `_write_canvas` with the same revision. A controlled barrier around revision reads and an 80 ms delay made both read the original version before either committed. Both returned `ok: True`; final canvas contained B, silently losing A. The scheduling instrumentation only controls interleaving, not route decisions or filesystem writes.
- Trigger/impact: two tabs/users save edits to one canvas concurrently. Both see successful saves while one edit is lost; simultaneous temp names may also cause spurious errors.
- Narrow fix: serialize revision-check-through-replace per canonical canvas path (cross-process if multiple server processes are supported); use unique temporary files. Include delete in the same synchronization policy. Return the revision belonging to the committed payload. Retain the existing 409 shape for the loser.
- Owned paths: `canvas_routes.py`, canvas route concurrency tests. No frontend schema change required.
- Meaningful validation: barrier-controlled two-writer test with same expectedRevision must yield exactly one success and one 409; final bytes match the winner. Separate canvas IDs should not block each other. Test deletion race and same-millisecond save temp handling. Browser: two isolated tabs, edit same revision, save together; loser shows existing conflict UX.
- Dependencies: independent of W01-W06. No SessionDB migration, provider, or lifecycle changes.

## Integration notes

Suggested order: W05 → W06; W03 → W04; W01 → W02; W07 independently. All backend workspace findings share one large file but separate areas; use explicit hunks or sequential PRs. Avoid concurrent writers for upload handlers and Git parser. No need to modify PLAN, generated manifests, lockfiles or web_dist during research. Rebuild tracked web_dist only through the established release gate after frontend implementation acceptance.

Executed validation was limited to source reads and the five isolated direct-route reproductions described above. No HTTP/browser suites, full test suite, real providers, or gateway sessions were run. Browser flows above are proposed acceptance work, not claimed evidence. Final `git status --short` retained only the original handoff move.
