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

- [ ] Delete `src/spark_cli/web/src/pages/WorkspacePage.tsx` (2,209 LOC stale
      duplicate of `ChatPage`).
- [ ] Delete `src/spark_cli/web/src/pages/ConversationsPage.tsx` and
      `ConnectorsPage.tsx` (orphaned).
- [ ] Grep for any now-unused imports/components/`lib/api` helpers left dangling by
      the deletions; remove them too (e.g. anything only `WorkspacePage` used).
- [ ] `npm run build` (in `src/spark_cli/web/`) + `eslint .` clean.
- [ ] Verify the dashboard still loads and Chat/Files/Kanban/Cron/Skills nav all
      render (preview tools — start server, snapshot, screenshot).

---

## Phase 2 — Memory that maintains itself — *targeted new*

Two distinct mechanisms, kept strictly separate (see [CONTEXT.md](CONTEXT.md)).

### 2a — Auto-memory (always-on, the headline behavior)

The "gets smarter over time" promise lives here, not in Dream. Runs at session end,
cheap, no user action.

- [ ] **Auto-update holographic memory by default.** Flip the holographic provider's
      `auto_extract` on by default (`config.py` `DEFAULT_CONFIG`, bump
      `_config_version` for migration). Verify `on_session_end` →
      `_auto_extract_facts` fires on a normal session. Keep an opt-out flag.
- [ ] **Auto-update MEMORY.md** (net-new — doesn't exist today). MEMORY.md currently
      only changes when the model explicitly calls the memory tool mid-conversation.
      Add a session-end distillation step that proposes/merges durable facts into
      MEMORY.md (dedup against existing entries; respect the memory-size limit in
      `memory_provider.py`). Write via `get_spark_home()`; never touch SOUL.md.
- [ ] Make the session-end hook robust: must run on clean exit AND interrupted exit
      (mirror the existing `on_session_end` safety-net path in `cli.py:12008`), must
      not block shutdown, must not raise. Cost-cheap (small/auxiliary model).
- [ ] **Caching safety:** Auto-memory must run strictly at/after session end — never
      mutate in-flight context, toolsets, or the system prompt mid-conversation
      (Critical Rule). Fact *retrieval* into the prompt is unchanged.
- [ ] Tests: auto-extract on by default writes facts; MEMORY.md distillation merges
      without duplicating; both SPARK_HOME-isolated and run on interrupted exit.

### 2b — Dream (manual/scheduled only)

Repair the existing pass and make it visible — but it stays explicitly invoked.

- [ ] **Fix Dream** (covered in Phase 0) and confirm `/dream` runs end-to-end:
      wiki entry + `dream`-category holographic facts written.
- [ ] **Guard against implicit runs.** Audit every caller of `run_dream` /
      `scheduler_tick`; confirm the only triggers are the `/dream` command and an
      explicit user schedule. Add a test asserting session end does NOT invoke Dream.
- [ ] **MEMORY.md compaction** (targeted new) — give Dream a pass that dedups and
      consolidates MEMORY.md, cleaning up the cruft Auto-memory (2a) appends over
      time. Heavy consolidation lives here, not in the per-session hook. Stale/merged
      entries route through the existing `pending-removals` confirm flow — never a
      silent rewrite of the curated file. Surface a before/after diff in the wiki entry.
- [ ] **`/learnings` review surface** (targeted new) — read-only TUI command +
      dashboard panel showing recent Dream syntheses and the `pending-removals`
      queue so users can see and confirm removals without digging into
      `~/.spark/dreams/`. (3-file slash-command rule: `commands.py` + `cli.py` +
      gateway handler.)
- [ ] **Skill-usage telemetry** (targeted new) — lightweight per-session counter of
      which skills/tools fire, feeding Dream's synthesis context. Store via
      `get_spark_home()`; no PII; opt-out flag.
- [ ] Tests for `/learnings`, telemetry, and the "Dream never auto-fires" guard.

---

## Phase 3 — Split `cli.py` (12.3K → `core/cli/` package) — *medium risk*

Mechanical decomposition, no behavior change. `SparkCLI` stays the public class.

- [ ] Map `cli.py` into cohesive seams: command dispatch, rendering/diff display,
      session lifecycle, input/prompt handling, slash-command handlers. Write the
      target module list in the PR before moving code.
- [ ] Extract into `core/cli/` submodules incrementally; keep `from core.cli import
      SparkCLI` working (re-export from `core/cli/__init__.py`).
- [ ] No logic edits during the move — pure relocation. Note the known pitfalls
      (no `\033[K` under `patch_stdout`; `curses` not `simple_term_menu`).
- [ ] Full suite green after each extraction commit; `mypy src/spark_cli/` clean.
- [ ] Smoke-test the live TUI (`spark`) — launch, run a slash command, edit a file,
      confirm diff rendering + spinner still work.

---

## Phase 4 — Split `run_agent.py` (11K → `core/run_agent/` package) — *highest risk*

Governed by **[ADR-0001](docs/adr/0001-preserve-prompt-caching-while-splitting-run-agent.md)**.
Do this last; it touches the caching-sensitive loop.

- [ ] **First, author the caching-invariant golden test** (ADR-0001 §1): capture
      the exact serialized request (system blocks, `cache_control` positions, tool
      schema order) for a representative conversation; assert byte-exact equality.
      This gates every commit in this phase.
- [ ] If the golden test is too entangled to write cheaply → **stop**, document
      why, and defer the split (per ADR consequences). Don't proceed blind.
- [ ] Extract into `core/run_agent/` submodules; isolate caching-sensitive code
      (system-prompt build + `cache_control` placement) into one named module
      (e.g. `run_agent/prompt_cache.py`). Re-export `AIAgent`.
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
