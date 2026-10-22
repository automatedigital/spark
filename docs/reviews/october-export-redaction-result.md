# PR182 export redaction implementation result

Commit for lead cherry-pick: `a0662f69f6fcf1deadcb50449852489aa7970c95`.

Base: `2695192f` (resolved via `git merge --ff-only 2695192`, succeeded).
Worktree: `/tmp/spark-export-redaction-20261022`.
Branch: `fix/export-redaction-182`. Requested `fix/export-redaction` was already attached to `/Users/joe/.t3/worktrees/spark/t3-fc2878c7`; initial worktree creation with that name failed safely. Used the descriptive suffixed branch to preserve the handoff checkout. No source edits or branch changes were made in either the handoff checkout or lead-owned `/tmp/spark-review-release-20261022`.

Read AGENTS.md, CONTEXT.md, STRUCTURE.md, accepted ADRs 0001/0012/0013, backend.md, backend-verdicts.json and the actual `182-redaction-repro.log`. The requested `reproduction182-redaction-repro.log` filename does not exist; `182-redaction-repro.log` is the review's referenced evidence.

## Change

Only `src/spark_cli/session_export.py` and `tests/spark_cli/test_session_export_markdown.py` changed. Apply the existing credential-field fullmatch policy before any type dispatch; matching field values become a single `[REDACTED]` marker for objects, lists, strings, integers, floats, booleans and null. Existing text force-redaction, field-name policy, default JSON export and format dispatch remain intact.

28 direct cases cover four credential names/cases and seven value types, both top-level and nested. Two real SQLite/CLI tests persist serialized tool arguments, export default JSON or explicit Markdown with log redaction disabled, and inspect actual final file bytes in a stub publisher. They verify object/numeric/list/nested secrets are absent, whole-field markers are present, ordinary nested values and Unicode survive, caller input remains unchanged, and raw SessionDB export remains equal. The publisher stub returns an example.invalid URL; no external publication occurs.

## Environment and exact commands

All Python/lint/type commands activated `/Users/joe/Developer/github/spark/.venv/bin/activate` and ran from the isolated worktree with:

```sh
export HOME=/tmp/spark-export-redaction-env-20261022/home
export USERPROFILE=/tmp/spark-export-redaction-env-20261022/home
export SPARK_HOME=/tmp/spark-export-redaction-env-20261022/profile
export PYTHONPATH="$PWD/src"
export PATH="/private/tmp/spark-packets-20261022/node-v22.23.4-darwin-arm64/bin:$PATH"
```

`node --version` returned `v22.23.4`; `node -p process.execPath` returned `/private/tmp/spark-packets-20261022/node-v22.23.4-darwin-arm64/bin/node`. Tests additionally isolate HOME/USERPROFILE/SPARK_HOME per test. No real provider or profile calls.

Before fix, new tests against unmodified base source:

```sh
python -m pytest tests/spark_cli/test_session_export_markdown.py -k credential_values_never_reach_publisher -m 'not integration and not network' -vv -n 0
```

Exit 1: **2 failed, 41 deselected**. Both final-byte assertions show `[b'SYNTHETIC_OPAQUE_CREDENTIAL', b'123456789', b'SYNTHETIC_LIST_OBJECT', b'SYNTHETIC_NESTED_CREDENTIAL']` leaked. The simple string list item was already redacted. Log: `export-redaction-before.log`.

After fix:

```sh
python -m pytest tests/spark_cli/test_session_export_markdown.py tests/spark_cli/test_session_export.py tests/agent/test_redact.py tests/spark_cli/test_profile_export_credentials.py -m 'not integration and not network' -q -n 0
```

Exit 0: **95 passed in 1.93s**, including both previously failing SQLite final-byte cases. Log: `export-redaction-after.log`.

```sh
ruff check src/spark_cli/session_export.py tests/spark_cli/test_session_export_markdown.py
ruff check src/ --select UP015,F,B,I,W,UP028,UP031,UP035,UP037,UP042 --ignore B027
mypy src/agent/ src/spark_cli/
git diff --check
```

All exit 0. Mypy: **Success: no issues found in 137 source files** (annotation-unchecked informational notes retained). Logs: `export-redaction-scoped-lint.log`, `export-redaction-lint-ratchet.log`, `export-redaction-mypy.log`.

## Existing debt and unexecuted checks

`ruff check src/` exits 1 with **298 existing findings**. Verified against a pristine `git archive 2695192 src` plus the base pyproject.toml in `/tmp/spark-export-redaction-baseline-20261022`: run `ruff check src/ --output-format json` from each checkout with its local config, normalize filenames relative to src, and compare code/location/message. Result: **baseline_findings=298 current_findings=298 identical=True**. Logs: `export-redaction-full-lint.log`, `export-redaction-baseline-lint.json`, `export-redaction-current-lint.json`, `export-redaction-lint-comparison.log`. An initial comparison using the worktree's absolute config path gave 369 baseline findings because per-file-ignore patterns were rooted to the other checkout; corrected by placing the base config alongside the archived source and rerunning from that directory. No lint debt was fixed or gates weakened.

Not executed: full pytest suite, browser flows, runtime cache/manifest/startup suites (runtime/tool discovery unchanged), frontend build/tests, production bundle generation, installed macOS/Windows acceptance, packaging, signing/notarization and publishing. No claims of all-20-PR integration or release readiness. No PR creation, merge, push, release, delegation, watch or external publication. No package/lockfile, generated bundle/manifest, PLAN or workflow edits.

Commit includes exactly the two allowed files. Isolated worktree clean after commit. Lead can cherry-pick the exact SHA above; integration and release remain lead-owned.
