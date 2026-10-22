# Independent workspace review — 2026-10-22

Recommendation: **hold all five current heads**. Remediate the concrete findings below before merging the planned stack. No source, PR, issue, merge, push, package or release changes were made. All five PRs were T3-linked; final link inventory confirms watching=false.

## Scope and evidence

Read AGENTS.md, CONTEXT.md, STRUCTURE.md, all three accepted ADRs, the relevant delivery reports under docs/reviews, packet evidence under /tmp/spark-packets-20261022, and the manifest. Independently ran `gh pr view` (body, comments, reviews, checks), `gh pr diff`, and fetched each actual PR head into `refs/review-workspace/<number>`. Reviewed source and tests, not just packet summaries. Each fetched SHA agrees with the live GitHub snapshot and manifest:

| PR | Actual head | Verdict |
|---|---|---|
| #155 | 6ef55a4ef7ea53924c94ed962f776cd9db582151 | BLOCKED |
| #171 | 10ba28f595c5c39e6c1918b01e2b3dab214d614a | BLOCKED |
| #168 | 797c0667b6c6bfd2c58232d94374d55c97d2c126 | BLOCKED |
| #173 | f3c76d3a6df859df9d1218bf7f50da7e896c3963 | BLOCKED |
| #177 | 64ced2ca82718903da24cb53f4c34eaaa5c9f022 | BLOCKED |

Used a new detached isolated worktree `/tmp/spark-workspace-review-20261022`, checking out the individual fetched heads sequentially. Root checkout status was clean on entry and remained clean; no handoff work was touched. Python commands activated `/Users/joe/Developer/github/spark/.venv`, used checkout `src` on PYTHONPATH and disposable HOME/USERPROFILE/SPARK_HOME. No provider/profile calls. Node explicitly verified as v22.22.1 at `/Users/joe/.nvm/versions/node/v22.22.1/bin/node`; no frontend acceptance run is claimed in this review.

Own focused results (all `-q -n 0 -m 'not integration and not network'`):

- #155: upload safety + file ops + Git: **52 passed, 11 Windows-only skipped**.
- #171: upload identity + file ops: **19 passed**.
- #168: Git + file ops: **41 passed**.
- #173: Git + file ops: **28 passed**.
- #177: canvas concurrency + canvas routes + canvas tool: **26 passed**.

Logs, exact diffs, GitHub snapshots and runnable probes are in `workspace-evidence/` alongside this report. Existing browser/component evidence was inspected but not rerun. No installed macOS/Windows package evidence was produced: that is an acceptance limitation, separate from the source defects established below.

## #155 — upload containment — BLOCKED

**P2: pinning every ancestor with O_RDONLY rejects supported search-only directories.** `src/spark_cli/workspace_routes.py:966-969` opens every canonical ancestor for reading; the same issue applies to the selected target directory at 977-979. Trigger: a writable project under an ancestor with mode 0111 (search permission but no directory listing permission). The previous pathname uploader can create/read the target file; the new `_upload_directory` raises EACCES before saving. Own probe of the exact fetched helper reports `baseline_succeeded:true, new_succeeded:false, errno:13`. Through the route this occurs outside the per-file exception mapping and fails the request. This is introduced permission incompatibility, not baseline lint debt.

Minimum: preserve safe traversal through search-only ancestors on supported POSIX platforms, or establish and explicitly approve a narrower supported permission contract. Add a real permission regression with try/finally restoring modes; retain no-follow and swap tests. Do not fix it by returning to an unchecked pathname write.

**Material Windows acceptance gap:** the current head does implement Windows handles. Earlier claims of blanket Windows 501 are stale. `CreateFileW` pins canonical ancestors with read sharing only; file opens use OPEN_ALWAYS + OPEN_REPARSE_POINT, inspect attributes, and transfer ownership to the CRT before truncation. This is materially different code from POSIX and remains unexecuted natively. Eleven skipped tests and Windows-target mypy do not establish junction/reparse containment, handle sharing/cleanup, ordinary create/replace, linked-profile support, or behavior under an existing incompatible handle. Require these on native Windows before declaring the security fix cross-platform safe.

The POSIX tests use real directories/files/symlinks/FIFOs and controlled swaps at actual open/read boundaries; they do not stub away no-follow behavior. They omit the permission case above, hard links, hostile relocation of the pinned inode outside the root, and returned-path validity after relocation. Hard-link/relocation limitations were already disclosed; no new hard-link regression is alleged here.

CI: initial current-head snapshot had Ruff success and other jobs pending. Inspected the newest prior failing job **exactly**, run 39797956538 / job 119890183892 (mypy-ratchet): ten Windows ctypes/CRT typing errors on 8987f857, saved as `155-newest-failed-job.log`. Current 6ef55a4e adds recognized platform guards/narrowing/cast; do not recommend re-fixing the obsolete ten errors. No polling/rerun performed.

## #171 — duplicate upload identity — BLOCKED

**P2: collision suffix truncation counts characters, not filesystem filename bytes.** `src/spark_cli/workspace_routes.py:880-881`. Trigger: filename = 40 emoji + `.` + 20 emoji (241 UTF-8 bytes). The initial upload succeeds. On collision the helper retains a 40-character stem and 20-character suffix and appends 33 ASCII characters, allocating **270 bytes**. On the Linux container filesystem the exact helper raises errno 36 ENAMETOOLONG, so the second route upload becomes HTTP 500. Previous bytes remain intact, but a valid duplicate filename cannot be attached.

Own macOS full-helper probe succeeds for the same 270-byte candidate, showing why macOS-only checks miss this. Own Linux probe executes the exact function AST extracted from the unchanged current-head source, with its actual Path/uuid stdlib dependencies and an actual Linux filesystem; no filesystem call is mocked. Container used existing `spark-ci:143`, no network, read-only source/evidence mounts, isolated homes and activated temporary venv. It is a helper regression, not a full Linux HTTP/package run. First full-module container attempt lacked FastAPI; that failure is recorded and not counted as source failure. An initial pip-populating venv attempt was stopped; the final probe used `--without-pip`.

Minimum: allocate storage names within the destination filesystem's byte/component budget (respecting Windows naming rules too), retaining a human display filename separately. Add actual POSIX multibyte collision tests, plus existing sequential/batch/concurrent identity cases.

Exclusively opening `xb` correctly prevents replacement of existing final entries, including dangling symlinks. Tests use real filesystem concurrent requests; root functions are patched to temporary fixture paths, not the writer. The frontend draft test genuinely reloads persisted draft state, but mocks the upload response and does not prove HTTP containment. Existing broad failures are not assigned to this PR. Current snapshot shows all five CI jobs successful.

Integration: cannot merge #171 over #155 by selecting its pathname writer. Combine collision allocation with descriptor-relative exclusive creation on POSIX and equivalent exclusive Windows handle creation. Preserve actual allocated storage names in both response paths. #155 currently expects ordinary duplicate replacement in one test; #171 intentionally changes that contract, so reconcile assertions explicitly rather than deleting safety coverage. Root-alias support in the NEW #155 is intentional and must remain; stale packet notes describing every aliased directory as rejected are not authoritative.

## #168 — Git byte/path parser — BLOCKED

**P2: a non-UTF-8 Git path now breaks the entire status response.** `src/spark_cli/workspace_routes.py:1178-1179,1236-1242`. NUL output plus `os.fsdecode` yields surrogateescaped Python strings, which are returned unchanged as JSON paths. Trigger: a Git tree entry `invalid-\xff.txt` missing from the working tree. Own real-Git probe inserts the raw-byte path with `git update-index --cacheinfo`, commits it, then calls the real route. Current head: **HTTP 500**. Base and #173: HTTP 200 with Git's escaped display path. This uses a real Git index/tree, allowing the malformed-name case even though macOS refuses to create that byte name on disk. A single imported repository entry therefore disables the entire Changes list. This is introduced; the base's escaped row was not correctly actionable either, which is a distinct existing limitation.

Minimum: define a response-safe representation for non-UTF-8 path bytes, keep display separate from reversible action identity (or safely disable actions for unsupported rows), and verify status remains available with ordinary neighboring files. Do not use lossy decoding that might discard a different file. Add real Git-tree byte-path tests through HTTP.

For normal Unicode and quoted paths, the new NUL parser is correct: destination-first porcelain rename records and numstat source/destination triples are consumed separately, tabs/CR/LF/whitespace stay intact, and binary counts remain nullable. Own 41 focused tests pass. Tests include real repos/HTTP and do not mock Git output. Several POSIX special-filename fixtures are not portable to Windows; a native Windows supported-name subset and POSIX-only skips are needed before calling the test suite cross-platform.

Existing staged-rename revert HTTP 500 is documented baseline behavior, not an introduced finding. Git pathspec wildcard semantics are another confirmed baseline danger: reverting `[ab].txt` also restored unsaved `a.txt`; the new parser does not introduce the `git checkout -- pathspec` implementation. Native Windows behavior and installed packages remain unverified. Current snapshot: all CI jobs successful.

## #173 — nested untracked rows — BLOCKED (new UI exposure of existing unsafe revert)

**P1: newly listed nested untracked symlinks discard their target, not the selected link.** The new `--untracked-files=all` at `src/spark_cli/workspace_routes.py:1227` exposes individual `nested/link.txt` rows. Revert still resolves the link through `_safe_path` at 1291, then unlinks the resolved file at 1302; the new directory guard at 1292 only catches directory targets. Trigger: nested untracked `nested/link.txt` symlinks to valuable `a.txt` within the project. Own current-head route probe lists that exact new row; POST revert returns 200, removes `a.txt`, and leaves the dangling selected symlink. In the base the same UI status lists `nested/` instead. **The backend target-following defect itself pre-exists** and is reproducible by direct API call on the base; this PR newly exposes its per-file destructive UI flow. This attribution is intentional, not a claim that `_safe_path` or unlink was newly added here.

Minimum before approving the newly actionable rows: validate lexical containment without dereferencing the final entry; inspect with lstat and remove the selected symlink itself, or explicitly reject symlink discard. Preserve ancestor containment against external links. Add status -> returned exact nested link path -> revert coverage proving the target stays unchanged and that only the selected entry is removed/rejected. Include dangling links, directory links and native Windows symlink/junction behavior where supported.

The added ordinary-file tests are meaningful real-Git/HTTP tests, cover ignored siblings and directory rejection, and pass with neighboring file ops (28 total); they omit symlinks. The directory guard is a useful improvement, but does not discharge the new row's data-loss flow. Other baseline Git pathspec and rename limitations remain separate.

Integration: retain #168 `--porcelain=v1 -z` parsing and add `--untracked-files=all` to that call; keep both regression sets. Do not restore this branch's line parser during conflict resolution. Resolve #168's byte-path failure too. Snapshot: all five CI jobs successful. No installed/native Windows evidence.

## #177 — canvas atomic revisions — BLOCKED

**P1: final symlink resolution turns saves and deletes into outside-target operations.** `src/spark_cli/canvas_routes.py:84`, used by `_write_canvas` at 252/293 and `_delete_canvas` at 311/316. Trigger: `escape.canvas.json` in a canvas scope symlinks to an outside writable JSON file. New `_canvas_path(...).resolve()` changes the *data target*, not just the lock key. Own current-head probe: save replaces outside content and leaves the link; delete removes the outside file and leaves the dangling link. Exact base comparison: save replaces the link and preserves outside content; delete removes the link and preserves outside file. This is an introduced containment/data-loss regression. It applies to both project and global scopes; project repository content can supply such a link.

Minimum: separate canonical directory/lock identity from the final data basename, enforce scope containment and a clear final-link policy, and keep the opened parent identity stable across validation and mutation. Add real final-link save/delete and swap regressions. A `.resolve().relative_to()` precheck alone is not a concurrent-swap guarantee.

**P1: lock sidecars are deletable through ordinary project file APIs, splitting lock ownership.** `src/spark_cli/canvas_routes.py:94-107`. Sidecars live beside project canvases as `.board.canvas.json.lock`. The implementation deliberately never unlinks them, but existing Files delete and Git revert can unlink them; #173 also lists them individually inside newly untracked directories. Own controlled real-thread probe holds `_canvas_lock(board)`, reverts the sidecar through the actual Git route (HTTP-equivalent success), and performs another save **before releasing the original lock**. The new save succeeds on a different inode. This violates the new concurrency guarantee; stale contenders on the old inode can then pass concurrent revision checks. Existing backend file deletion is not newly added; the exposed persistence/locking object and reliance on its permanent inode are new.

Minimum: locate lock identity in profile-owned storage outside mutable project files, keyed by a stable canonical scope identity, or enforce inode lifetime across every mutation path. Validate actual waiter/holder/removal/reacquire interleavings across processes, including project delete/recreate, Files and Git operations. Hiding a file from the UI alone is insufficient.

Ordinary lock/revision implementation has useful coverage: same-revision winner/409, spawn processes, per-canvas independence, save/delete ordering, unique temps and cleanup. The tests wrap the real lock and replace operations to control timing; they do not stub the lock itself. They keep sidecars intact and test no malicious final links, thus miss both findings. Canvas tool calls the same `_write_canvas` and receives the lock; tool calls without expectedRevision intentionally replace and are not evidence of a CAS bug.

Windows uses `msvcrt.locking`, not flock, and has no native evidence. Require native contention, initial empty lock initialization, unlock/exception cleanup, deletion/recreation and temp replacement tests. POSIX passing tests do not establish that branch. Existing mypy skip-import errors were reproduced in the packet's base; not new source debt. All five CI jobs in the current snapshot are successful. Source-level atomic replace is not proof of crash/fsync durability, which this review does not claim.

## Combined merge gate

1. Repair #155 permission compatibility and prove native Windows containment; combine #171 allocation with its pinned writer and byte-safe names.
2. Repair #168 response handling and #173 symlink discard; integrate their status flag conflict preserving NUL parsing and untracked expansion.
3. Repair #177 final target containment and lock storage lifetime before adding it to the project Files/Git surface.
4. Rerun the combined relevant route suites and real UI attachment reload, nested Changes diff/discard, and two-editor canvas conflict flows. Specifically test lock survival during Files/Git operations, canvas-as-upload name collisions, and project rename/delete. Project canvas updates through generic file endpoints bypass the canvas lock/revision contract unless explicitly coordinated; do not claim all-writer serialization from canvas-only tests.
5. Build/install/release acceptance is owned by the lead. This report neither blocks on nonexistent package evidence as a *source defect* nor authorizes inferring package safety from these tests. Missing native Windows security/locking validation is independently material before cross-platform acceptance.

No endless diagnostics, additional agents, PR polling, or monitoring were used. Worktree ends detached on the known base for baseline comparison and is clean; evidence is outside source.
