"""Typed, compact model-visible facades over Spark's legacy tool handlers.

The facade contract is deliberately data-only.  One definition generates the
model schema, validates calls, and maps them back to the existing handler.  The
legacy names remain registered for saved transcripts and API callers, while a
new model request sees only one stable schema per family.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ActionDefinition:
    name: str
    tool: str
    summary: str


@dataclass(frozen=True, slots=True)
class FacadeDefinition:
    name: str
    summary: str
    actions: tuple[ActionDefinition, ...]

    def action_map(self) -> dict[str, ActionDefinition]:
        return {action.name: action for action in self.actions}


FACADES: tuple[FacadeDefinition, ...] = (
    FacadeDefinition("files", "Read, search, create, or patch workspace files.", (
        ActionDefinition("read", "read_file", "Read a bounded file range: path, offset?, limit?."),
        ActionDefinition("search", "search_files", "Search names/content: pattern, path?, glob?, max_results?."),
        ActionDefinition("write", "write_file", "Create/replace a file: path, content."),
        ActionDefinition("patch", "patch", "Replace exact text: path, old_text, new_text."),
        ActionDefinition("artifact_read", "artifact_read", "Read a bounded artifact page: handle, offset?, limit?."),
        ActionDefinition("artifact_search", "artifact_search", "Search an artifact: handle, query, limit?."),
    )),
    FacadeDefinition("skills", "List, inspect, create, update, or remove Spark skills.", (
        ActionDefinition("list", "skills_list", "List available skills: query?."),
        ActionDefinition("view", "skill_view", "Read a skill: name."),
        ActionDefinition("manage", "skill_manage", "Manage a skill: action plus the legacy skill arguments."),
    )),
    FacadeDefinition("preview", "Open and verify the project-scoped web preview.", (
        ActionDefinition("open", "preview_open", "Open preview: url?."),
        ActionDefinition("snapshot", "preview_snapshot", "Read accessible page state."),
        ActionDefinition("console", "preview_console", "Read browser console output."),
        ActionDefinition("screenshot", "preview_screenshot", "Capture the rendered page."),
        ActionDefinition("click", "preview_click", "Click an element: selector or ref."),
        ActionDefinition("type", "preview_type", "Enter text: selector/ref and text."),
        ActionDefinition("evaluate", "preview_evaluate", "Evaluate JavaScript: expression."),
    )),
    FacadeDefinition("canvas", "Render or wait for an agent-driven visual board.", (
        ActionDefinition("render", "canvas", "Render canvas content using the legacy canvas arguments."),
        ActionDefinition("await", "canvas_await", "Wait for a canvas interaction/result."),
    )),
    FacadeDefinition("web", "Search the public web or extract a known page.", (
        ActionDefinition("search", "web_search", "Search: query, max_results?."),
        ActionDefinition("extract", "web_extract", "Extract: url or urls, prompt?."),
    )),
    FacadeDefinition("browser", "Operate one browser session without changing the tool schema.", (
        ActionDefinition("open", "browser_open", "Open the browser."),
        ActionDefinition("navigate", "browser_navigate", "Navigate: url."),
        ActionDefinition("snapshot", "browser_snapshot", "Read the page snapshot."),
        ActionDefinition("a11y", "browser_a11y", "Read the accessibility tree."),
        ActionDefinition("click", "browser_click", "Click: selector/ref."),
        ActionDefinition("type", "browser_type", "Type: selector/ref and text."),
        ActionDefinition("scroll", "browser_scroll", "Scroll the page."),
        ActionDefinition("back", "browser_back", "Navigate back."),
        ActionDefinition("press", "browser_press", "Press a key."),
        ActionDefinition("images", "browser_get_images", "List page images."),
        ActionDefinition("vision", "browser_vision", "Inspect a browser screenshot."),
        ActionDefinition("console", "browser_console", "Read browser console output."),
    )),
)

_BY_NAME = {facade.name: facade for facade in FACADES}
_BY_TOOL = {
    action.tool: (facade, action)
    for facade in FACADES
    for action in facade.actions
}

_COMPACT_STANDALONE_SUMMARIES = {
    "terminal": (
        "Run a shell command in the configured backend. Use workdir for scope; "
        "commands may be synchronous, background, or polled by session_id."
    ),
    "process": "List, poll, write to, or stop a background terminal process.",
    "memory": "Read or update durable MEMORY.md/USER.md state using an explicit action.",
    "session_search": "Search prior Spark sessions and return bounded matching context.",
    "todo": "Replace or merge the durable task list; preserve incomplete work.",
    "clarify": "Ask one blocking question, optionally with concise choices.",
    "connectors": "List, connect, inspect, or disconnect external connectors.",
    "vision_analyze": "Analyze one or more images using the configured vision model.",
}


def _compact_standalone_schema(definition: dict[str, Any]) -> dict[str, Any]:
    """Compact prose while retaining every parameter/type/enum/required key."""

    function = definition.get("function", {})
    name = function.get("name", "")
    summary = _COMPACT_STANDALONE_SUMMARIES.get(name)
    if summary is None:
        return definition
    parameters = dict(function.get("parameters") or {})
    properties = {}
    for key, raw_property in (parameters.get("properties") or {}).items():
        prop = dict(raw_property)
        description = prop.get("description")
        if isinstance(description, str) and len(description) > 140:
            prop["description"] = description[:137].rsplit(" ", 1)[0] + "..."
        properties[key] = prop
    parameters["properties"] = properties
    return {
        **definition,
        "function": {**function, "description": summary, "parameters": parameters},
    }


def facades_enabled() -> bool:
    """Return whether new sessions should use facades.

    This is intentionally resolved once by ``get_tool_definitions``.  Existing
    AIAgent instances keep their ordered schema list.  The environment escape
    hatch is a new-session rollback boundary, not a mid-thread switch.
    """

    return os.getenv("SPARK_LEGACY_TOOL_SCHEMAS", "").strip().lower() not in {
        "1", "true", "yes", "on",
    }


def _available_actions(
    facade: FacadeDefinition,
    available_legacy_names: set[str],
) -> tuple[ActionDefinition, ...]:
    actions = tuple(a for a in facade.actions if a.tool in available_legacy_names)
    # browser_open is the stable capability gate.  Once it is available, keep
    # every browser action in the schema even before the browser is launched.
    if facade.name == "browser" and "browser_open" in available_legacy_names:
        return facade.actions
    return actions


def build_facade_schema(
    facade: FacadeDefinition,
    available_legacy_names: set[str],
) -> dict[str, Any] | None:
    actions = _available_actions(facade, available_legacy_names)
    if not actions:
        return None
    action_help = " ".join(f"{a.name}: {a.summary}" for a in actions)
    return {
        "type": "function",
        "function": {
            "name": facade.name,
            "description": f"{facade.summary} Actions — {action_help}",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": [a.name for a in actions]},
                    "arguments": {
                        "type": "object",
                        "description": "Arguments for the selected action.",
                        "additionalProperties": True,
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
        },
    }


def compact_tool_definitions(
    definitions: list[dict[str, Any]],
    *,
    profile_facades: bool = True,
) -> list[dict[str, Any]]:
    """Replace visible legacy family schemas with generated facades.

    Non-facade and plugin tools keep their original relative order.  Each
    facade is inserted where the first member occurred, making ordering fully
    deterministic without exposing both contracts.
    """

    if not profile_facades or not facades_enabled():
        return definitions
    available = {
        d.get("function", {}).get("name", "") for d in definitions
        if isinstance(d, dict)
    }
    emitted: set[str] = set()
    compacted: list[dict[str, Any]] = []
    for definition in definitions:
        legacy_name = definition.get("function", {}).get("name", "")
        mapped = _BY_TOOL.get(legacy_name)
        if mapped is None:
            compacted.append(_compact_standalone_schema(definition))
            continue
        facade, _ = mapped
        if facade.name in emitted:
            continue
        schema = build_facade_schema(facade, available)
        if schema is not None:
            compacted.append(schema)
            emitted.add(facade.name)
    return compacted


def normalize_facade_call(name: str, args: Mapping[str, Any] | None) -> tuple[str, dict[str, Any]]:
    """Validate and translate a facade call to a legacy handler call.

    ``arguments`` is preferred, but top-level legacy arguments are accepted to
    make model/API callers robust during rollout.  Unknown actions and calls to
    handlers not currently registered fail before dispatch.
    """

    facade = _BY_NAME.get(name)
    if facade is None:
        return name, dict(args or {})
    raw = dict(args or {})
    action_name = raw.pop("action", None)
    action = facade.action_map().get(str(action_name))
    if action is None:
        allowed = ", ".join(a.name for a in facade.actions)
        raise ValueError(f"Unknown {name} action {action_name!r}; expected one of: {allowed}")
    nested = raw.pop("arguments", None)
    if nested is not None:
        if not isinstance(nested, Mapping):
            raise ValueError(f"{name}.arguments must be an object")
        raw = {**raw, **dict(nested)}

    # Validate with the legacy schema so the generated model schema and runtime
    # share the authoritative action contract without duplicating definitions.
    from tools.registry import registry

    legacy_schema = registry.get_schema(action.tool)
    if legacy_schema is None:
        raise ValueError(f"{name}.{action.name} is unavailable in this profile")
    parameters = legacy_schema.get("parameters") or {}
    missing = [key for key in parameters.get("required", []) if key not in raw]
    if missing:
        raise ValueError(
            f"{name}.{action.name} missing required argument(s): {', '.join(missing)}"
        )
    return action.tool, raw


def normalize_saved_tool_call(name: str, args: Mapping[str, Any] | None) -> tuple[str, dict[str, Any]]:
    """Normalize either new facade calls or legacy saved transcript calls."""

    return normalize_facade_call(name, args)


def facade_action_inventory() -> dict[str, tuple[str, ...]]:
    return {
        facade.name: tuple(action.tool for action in facade.actions)
        for facade in FACADES
    }


def facade_action_manifest() -> tuple[dict[str, str], ...]:
    """Stable lazy-loader join surface; contains no handler imports."""

    return tuple(
        {
            "facade": facade.name,
            "action": action.name,
            "legacy_tool": action.tool,
        }
        for facade in FACADES
        for action in facade.actions
    )


def expand_facade_tool_names(names: Iterable[str]) -> set[str]:
    """Expand visible facade IDs for legacy capability checks/sandboxes."""

    expanded: set[str] = set()
    for name in names:
        facade = _BY_NAME.get(name)
        if facade is None:
            expanded.add(name)
        else:
            expanded.update(action.tool for action in facade.actions)
    return expanded


def serialized_schema_chars(definitions: Iterable[dict[str, Any]]) -> int:
    return len(json.dumps(list(definitions), ensure_ascii=False, separators=(",", ":")))


def canonical_schema_json(definitions: Iterable[dict[str, Any]]) -> str:
    """Canonicalize keys while retaining the ordered schema list."""

    return json.dumps(
        list(definitions), ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    )


def schema_fingerprint(definitions: Iterable[dict[str, Any]]) -> str:
    canonical = canonical_schema_json(definitions)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
