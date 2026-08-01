"""Central registry for all spark-agent tools.

Each tool file calls ``registry.register()`` at module level to declare its
schema, handler, toolset membership, and availability check.  ``model_tools.py``
queries the registry instead of maintaining its own parallel data structures.

Import chain (circular-import safe):
    tools/registry.py  (no imports from model_tools or tool files)
           ^
    tools/*.py  (import from tools.registry at module level)
           ^
    model_tools.py  (imports tools.registry + all tool modules)
           ^
    run_agent.py, cli.py, batch_runner.py, etc.
"""

import json
import importlib
import logging
import threading
from collections.abc import Callable

from tools.effects import NETWORK, ToolEffects, infer_tool_effects

logger = logging.getLogger(__name__)


class ToolEntry:
    """Metadata for a single registered tool."""

    __slots__ = (
        "name", "toolset", "schema", "handler", "check_fn",
        "requires_env", "is_async", "description", "emoji",
        "max_result_size_chars", "normalize", "screen", "handler_module",
        "check_spec", "extra", "effects",
    )

    def __init__(self, name, toolset, schema, handler, check_fn,
                 requires_env, is_async, description, emoji,
                 max_result_size_chars=None, normalize=True, screen=True,
                 handler_module=None, check_spec=None, extra=None, effects=None):
        self.name = name
        self.toolset = toolset
        self.schema = schema
        self.handler = handler
        self.check_fn = check_fn
        self.requires_env = requires_env
        self.is_async = is_async
        self.description = description
        self.emoji = emoji
        self.max_result_size_chars = max_result_size_chars
        self.normalize = normalize
        self.screen = screen
        self.handler_module = handler_module
        self.check_spec = check_spec
        self.extra = extra
        self.effects = effects or infer_tool_effects(name, toolset)


class ToolRegistry:
    """Singleton registry that collects tool schemas + handlers from tool files."""

    def __init__(self):
        self._tools: dict[str, ToolEntry] = {}
        self._toolset_checks: dict[str, Callable] = {}
        # MCP dynamic refresh can mutate the registry while other threads are
        # reading tool metadata, so keep mutations serialized and readers on
        # stable snapshots.
        self._lock = threading.RLock()
        self._module_locks: dict[str, threading.Lock] = {}
        self._module_load_counts: dict[str, int] = {}

    def _snapshot_state(self) -> tuple[list[ToolEntry], dict[str, Callable]]:
        """Return a coherent snapshot of registry entries and toolset checks."""
        with self._lock:
            return list(self._tools.values()), dict(self._toolset_checks)

    def _snapshot_entries(self) -> list[ToolEntry]:
        """Return a stable snapshot of registered tool entries."""
        return self._snapshot_state()[0]

    def _snapshot_toolset_checks(self) -> dict[str, Callable]:
        """Return a stable snapshot of toolset availability checks."""
        return self._snapshot_state()[1]

    def _evaluate_toolset_check(self, toolset: str, check: Callable | None) -> bool:
        """Run a toolset check, treating missing or failing checks as unavailable/available."""
        if not check:
            return True
        try:
            return bool(check())
        except Exception:
            logger.debug("Toolset %s check raised; marking unavailable", toolset)
            return False

    def get_entry(self, name: str) -> ToolEntry | None:
        """Return a registered tool entry by name, or None."""
        with self._lock:
            return self._tools.get(name)

    def get_registered_toolset_names(self) -> list[str]:
        """Return sorted unique toolset names present in the registry."""
        return sorted({entry.toolset for entry in self._snapshot_entries()})

    def get_tool_names_for_toolset(self, toolset: str) -> list[str]:
        """Return sorted tool names registered under a given toolset."""
        return sorted(
            entry.name for entry in self._snapshot_entries()
            if entry.toolset == toolset
        )

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        name: str,
        toolset: str,
        schema: dict,
        handler: Callable,
        check_fn: Callable = None,
        requires_env: list = None,
        is_async: bool = False,
        description: str = "",
        emoji: str = "",
        max_result_size_chars: int | float | None = None,
        normalize: bool = True,
        screen: bool = True,
        effects: ToolEffects | None = None,
    ):
        """Register a tool.  Called at module-import time by each tool file."""
        with self._lock:
            existing = self._tools.get(name)
            if existing and existing.toolset != toolset:
                logger.warning(
                    "Tool name collision: '%s' (toolset '%s') is being "
                    "overwritten by toolset '%s'",
                    name, existing.toolset, toolset,
                )
            self._tools[name] = ToolEntry(
                name=name,
                toolset=toolset,
                schema=schema,
                handler=handler,
                check_fn=check_fn,
                requires_env=requires_env or [],
                is_async=is_async,
                description=description or schema.get("description", ""),
                emoji=emoji,
                max_result_size_chars=max_result_size_chars,
                normalize=normalize,
                screen=screen,
                handler_module=getattr(handler, "__module__", None),
                effects=effects,
            )
            if check_fn and toolset not in self._toolset_checks:
                self._toolset_checks[toolset] = check_fn

    def register_manifest(self, entries: list[dict]) -> None:
        """Register schema-only built-ins without importing their handlers.

        A real module registration always wins. This makes the operation safe
        when a feature module was imported directly before ``model_tools``.
        """
        with self._lock:
            for item in entries:
                existing = self._tools.get(item["name"])
                if existing is not None and existing.handler is not None:
                    continue
                max_size = item.get("max_result_size_chars")
                if max_size == "infinity":
                    max_size = float("inf")
                self._tools[item["name"]] = ToolEntry(
                    name=item["name"],
                    toolset=item["toolset"],
                    schema=item["schema"],
                    handler=None,
                    check_fn=None,
                    requires_env=item.get("requires_env") or [],
                    is_async=bool(item.get("is_async")),
                    description=item.get("description") or item["schema"].get("description", ""),
                    emoji=item.get("emoji") or "",
                    max_result_size_chars=max_size,
                    normalize=item.get("normalize", True),
                    screen=item.get("screen", True),
                    handler_module=item["handler_module"],
                    check_spec=item.get("check_spec"),
                    extra=item.get("extra"),
                )

    def _entry_available(self, entry: ToolEntry) -> bool:
        if entry.check_fn is not None:
            return self._evaluate_toolset_check(entry.toolset, entry.check_fn)
        if entry.check_spec:
            from tools.lazy_availability import evaluate_check

            return evaluate_check(entry.check_spec, entry.requires_env)
        return True

    def _load_handler(self, name: str) -> ToolEntry:
        """Load one built-in handler module exactly once, safely across threads."""
        entry = self.get_entry(name)
        if entry is None:
            raise LookupError(f"Unknown tool: {name}")
        if entry.handler is not None:
            return entry
        module_name = entry.handler_module
        if not module_name:
            raise RuntimeError(f"Tool {name!r} has no handler module in the manifest")
        with self._lock:
            module_lock = self._module_locks.setdefault(module_name, threading.Lock())
        with module_lock:
            current = self.get_entry(name)
            if current is not None and current.handler is not None:
                return current
            try:
                importlib.import_module(module_name)
            except ModuleNotFoundError as exc:
                missing = exc.name or "an optional dependency"
                extra = f" Install Spark with the {entry.extra!r} extra." if entry.extra else ""
                raise RuntimeError(
                    f"Tool {name!r} requires optional dependency {missing!r}.{extra}"
                ) from exc
            with self._lock:
                self._module_load_counts[module_name] = self._module_load_counts.get(module_name, 0) + 1
            loaded = self.get_entry(name)
            if loaded is None or loaded.handler is None:
                raise RuntimeError(
                    f"Handler module {module_name!r} did not register manifest tool {name!r}"
                )
            return loaded

    def get_module_load_count(self, module_name: str) -> int:
        """Return successful first-use imports; exposed for diagnostics/tests."""
        with self._lock:
            return self._module_load_counts.get(module_name, 0)

    def deregister(self, name: str) -> None:
        """Remove a tool from the registry.

        Also cleans up the toolset check if no other tools remain in the
        same toolset.  Used by MCP dynamic tool discovery to nuke-and-repave
        when a server sends ``notifications/tools/list_changed``.
        """
        with self._lock:
            entry = self._tools.pop(name, None)
            if entry is None:
                return
            # Drop the toolset check if this was the last tool in that toolset
            if entry.toolset in self._toolset_checks and not any(
                e.toolset == entry.toolset for e in self._tools.values()
            ):
                self._toolset_checks.pop(entry.toolset, None)
        logger.debug("Deregistered tool: %s", name)

    # ------------------------------------------------------------------
    # Schema retrieval
    # ------------------------------------------------------------------

    def get_definitions(self, tool_names: set[str], quiet: bool = False) -> list[dict]:
        """Return OpenAI-format tool schemas for the requested tool names.

        Only tools whose ``check_fn()`` returns True (or have no check_fn)
        are included.
        """
        result = []
        check_results: dict[Callable, bool] = {}
        entries_by_name = {entry.name: entry for entry in self._snapshot_entries()}
        for name in sorted(tool_names):
            entry = entries_by_name.get(name)
            if not entry:
                continue
            if entry.check_fn:
                if entry.check_fn not in check_results:
                    try:
                        check_results[entry.check_fn] = bool(entry.check_fn())
                    except Exception:
                        check_results[entry.check_fn] = False
                        if not quiet:
                            logger.debug("Tool %s check raised; skipping", name)
                if not check_results[entry.check_fn]:
                    if not quiet:
                        logger.debug("Tool %s unavailable (check failed)", name)
                    continue
            elif entry.check_spec and not self._entry_available(entry):
                if not quiet:
                    logger.debug("Tool %s unavailable (manifest check failed)", name)
                continue
            # Ensure schema always has a "name" field — use entry.name as fallback
            schema_with_name = {**entry.schema, "name": entry.name}
            result.append({"type": "function", "function": schema_with_name})
        return result

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def dispatch(self, name: str, args: dict, **kwargs) -> str:
        """Execute a tool handler by name.

        * Async handlers are bridged automatically via ``_run_async()``.
        * All exceptions are caught and returned as ``{"error": "..."}``
          for consistent error format.
        * Output is passed through the TokenJuice compaction + prompt-injection
          screening pipeline when those layers are enabled in config.
        """
        entry = self.get_entry(name)
        if not entry:
            return json.dumps({"error": f"Unknown tool: {name}"})
        try:
            if entry.handler is None:
                entry = self._load_handler(name)
            if entry.is_async:
                from core.model_tools import _run_async
                raw = _run_async(entry.handler(args, **kwargs))
            elif NETWORK in entry.effects.effects and not threading.current_thread().name.startswith(
                "spark-tool-worker"
            ):
                # Keep the synchronous registry API while moving blocking
                # network handlers (web, Skills Hub, connectors, HA, MCP) to
                # the bounded process tool pool.  Scheduler workers already
                # run in that pool and execute directly to avoid nested waits.
                from core.async_runtime import get_async_runtime

                raw = get_async_runtime().submit_tool(entry.handler, args, **kwargs).result()
            else:
                raw = entry.handler(args, **kwargs)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as e:
            logger.exception("Tool %s dispatch error: %s", name, e)
            return json.dumps({"error": f"Tool execution failed: {type(e).__name__}: {e}"})

        return _post_process(name, entry, raw, args)

    # ------------------------------------------------------------------
    # Query helpers  (replace redundant dicts in model_tools.py)
    # ------------------------------------------------------------------

    def get_max_result_size(self, name: str, default: int | float | None = None) -> int | float:
        """Return per-tool max result size, or *default* (or global default)."""
        entry = self.get_entry(name)
        if entry and entry.max_result_size_chars is not None:
            return entry.max_result_size_chars
        if default is not None:
            return default
        from tools.budget_config import DEFAULT_RESULT_SIZE_CHARS
        return DEFAULT_RESULT_SIZE_CHARS

    def get_all_tool_names(self) -> list[str]:
        """Return sorted list of all registered tool names."""
        return sorted(entry.name for entry in self._snapshot_entries())

    def get_schema(self, name: str) -> dict | None:
        """Return a tool's raw schema dict, bypassing check_fn filtering.

        Useful for token estimation and introspection where availability
        doesn't matter — only the schema content does.
        """
        entry = self.get_entry(name)
        return entry.schema if entry else None

    def get_toolset_for_tool(self, name: str) -> str | None:
        """Return the toolset a tool belongs to, or None."""
        entry = self.get_entry(name)
        return entry.toolset if entry else None

    def get_emoji(self, name: str, default: str = "⚡") -> str:
        """Return the emoji for a tool, or *default* if unset."""
        entry = self.get_entry(name)
        return (entry.emoji if entry and entry.emoji else default)

    def get_effects(self, name: str) -> ToolEffects:
        """Return the complete scheduling contract for *name*.

        Unknown names receive a strict global contract so callers never turn
        missing metadata into unsafe parallelism.
        """
        entry = self.get_entry(name)
        if entry is not None:
            return entry.effects
        return infer_tool_effects(name, "unknown")

    def get_tool_to_toolset_map(self) -> dict[str, str]:
        """Return ``{tool_name: toolset_name}`` for every registered tool."""
        return {entry.name: entry.toolset for entry in self._snapshot_entries()}

    def is_toolset_available(self, toolset: str) -> bool:
        """Check if a toolset's requirements are met.

        Returns False (rather than crashing) when the check function raises
        an unexpected exception (e.g. network error, missing import, bad config).
        """
        with self._lock:
            check = self._toolset_checks.get(toolset)
            entries = [entry for entry in self._tools.values() if entry.toolset == toolset]
        if check is not None:
            return self._evaluate_toolset_check(toolset, check)
        return any(self._entry_available(entry) for entry in entries)

    def check_toolset_requirements(self) -> dict[str, bool]:
        """Return ``{toolset: available_bool}`` for every toolset."""
        entries, toolset_checks = self._snapshot_state()
        toolsets = sorted({entry.toolset for entry in entries})
        return {
            toolset: (
                self._evaluate_toolset_check(toolset, toolset_checks.get(toolset))
                if toolset_checks.get(toolset) is not None
                else any(self._entry_available(entry) for entry in entries if entry.toolset == toolset)
            )
            for toolset in toolsets
        }

    def get_available_toolsets(self) -> dict[str, dict]:
        """Return toolset metadata for UI display."""
        toolsets: dict[str, dict] = {}
        entries, toolset_checks = self._snapshot_state()
        for entry in entries:
            ts = entry.toolset
            if ts not in toolsets:
                toolsets[ts] = {
                    "available": (
                        self._evaluate_toolset_check(ts, toolset_checks.get(ts))
                        if toolset_checks.get(ts) is not None
                        else self._entry_available(entry)
                    ),
                    "tools": [],
                    "description": "",
                    "requirements": [],
                }
            toolsets[ts]["tools"].append(entry.name)
            if entry.requires_env:
                for env in entry.requires_env:
                    if env not in toolsets[ts]["requirements"]:
                        toolsets[ts]["requirements"].append(env)
        return toolsets

    def get_toolset_requirements(self) -> dict[str, dict]:
        """Build a TOOLSET_REQUIREMENTS-compatible dict for backward compat."""
        result: dict[str, dict] = {}
        entries, toolset_checks = self._snapshot_state()
        for entry in entries:
            ts = entry.toolset
            if ts not in result:
                result[ts] = {
                    "name": ts,
                    "env_vars": [],
                    "check_fn": toolset_checks.get(ts),
                    "setup_url": None,
                    "tools": [],
                }
            if entry.name not in result[ts]["tools"]:
                result[ts]["tools"].append(entry.name)
            for env in entry.requires_env:
                if env not in result[ts]["env_vars"]:
                    result[ts]["env_vars"].append(env)
        return result

    def check_tool_availability(self, quiet: bool = False):
        """Return (available_toolsets, unavailable_info) like the old function."""
        available = []
        unavailable = []
        seen = set()
        entries, toolset_checks = self._snapshot_state()
        for entry in entries:
            ts = entry.toolset
            if ts in seen:
                continue
            seen.add(ts)
            available = (
                self._evaluate_toolset_check(ts, toolset_checks.get(ts))
                if toolset_checks.get(ts) is not None
                else any(self._entry_available(e) for e in entries if e.toolset == ts)
            )
            if available:
                available.append(ts)
            else:
                unavailable.append({
                    "name": ts,
                    "env_vars": entry.requires_env,
                    "tools": [e.name for e in entries if e.toolset == ts],
                })
        return available, unavailable


# Module-level singleton
registry = ToolRegistry()


# ---------------------------------------------------------------------------
# Post-dispatch pipeline (TokenJuice compaction + prompt-injection screening)
# ---------------------------------------------------------------------------


class _PipelineSettings:
    """Cached config for the post-dispatch pipeline.

    Loaded lazily on first dispatch, then cached. Call ``reload()`` after
    config changes (e.g. from ``/reload`` or ``spark config set``) to pick
    up new values without restarting.
    """

    __slots__ = ("normalize_enabled", "injection_mode",
                 "block_threshold", "review_threshold", "_loaded")

    def __init__(self):
        self.normalize_enabled = False
        self.injection_mode = "off"   # "off" | "warn" | "enforce"
        self.block_threshold = 0.70
        self.review_threshold = 0.45
        self._loaded = False

    def ensure_loaded(self):
        if self._loaded:
            return
        try:
            from spark_cli.config import load_config
            cfg = load_config() or {}
            pipe = (cfg.get("tool_pipeline") or {})
            norm = pipe.get("normalization") or {}
            guard = pipe.get("injection_guard") or {}
            self.normalize_enabled = bool(norm.get("enabled", False))
            self.injection_mode = str(guard.get("mode", "off")).lower()
            self.block_threshold = float(guard.get("block_threshold", 0.70))
            self.review_threshold = float(guard.get("review_threshold", 0.45))
        except Exception as e:
            logger.debug("Pipeline settings load failed (using defaults): %s", e)
        self._loaded = True

    def reload(self):
        self._loaded = False
        self.ensure_loaded()


_pipeline_settings = _PipelineSettings()


def reload_pipeline_settings():
    """Re-read tool_pipeline config from disk (call after config changes)."""
    _pipeline_settings.reload()
    try:
        from tools.normalize import reload_default_rules
        reload_default_rules()
    except Exception:
        pass


def _argv_from_args(args: dict | None) -> list[str] | None:
    """Best-effort extraction of an argv-like list from tool args.

    Used by TokenJuice match rules (argv0, argv_includes_any). Falls back
    to None if no obvious command/argv field is present.
    """
    if not isinstance(args, dict):
        return None
    if isinstance(args.get("argv"), list):
        return [str(x) for x in args["argv"]]
    cmd = args.get("command") or args.get("cmd")
    if isinstance(cmd, str) and cmd.strip():
        try:
            import shlex
            return shlex.split(cmd)
        except Exception:
            return cmd.split()
    if isinstance(cmd, list):
        return [str(x) for x in cmd]
    return None


def _post_process(name: str, entry: "ToolEntry", raw: str, args: dict | None) -> str:
    """Apply compaction + injection screen. Always returns a string."""
    if not isinstance(raw, str):
        import json as _json
        try:
            return _json.dumps(raw)
        except (TypeError, ValueError):
            return str(raw)

    _pipeline_settings.ensure_loaded()
    text = raw

    if entry.normalize and _pipeline_settings.normalize_enabled:
        try:
            from tools.normalize import compact_tool_output
            text, stats = compact_tool_output(text, name, _argv_from_args(args))
            if stats.rules_applied and stats.output_chars < stats.input_chars:
                logger.debug(
                    "normalize[%s]: %d→%d chars (-%.0f%%) rules=%s",
                    name, stats.input_chars, stats.output_chars,
                    stats.reduction_ratio * 100, stats.rules_applied,
                )
        except Exception as e:
            logger.warning("normalize[%s] failed (passthrough): %s", name, e)

    if entry.screen and _pipeline_settings.injection_mode != "off":
        try:
            from tools.injection_guard import screen_tool_output, blocked_stub
            text, decision = screen_tool_output(
                text, name,
                block_threshold=_pipeline_settings.block_threshold,
                review_threshold=_pipeline_settings.review_threshold,
            )
            if decision.verdict != "allow":
                logger.warning(
                    "injection_guard[%s]: verdict=%s score=%.2f sha=%s reasons=%s",
                    name, decision.verdict, decision.score,
                    decision.prompt_sha256[:12],
                    [r.code for r in decision.reasons],
                )
                if (_pipeline_settings.injection_mode == "enforce"
                        and decision.verdict == "block"):
                    text = blocked_stub(decision, name)
        except Exception as e:
            logger.warning("injection_guard[%s] failed (passthrough): %s", name, e)

    return text


# ---------------------------------------------------------------------------
# Helpers for tool response serialization
# ---------------------------------------------------------------------------
# Every tool handler must return a JSON string.  These helpers eliminate the
# boilerplate ``json.dumps({"error": msg}, ensure_ascii=False)`` that appears
# hundreds of times across tool files.
#
# Usage:
#   from tools.registry import registry, tool_error, tool_result
#
#   return tool_error("something went wrong")
#   return tool_error("not found", code=404)
#   return tool_result(success=True, data=payload)
#   return tool_result(items)            # pass a dict directly


def tool_error(message, **extra) -> str:
    """Return a JSON error string for tool handlers.

    >>> tool_error("file not found")
    '{"error": "file not found"}'
    >>> tool_error("bad input", success=False)
    '{"error": "bad input", "success": false}'
    """
    result = {"error": str(message)}
    if extra:
        result.update(extra)
    return json.dumps(result, ensure_ascii=False)


def tool_result(data=None, **kwargs) -> str:
    """Return a JSON result string for tool handlers.

    Accepts a dict positional arg *or* keyword arguments (not both):

    >>> tool_result(success=True, count=42)
    '{"success": true, "count": 42}'
    >>> tool_result({"key": "value"})
    '{"key": "value"}'
    """
    if data is not None:
        return json.dumps(data, ensure_ascii=False)
    return json.dumps(kwargs, ensure_ascii=False)
