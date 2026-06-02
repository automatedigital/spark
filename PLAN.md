# Spark — Drastic Improvement Plan

Goal: make Spark **excellent and trustworthy** — fix what's broken, pay down the
worst structural debt, and remove dead weight — while landing a few high-leverage
new wins. Mostly polish + hardening, with targeted net-new.

Grounded in a codebase audit + a grilling session (2026-06-01). Decisions locked:

- **Balanced** across the three axes: self-improvement, codebase debt, webui.
- **Two separate memory mechanisms** (see [CONTEXT.md](CONTEXT.md)):
  - **Dream** = heavy synthesis pass, **manual/scheduled only** (`/dream` or cron).
    Must NOT run at session end. Currently *broken* (6 failing tests) — repair it.
  - **Auto-memory** = lightweight, **always-on** at session end. Auto-updates
    **MEMORY.md** *and* **holographic memory** with no user action. This is the
    "gets smarter over time" default. Holographic `auto_extract` exists but is off
    by default; MEMORY.md auto-distillation doesn't exist yet — both are net-new work.
- **Split both** monoliths (`cli.py`, `run_agent.py`) — with a prompt-caching
  golden-test guardrail (see [ADR-0001](docs/adr/0001-preserve-prompt-caching-while-splitting-run-agent.md)).
- **Chat is canonical**; `WorkspacePage`/`ConversationsPage`/`ConnectorsPage` are
  dead — delete. (See [CONTEXT.md](CONTEXT.md).)
- **Mostly polish + targeted new** (e.g. `/learnings` review surface, skill telemetry).

Process: each phase is its own **feature branch → PR** (never push to main). Check
off items in this file the moment they're done + verified, not batched. Run
`ruff check src/` and the relevant tests before each PR.

Baseline at audit: **29 failing tests** (fast subset), 11,314 passing. Ruff clean.

---

## Phase 0 — Stop the bleeding (tests green) — *prerequisite gate*

No refactor or feature work starts until the suite is trustworthy. A red baseline
makes every later "did I break it?" question unanswerable.

> **Triage outcome (2026-06-01):** The "29 failures" were an **interpreter
> artifact** — measured under anaconda Python instead of the project's `.venv`.
> Under `.venv` the **default suite (`pytest tests/`) is green** (11,247 passed),
> and Dream / config-env / web_server / Discord-voice all pass. The *only* genuine
> failures were **3 Home Assistant integration tests** (excluded from the default
> suite by `addopts = -m 'not integration'`). Two distinct real issues surfaced and
> were fixed; one new pre-existing issue (flakiness) was found and recorded below.

- [x] Triage the failing tests; categorize each. **Verdict:** 26 of 29 were
      environment-only (wrong interpreter); 3 were real (HA integration — 1 stale
      test, 2 a real `ws_close` timeout stall).
- [x] ~~Fix Dream~~ — **not broken.** `tests/core/test_dream.py` passes 14/14 under
      `.venv`. Failure was an anaconda artifact. No code change needed.
- [x] ~~Fix `test_config_env_expansion.py` / `test_web_server.py` / Discord
      `test_voice_channel_flow.py`~~ — **not broken** under `.venv`; all pass. No
      change needed.
- [x] Fix `tests/integration/test_ha_integration.py` — **2 real fixes landed:**
      (1) `homeassistant.py` passed a bare `timeout=30` float to `ws_connect`, which
      current aiohttp maps to the *ws-close* timeout → 30s stall on disconnect; now
      uses `aiohttp.ClientWSTimeout(ws_close=10.0)`. (2) `test_event_received_and_
      forwarded` was stale (predates event filtering) — added `watch_all=True`.
      Result: **14/14 HA integration tests pass.**
- [x] Run the **full** default suite — **11,247 passed, 150 skipped, 0 deterministic
      failures.** Baseline is green.
- [x] **(New finding) Stabilize intermittent xdist flakiness.** Root cause: the E2E
      approval tests (`TestBlockingApprovalE2E`) spawn real threads with tight
      2.5–5s waits that starve under 12-worker CPU contention (`notified`/`results`
      empty before the deadline). **Fix:** widened the thread-wait windows
      (poll loops 2.5s→10s, `join`/deadline 5s→20s); they return early in the happy
      path, so the suite isn't slower. **Full suite now green 3/3 consecutive runs**
      (11,248 passed).
      - **Rejected approach — serial marker via xdist `loadgroup`:** wiring the
        existing `serial` marker through `--dist loadgroup` (+ a `tryfirst` conftest
        hook) *did* correctly pin serial tests to one worker, but switching the global
        dist mode destabilized the **whole** suite — it changed distribution for all
        11k tests and unmasked latent cross-test contamination (module reloads,
        env-var and global-config bleed), producing 9–18 failures vs. the 0–1 of
        default `load`. Net-negative; reverted. Recorded here so it isn't retried.

---

## Phase 1 — Cut the dead weight (webui) — *low risk, high signal*

Delete the stale duplicate surfaces. Confirmed orphaned (imported nowhere):

- [x] Delete `src/spark_cli/web/src/pages/WorkspacePage.tsx` (2,209 LOC stale
      duplicate of `ChatPage`).
- [x] Delete `src/spark_cli/web/src/pages/ConversationsPage.tsx` and
      `ConnectorsPage.tsx` (orphaned). All three had **0 external references**.
- [x] Checked for dangling imports — **none.** The orphans imported only shared
      components (`ChatPanel`, `ui/*`, `chat/*`, hooks, `lib/api`) that `ChatPage`
      and other live pages still use. Nothing became unreferenced.
- [x] `npm run build` (tsc + vite) — **clean** (`tsc -b` passed → no dangling refs;
      2,077 modules transformed). Note: `eslint .` has ~13.7K *pre-existing* errors
      (separate lint debt, tracked for a later phase); the deletions added none.
      Restored the gitignored `web_dist/` build artifacts so the commit is source-only.
- [x] Verified via preview tools: dashboard loads, all nav renders (Chat / Files /
      Tasks / Schedule / Skills + Settings), Chat surface intact. Only console errors
      are `500`s from the absent backend (vite-only preview) — unrelated to deletions.

---

## Phase 2 — Memory that maintains itself — *targeted new*

Two distinct mechanisms, kept strictly separate (see [CONTEXT.md](CONTEXT.md)).

### 2a — Auto-memory (always-on, the headline behavior)

The "gets smarter over time" promise lives here, not in Dream. Runs at session end,
cheap, no user action.

- [x] **Auto-update holographic memory by default.** Flipped the holographic
      provider's `auto_extract` default `false`→`true` in
      `plugins/memory/holographic/__init__.py` (the `on_session_end` `.get` default +
      schema + docstring), with robust bool/string coercion. The holographic provider
      is already the default `memory.provider`, so no config-migration needed — the
      default simply changes when unset. `on_session_end`→`_auto_extract_facts` now
      fires on every normal session; `auto_extract: false` opts out. Caching-safe
      (session-end only). 5 new tests in `test_holographic_auto_extract.py`, all pass.
- [x] **Auto-update MEMORY.md** — **already exists** (premise was wrong, like Phase 0).
      `AIAgent.flush_memories()` (`run_agent.py:6650`) gives the model one
      auxiliary-model turn to persist durable memory at session end, **gated by turn
      count** (`memory.flush_min_turns`, default 6 — exactly the chosen design). It's
      wired at CLI exit (`cli.py:11981`), `/reset`, pre-compression, and gateway
      session expiry; the `memory` tool is in the core toolset (default-on) and
      `memory_enabled` defaults `True`. Mature feature with 5 existing test files. No
      new build needed — would have duplicated/conflicted with it.
- [x] Session-end hook robustness — **already handled.** The CLI-exit flush
      (`cli.py:11979`) catches `(Exception, KeyboardInterrupt)` so it runs on clean
      AND interrupted exit; the gateway path has stale-session guards
      (`test_flush_memory_stale_guard.py`). Uses the auxiliary (cheap) client.
- [x] **Caching safety** — **satisfied by design.** `flush_memories` appends a flush
      message, makes one call, then strips every flush artifact back off the message
      list (`run_agent.py:6802`, sentinel-matched), so the conversation/cache is
      unchanged. The new holographic auto-extract runs only in `on_session_end`. Fact
      retrieval into the prompt is untouched.
- [x] Tests — holographic default-on covered by the 5 new tests; MEMORY.md flush
      covered by 5 pre-existing files (`test_flush_memories_codex.py`,
      `test_flush_memory_stale_guard.py`, `test_cli_new_session.py`, etc.).

### 2b — Dream (manual/scheduled only)

Repair the existing pass and make it visible — but it stays explicitly invoked.

- [x] **Fix Dream / confirm it runs** — Dream was never broken (the Phase 0 "6
      failures" were an interpreter artifact). `test_dream.py` passes 16/16: dry-run,
      wiki-entry write, `dream`-category fact insertion, consolidation, stale-queueing.
- [x] **Guard against implicit runs.** Audited all callers of `run_dream` /
      `scheduler_tick`: the **only** triggers are the `/dream` command (`cli.py:6008`,
      `gateway/run.py:6062`) and `scheduler_tick()` from the cron loop
      (`cron/scheduler.py:924`), itself gated by an opt-in daily schedule that is
      **disabled by default**. No session-end path touches Dream. Added 2 guard tests:
      `test_dream_disabled_by_default` and `test_memory_session_end_does_not_invoke_dream`.
- [x] **MEMORY.md compaction** — Dream now reads MEMORY.md (`_gather_memory_md`),
      feeds it to the synthesis LLM as a 4th input, and the model proposes a deduped/
      consolidated rewrite (`memory_compaction` schema field). **Never a silent
      rewrite** — the proposal + a before/after unified diff (`_unified_memory_diff`)
      are written into the Dream wiki entry for review; MEMORY.md on disk is untouched.
      3 new tests (incl. one asserting MEMORY.md is byte-unchanged after a proposal).
- [x] **`/learnings` review surface** — built across all three surfaces.
      Backend API in `dream.py` (`get_pending_removals`, `resolve_removal`,
      `list_recent_dreams`). **CLI** `/learnings` (interactive keep/remove/skip on
      flagged facts) via the 3-file rule (`commands.py` + `cli.py` + gateway). The
      **gateway** and **web dashboard** (command palette, `_web_cmd_learnings`)
      surfaces are read-only — they show recent dreams + the pending queue; removals
      are confirmed from the CLI where the prompt lives. Alias `/learned`. Unlike
      `/dream review` (display-only), this actually resolves the queue.
- [x] **Skill-usage telemetry** — the per-session counter **already exists**
      (`spark_state.py` records `tool_name`/`tool_call_count`; `agent/insights.py`
      `InsightsEngine._get_tool_usage` aggregates it; `/api/analytics/skills` serves
      it). So no redundant store/dispatch-hook/opt-out was built — the missing piece
      was *feeding it to Dream*. Added `_gather_tool_usage` + `_format_tool_usage` to
      `dream.py` (reusing `InsightsEngine`, best-effort/non-fatal) and a third
      "TOOL / SKILL USAGE" block in the synthesis prompt so Dream grounds insights in
      the user's real workflow. Tool names only (no PII). 4 new tests; 20/20 dream
      tests pass.
- [x] Tests for `/learnings`, telemetry, compaction, and the "Dream never
      auto-fires" guard — all in `tests/core/test_dream.py` (14 → **28 tests**).
      Dream docs updated in `docs/cli/slash-commands.md` (new inputs, MEMORY.md
      compaction, `/learnings`, and an Auto-memory section).

---

## Phase 3 — Split `cli.py` (12.3K → `core/cli/` package) — *medium risk*

Mechanical decomposition, no behavior change. `SparkCLI` stays the public class.

Staged extraction, full suite green after each commit. `SparkCLI` stays the public
class; `core.cli` stays the import + monkeypatch namespace via re-export.

- [x] **Stage 1** — `core/cli.py` → `core/cli/__init__.py` (package skeleton). Same
      namespace, so all `from core.cli import X` + the ~47 test files patching
      `core.cli.X` keep working. Only 2 source-inspection tests updated (hardcoded path).
- [x] **Stage 2** — worktree helpers (~383 lines) → `core/cli/worktree.py`. Shared
      `_active_worktree` global handled via a `set_active_worktree()` accessor.
- [x] **Stage 3** — attachment/file-drop helpers (~247 lines) → `core/cli/attachments.py`
      (incl. `_IMAGE_EXTENSIONS`). `os.path` patches still work (shared `os` module).
- [x] **Stage 4** — config/arg parsers (~116 lines) → `core/cli/parsing.py`. Broadened
      the `sys.modules` wipe in `test_cli_provider_resolution` to clear `core.cli.*`.
- [x] **Stage 5** — ANSI/render helpers (`_cprint`, `_SkinAwareAnsi`, `_ACCENT`/`_DIM`,
      ~88 lines) → `core/cli/render.py`. `_cprint` has no `CLI_CONFIG` coupling, so
      callers staying in `__init__` keep `core.cli._cprint` patches working.
- [x] **Stage 6 — de-globalize `CLI_CONFIG`** → `core/cli/config_state.py` (with
      `load_cli_config`/`save_config_value`, ~425 lines). The shared config module
      mixins import directly; re-exported so existing patches keep working.
- [x] **Stages 7–19 — split the 167-method `SparkCLI` class into 14 concern-based
      mixins**, combined via inheritance (`SparkCLI(_CommandHandlersMixin, …)`):
      `commands_mixin` (slash handlers), `display_mixin` (commands+display),
      `streaming_mixin`, `status_bar_mixin`, `voice_mixin`, `callbacks_mixin`,
      `tui_mixin`, `model_mixin`, `agent_setup_mixin`, `info_mixin`, `session_ops_mixin`.
      Each mixin imports its helpers from `render`/`config_state`/etc.; the heavily
      patched `_cprint`/`save_config_value`/`CLI_CONFIG` test targets were redirected to
      the owning mixin module (~12 test files). Core orchestration (`__init__`,
      `process_command`, `chat`, `run`, `main`) stays in `__init__.py`.
- [x] **Smoke-tested**: `SparkCLI()` constructs, all mixin methods resolve via the MRO,
      `/help` dispatches, and `spark version` runs (RC 0). **mypy:** `core/` is *excluded*
      from the mypy config (`exclude = [… "src/core/"]`), so the split was never in mypy
      scope; the in-scope packages' pre-existing errors are unchanged by it.

**Result: `__init__.py` 12,328 → 4,086 lines (67% reduction); 14 cohesive submodules.**
Full suite green (**11,267 passed**) after every one of the 19 stages. `core.cli` stays
the public import + monkeypatch namespace via re-export throughout.

---

## Phase 4 — Split `run_agent.py` (11K → `core/run_agent/` package) — *highest risk*

Governed by **[ADR-0001](docs/adr/0001-preserve-prompt-caching-while-splitting-run-agent.md)**.
Do this last; it touches the caching-sensitive loop.

- [x] **First, author the caching-invariant golden test** (ADR-0001 §1): captured
      the exact serialized request (system blocks, `cache_control` positions, tool
      schema order) for a representative conversation; asserts byte-exact equality.
      Landed in `tests/run_agent/test_caching_golden.py` (3 tests): the Anthropic
      `system_and_3` breakpoints + tool order, the Codex Responses payload
      (instructions/input order/`prompt_cache_key`), and a defense-in-depth
      assertion that breakpoints never exceed Anthropic's max of 4. Gates every
      commit in this phase.
- [x] If the golden test is too entangled to write cheaply → **stop**. **Verdict:
      not entangled.** The serialization is reachable through the existing
      deterministic `_build_api_kwargs` + `apply_anthropic_cache_control` seam with
      pinned tools/session_id, so the golden was cheap to write. Proceeding.
- [ ] Extract into `core/run_agent/` submodules; isolate caching-sensitive code
      (system-prompt build + `cache_control` placement) into one named module
      (e.g. `run_agent/prompt_cache.py`). Re-export `AIAgent`.
  - [x] **Stage 1** — `core/run_agent.py` → `core/run_agent/__init__.py` (package
        skeleton). Same `core.run_agent` namespace, so all `from core.run_agent
        import X` and the ~30 test files patching `core.run_agent.X` keep working.
        Fixed the dev-fallback `.env` resolution (`Path(__file__).parent` →
        `.parent.parent`) to still point at `src/core/.env`, and updated the one
        source-inspection test (`test_voice_cli_integration.py`) to the new path.
        Golden + run_agent suite green (834 passed).
  - [x] **Stage 2** — tool-batch parallelism heuristics (constants +
        `_is_destructive_command`/`_should_parallelize_tool_batch`/
        `_extract_parallel_scope_path`/`_paths_overlap`, ~120 lines) →
        `run_agent/parallelism.py`. Pure stdlib, zero `AIAgent` coupling.
        Re-exported into `__init__` via redundant-alias form so the tests'
        `from core.run_agent import _paths_overlap` and the loop's bare-name
        references keep working. Zero new lint debt (lint profile identical to
        Stage 1). `tests/run_agent/` green (755 passed).
  - [x] **Stage 3** — payload sanitization (surrogate + non-ASCII scrubbing:
        `_SURROGATE_RE`, `_sanitize_surrogates`, `_sanitize_messages_surrogates`,
        `_strip_non_ascii`, `_sanitize_messages_non_ascii`, `_sanitize_tools_non_ascii`,
        `_sanitize_structure_non_ascii`, ~155 lines) → `run_agent/sanitize.py`. Pure,
        no `AIAgent` coupling. Re-exported via redundant-alias (also consumed by
        `core/cli` via `from core.run_agent import _sanitize_surrogates`). Lint
        profile identical to Stage 2; `core.cli` import verified. `tests/run_agent/`
        green (755 passed).
- [ ] No behavioral edits — relocation only. Golden test + full suite green per commit.
- [ ] Manual cost-sanity check: run a multi-turn session, confirm cache-read tokens
      appear as before (no cache-miss regression).

---

## Phase 5 — Webui & app polish — *visible quality*

After the structural work, a focused UX pass on the surfaces users actually touch.

- [ ] Audit the Settings sub-pages (`Status/Analytics/Admin/Logs/Env/Config/
      Appearance/Updates`) — confirm each renders, loads data, and has no console
      errors (preview tools). Fix the broken ones; note any kept intentionally bare.
- [ ] Chat surface polish: verify file tree + terminal + multi-thread switching all
      work post-Workspace-deletion; tighten obvious rough edges found during audit.
- [ ] Onboarding wizard pass — confirm the name/skills steps (recent work) flow
      cleanly on a fresh `SPARK_HOME`.
- [ ] Accessibility/consistency sweep on `ui/` primitives if cheap (focus states,
      keyboard nav for the command palette).

---

## Phase 6 — Docs & housekeeping — *close the loop*

- [ ] Refresh `STRUCTURE.md` + `AGENTS.md` to reflect the new `core/cli/` and
      `core/run_agent/` packages.
- [ ] Update `README` "self-improving" claims to point at the now-working Dream +
      `/learnings` surface (make the marketing match reality).
- [ ] Update the `project_spark_state` memory: Dream is real, monoliths split,
      orphans deleted, true test baseline.
- [ ] Triage the 401 files carrying `TODO/FIXME` — not to fix all, but to convert
      the few real ones into tracked issues and delete stale ones.

---

## Sequencing rationale

0 → 1 → 2 → 3 → 4 → 5 → 6. Tests green **first** (everything downstream depends on a
trustworthy suite). Dead-code deletion next (free risk reduction). Land Auto-memory
+ repair Dream (Phase 2) before the scary refactors so the headline "gets smarter
over time" behavior works regardless of how far the splits get. `cli.py` before
`run_agent.py` (lower risk first, builds the refactor muscle). Polish + docs last,
once the foundation is solid.

Each phase is independently shippable — if appetite runs out after Phase 2, Spark is
already materially better (green tests, no dead code, self-maintaining MEMORY.md +
holographic memory, and a working manual Dream).
