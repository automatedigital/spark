# Profile credential write protection — 15 October 2026

The plain nonserial acceptance run failed **1 / 12,453 passed / 151 skipped /
135 warnings / 408.36s**. Its sole failure was the existing default-home
credential denial assertion in `tests/tools/test_write_deny.py`. Raw evidence:
`/tmp/spark-upgrade-plain-nonserial-20261015T214537Z/`.
All 37 historical interrupted nodes passed in that run; their earlier
contamination cause remains unproved and is separate from this guard defect.

`WRITE_DENIED_PATHS` captured only the active Spark `.env` at import. With a
custom `SPARK_HOME`, the default-home credential path was missing. Changing
`SPARK_HOME` after import also left the new active credential path unprotected.

Two subprocess regressions establish both gaps without writing credential
files. Each imports the real guard with synthetic home/profile paths, changes
the active profile, and checks its decisions. Both fail before the correction
**(2 failed / 0.17s)**: default and changed-profile credentials are allowed,
while the import-time profile remains denied. The original default-path
assertion remains unchanged.

The five-line source correction retains all existing deny entries, adds the
HOME-anchored default credential path, and resolves the current Spark `.env`
at call time. This HOME anchor protects credentials; it does not store state.
No general `.env` pattern or profile-directory restriction is added. Regression
assertions retain allowed default/active `config.yaml` and project `.env` paths.

Validation used the root `.venv`, this worktree's `src` on `PYTHONPATH`, an
outer temporary `SPARK_HOME` during collection, and no diagnostic plugin:

```sh
python -m pytest tests/tools/test_write_deny.py tests/tools/test_file_write_safety.py tests/tools/test_file_operations.py tests/tools/test_native_file_operations.py tests/tools/test_file_read_guards.py tests/tools/test_file_operations_edge_cases.py tests/tools/test_file_tools.py tests/tools/test_file_tools_live.py -q -n0 -m 'not integration and not network'
```

**192 passed / 32.99s**, including real local file operations. Ruff passed for
both touched Python files and the repository's selected source gate; whitespace
checks passed. Independent read-only review identified a Windows test-isolation
issue: `Path.home()` uses `USERPROFILE`. The tests now set both `HOME` and
`USERPROFILE` and verify the child's home before importing application code.
The final test module passes **21 / 0.24s**; follow-up review has no remaining
findings. Windows execution was not performed.

Commands, source provenance, before-source snapshot, test-proof version,
logs and hashes are retained in
`/tmp/spark-upgrade-profile-write-deny-20261015-v1/` and summarized in the
adjacent JSON. Both touched Python files matched root's committed versions
before this change. No full-suite rerun, browser, build or performance capture
was run for this correction. Integration and broad acceptance remain root gates.
