# Explicit legacy-pin import follow-up

Extension to existing `sidebar-scale.mjs`, validated after root released the
exclusive performance window. No application source changes.

The existing no-auto-import fixture now includes an eligible revision-zero ID,
an edited ID, a missing ID, a number and null. After existing timing observations,
the flow clicks the explicit import button, asserts exactly one PATCH for the
eligible ID at revision zero, verifies all other metadata remains unchanged,
checks the scoped import marker, and reloads to verify persistence and dismissal.
The second real profile must not receive that marker.

Additional receipts: the eligible session starts with exact default metadata and
zero messages, opens the existing empty-conversation UI, and a no-match search
waits for its real 200 search response before checking the no-results row.

Validation: actual Node 22.22.1 at
`/Users/joe/.nvm/versions/node/v22.22.1/bin/node`, root venv activated,
`PYTHON=/Users/joe/Developer/github/spark/.venv/bin/python`, and `PYTHONPATH=$PWD/src`:

```sh
SPARK_E2E_OUTPUT_DIR=/tmp/spark-finish-20261017-browser-00a025d1/sidebar-explicit-import-corrected node src/spark_cli/web/e2e/sidebar-scale.mjs
```

Exit 0: all 12 checks passed, no correctness failures or page errors. The JSON
report records the one import PATCH (`scale-049`, `expected_revision: 0`,
`pinned: true`), marker key and refresh-persistence receipt. Empty-session default
metadata/zero messages/empty-conversation UI and real empty-search response/row
checks passed. Screenshot, report and network trace are in the output directory;
stdout is its sibling `sidebar-explicit-import-corrected.log`.

The initial attempt passed the import mutation assertions but stopped at a
post-refresh locator that incorrectly expected the regular-row comma in an Inbox
pinned row's accessible name. Source inspection corrected only that locator.
Original failure JSON/screenshot/trace remain in sibling `sidebar-explicit-import`
and its `.log`; no application fix or assertion removal was needed.

No installs, builds, tests or browser work occurred during the performance hold.
Existing timing assertions remained intact, but this concurrent desktop-build run
is functional acceptance only; no performance comparison is claimed.
