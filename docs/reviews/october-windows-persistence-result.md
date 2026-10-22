# Windows persistence repair handoff

- Commit: `168e89d2175035a6fcca186c1906bcf0f6991e3b`
- Branch: `fix/windows-persistence-contracts`
- Base: `16d9d8d9` (shared local commit, not the older parent checkout).
- Isolated checkout: `/tmp/spark-windows-persistence-20261022` (resolves under `/private/tmp` on macOS). The original checkout was detached before moving its branch to the requested base. Final isolated checkout is clean.
- Exactly four committed files: `src/cron/jobs.py`, `tests/cron/test_jobs_concurrency.py`, `src/spark_cli/skill_history.py`, `tests/spark_cli/test_skill_history.py`.

## Before and after

The supplied actual Windows job `119919216239` log, `windows-contract-failure.log`, shows cron `load-create` failing before its snapshot gate because repair calls `os.replace` while the source file is still open (`WinError 5`, log lines 715–813). Skill-history children fail at the pre-acquisition `lock.read(1)` (`PermissionError`, lines 865–893). The two upload assertion failures are lead-owned and untouched.

Cron now exits the permissive reader context before publishing its repaired snapshot. The enclosing jobs lock remains held through publication. The portable replacement spy requires both strict/permissive readers closed, requires the thread lock held, checks strict JSON and job identity after success, and injects a publication failure to verify its PermissionError cause propagates, the malformed original survives, temporary files are cleaned, and a later mutation recovers. Existing real-process contracts are unchanged.

Skill history no longer reads the lock byte. It acquires the existing bounded Windows byte lock at offset zero first, then uses `fstat` to initialize an empty file within the protected scope. Windows allows byte locks beyond EOF; serialized initialization avoids simultaneous first-writer races. Initialization is inside the unlock-protected try/finally. Portable tests substitute only this module's OS reference and msvcrt, keeping global os.name and pathlib behavior intact. They forbid lock content reads, simulate contention and retry, require initialization under the acquired lock, cover empty/existing lock files, and verify body exceptions propagate while unlocking. The unchanged native three-process history chain test remains runnable on Windows.

The four new parameterized regression cases were run against the exact original source from `16d9d8d`, then the fixed source restored: **4 failed, 19 deselected**, exit **1**, at the intended closed-reader and forbidden-byte-read assertions. See `windows-persistence-before.log`. This is portable defect reproduction, not native Windows execution.

## Commands and exits

All Python/check commands activated `/Users/joe/Developer/github/spark/.venv/bin/activate`; tests used this checkout's `PYTHONPATH=$PWD/src`. The successful targeted run used synthetic `SPARK_HOME=/tmp/spark-windows-persistence-state-20261022`, `HOME=/tmp/spark-windows-persistence-home-20261022`, and matching `USERPROFILE`, plus the existing per-test isolation fixtures. No provider calls were requested.

```sh
# Original source, new regression tests only: exit 1 (expected, four failures)
python -m pytest tests/cron/test_jobs_concurrency.py tests/spark_cli/test_skill_history.py -k 'closes_readers or acquires_before_initialization' -q -n 0 -m 'not integration and not network'

# Fixed source: exit 0; 296 passed in 23.55s
python -m pytest tests/cron/ tests/spark_cli/test_skill_history.py tests/spark_cli/test_skills_management_api.py tests/tools/test_skill_manager_tool.py tests/test_cron_output_routes.py tests/spark_cli/test_cron_overrides.py -q -n 0 -m 'not integration and not network'

# Exit 0
ruff check src/cron/jobs.py src/spark_cli/skill_history.py tests/cron/test_jobs_concurrency.py tests/spark_cli/test_skill_history.py

# CI Ruff: exit 0
ruff check src/ --select UP015,F,B,I,W,UP028,UP031,UP035,UP037,UP042 --ignore B027

# CI mypy: exit 0; no issues in 137 source files
mypy src/agent/ src/spark_cli/

# Extra scoped mypy: exit 1 on BOTH original and fixed source; same seven errors
mypy src/cron/jobs.py src/spark_cli/skill_history.py

# Exit 0
git diff --check
```

Scoped mypy debt: missing croniter stubs at line 32; existing Any returns at lines 256, 275, 308, 436 and the repaired return (base 447 / fixed 448); existing incompatible assignment at 338. No new diagnostics. Exact logs: `windows-persistence-mypy-before.log`, `windows-persistence-mypy.log`, `windows-persistence-ci-mypy.log`, `windows-persistence-ci-ruff.log`, and `windows-persistence-targeted.log` in this report's directory. An initial focused run had two failures caused by the new lock spy also intercepting the test's final read-back; the spy was narrowed to `a+b` opens before base/fixed acceptance runs.

## Limits and integration

Execution host was Darwin/macOS using Python 3.11. The 296 passing cases include real spawned cron processes and the real three-process skill-history sequence on macOS; fake-msvcrt tests establish ordering/read contracts only. Native Windows evidence must come from root's integrated rerun. No full-suite run, CI rerun, push, PR creation/update, merge, watcher, bundle, build, or release was performed. No timeouts or existing process contracts were weakened. Root can cherry-pick the exact commit above onto the draft lead PR integration branch, combine the separate upload assertion correction, and rerun native Windows.
