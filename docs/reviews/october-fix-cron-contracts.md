# Cron contract implementation handoff

Status: both requested source contracts implemented and locally verified; ready for lead cherry-pick and integrated gates. This is not a merge/release or native Windows acceptance claim.

- Worktree: `/tmp/spark-cron-contracts-20261022` (macOS canonical path `/private/tmp/spark-cron-contracts-20261022`).
- Branch: `fix/cron-contracts`.
- Base: fast-forwarded with `git merge --ff-only 2695192` to `2695192f` before editing.
- Commit: `33cda3be1eb8a657c7ad72be4981b660423358e4` (parent `2695192f`; scoped cherry-pick ready).
- Final worktree Git status: clean.
- Read repository AGENTS/CONTEXT/STRUCTURE, relevant accepted ADRs 0001/0012/0013, F02/F10 plan scope and rendering.md/json findings. No edits to the lead integration checkout or original checkout.

## PR 179: stable scheduler-compatible skill identity

Added `/api/cron/skills`, preserving separate display labels and scheduler-compatible POSIX-form relative folder paths. The catalog reads real local/configured external roots without display-name deduplication, respects disabled/platform restrictions, and marks colliding relative paths unavailable. The picker presents label plus path and saves the path. It excludes unavailable entries and displays their reason. Exact paths take precedence; unique old display/basename values canonicalize on save; ambiguous aliases or colliding paths are rejected. Existing unavailable string references remain editable, and old actual folder-path/legacy single-skill jobs keep their loader contract. Both canonical and legacy API updates validate ambiguity; explicit canonical clear wins over a stale legacy value. Ordered deduplication, model/provider/default clearing remain intact.

No scheduler or tools source changes: the persisted path works with the existing real `skill_view` loader. No runtime claim is made that an already-saved job will detect a future installed-root collision without being edited; the catalog/save boundary rejects those collisions, while existing runtime lookup behavior is unchanged.

Evidence:
- `cron-contracts-identity-before-after.log`: real `_find_all_skills` returns `FriendlySkill` for `folder-slug`; real loader returns success=False for that display value; old prompt omits instruction and contains skipped notice. New catalog returns id=`folder-slug`; HTTP save/reload preserves it; real prompt contains instruction with no skipped notice.
- `cron-contracts-before-skill.log`: the new real-filesystem regression fails against original base cron_routes.py (missing scheduler-specific catalog), then passes with this fix.
- Fresh-process filesystem regression covers duplicate display names, nested paths, canonical order/deduplication, on-disk persisted JSON/reload, real `_build_job_prompt`, unique legacy alias/old string loading, ambiguity on canonical and single-skill updates, cross-root path collision and explicit clearing. No `skill_view`, filesystem/catalog or prompt builder mocks. No provider call required.
- Browser uses real files with duplicate `FriendlySkill` labels, pointer and keyboard selection, reorder, save, real scheduler prompt order, reload, model edit, clear, reload/reopen. Only provider/model boundaries are synthetic.

## PR 181: fail-closed output capability and UI

Added `/api/cron/output-capability`, checking O_NOFOLLOW/O_DIRECTORY/O_NONBLOCK, descriptor-relative open and descriptor-capable scandir. The accessor uses the same predicate and keeps exact unsupported 503 behavior. Directory-relative no-follow security, symlink rejection, regular-file enforcement, page/read caps, keyset paging, pruning and request-time profile resolution are preserved. No resolve-then-open fallback.

CronPage starts disabled, reads backend capability, and enables Outputs only when supported. Unsupported/unverified capability leaves the action disabled with a visible reason and an accessible description. A single reason near the list avoids overflowing mobile action rows. Capability-load failure remains disabled with a reload explanation.

Evidence:
- `cron-contracts-before-output.log`: original base capability URL=404, output URL=503 with exact platform-unavailable reason when dir_fd is absent.
- Real backend tests exercise supported POSIX list/read/paging/pruning/limits/symlinks/FIFO/profile changes, live capability payload, and missing dir_fd/no-follow/scandir-fd/directory/nonblock simulations.
- Only eight cases requiring POSIX output access are platform-specific. Filename/query/job validation and native capability/fail-closed tests still run on Windows. Windows host expectation is explicitly unsupported.
- Whole test module with descriptor capability removed before collection: **17 passed, 8 skipped** (`cron-contracts-unsupported-module.log`), not a blanket skip.
- Browser tests use the actual backend capability and mounted CronPage: supported list/read/plain-text/copy/paging/truncation/pruning/recovery/mobile/Escape/focus/empty cases, then actual backend unsupported simulation -> page reload -> disabled buttons and exact visible reason, and output endpoint still 503. Native unsupported hosts take this unsupported UI branch without attempting POSIX reads.
- Visually inspected mobile unsupported screenshot and moved reason outside the action row after detecting overflow. Final screenshots: `cron-contracts-unsupported.png`, `cron-contracts-output-drawer.png`.

## Final validation

All Python invocations activated the shared `.venv` (worktree-local temporary symlink), with this checkout's `src` on PYTHONPATH and synthetic HOME/USERPROFILE/SPARK_HOME. Browser fixtures create their own isolated homes as well. Actual Node **v22.22.1**, executable `/Users/joe/.nvm/versions/node/v22.22.1/bin/node`. Frozen `npm ci --ignore-scripts`: 399 packages, audit zero vulnerabilities; no lockfile modifications.

- `python -m pytest tests/spark_cli/test_cron_overrides.py tests/test_cron_output_routes.py tests/cron/test_jobs.py tests/cron/test_jobs_concurrency.py -q -n 0 -m 'not integration'`: **100 passed**; `cron-contracts-pytest.log`.
- Focused Ruff over both changed Python sources and three changed test/fixture files: **pass**; `cron-contracts-ruff-focused.log`.
- `mypy src/spark_cli/cron_routes.py src/spark_cli/cron_output_routes.py --follow-imports=silent`: **pass**, two files; `cron-contracts-mypy.log`.
- `npx tsc -b`: **pass**; `cron-contracts-types.log`.
- `npm run lint`: **pass**; `cron-contracts-eslint.log`.
- `npm test`: **86 files, 548 tests passed**; `cron-contracts-vitest.log`.
- `node src/spark_cli/web/e2e/cron-overrides.mjs`: **pass**; `cron-contracts-browser-overrides.log` (fixture output folder recorded there).
- `node src/spark_cli/web/e2e/cron-outputs.mjs`: **pass**, supported and unsupported UI/backend flows; `cron-contracts-browser-outputs.log`.
- `git diff --check`: **pass**.

Full-source `ruff check src/` returns **298 findings**, all outside the two changed Python source files; this is existing unrelated debt, not a green whole-repository gate (`cron-contracts-ruff-full.log`). An initial browser run exposed the custom Select string-label requirement; that was fixed and final pointer/keyboard flows pass. Initial focused type/import findings were fixed; final focused gates pass.

## Constraints and unexecuted checks

No native Windows machine/Windows CI run was available here. Unsupported capability + real UI behavior was simulated on macOS, and the Python module's portable-vs-POSIX partition was exercised before collection. The existing release-contracts workflow is unchanged and will exercise the native Windows capability API tests; its Python-only job does not itself launch the separate Node browser suite. Lead must retain native Windows CI/installed-package validation as distinct evidence.

No full repository pytest or broad mypy suite, general multi-chat browser suite, real-provider/profile call, generated manifest/bundle rebuild, Vite production build, installed macOS/Windows app test, package/release, PR operation, merge/push, delegation or watcher was performed. Package/bundle ownership remains with lead. Only the nine scoped source/test/browser files are committed; no PLAN/workflow/package/lockfile/generated files changed. Original and lead checkout handoffs are preserved.
