# I09 result

PR: https://github.com/automatedigital/spark/pull/169 (registered with T3 link_pull_request successfully).
Issue: https://github.com/automatedigital/spark/issues/153
Head: 4231e200ea55d77abb17698d2ef4e24e69ebe9cd
Branch: fix/cron-mutation-locking
Worktree: /Users/joe/.t3/worktrees/spark/t3-769f94dc
Base: 64af0d26976714b747dd4f1cc5b495c47c7f7567

Committed only src/cron/jobs.py and tests/cron/test_jobs_concurrency.py. Push exited 0. Root checkout was untouched. No nested delegation, merge, release, deploy or PR monitoring.

Python checks used `source /Users/joe/Developer/github/spark/.venv/bin/activate` (no worktree .venv), `PYTHONPATH=$PWD/src`. Test and CLI commands exported synthetic SPARK_HOME/HOME/USERPROFILE; each spawned concurrency worker also set all three before importing cron.jobs. No real provider calls. Broader mypy and Ruff are static checks.

Detailed implementation, commands, exact exits, baseline debt, CLI evidence and integration limitations follow (same evidence in PR):

Concurrent CLI/tool/API writes and scheduler run marking currently overwrite each other's jobs.json snapshots. This change holds a profile-local `.jobs.lock` across each complete read-modify-write operation, including run counters, schedule advancement, pause/resume, stale-time repair and control-character repair. Atomic replacement remains intact. Separate unlocked helpers avoid nested acquisition; contention fails explicitly after bounded waits and leaves storage untouched.

Adds real spawned-process regressions for create/create, create/mark, pause/mark in both orders, advance/create, remove/create, repair/create, load-repair/create and resume/schedule-update. Tests bound child waits, check exit codes, preserve actual disk writes and assert persisted jobs/counters/pause state. Failure cases cover lock timeout, failed replacement cleanup and unrepairable JSON preservation.

Validation on macOS with activated shared `.venv`, checkout `PYTHONPATH`, and synthetic HOME/USERPROFILE/SPARK_HOME:

- `python -m pytest tests/cron/ tests/tools/test_cronjob_tools.py -m 'not integration and not network' -q -n 0`: exit 0, 215 passed in 89.51s (before the last added corruption test).
- Final `python -m pytest tests/cron/test_jobs_concurrency.py -m 'not integration and not network' -q -n 0`: exit 0, 12 passed in 40.80s.
- `ruff check src/cron/jobs.py tests/cron/test_jobs_concurrency.py`: exit 0.
- CI Ruff families (`--select UP015,F,B,I,W,UP028,UP031,UP035,UP037,UP042 --ignore B027`): exit 0.
- `mypy src/agent/ src/spark_cli/`: exit 0, 133 source files.
- `mypy src/cron/jobs.py`: exit 1, seven baseline errors; checked the exact base file separately and found the same seven (croniter stubs, existing Any returns and datetime assignment). No new type errors.
- `ruff check src/`: exit 1, 298 existing findings outside the changed module; focused module is clean. The original module also had E402, fixed by grouping its imports.
- Controlled create/create test against base 64af0d2, adapting only observation hooks to the prior public loader: exit 1, `second mutation read before first committed`; fixed version passes.
- `python /tmp/I09-cli-flow.py`: exit 0. Real subprocess CLI create → pause → list --all → resume → remove → empty list, with disk assertions and every CLI exit 0. No tick/provider execution.
- `git diff --check`: exit 0. Node verified as v22.23.4 at `/Users/joe/.npm/_npx/52027bd8fc0022aa/node_modules/node/bin/node`; system `node` and `node@22` symlink actually resolve to v25.8.0.

Windows msvcrt branch, browser UI, packaging and the full repository test suite were not run. This packet changes only backend storage; CLI and real-process persistence are the acceptance flow. No dependency, manifest, migration, PLAN.md or production bundle changes.

Integration: based directly on 64af0d26976714b747dd4f1cc5b495c47c7f7567. B3/B4 share jobs.py and should rebase after this packet, preserving the locked public boundaries and internal helpers. Expected conflicts are around create/update helpers and imports; neither fix is included here.

Closes #153.
