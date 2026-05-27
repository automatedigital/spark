# Tasks

## Bug Fixes

- [x] Fix missing import in `src/core/rl_cli.py` — `get_spark_home` is used on line 32 but never imported
  - [x] Add `from spark_constants import get_spark_home` before its first use

- [x] Fix loop-variable capture bug in `src/core/run_agent.py` — `_recover_from_stream_parts` closure captures `collected_output_items` by name instead of binding it (B023, lines ~4399–4407)
  - [x] Rebind `collected_output_items` as a default argument in the nested function signature: `def _recover_from_stream_parts(exc, _items=collected_output_items):`

- [x] Fix invalid `# noqa` directive in `src/gateway/platforms/discord.py:279` — bare `# noqa` without a code list produces a ruff warning
  - [x] Change to `# noqa: <code>` (inspect the line to pick the right code)

- [x] Fix F821 undefined names in plugin `__init__` files — `ContextEngine` and `MemoryProvider` are referenced in string annotations without being imported
  - [x] `src/plugins/context_engine/__init__.py:79` — add `from __future__ import annotations` or import `ContextEngine` under `TYPE_CHECKING`
  - [x] `src/plugins/memory/__init__.py:78` — same fix for `MemoryProvider`

## Type Annotation Fixes

- [x] Fix implicit `Optional` parameters in `src/agent/context_engine.py` (lines 73, 80) — mypy rejects `param: int = None` without `Optional[int]`
  - [x] Change `prompt_tokens: int = None` → `prompt_tokens: Optional[int] = None`
  - [x] Change `current_tokens: int = None` → `current_tokens: Optional[int] = None`

- [x] Fix implicit `Optional` in `src/agent/trajectory.py:31` — same pattern as context_engine
  - [x] Change `filename: str = None` → `filename: Optional[str] = None`

- [x] Fix implicit `Optional` in `src/agent/anthropic_adapter.py:243`
  - [x] Change `base_url: str = None` → `base_url: Optional[str] = None`

## Auto-fixable Lint Cleanup

- [x] Remove unused imports (F401) across the codebase — run `ruff check src/ --select F401 --fix`

- [x] Fix f-strings missing placeholders (F541, 58 occurrences) — run `ruff check src/ --select F541 --fix`

- [x] Fix invalid escape sequences (W605, 6 occurrences) — run `ruff check src/ --select W605 --fix`
