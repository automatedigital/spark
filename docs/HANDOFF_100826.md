# Handoff — codebase health branch (2026-08-10)

Branch `fix/plan-quality-gates`, PR
[#126](https://github.com/automatedigital/spark/pull/126) (open, mergeable).
The remote head has 56 commits. The cleanup described below is currently an
uncommitted working-tree diff and must be reviewed before the PR is updated.

The committed head checks were green before cleanup. The uncommitted cleanup
has now passed the full local safe Python suite, Ruff, mypy, frontend lint,
TypeScript, Vitest, production build, and both browser E2E suites. Remote CI has
not been rerun because nothing in this cleanup has been pushed.

`docs/plans/2026-08-10-codebase-health.md` is the source of truth for this
maintenance work. Root `PLAN.md` remains the web UI, skills, and adaptive
routing roadmap. This document covers the blockers, CI history, and traps.

---

## Read these first

| Path | Why |
| --- | --- |
| `docs/plans/2026-08-10-codebase-health.md` | The ten maintenance items, status, and evidence |
| That plan § "Getting CI green" | The six rounds it took to turn the test job on |
| That plan § "Fixed: turns could report success, or never finish" | Two real bugs in the turn lifecycle |
| `git log main..HEAD` | Each commit message explains one decision |

Do not re-derive the audit. It is already written down.

---

## State in one table

| Item | Result | Open |
| --- | --- | --- |
| 1 Tests in CI | 12,287 safe fast/non-integration tests now run; none did before | — |
| 2 Undefined names | 6 fixed, `F821` gated | — |
| 3 Split `web_server.py` | 11,647 → 9,000 lines, 54/123 routes | 69 routes |
| 4 `run_agent`/`cli` splits | 11,341 → 1,744 and 4,101 → 1,134 | constructor decomposition only |
| 5 Ruff ratchet | 6,944 → ~300 findings; `F,B,I,W` gated | — |
| 6 Silent exceptions | 955 of 955 now log a traceback | — |
| 7 mypy | 126 modules clean **and gated** | — |
| 8 Event loop | Withdrawn — the finding was wrong | — |
| 9 React split | `api.ts` 3,052 → 487 | `ChatPanel.tsx` 2,047 |
| 10 Frontend CI | eslint + tsc + vitest + non-blocking multi-chat/restart and contract e2e | — |

---

## Blockers — what was attempted and reverted

These are not "not started". Each was built, failed verification, and was
backed out. Do not repeat them the same way.

### 1. `web_turns.py` — the enabler for item 3's remaining 69 routes

The remaining route families depend on state `web_server` owns (turn registry,
event queues, agent cache). A route module holding them must import
`web_server`, which imports route modules to register them — a cycle.

I extracted that shared core into `src/spark_cli/web_turns.py`. Dependency
closure worked (4 iterative passes, ~1,450 lines moved). **It broke 45 tests in
`test_web_server_events.py` and was reverted.**

The specific failure worth knowing: `web_server._lifespan` did
`global _web_event_loop; _web_event_loop = ...`. Once that variable lived in
`web_turns`, the `global` statement bound a **different** name, so the event
fanout read `None` forever and every SSE test timed out. A setter
(`set_web_event_loop`) fixes that one, but more of the same class remained.

If you retry: move the state **with its mutators**, give every module-level
mutable a setter rather than a `global`, and expect to re-point a large number
of `monkeypatch.setattr(web_server, ...)` calls.

### 2. Moving `AIAgent.__init__` into a mixin (item 4's last 744 lines)

Mechanically fine — the mixin resolved and imports worked. But it changed which
**tool-schema profile** was resolved, and
`tests/run_agent/test_caching_golden.py` (byte-exact, ADR-protected) caught it.
Reverted. The constructor is 1,040 lines. The orchestration loop now has
byte-exact standard chat-completions, Anthropic Messages, and Codex Responses
coverage and lives in `turn_loop.py`, so `run_agent/__init__.py` is 1,744
lines without crossing ADR 0012 unsafely. Going lower means decomposing the
constructor, not relocating it unchanged.

`SparkCLI.__init__` (322 lines) is the same situation at smaller scale.

### 3. `ChatPanel.tsx`

2,047 lines: 1,482 of orchestration across interdependent hooks, then 435 of JSX.
Unlike `api.ts`, the pieces share closure state, so this is a real React
refactor. `CLAUDE.md` also names this component as the one needing manual
verification of loading, streaming, offline, reconnect and gateway-restart
states — a type checker will not catch a broken streaming state machine.
Not attempted.

---

## The trap that caused most of the CI failures

**Tests monkeypatch names on the module where the code used to live.** Move a
function and the patch silently stops applying — the test either fails or, far
worse, exercises the real thing.

This is not theoretical. During the route extraction, the mac-update tests
patched `subprocess.Popen` through `ws.subprocess` where `ws` was
`spark_cli.web_server`. When those handlers moved to `mac_routes`, the patch
stopped covering them, **the real installer ran**, quit the desktop app,
installed a DMG, and relaunched it inheriting pytest's `SPARK_HOME`. The user's
app then showed an empty chat list because it was pointed at a temp directory.
No data was lost. Two mitigations landed:

- Those tests patch `subprocess` and `urllib.request` at the source module.
- `tests/conftest.py` has a `_block_desktop_app_spawn` fixture that refuses any
  spawn mentioning `/Applications/Spark.app`, `hdiutil` or `osascript`. Ordinary
  subprocess use is untouched. (A first version blocked *all* spawning and broke
  168 tests — that is not what shipped.)

**Rule for any further extraction:** after moving code, grep for
`core.run_agent.<name>`, `core.cli.<name>`, `spark_cli.web_server.<name>` in
`tests/`. Where a name is widely patched, the moved code resolves it through the
package at call time via a `_pkg()` accessor rather than binding it at import.
See `src/core/run_agent/agent_support.py` and `src/core/cli/main_loop.py` for
the pattern and the comment explaining it.

---

## CI failure history (why it took six rounds)

The suite had never run in CI. It passed locally only because the developer
machine had credentials, macOS, ripgrep and a populated `~/.spark`.

| Round | Failures | Cause |
| --- | --- | --- |
| 1 | 576 | Job installed `[dev]`; `workspace_routes` needs FastAPI from `[web]` |
| 2 | 8 | Credentials, macOS-only gates, 2s async timeouts |
| 3 | 4 | `conftest` deleted `OPENROUTER_API_KEY`, leaving an empty key |
| 4 | 1 | Diagnostics added to a CI-only web-turn failure |
| 5 | 2 | A missing `os` import (mine) and an agent built without credentials |
| 6 | 0 | Green |

Two of these were real user-facing bugs found only because CI runs clean:
content search crashed without ripgrep, and `@`-completion silently returned
nothing without `rg`/`fd`.

### Verify on Linux locally, never by pushing

Pushing to watch CI emails the user on every red run. Use a container:

```bash
docker run --rm -v "$PWD":/w -w /w -e CI=true python:3.11-slim bash -c \
  'apt-get update -qq && apt-get install -y -qq git \
   && git config --global --add safe.directory /w \
   && pip install -q -e ".[dev,web]" \
   && ruff check src/ --select UP015,F,B,I,W,UP028,UP031,UP035,UP037,UP042 --ignore B027 \
   && mypy src/agent/ src/spark_cli/ \
   && python -m pytest tests/ -m "not slow and not integration" -q --timeout=60'
```

Install `git` — without it ~30 tests fail for unrelated reasons.

**Expect exactly 8 failures in that container.** They pass on the GitHub runner
and are environment artifacts, not regressions:

- `test_gateway_service` (3) — container runs as root, no systemd
- `test_voice_mode` (4) — no audio device
- `test_tool_facades` (1) — `web_search` only registers with `EXA_API_KEY`

Anything beyond those 8 is yours.

### Known flakes (pre-existing, not from this branch)

The suite has xdist ordering pollution. These pass in isolation and fail
intermittently depending on which tests share a worker:
`test_config_env_expansion`, `test_modal_sandbox_fixes`, `test_model_tools`,
and occasionally `test_web_server_events`. They surface more in a 12-core
container than on GitHub's 4-core runner. `--dist loadfile` makes it worse
(21 failures) — do not try that again.

### Web-turn test isolation

The web-event fixture now owns a fresh `AsyncRuntime` per test and shuts it down
after draining active turns. The former CI-only skip was removed. The runtime,
scheduler, and full web-event sequence passes with `CI=true` (124 tests).

---

## Gates you must keep green

```bash
ruff check src/ --select UP015,F,B,I,W,UP028,UP031,UP035,UP037,UP042 --ignore B027
mypy src/agent/ src/spark_cli/                          # full declared scope
python -m pytest tests/ -m "not slow and not integration" -q --timeout=60
cd src/spark_cli/web && npm run lint && npx tsc --noEmit -p tsconfig.app.json && npx vitest run
```

There is no mypy exemption block. Do not reintroduce one; fix errors at the
typed boundary.

`B027` is a deliberate permanent ignore — Spark's base classes use empty
methods as optional hooks; making them abstract would force every subclass to
implement hooks it never uses.

---

## Highest-value next steps

1. **Merge #126 after the cleanup diff is reviewed.** 56 commits is already a
   large review surface.
2. **Retry `web_turns`** on its own branch, using the setter guidance above.
   That unblocks item 3's remaining 69 routes.
3. **`ChatPanel.tsx`** last — it needs a browser, not a type checker.

---

## Cleanup acceptance (2026-08-10)

- Ruff ratchet: clean, including the final 14 UP rules.
- mypy: 126 modules checked, zero errors, no exemption block.
- Python: 12,288 passed, 151 skipped (`not integration`).
- Frontend: ESLint and TypeScript clean; 369 Vitest tests passed.
- Production web build: passed; initial static entry graph 214.97 KiB gzip
  against a 600 KiB budget.
- Browser: `multi-chat.mjs` and `chat-contracts.mjs` both passed, including
  active-chat switching, refresh/reconnect recovery, restart recovery, paged
  history anchoring, action contracts, and project grouping.
- Routes: 251 method/path entries, all unique, matching the recorded baseline.

---

## Suggested skills

- `mattpocock-skills:diagnosing-bugs` — for the `AsyncRuntime` teardown flake
  and any resurfacing web-turn failure. These are ordering/state bugs where a
  disciplined loop beats guessing; this session lost a lot of time guessing.
- `mattpocock-skills:codebase-design` — before retrying `web_turns`. The
  question is where the seam goes between the app, the turn registry and the
  route modules. That is a deep-module question, not a text-moving one.
- `mattpocock-skills:tdd` — for the constructor decomposition in item 4. The
  caching golden test already exists and is the safety net; drive the split
  from it.
- `mattpocock-skills:code-review` — before merging #126, to review the branch
  against the repo's standards in one pass.
- `build-mac` / `release-mac` — only after #126 merges. Note the desktop app
  incident above; do not run installer paths from a test context.

---

## Conventions worth respecting

- Feature branches and PRs only; never push to `main`.
- No AI attribution in commits or PR bodies.
- Check items off in the codebase-health plan as you complete them, not in a
  batch at the end.
- Use `.venv`, not anaconda. `pip install` in this session silently landed a
  package in `/opt/anaconda3` — verify with `python -c "import x"` after.
- Route extractions are verified by diffing the app's full route table against
  `main` (251 routes, identical paths and methods). Keep doing that.
