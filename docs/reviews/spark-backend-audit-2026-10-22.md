# Spark backend audit — 2026-10-22

Repository: `/Users/joe/Developer/github/spark`
Verified HEAD: `64af0d26976714b747dd4f1cc5b495c47c7f7567` (main supplied in brief).
Scope: research only; six confirmed defects, suitable for narrow issue-fix PRs. No source changes, issues, PRs, delegation, provider calls, server startup, or live Spark profile access. Existing dirty handoff move was preserved: deleted `HANDOFF_100826.md`, untracked `docs/HANDOFF_100826.md`.

Read: AGENTS.md, CONTEXT.md, STRUCTURE.md, accepted ADRs 0001, 0012 and 0013. All executable checks used activated `.venv`, temporary storage and isolated SPARK_HOME. This backend subset does not attempt the parent task's reference-repository feature research or ten-PR quota.

## B1 — P1: ordinary SQLite contention rebuilds a healthy holographic memory database

**Evidence:** `src/plugins/memory/holographic/store.py:136-143` catches every `sqlite3.DatabaseError` from initialization and invokes corrupt recovery. `sqlite3.OperationalError` is a subclass, including `database is locked`. Recovery closes the connection and renames the DB and sidecars at `:150-168`, then creates an empty store at `:176-182`. Initial PRAGMA/schema writes are at `:188-196`.

**Trigger / impact:** another connection holds a database lock longer than the ten-second connect timeout while MemoryStore initializes. A valid memory DB is labeled corrupt and replaced with an empty active DB. Facts become unavailable even though the original DB was healthy; renaming files while another process has them open also splits the stores on POSIX.

**Confirmed:** created one fact in a temporary DB, closed it, switched its journal to DELETE, held `BEGIN EXCLUSIVE` from a second SQLite connection, then constructed MemoryStore against the same path. After 10.5 seconds it logged `memory_store.db was corrupted (database is locked)`, created a `.corrupt-*` file and returned a store with zero facts. Also reproduced through one-shot initialization fault injection. No provider was initialized.

**Narrow fix / owned paths:** only enter destructive recovery for SQLite corruption/not-a-database errors, using SQLite error codes where available. Propagate or explicitly defer transient lock/busy/I/O failures without moving/removing files. Own `src/plugins/memory/holographic/store.py` and `tests/plugins/memory/test_holographic_recovery.py`. Preserve actual garbage-file recovery.

**Coverage / meaningful validation:** existing tests at `tests/plugins/memory/test_holographic_recovery.py:18-47` cover garbage-file rebuilding and uncontended reopen, not lock/busy initialization. Add a real two-connection locked-DB regression with a shortened test connection timeout, assert no quarantine, release lock, reopen and assert the original fact survives. Keep corrupt-file test. Fail-inject non-corruption OperationalErrors too. Existing selected tests passed.

**Overlap / dependencies:** independent of cron, CLI config and filesystem fixes. Does not change memory prompt snapshots, schema or provider policy.

## B2 — P1: atomic cron saves still lose concurrent mutations

**Evidence:** `src/cron/jobs.py:485-487` performs an unlocked load/append/save; update at `:511-537`, remove at `:593-597`, run marking at `:613-646`, advance at `:664-674`, and stale-time repair at `:689-754` use the same pattern. `save_jobs` at `:371-387` protects against torn writes with temp/replace, but has no transaction lock. The scheduler's `.tick.lock` serializes ticks, not API/CLI/tool mutations (`src/cron/scheduler.py:901-940`).

**Trigger / impact:** two CLI/tool/web/gateway processes update jobs.json concurrently, or a user edits a job while a gateway tick writes run metadata. Last full snapshot wins: newly created jobs, edits, pause state or run counters disappear. This is ordinary functional persistence loss, not speculative hardening.

**Confirmed:** two concurrent create_job callers used a barrier immediately after each real load_jobs read. Both returned successfully; persisted storage contained one job instead of two. Disk writes remained real and atomic. Deterministic interleaving, not an unreliable stress-only result.

**Narrow fix / owned paths:** add a profile-local, cross-process lock around the entire read-modify-write transaction for every mutation, including get_due_jobs repair; use a distinct stable lock file because jobs.json is replaced. Structure unlocked internal helpers to avoid nested locking during repair. Own `src/cron/jobs.py`, `tests/cron/test_jobs.py`; add a focused concurrency fixture/test file if useful. No scheduler redesign or SQLite migration required.

**Coverage / meaningful validation:** current CRUD tests (`tests/cron/test_jobs.py:271-314`) are sequential. Add deterministic two-process create/create and create/mark interleavings; verify both jobs and updated counters survive. Include pause/mark overlap and ensure a paused job stays paused. Keep permission and corruption-repair tests. Tests must bound waits and propagate child errors.

**Overlap / dependencies:** shares jobs.py with B3/B4. One integration owner or land B2 first, then rebase the smaller changes. No source dependency on those changes.

## B3 — P2: zero-minute recurring schedules never advance

**Evidence:** `src/cron/jobs.py:108-116` accepts zero duration; recurring parser at `:141-149` persists it without a positive-interval check. `compute_next_run` at `:318-327` adds zero minutes. `advance_next_run` at `:670-676` can return false, and scheduler `src/cron/scheduler.py:957-970` proceeds to execute anyway.

**Trigger / impact:** create `every 0m` (also `every 0h`/`every 0d`). An infinite recurring job is accepted and stays due at every subsequent gateway tick; its requested cadence cannot exist and can consume repeated execution costs. This is not a tight CPU loop: ticks still control frequency.

**Confirmed:** with a fixed aware clock, create_job accepted `{kind: interval, minutes: 0}`, next_run_at equaled now, advance_next_run returned false and get_due_jobs still returned the job. No scheduled task was executed.

**Narrow fix / owned paths:** reject non-positive recurring intervals in parse_schedule and validate structured interval schedules at the job mutation boundary. Keep any intended immediate one-shot `0m` behavior separate. Own `src/cron/jobs.py`, `tests/cron/test_jobs.py`, and a small public cron-tool/API rejection test as needed. Decide explicit handling for already stored zero intervals, preferably disable/report rather than perpetually schedule.

**Coverage / meaningful validation:** parse-duration and interval tests exist, but no zero-interval rejection; `test_repeat_zero_is_infinite` is about repeat counts and should remain unchanged. Add create/update tests for every 0m/0h/0d; assert errors and no storage mutation; prove every 1m has a future next occurrence. If legacy records are handled, test safe reporting/disable with no provider run.

**Overlap / dependencies:** B2/B4 share jobs.py; no runtime dependency. Avoid treating repeat=0 as interval=0.

## B4 — P2: legacy cron skill updates succeed without updating the skill

**Evidence:** `src/cron/jobs.py:516` normalizes the merged old record before considering which fields the caller supplied. `_apply_skill_fields` at `:59-65` prefers an existing non-null skills list. Consequently a new `skill` is overwritten by old `skills` before `:519-522` runs. HTTP update accepts an arbitrary updates mapping and forwards it at `src/spark_cli/cron_routes.py:65-73`.

**Trigger / impact:** a job has skill `old` and canonical skills `['old']`; PUT `/api/cron/jobs/{id}` with `{"updates":{"skill":"new"}}`, or direct update_job with that patch. Response reports success but old instructions remain scheduled. Clearing with `skill: null` is likewise ignored. This affects the compatibility/API path; the model cron tool avoids it by supplying both fields.

**Confirmed:** create_job(skill='old'), then update_job(id, {'skill':'new'}) returned `skill='old', skills=['old']`.

**Narrow fix / owned paths:** normalize explicitly supplied update fields before merging: supplied `skills` wins when present; otherwise supplied `skill` becomes the new canonical list, including null/empty clear; neither supplied preserves existing values. Own `src/cron/jobs.py`, `tests/cron/test_jobs.py` and route coverage in an existing/new focused cron route test.

**Coverage / meaningful validation:** `tests/tools/test_cronjob_tools.py:219-233` checks clearing via canonical skills, which does not exercise this branch. Add replace and clear tests via legacy-only patches; add canonical-list precedence tests when both are supplied and an unrelated update preservation case. Use the actual route function or an isolated FastAPI app, no server/provider needed.

**Overlap / dependencies:** same file as B2/B3, but otherwise independent. Preserve existing model-tool and CLI normalization behavior.

## B5 — P2: atomic file and skill edits strip executable permissions

**Evidence:** `src/tools/file_operations.py:1328-1333` replaces existing targets with a NamedTemporaryFile inode (0600) without copying the original mode. Native patch calls that writer at `:1385`. Real local tools select NativeFileOperations at `src/tools/file_tools.py:324-332`. The same problem exists in skill `_atomic_write_text` at `src/tools/skill_manager_tool.py:270-278`, reached by patch at `:522` and supporting-file overwrite at `:590`.

**Trigger / impact:** edit an existing 0755 script with write_file/patch, or patch a skill's executable helper. Contents update successfully, but the resulting file is 0600 and direct execution fails. Ordinary 0644 files also become owner-only, breaking consumers that relied on the prior mode.

**Confirmed:** native overwrite of temporary run.sh changed 0755 to 0600 with no error; skill atomic helper independently did the same. These are one defect class across two writers; do not inflate the PR quota by counting each as a separate finding.

**Narrow fix / owned paths:** preserve permission bits of an existing regular target on the temporary inode before replace (POSIX); retain deliberate defaults for newly created files and platform-safe behavior on Windows. Keep atomic replacement and failure cleanup. Own `src/tools/file_operations.py`, `src/tools/skill_manager_tool.py`, `tests/tools/test_native_file_operations.py`, `tests/tools/test_skill_manager_tool.py`. Avoid a broad shared utility refactor solely for this fix.

**Coverage / meaningful validation:** native tests check exact bytes, task CWD and symlink scope, but no mode preservation. Skill tests cover edits/support files without executable-bit assertions. Add native write and patch tests preserving 0755/0644, execute a harmless edited local script on POSIX, and public skill patch/overwrite checks on scripts/helper.sh. Keep atomic failure and temporary cleanup assertions. No provider or real profile needed.

**Overlap / dependencies:** one coordinated PR is appropriate for both writers. Independent of B1-B4/B6; does not change tool schemas or manifest. If implementation touches dispatch/startup, retain lazy-manifest/cache regression gates.

## B6 — P2: first config save writes into the installation instead of the active profile

**Evidence:** `src/core/cli/config_state.py:388-390` selects package `cli-config.yaml` whenever active-profile config.yaml is absent, then writes that chosen path at `:396-416`. Calls include skin/system-prompt/reasoning/backend settings (`src/core/cli/commands_mixin.py:46-56`, `:1379`, `:1494`, `:1518`). Read fallback is reasonable; using the installation path as a user mutation target violates profile isolation.

**Trigger / impact:** a valid active Spark home lacks config.yaml, for example a new/manual isolated profile, then a persistent slash setting is changed. Writable installation: the call returns success, creates no profile config and changes installation defaults potentially visible to other profiles. Read-only installation: the user's setting fails despite a writable Spark home.

**Confirmed:** used a temporary fresh SPARK_HOME and redirected the module's __file__ to a fake package directory (to prevent actual source/install writes). save_config_value('display.skin','mono') returned true; active profile config did not exist; fake-package/cli-config.yaml did exist. This executes the real persistence function with only its package location redirected.

**Narrow fix / owned paths:** always persist user mutations to get_spark_home()/config.yaml. If compatibility requires package defaults, seed the new user config from that fallback without writing it. Own `src/core/cli/config_state.py`, `tests/cli/test_cli_save_config_value.py`; consider existing env-expansion tests when adjusting read/seed behavior. Preserve root-level provider precedence: it is deliberately tested and is not a finding here.

**Coverage / meaningful validation:** the save fixture at `tests/cli/test_cli_save_config_value.py:14-23` always creates config.yaml, so it misses first use. Add absent-profile-config tests with an existing package fallback; assert user file is created and package bytes remain identical. Save different settings to two temp profiles and assert isolation. Include a read-only fallback/no fallback case and atomic failure preservation. No CLI provider initialization needed; import the owner directly if package startup is heavy.

**Overlap / dependencies:** independent of all other fixes. Does not require config version bump or schema migration; do not change intended model/provider precedence incidentally.

## Verification performed

Reproduction script retained at `/tmp/spark-backend-audit-repro-20261022.py`. It uses temporary filesystem/SQLite storage and the real owners, with a barrier for deterministic cron interleaving and a redirected package location for first-use config. Its extra root-provider observation was excluded after finding the explicit intended behavior test at `tests/cli/test_cli_init.py:260-282`.

Ran with `.venv` activated and isolated SPARK_HOME:

```sh
python -m pytest tests/cron/test_jobs.py tests/tools/test_cronjob_tools.py tests/tools/test_native_file_operations.py tests/tools/test_skill_manager_tool.py tests/plugins/memory/test_holographic_recovery.py tests/cli/test_cli_save_config_value.py -m 'not integration and not network' -q -n 0
```

Result: **149 passed in 12.92s**. Passing existing tests establishes the coverage gap; this research did not add failing tests to the repository. Also ran the real two-connection SQLite lock reproduction described in B1 (10.5s; empty rebuilt store and quarantine observed).

No browser behavior, installed package acceptance, full-suite pass or external-provider behavior is claimed. These findings concern local deterministic backend/storage behavior and need their own regression tests in implementation PRs.

## Suggested integration order

1. B1 (memory persistence) and B6 (config isolation) can be developed independently.
2. B2 establishes cron transaction locking; integrate B3 and B4 afterward to avoid three simultaneous writers in jobs.py.
3. B5 owns both filesystem writers as one coherent permission-preservation fix.

No finding depends on new orchestration infrastructure or unresolved earlier orchestration issues. No GitHub objects were created.
