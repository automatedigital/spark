# SP01 multi-chat backend startup repair — 2026-11-06

Failed head: 5ee7ae6c. Hosted web-quality run 42245837039, e2e job
127987695427. Playwright installation now succeeds on Ubuntu24.04. The next
step times out waiting 45 seconds for `/api/status`; Vite is ready but backend
logs are empty. No chat assertion was reached.

## Cause and change

The multi-chat runner uniquely started its API through `spark dashboard`.
`cmd_dashboard` unconditionally calls `_build_web_ui`, which runs `npm install
--silent` followed by `npm run build` before importing/starting the backend.
Those operations are captured and Python stdout was buffered, explaining the
lack of backend diagnostics while waiting. CI already installed frozen web
dependencies and the runner separately starts Vite. Backend readiness therefore
unnecessarily depended on another network/package-install/build cycle, potentially
changing the dependency tree while Vite was using it.

Start the real `spark_cli.web_server.start_server` directly, as the other chat,
sidebar and recovery browser fixtures do. Pass the chosen port as an argument
and run Python unbuffered so startup errors appear in retained logs. Keep the
same real app, lifecycle, fake-stream boundary, isolated profile, restart flow,
readiness timeout and every chat assertion. No product runtime changes or timeout
increases. This suite tests the source frontend served by Vite; canonical built
frontend acceptance remains in the existing later workflow gates.

## Reproduction and verification

Node22.22.1, Python3.11.7, fresh isolated venv installed with `.[dev,web]` and
fresh nested-lockfile `npm ci`. Fresh Python packages include pytest9.2.0,
FastAPI0.162.0, Starlette1.10.0 and Uvicorn0.54.0 (matching relevant packages from
the hosted dependency resolution). This is macOS verification, not Linux proof.

- Original runner under an isolated HOME and a PATH npm guard which rejects
  `install`, `ci` and `run build` but delegates `run dev`: exit1, backend status
  timeout, guard records `install --silent`. No external npm call is allowed.
- Identical guarded environment with corrected runner: exit0; initial backend,
  real multi-chat switching and backend restart pass. Guard log gains no further
  install/build attempt. This proves frontend installation is no longer a
  prerequisite for the test backend rather than relying on a warm npm cache.
- Fresh dependencies, normal environment: `npm run test:e2e` and
  `npm run test:e2e:recovery` both exit0. Recovery reports stalled reconnect,
  no unintended POST, failure outcome, approval, three-chat switching and gateway
  restart passed.
- Node22 `npm run lint`: exit0; `npm test`: 566 tests / 89 files pass.
- Fresh venv `PYTHONPATH=src python -m pytest
  tests/spark_cli/test_root_submissions.py tests/test_minimal_startup.py
  -q -n 0 -m 'not integration and not network'`: 13 passed, 3.04s.
- `node --check e2e/multi-chat.mjs` and `git diff --check`: pass.

No provider call, npm audit remediation, lockfile change, generated bundle or
relaxed assertion is included. Feature publication stays stopped until the next
hosted results are reconciled. The remaining hosted gates were not rerun locally
for this two-line launch change; their previous successes are not claimed as
results for this head. Do not rerun an unchanged failed job blindly.
