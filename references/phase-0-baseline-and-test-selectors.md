# Phase 0 Baseline And Test Selectors

Collected on 2026-06-25 on branch `improve-spark-maintainability`.

## Direction Decisions

- First priority: stabilization and navigability before new feature work.
- `PLAN.md` intentionally replaced the completed tactical chat-streaming plan;
  the old plan remains recoverable from git history, and this branch preserves
  the new strategic plan as the working tracker.
- `src/spark_cli/web_dist/` should remain tracked if packaging depends on it, but
  generated dashboard bundles should stay out of audits and ordinary development
  diffs unless a packaging change explicitly requires them.
- The local per-phase checklists in `PLAN.md` are the current tactical tracker.
  Create external issues only when a slice leaves this feature branch.

## Baseline Command Outputs

### Source Hotspots

Command:

```bash
source venv/bin/activate && python scripts/source_hotspots.py --limit 8
```

Output:

```text
   lines      bytes  path
-------- ----------  -----------------------------------------------------
   16799    1077225  skills/mlops/training/unsloth/references/llms-full.md
   12044     813089  skills/mlops/training/unsloth/references/llms-txt.md
   10719     550964  src/core/run_agent/__init__.py
    9737     446139  src/gateway/run.py
    7713     283405  src/spark_cli/main.py
    7204     268329  src/spark_cli/web_server.py
    5548     121144  skills/mlops/training/axolotl/references/api.md
    5386     190949  src/spark_cli/web/package-lock.json
```

Generated outputs excluded by the helper:

- `graphify-out/`
- `src/spark_cli/web/src-tauri/target/`
- `src/spark_cli/web/src-tauri/resources/`
- `src/spark_cli/web_dist/`
- `src/spark_cli/web/dist/`

### Ruff Statistics

Command:

```bash
source venv/bin/activate && ruff check src/ --statistics --exit-zero
```

Summary:

```text
Found 7050 errors.
6029 fixable with --fix.
```

Largest buckets:

```text
2130 W293  blank-line-with-whitespace
1999 UP006 non-pep585-annotation
1630 UP045 non-pep604-annotation-optional
 379 I001  unsorted-imports
 292 UP035 deprecated-import
 248 E402  module-import-not-at-top-of-file
```

### Safe Ruff Fix Pass

Command:

```bash
source venv/bin/activate && ruff check src/ --fix
```

Result:

```text
Found 7284 errors (6439 fixed, 845 remaining).
No fixes available (412 hidden fixes can be enabled with the --unsafe-fixes option).
```

Remaining categories after the safe pass:

```text
373 W293 blank-line-with-whitespace
277 E402 module-import-not-at-top-of-file
 69 F401 unused-import
 24 UP035 deprecated-import
 20 B007 unused-loop-control-variable
 18 E741 ambiguous-variable-name
 15 B027 empty-method-without-abstract-decorator
  9 B905 zip-without-explicit-strict
```

Review decision: do not run `--unsafe-fixes` on this mixed maintainability branch.
Handle the remaining categories in separate manual slices so behavior-affecting
changes, import-order changes, and potentially intentional no-op methods are
reviewed with local context.

### Mypy Ratchet

Command:

```bash
source venv/bin/activate && python scripts/mypy_ratchet.py --skip-strict
```

Output:

```text
mypy ratchet passed: 458 errors <= baseline 458.
```

The checked-in baseline is `scripts/mypy_baseline.json`.

### Current Focused Test Health

Recent verification on this branch:

```bash
source venv/bin/activate && python -m pytest tests/spark_cli/test_web_turn_state.py tests/spark_cli/test_web_server_events.py tests/test_model_tools.py -q -n0
cd src/spark_cli/web && npm run test -- --run
cd src/spark_cli/web && npm run lint
cd src/spark_cli/web && npx tsc -b --noEmit
cd src/spark_cli/web && npm run build -- --outDir /tmp/spark-web-build-check --emptyOutDir
```

Notes:

- Frontend lint currently reports 0 errors and 6 pre-existing React hook warnings.
- The temporary web build verifies Vite output without dirtying tracked
  `src/spark_cli/web_dist/`.
- Desktop/Tauri packaging has not been rebuilt on this branch.

## Rapid Test Selectors

Use these while slicing the plan. Run broader suites before pushing.

| Area | Fast command |
| --- | --- |
| Agent loop | `source venv/bin/activate && python -m pytest tests/run_agent/ tests/tools/test_interrupt.py -q` |
| Prompt caching | `source venv/bin/activate && python -m pytest tests/run_agent/ tests/agent/test_prompt_caching.py -q` |
| Gateway | `source venv/bin/activate && python -m pytest tests/gateway/ -q` |
| Web backend | `source venv/bin/activate && python -m pytest tests/spark_cli/test_web_server.py tests/spark_cli/test_web_server_events.py tests/spark_cli/test_web_turn_state.py -q -n0` |
| Frontend | `cd src/spark_cli/web && npm run test -- --run && npm run lint && npx tsc -b --noEmit` |
| Tool runtime | `source venv/bin/activate && python -m pytest tests/test_model_tools.py tests/tools/ -q` |
| Profiles | `source venv/bin/activate && python -m pytest tests/spark_cli/test_profiles.py tests/test_subprocess_home_isolation.py -q` |
| Docs/graph upkeep | `source venv/bin/activate && graphify update .` |

## Refactor Safety Checklist

Use the checklist in `PLAN.md` for each slice before marking it complete. In
particular, confirm compatibility for public routes, prompt-caching stability for
agent-loop work, profile-safe paths for state changes, and graph/docs freshness
for architecture moves.
