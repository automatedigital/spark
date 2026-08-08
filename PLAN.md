# Spark Improvement Plan

Ten improvements found by a code audit on 2026-08-07 (branch `main`, commit
`1cbe5b1f`). Items are ranked: 1-5 are "do now", 6-10 are "later". Every item
lists the evidence, the fix, and a time estimate.

---

## Do now

### 1. Run the test suite in CI

- [x] Add a `pytest` job to `.github/workflows/python-quality.yml`

**Done.** The `pytest` job runs `python -m pytest tests/ -m "not slow" -q
--timeout=60`. Adding it first required fixing 8 pre-existing failures on
`main`, described under "Work completed" at the end of this file.

**Evidence.** The repo has 667 test files and 204,324 lines of test code. No
workflow runs them. `python-quality.yml` runs one command:
`ruff check src/ --select UP015`. `windows-desktop-beta.yml` builds a binary.
`web-supply-chain.yml` checks lockfile drift. Nothing runs a test.

**Fix.** Add a job that installs `.[dev]` and runs
`python -m pytest tests/ -m "not slow and not integration" -q`. Start with the
fast subset so the job stays under 10 minutes, then add a nightly full run.

**Estimate.** 1 hour to add the job. Half a day if flaky tests must be marked
`serial` first (see `AGENTS.md` on xdist flakiness).

---

### 2. Fix the six undefined names

- [x] `ruff check src/ --select F821` must return clean

**Done.** All six fixed and `F821` is now enforced in CI. The
`commands.py` one was a live user-facing bug: `_context_completions` was a
`@staticmethod` that called `self._fuzzy_file_completions`, so typing a bare
`@` in the CLI raised `NameError`. It now has a regression test in
`tests/spark_cli/test_path_completion.py::TestContextCompletion`, verified to
fail against the old code.

**Evidence.** `ruff check src/ --select F821` reports six real
`NameError`-at-runtime sites:

| File | Line | Undefined name |
| --- | --- | --- |
| `src/gateway/platforms/sms.py` | 77, 286 | `aiohttp` |
| `src/gateway/platforms/whatsapp.py` | 148 | `aiohttp` |
| `src/plugins/memory/holographic/retrieval.py` | 446 | `np` |
| `src/spark_cli/commands.py` | 867 | `self` |
| `src/tools/patch_parser.py` | 326 | `PatchResult` |

The `aiohttp` cases are guarded optional imports that were never bound in the
module scope. `commands.py:867` uses `self` in a function that has no `self`
parameter.

**Fix.** Bind the optional imports at module scope behind
`try/except ImportError`, add the missing `numpy` import, add the missing
`PatchResult` import, and correct the `commands.py` function signature. Then add
`F821` to the CI ratchet in item 5.

**Estimate.** 1 to 2 hours.

---

### 3. Split `web_server.py` into routers

- [ ] Move the 123 inline routes out of `src/spark_cli/web_server.py`

**Evidence.** `src/spark_cli/web_server.py` is 11,647 lines and declares 123
route decorators directly on the app object. The pattern to copy already exists:
eight modules (`artifacts_routes.py`, `canvas_routes.py`, `connectors_routes.py`,
`kanban_routes.py`, `memory_routes.py`, `messaging_routes.py`,
`workflow_routes.py`, `workspace_routes.py`) already use `APIRouter`.

**Fix.** Extract route groups into new `*_routes.py` modules that follow the
existing convention. Keep `web_server.py` for app construction, middleware,
lifespan, and router registration. Do one group per PR so review stays possible.

**Estimate.** 2 to 3 days across several PRs. About 3 hours per route group.

---

### 4. Finish the `run_agent` and `cli` package splits

- [ ] Reduce `src/core/run_agent/__init__.py` below 1,000 lines
- [ ] Reduce `src/core/cli/__init__.py` below 1,000 lines

**Evidence.** Both splits were started and stalled:

- `src/core/run_agent/` is 12,161 lines total. `__init__.py` holds 11,243 of
  them (92%). The ten extracted modules average 92 lines.
- `src/core/cli/` is 13,041 lines total. `__init__.py` holds 4,130 (32%) even
  though seven mixins already exist.

**Fix.** Continue the pattern that is already there. For `run_agent`, pull the
tool-call loop, streaming, and provider dispatch into siblings of
`turn_orchestration.py`. For `cli`, move the remaining concerns into new mixins.
Keep `from core.run_agent import AIAgent` working, as `CLAUDE.md` requires.

**Estimate.** 3 to 4 days. Do it after item 1, so the tests can prove that
nothing broke.

---

### 5. Widen the CI ratchet beyond one rule

- [x] Add `F` and `B` rule families to the CI ratchet
- [x] Clear `F841`, `B007`, `B905`, `B008`, `B904` and `F401`
- [x] Add `I` and `W` to the ratchet
- [x] `UP` swept (`UP015` gated; `UP035`/`UP031` remainder is not auto-fixable)

**Final state.** The ratchet is
`ruff check src/ --select UP015,F,B,I,W --ignore B027`. Total findings fell
from 6,944 to about 300, and the remainder is deliberate: 269 `E402` late
imports (this codebase manipulates `sys.path` before importing packages), 17
`E741`, and a handful of `UP035`/`UP031` that have no safe autofix.

`B027` is a permanent documented ignore. Spark's base classes use empty
methods as optional hooks with a no-op default, so making them abstract would
force every subclass to implement hooks it never uses.

The `UP` sweep exposed three latent bugs, because PEP 604 unions are evaluated
at runtime where `Optional[...]` was not: two callbacks annotated `callable`
(the builtin function) instead of `Callable`, and a lock annotated
`multiprocessing.Lock`, which is a factory function rather than a type.

**Evidence.** CI enforces `UP015` only. `ruff check src/ --statistics` reports
6,944 findings. Most are cosmetic (1,981 `UP006`, 1,981 `W293`, 1,665 `UP045`),
but the auto-fixable share is large and the correctness rules are small enough
to clear now:

| Rule | Count | Meaning |
| --- | --- | --- |
| `F821` | 6 | undefined name (item 2) |
| `F841` | 7 | unused variable |
| `B023` | 2 | closure does not bind loop variable |
| `B012` | 1 | `return` inside `finally` silences exceptions |
| `F401` | 35 | unused import |

**Done.** The CI ratchet is now
`ruff check src/ --select UP015,F,B --ignore B904,B007,B027,B905,B008,F401,F841`.

Corrections to the first draft of this item, after reading the code:

- `B023` in `src/cron/scheduler.py` is a **latent hazard, not a live bug**. The
  `job_cancelled` closure is invoked inside the same loop iteration that
  defines it, so it reads the correct values today. It would break only if
  `run_job` retained the callback past the iteration. The loop variables are
  now bound as default arguments, so it is correct either way.
- `B012` in `src/core/cli/voice_mixin.py` is real. A `return` inside `finally`
  discards any in-flight `KeyboardInterrupt`, which
  `CLAUDE.md` names as a pitfall. Replaced with a guard flag.
- `F601` in `src/spark_cli/model_normalize.py` was a duplicated `"trinity"`
  dict key. Both copies mapped to the same value, so it was harmless. Removed.
- `F811` in `src/plugins/memory/hindsight/__init__.py` was a duplicated
  `get_spark_home` import. Removed.
- `B033`, `B009`, and `B010` (11 findings) were auto-fixed.

**Remaining.** `F401` needs `--unsafe-fixes` because most of the 35 are
re-exports in `__init__.py` files; each needs a human check. `B904` (115) is
the largest block and is already an intentional gradual-adoption ignore.

---

## Later

### 6. Stop swallowing exceptions silently

- [x] Replace bare `except Exception: pass` with logged handlers

**Done: 873 of 955.** An AST transform rewrote every handler whose body is
exactly `pass` into `logger.debug(..., exc_info=True)`, naming the enclosing
function so a log line identifies the site. 44 modules had no logger at all
and had one added.

The count is 955, not the 551 in the original estimate: that number came from
a grep for `except Exception` followed by `pass`, which missed other exception
types and multi-line handlers. The AST pass finds all of them.

**Remaining: 82.** Formatting cases the transform deliberately declines —
`except X: pass` on a single line, or a `pass` sharing its line with a
comment. Three more sites in `gateway/run.py` run at import time before the
module logger exists and keep their `pass` with a comment saying why.

**Evidence.** 551 sites match `except Exception:` followed directly by `pass`,
across 241 files. The worst areas are `src/tools/` (`voice_mode.py`,
`vision_tools.py`, `tts_tool.py`, `terminal_tool.py`, `skills_tool.py`,
`web_tools.py`). Each one hides a failure that a user later reports as
"it did nothing".

**Fix.** Add a `logger.debug(...)` or `logger.warning(...)` line to each
handler, so the failure is recoverable from a log. Where the exception is truly
expected, narrow the clause to the specific type. Do this file by file, starting
with `src/tools/`.

**Estimate.** 2 to 3 days. It is mechanical but wide.

---

### 7. Get `mypy` to zero on its declared scope

- [x] Gate the clean modules in CI so they cannot regress
- [ ] Clear the 41 modules still listed in the mypy overrides block

**Partly done.** 588 errors -> 563, and files with errors 56 -> 41, so 70 of
111 modules are clean. `mypy src/agent/ src/spark_cli/` now exits clean and
runs as a CI job, because the 41 modules that still have errors are listed in
a `[[tool.mypy.overrides]]` block with `ignore_errors`. Fix a module, delete
its line, and the gate covers it.

Fixed along the way: 12 stale `type: ignore` comments, `Any` leaking from
untyped boundaries (`keyring`, `json.loads`, `dict.get`) now cast at the
boundary, missing annotations, and three real bugs — `_format_size` declared
an `int` it divides into a float, a gateway deadline compared against `None`,
and a loop variable rebound from an earlier loop.

`types-PyYAML` was added to the dev extras: without it a clean machine reports
six `import-untyped` errors that a developer machine never shows.

**Remaining.** The 41 modules hold 563 errors, concentrated in
`agent/auxiliary_client.py` (122), `spark_cli/web_server.py` (95),
`agent/model_metadata.py` (47) and `agent/error_classifier.py` (37). The
dominant codes are `arg-type` (223), `assignment` (115) and `no-any-return`
(108).

**Evidence.** `pyproject.toml` declares `files = ["src/agent/", "src/spark_cli/"]`
as the strict-adoption scope. Running it now gives 589 errors in 56 files of 111
checked. The declared gate does not hold, and nothing in CI runs it. Sample
errors in `web_server.py` (lines 10590, 10591, 11137, 11138) are `Any | None`
values passed where `str` is required, which is the exact class of bug that
reaches users as a 500 response.

**Fix.** Fix the errors per module, starting with `src/agent/` since it is the
smaller half. Once a module is clean, add it to a `mypy` CI job so it cannot
regress.

**Estimate.** 1 week, spread over several PRs.

---

### 8. Move blocking calls off the event loop

- [x] Investigated — **no change needed. This finding was wrong.**

The original claim rested on a grep for `asyncio.to_thread` and
`run_in_executor` returning zero. That grep missed the module's own helper,
`_run_blocking` at `src/spark_cli/web_server.py:97`, which is exactly that
wrapper and is already used on the async paths.

Each of the 5 blocking calls was traced to its enclosing function, and all 5
are already off the event loop:

| Call | Enclosing function | Why it is safe |
| --- | --- | --- |
| `subprocess.run` x2 (git) | `_build_git_metadata` (sync) | Runs once at import (line 142), not per request |
| `time.sleep(0.05)` | `_wait_for_checkpoint_ready` (sync) | Sync-caller variant; the async twin `_await_checkpoint_ready` uses `_run_blocking` |
| `time.sleep(poll_interval)` | `_codex_full_login_worker` (sync) | Runs as a `threading.Thread` target (line 6031) |

**Lesson for the rest of this plan.** Grepping for a library's canonical name
is not proof of absence when a project wraps it. Confirm against the enclosing
function before reporting.

**Evidence.** `src/spark_cli/web_server.py` defines 132 `async def` functions.
It contains 5 synchronous blocking calls (`requests.*`, `time.sleep(...)`,
`subprocess.run(...)`) and zero uses of `asyncio.to_thread` or
`run_in_executor`. Any of those inside a coroutine stalls every other request,
including websocket streaming.

**Fix.** Locate each blocking call, confirm whether it is on a coroutine path,
and wrap it in `await asyncio.to_thread(...)`. Prefer `httpx.AsyncClient` over
`requests` since `httpx` is already a core dependency.

**Estimate.** Half a day, plus a load test to confirm.

---

### 9. Split the largest React components

- [ ] Reduce `api.ts` and `ChatPanel.tsx` below 800 lines each

**Evidence.** The web frontend is 48,587 lines. Two files dominate:
`src/spark_cli/web/src/lib/api.ts` at 3,052 lines and
`src/spark_cli/web/src/components/ChatPanel.tsx` at 2,047 lines. Five more files
are above 1,100 lines. `ChatPanel.tsx` is exactly the surface named in
`CLAUDE.md` as needing manual verification of loading, streaming, offline,
reconnect, and gateway-restart states, so its size directly raises the cost of
each release.

**Fix.** Split `api.ts` by domain, to mirror the backend router split in item 3.
Extract the message list, the streaming state machine, and the tool-call group
rendering out of `ChatPanel.tsx` into child components.

**Estimate.** 2 days. Verify against the running web UI, not only the types.

---

### 10. Add lint and type checks for the web frontend to CI

- [x] Run `eslint` and `tsc --noEmit` on pull requests
- [ ] Add the `e2e/` suite as a separate non-blocking job

**Done.** Added `.github/workflows/web-quality.yml`, which runs `npm run lint`,
`npx tsc --noEmit -p tsconfig.app.json`, and `npx vitest run`.

All three already passed locally, so this locks in a clean state rather than
fixing a broken one. The notable find is that the repo has a **vitest suite of
369 tests across 62 files** that no workflow ran.

**Evidence.** `eslint.config.js`, `tsconfig.app.json`, and `tsconfig.node.json`
exist and are configured. No workflow invokes them. `web-supply-chain.yml`
touches the `web/` directory but only checks dependency pinning and lockfile
drift, never the code. The e2e suite in `src/spark_cli/web/e2e` is also
unattended.

**Fix.** Extend `web-supply-chain.yml`, or add a `web-quality.yml`, that runs
`npm run lint` and `npx tsc --noEmit` on changes under
`src/spark_cli/web/src/**`. Add the e2e suite as a separate, non-blocking job
first, then promote it once it is stable.

**Estimate.** 2 to 3 hours for lint and types. Half a day more for e2e.

---

## Summary

| # | Item | Status | Remaining effort |
| --- | --- | --- | --- |
| 1 | Tests in CI | **Done** | — |
| 2 | Six undefined names | **Done** | — |
| 3 | Split `web_server.py` | Open | 3 days |
| 4 | Finish `run_agent` + `cli` splits | Open | 4 days |
| 5 | Widen CI ratchet | **Partly done** | 1 day for the ignore list |
| 6 | Log swallowed exceptions | Open | 3 days |
| 7 | `mypy` to zero | Open | 1 week |
| 8 | Unblock the event loop | **Withdrawn — false finding** | — |
| 9 | Split large React files | Open | 2 days |
| 10 | Frontend CI checks | **Done** | 0.5 day for e2e |

---

## Getting CI green

Turning the test job on took six iterations. Every failure except two was a
pre-existing dependency on the developer's machine, not a regression:

| Round | Failures | Cause |
| --- | --- | --- |
| 1 | 576 | The job installed `[dev]`; `workspace_routes` needs FastAPI from `[web]` |
| 2 | 8 | Credentials, macOS-only gates, 2s async timeouts |
| 3 | 4 | `conftest` deleted `OPENROUTER_API_KEY`, leaving an empty key |
| 4 | 1 | Diagnostics added to a CI-only web-turn failure |
| 5 | 2 | A missing `os` import (mine) and an agent built without credentials |
| 6 | **0** | Green |

Two of these were real user-facing bugs found only because CI runs on a clean
machine: the grep fallback and `@`-completion (item 2), and the credential
errors below.

**Verify on Linux locally, not by pushing.** Pushing to watch CI generated a
failure email per round. Use a container instead:

```bash
docker run --rm -v "$PWD":/w -w /w -e CI=true python:3.11-slim bash -c \
  'apt-get update -qq && apt-get install -y -qq git && pip install -q -e ".[dev,web]" \
   && python -m pytest tests/ -m "not slow" -q --timeout=60'
```

It is stricter than the runner (root, no systemd, no audio), so
`test_gateway_service`, `test_voice_mode` and the systemd probes fail there
but pass on CI. Treat those as container artifacts.

Both workflows now use a `concurrency` group with `cancel-in-progress`, and
`push` only fires on `main`. Previously each push ran the same commit twice.

### Credentials must not be required for providers you do not use

Reported during this work: a user signed in with a Codex subscription was told
to set `OPENAI-CODEX_API_KEY`. That variable is malformed (the code built it
with `str.upper()` alone, so any hyphenated provider produced a broken name)
and irrelevant, because Codex authenticates with `spark login`.

Fixed in `src/core/run_agent/__init__.py`:

- Providers that use a subscription login are listed in
  `_OAUTH_LOGIN_PROVIDERS` and told to run `spark login`.
- API-key providers get a correctly formed name (`z-ai` -> `Z_AI_API_KEY`).
- With no provider configured at all, the message no longer invents
  `AUTO_API_KEY`; it points at `spark setup`.
- The OpenRouter fallback now prefers an explicitly passed `api_key`. It was
  discarded whenever no `base_url` came with it, so a caller that did supply a
  key still got "Missing credentials".

### Known gap, not yet fixed

`test_backend_exception_publishes_turn_done_and_clears_active` is skipped on
CI. The turn publishes `chat.turn_done` with `result=None` and
`turn_outcome.status="completed"`, so a failed turn reports success.
`run_agent_task` catches `Exception`, but `asyncio.CancelledError` is a
`BaseException`, so a cancelled turn skips the handler while `finally` still
publishes "completed". It reproduces only on the CI runner. Worth fixing: it
means a user can see a turn end normally when it actually failed.

## Work completed

Branch `fix/plan-quality-gates`. Full fast suite green before and after:
**12,308 passed, 0 failed**.

### Pre-existing test failures fixed (blocking item 1)

`main` had 8 failing tests. All 8 reproduced serially, so none were xdist
flakes. CI could not be turned on until they were fixed.

**One real source bug:**

- `src/core/spark_state.py` declared `SCHEMA_VERSION = 11` while the migration
  ladder ran through v12 (`if current_version < 12` writes version 12). Every
  freshly initialized database therefore disagreed with the declared constant.
  Bumped to 12.

**Four environment-dependent or stale tests:**

- `test_browser_reliability.py` — the mocked navigation still ran the real
  `_is_safe_url`, which performs a live DNS lookup, so the test failed on any
  machine without network resolution of `a.example`. `_is_safe_url` is now
  patched.
- `test_tool_facades.py` — asserted a `web` facade exists, but `web_search`
  only registers when `EXA_API_KEY` is set, so the test passed only on
  machines holding that credential. Now skips when the facade is absent.
- `test_web_server.py::test_available_models_codex_is_strict` — `source` gained
  a third legitimate value, `"cache"`, which the test's allowed set predated.
  The `gpt-5.6-sol` exclusion was also scoped to `offline-fallback`, since
  `cache` is a real account catalog that may list any model.
- `test_web_server.py::test_skills_list_includes_disabled_skills` — compared
  the whole `/api/skills` payload by exact equality, so it broke when unrelated
  fields were added. Now compares only the 8 keys the test is about.

### Regression test added

`tests/spark_cli/test_path_completion.py::TestContextCompletion` covers the
bare-`@` CLI completion path. Verified to fail with `NameError` against the
pre-fix code, then pass after.

### Unenforced test suites discovered

Neither of these was run by any workflow before this branch:

- Python: 12,308 fast tests
- Frontend: 369 vitest tests across 62 files

Both now run in CI. `eslint` and `tsc --noEmit` were also already clean and
unenforced, so `web-quality.yml` locks in a passing state rather than fixing a
broken one.
