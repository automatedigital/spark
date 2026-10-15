# Claude Code entry point

Read [AGENTS.md](AGENTS.md) first. It is the canonical development guide and
contains the full safety, extension and verification rules. This file adds no
separate architecture or permission policy.

## Orientation

- [CONTEXT.md](CONTEXT.md): domain vocabulary and current/proposed distinctions.
- [STRUCTURE.md](STRUCTURE.md): source map, state ownership and build boundaries.
- [PLAN.md](PLAN.md): approved app upgrade, packet dependencies, delegated briefs,
  estimates and acceptance gates. Pending packets are not implemented features.
- [Rollout runbook](docs/development/app-upgrade-rollout.md): consistent backups,
  isolated opt-in flags, process-local limits and schema-compatible rollback.
- [docs/adr/](docs/adr/): accepted decisions, especially ADR-0001 (prompt cache)
  and ADR-0012 (lazy discovery and runtime boundaries).
- [Issue workflow](docs/agents/issue-tracker.md) and
  [triage labels](docs/agents/triage-labels.md): GitHub Issues via `gh`.

## Development commands

Activate `.venv` before Python, tests, linters or local servers. Include the web
extra for dashboard work and tests that import route modules.

```bash
source .venv/bin/activate
pip install -e ".[dev,web]"
python -m pytest tests/ -m "not slow and not integration" -q -n 0
ruff check src/
mypy src/agent/ src/spark_cli/
python scripts/generate_tool_manifest.py --check

(cd src/spark_cli/web && npm ci)
(cd src/spark_cli/web && npm run lint && npm test && npm run build)
(cd src/spark_cli/web && npm run test:e2e)
(cd src/spark_cli/web && npm run test:e2e:recovery)
(cd src/spark_cli/web && npm run test:e2e:sidebar)
(cd src/spark_cli/web && npm run test:e2e:subagents)
(cd src/spark_cli/web && npm run test:e2e:navigation)
```

Use Node.js 22 and the frontend's own lockfile. Browser suites need the Playwright
browsers specified in `web-quality.yml`; Python and Node suites use separate
installations. Use isolated `SPARK_HOME` and synthetic data for manual servers.
Verify `node --version` and `node -p process.execPath` before frontend acceptance;
a directory or symlink named `node@22` does not establish the runtime version.
Run focused checks while iterating, then the relevant wider suite. Record preexisting
lint/type failures separately. Override pytest markers carefully: integration tests
are excluded by default, but a supplied `-m` replaces that expression.
The `serial` marker does not override xdist's default workers. Use `-n 0` when
serial cases are selected, or run the separate parallel/serial selections in
`AGENTS.md` sequentially and require both to pass.

## Boundaries to preserve

- Import `AIAgent` from `core.run_agent`; its loop lives in `turn_loop.py`.
- Built-in schemas come from `tools/generated_manifest.py`. Register handlers,
  update `tools/manifest_spec.py` and toolsets, then regenerate the manifest.
  Do not add eager imports to `_discover_tools()` or hand-edit generated schemas.
- Keep tool schemas, cached prompt prefixes and past messages stable during a
  conversation. ADR-0001 cache goldens gate runtime changes; ADR-0012 guards lazy
  startup. Skill instructions enter as user messages, not system-prompt edits.
- Use `get_spark_home()` for state and `display_spark_home()` in messages.
  Profile listing is HOME-anchored by design. Never test against real user state.
- `web_server.py` owns chat lifecycle; `spark_state.py` owns durable session
  persistence; `web_state.py` owns bounded web journal envelopes. Their cursors
  differ. Reconcile snapshots after restart; do not replay uncertain side effects.
- Root completion owns parent completion. Child completion, cancel acceptance,
  stale UI and worker silence do not establish it. Preserve child permissions.
- Keep Kanban Task identity separate from conversation Run/Attempt and Subagent.
  Fence worker writes by claim ownership when changing execution behavior.
- Gate provider-specific controls by supported capabilities and existing runtime
  resolution; do not invent provider parity or silently downgrade isolation.
- Make source edits in `web/src/` and Tauri edits in `web/src-tauri/`.
  Regenerate tracked `web_dist/` only through the build workflow at the web gate.

## Team execution and reporting

Inspect dirty work first and preserve unrelated edits. Use descriptive `feat/`,
`fix/` or `docs/` branches, isolated worktrees and narrow staging. Give delegated
packets a committed base, allowed paths, dependencies, contract, acceptance checks
and required evidence. One agent owns each shared schema, migration, lockfile,
manifest and bundle at a time. Integrate in dependency order.

For chat/gateway changes, verify three concurrent chats, long history, project
creation/expansion, child detail, pending decisions, refresh, disconnection and
gateway restart. Keep drafts, staged attachments, scroll and thread identity
intact. Report the exact browser flow, test exit status and remaining limitations.
Mark a packet complete only with acceptance evidence. Verify served web assets and
installed desktop packages independently; a successful build is not platform QA.
