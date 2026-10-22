# Independent backend review — 2026-10-22

Recommendation: **merge #166, #169, #175 and #178 after normal integrated checks; hold #182 for the P1 redaction repair below.** This is a source merge assessment, not approval to release installed applications.

## Scope and provenance

Reviewed actual GitHub heads using `gh pr view`, `gh pr diff`, fetched refs and source in a new detached worktree `/tmp/spark-backend-review-20261022`. All five heads match the prior manifest, but verdicts are based on the fetched source and new checks, not previous summaries. All share base `64af0d26976714b747dd4f1cc5b495c47c7f7567`.

Read AGENTS.md, CONTEXT.md, STRUCTURE.md and accepted ADRs 0001, 0012 and 0013. Consulted relevant delivery reports and packet evidence. The parent checkout was inspected first and left unchanged. No source edits, commits, PR comments, merges, pushes, releases, provider calls, further delegation or PR watches/poll loops. Every reviewed PR was T3-linked; final list confirmed all five with watching=false. GitHub metadata, diffs, run snapshots and logs are adjacent to this report.

| PR | Exact reviewed head | Verdict |
| --- | --- | --- |
| #166 | `4e8828a6ed220ed3d098030f3773ea2a27335970` | SAFE |
| #169 | `4231e200ea55d77abb17698d2ef4e24e69ebe9cd` | SAFE |
| #175 | `0d3caa4cb1410f8d1ae115b6360676c3b201bff2` | SAFE |
| #182 | `314b876c4bde42f7696235461c4729ce80d94472` | BLOCKED |
| #178 | `5b125dccd1208cb326bb0ad8cdab8eae308799a0` | SAFE |

SAFE means no merge-blocking P1/P2 was found in this bounded review. It does not guarantee absence of bugs or completion of release gates.

## #182 — BLOCKED: export redaction

**P1 — Credential-named fields leak objects and numeric secrets.** Location: `src/spark_cli/session_export.py:39-56`, especially the credential check at lines 39-41 and dictionary traversal at lines 52-56.

Trigger: persist an assistant tool call with serialized arguments such as:

```json
{"authorization":{"value":"SYNTHETIC_OPAQUE_CREDENTIAL"},"password":123456789,"secret":["SYNTHETIC_LIST_CREDENTIAL"]}
```

Export that real SessionDB session using either JSON or Markdown. The nested authorization value and numeric password appear unchanged in both final files. The string inside the secret list is removed, demonstrating that the missing cases are type-dependent. The credential-name check runs only for strings; dictionary recursion replaces the parent credential key with `value`, while numeric values fall through untouched. These files can then be explicitly published through the existing public Gist path.

Reproduced on the exact head with actual SQLite persistence and both final export files. `182-redaction-repro.log` reports object_secret_leaked=True and numeric_secret_leaked=True for both formats, list_secret_leaked=False, and raw_db_unchanged=True. All values were synthetic. No Gist was created.

Classification: an essential safety gap in this feature's new recursive sanitizer and new Markdown sharing surface. The old JSON exporter also lacked this protection; **this is not a newly introduced JSON regression**. The PR explicitly owns mandatory nested export sanitation, so carrying the gap into the new shareable format is a blocker.

Minimum remediation: apply the credential-field policy before branching on the value type. Redact a credential field's entire value, including mappings, lists and numbers, or otherwise propagate credential context so no child value escapes. Preserve ordinary non-secret types and raw DB/input data. Add regressions through actual SessionDB export for both formats with the payload above, disabled log redaction, a fake publisher inspecting final bytes, and unchanged raw DB assertions. Re-review the fixed head.

Other inspected behavior: default JSON command remains compatible, `--format markdown` and `--format=markdown` are additive, explicit `--publish` remains opt-in, invalid options do not export, forced export redaction is independent of log opt-out, fences exceed embedded backtick runs, unknown roles remain literal, and only the selected session is fetched. No historical/system prompt mutation.

Test quality: the 166-test selection passes, including real SQLite slash-handler acceptance. Its credential fixtures use string-valued secret fields; passing them does not exercise the demonstrated object/numeric leak. Publisher mocking is appropriate to avoid external publication, but should inspect the additional unsafe bytes.

Compatibility/integration: coordinate `session_ops_mixin.py`, `commands.py`, `session_export.py` and `agent/redact.py` with sibling packets. Raw SessionDB backup/export semantics remain separate from shareable sanitation. No frontend/package claim follows from this CLI feature.

## #166 — SAFE: memory recovery

No P1/P2 found. `src/plugins/memory/holographic/store.py:139-151` gates destructive recovery on CORRUPT/NOTADB primary SQLite result codes, including extended codes masked with 0xFF. Other DatabaseErrors close the failed connection and propagate instead of renaming/removing the database and sidecars. Missing codes fail conservatively. Profile path resolution is unchanged.

New review run: **25 passed** across recovery, dedup and auto-extraction tests (`test-166.log`). The key test creates a real database and persisted fact, holds BEGIN EXCLUSIVE using a second real connection, verifies SQLITE_BUSY without quarantine or changed DB bytes, then reopens and checks the same fact ID/content. Only timeout duration is shortened; SQLite locking and persistence are real. Injected non-corruption code cases complement this proof rather than replace it. Real garbage-file recovery remains covered.

Compatibility/limits: no retry policy is introduced; callers still receive a transient initialization error during contention. The pre-existing confirmed-corruption quarantine implementation and its last-resort unlink behavior are unchanged, not newly validated against concurrent corruption recovery. No installed-platform acceptance was run. Minimum source remediation: none; preserve this guard during integration and rerun the focused persistence checks if changed.

## #169 — SAFE: cron mutation serialization

No P1/P2 found. `src/cron/jobs.py:349-414` locks a stable profile-local `.jobs.lock` inode, not replaceable jobs.json. A thread lock complements OS process locking; lock acquisition is bounded and releases in finally paths. Mutation APIs use unlocked internal helpers only while the public transaction lock is held. Public snapshot save remains documented whole-snapshot replacement, not an advertised compare-and-swap API.

Inspected create/update/pause/resume/remove/run-marking/advance/due-job-repair and load-time repair. Repository production callers do not retain a separate public load/modify/save mutation path that bypasses the new transaction boundaries. Existing import-time profile anchoring of cron constants is unchanged; workers set profile environment before imports.

New review run: **71 passed** across concurrency and normal job tests (`test-169.log`). Spawned processes read/write the real same-profile jobs.json. Observation hooks wrap the original lock/loader and deliberately pause a real disk reader; they do not supply fake storage or replace the lock. Tests assert the second mutation cannot read before commit, persisted counters and paused state survive, timeouts do not read/write, replacement failures preserve storage and release the lock, and repair paths serialize. Windows msvcrt byte-zero initialization/seek/acquire/release was inspected but **not executed** on this macOS host.

CI: Python workflow succeeds. The web workflow is cancelled, not a demonstrated source failure. Read the exact cancelled job `119862178452` in run `39789714961`; `169-cancelled-e2e.log:629` says `Install Chromium for Playwright ... ##[error]The operation was canceled.` No application assertion ran to justify a source change. If branch protection requires a completed E2E gate, lead should obtain it; do not modify code in response to this cancellation alone.

Compatibility/integration: cron jobs.py overlaps sibling cron changes. Keep the complete read-modify-write boundary and avoid calling newly decorated public functions from inside it. The lock is separate from scheduler tick ownership and does not promise exactly-once job execution. Minimum remediation: none; run integrated cron/tool checks after conflict resolution and execute Windows contention acceptance before claiming Windows lock proof.

## #175 — SAFE: atomic permission preservation

No P1/P2 found. `src/tools/file_operations.py:1328-1345` and `src/tools/skill_manager_tool.py:271-291` capture an existing regular target's POSIX mode and apply it to the temporary inode before replacement. Native writes retain flush/fsync behavior; skill writes flush before fchmod. New files retain the existing private temporary-file default. Windows skips POSIX handling. Existing path/credential guards are not removed.

New review run: **71 passed** across native file operations and skill-manager tests (`test-175.log`). Real write/patch paths preserve 0755 and 0644 and edited executable scripts are directly executed. Tests verify new-file 0600 and original bytes/mode plus temporary-file cleanup after fchmod or replacement failure. Failure injection tests only the failure boundary; normal permission/execution tests use actual filesystem operations.

Compatibility/integration: atomic replacement still does not promise ownership/ACL/xattr/hardlink preservation; these are pre-existing properties rather than introduced defects. Coordinate the skill atomic writer with #178 and any other skill mutation packets; history should continue using the validated shared writer. Minimum remediation: none; preserve permissions on normal and rollback writes during integration. No Windows execution or installed package evidence claimed.

## #178 — SAFE: dashboard skill history

No merge-blocking P1/P2 found. Inspected backend store/route, shared save helper, typed API and drawer. Active-profile history uses one file retaining the newest 20 dashboard edits across skills, bounded per-text sizes and store-size validation. UUID identity and stored order do not depend on wall-clock uniqueness. Stable lockfile plus thread lock serialize real dashboard read/save/append operations. POSIX flock and Windows msvcrt branches were inspected; only POSIX was executed.

New review run: **65 passed** across history, management API and skill-manager tests (`test-178.log`). This includes real saves/routes, subprocess and thread sequencing, retention, profile isolation, corrupt history rejecting a save before mutation, no-op and validation failures, and equal timestamps. The history-publication-failure test substitutes the skill writer to isolate append failure after successful content save. That test alone does not prove the shared writer; separate real saves/API/process tests do exercise it.

New browser acceptance on this exact source head passed using the repository workflow `python src/spark_cli/web/e2e/skill-history.py`, real FastAPI/Vite and a temporary profile. Tested empty history and coverage label → two dashboard saves → newest Before/After pair → reload persistence → malformed-store unavailable-history alert. Zero page errors; screenshot inspected at `178-browser-final/history.png` and report at `178-browser-final/report.json`. Node was explicitly v22.23.4 at `/private/tmp/spark-packets-20261022/node-v22.23.4-darwin-arm64/bin/node`; npm ci completed without source/lockfile changes. The first launch raced the unfinished dependency install and failed with missing node_modules/.bin/vite before feature interaction; one retry after installation completed passed. That was reviewer setup, not a source failure.

The store deliberately covers dashboard SKILL.md edits only. Agent edits, external editors and supporting files are labelled excluded. External changes can create gaps; a crash between the two file replacements can omit a history entry. These are disclosed limitations of bounded snapshots, not a durable authoritative mutation ledger. A caught append OSError returns successful save with a visible history warning rather than a retryable false failure.

Non-blocking robustness limit: the POSIX flock and the local thread lock have no acquisition deadline (skill_history.py:32,51), unlike cron's lock. A live process that holds the history lock indefinitely can leave history/save requests waiting. This review found no ordinary bounded save that causes that condition; do not describe history lock waits as bounded. Consider deadline handling if this service needs guaranteed request timeouts.

Compatibility/integration: #175 changes the helper writer; shared web_server.py and SkillsToolsPage.tsx overlap other dashboard features. Keep history inside the validation/persistence route, preserve its warning, API auth/opaque-ID resolution and future-context semantics. No web_dist regeneration was performed. Minimum source remediation: none; rerun the real history/browser flow on the integrated frontend before release.

## Validation and release boundaries

All Python checks activated `/Users/joe/Developer/github/spark/.venv`, set the current review checkout's `src` on PYTHONPATH, used temporary SPARK_HOME and `-m 'not integration and not network' -q -n 0`. **398 focused tests passed total.** No full-suite, broad lint/type rerun or provider call was made. Prior full-source Ruff debt and historical manifest-test timeouts were not reclassified as new failures. Current-head Python CI snapshots are successful for all five. #166/#175/#178 web workflows are successful; #169 is cancelled; #182 web workflow was still in progress in the one run snapshot. No monitoring was started and no pending result is inferred.

Installed macOS/Windows package execution, signatures, notarization, bundled served assets and release publishing were not tested by this reviewer. Their absence is **release evidence missing**, not an introduced source defect. Lead owns integrated checks, production bundle regeneration and platform packaging/install acceptance after safe merges. Do not ship #182 until its redaction defect is repaired and tested.
