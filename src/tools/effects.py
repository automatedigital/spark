"""Declarative side-effect metadata for dependency-aware tool scheduling."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

READ = "read"
WRITE = "write"
NETWORK = "network"
PROCESS = "process"
USER_INTERACTION = "user_interaction"


@dataclass(frozen=True, slots=True)
class ToolEffects:
    """Scheduling contract attached to every registered tool.

    ``resource_templates`` use ``kind:argument`` notation.  Known kinds are
    ``path``, ``url``, ``value`` and ``const``.  Missing arguments resolve to a
    conservative tool-family resource instead of accidentally permitting
    concurrency.
    """

    effects: frozenset[str]
    resource_templates: tuple[str, ...]
    ordered: bool = False
    concurrency_cap: int | None = None
    service: str | None = None
    deadline_seconds: float | None = 300.0

    @property
    def writes(self) -> bool:
        return bool(self.effects & {WRITE, PROCESS, USER_INTERACTION})

    def resources(self, args: dict[str, Any]) -> tuple[str, ...]:
        resolved = tuple(
            resource
            for template in self.resource_templates
            if (resource := _resolve_template(template, args))
        )
        if resolved:
            return resolved
        family = self.service or "unknown"
        return (f"family:{family}",)


def _resolve_template(template: str, args: dict[str, Any]) -> str | None:
    kind, _, value = template.partition(":")
    if kind == "const":
        return value
    raw = args.get(value)
    if raw is None or raw == "":
        return None
    if kind == "path":
        path = Path(str(raw)).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        return f"path:{os.path.abspath(str(path))}"
    if kind == "url":
        split = urlsplit(str(raw))
        return f"remote:{split.scheme.lower()}://{split.netloc.lower()}" if split.netloc else None
    if kind == "value":
        return f"value:{value}:{raw}"
    return None


_READ_TOOLS = frozenset({
    "read_file", "search_files", "session_search", "skills_list", "skill_view",
    "ha_get_state", "ha_list_entities", "ha_list_services", "browser_snapshot",
    "browser_screenshot", "browser_get_text", "preview_status", "process_status",
})
_FILE_WRITES = frozenset({"write_file", "patch"})
_USER_TOOLS = frozenset({"clarify"})
_STATE_WRITES = {
    "todo": "state:todo",
    "memory": "state:memory",
    "cronjob": "state:cron",
    "kanban": "state:kanban",
    "skill_manage": "state:skills",
    "canvas": "state:canvas",
}


def infer_tool_effects(name: str, toolset: str) -> ToolEffects:
    """Return a complete conservative contract for a registered tool.

    Registration sites may override this inferred contract, but no entry can
    exist without metadata.  The fallback is deliberately serialized.
    """
    if name in _USER_TOOLS:
        return ToolEffects(
            frozenset({USER_INTERACTION}), ("const:user:interaction",),
            ordered=True, concurrency_cap=1, service="user",
            deadline_seconds=None,
        )
    if name in _FILE_WRITES:
        return ToolEffects(
            frozenset({WRITE}), ("path:path",), service="filesystem",
        )
    if name in {"read_file", "search_files"}:
        return ToolEffects(
            frozenset({READ}), ("path:path",), service="filesystem",
        )
    if name == "terminal":
        return ToolEffects(
            frozenset({READ, WRITE, PROCESS}),
            ("path:workdir", "const:process:terminal"),
            ordered=True, concurrency_cap=1, service="terminal",
            deadline_seconds=None,
        )
    if name.startswith("browser_"):
        effects = {READ, NETWORK}
        if name not in _READ_TOOLS:
            effects.add(WRITE)
        return ToolEffects(
            frozenset(effects), ("const:browser:session",),
            ordered=True, concurrency_cap=1, service="browser",
        )
    if name in _STATE_WRITES:
        effects = {WRITE}
        if name == "skill_manage":
            effects.add(NETWORK)
        return ToolEffects(
            frozenset(effects), (f"const:{_STATE_WRITES[name]}",),
            ordered=True, concurrency_cap=1, service=_STATE_WRITES[name],
        )
    if name.startswith("process_") or name == "execute_code":
        return ToolEffects(
            frozenset({READ, WRITE, PROCESS}),
            ("value:process_id", "const:process:managed"),
            ordered=True, concurrency_cap=1, service="process",
            deadline_seconds=None,
        )
    if name in _READ_TOOLS:
        resource = "const:state:sessions" if name == "session_search" else f"const:tool:{name}"
        return ToolEffects(frozenset({READ}), (resource,), service=toolset)
    if name.startswith("ha_"):
        effects = {NETWORK, READ}
        if name == "ha_call_service":
            effects.add(WRITE)
        return ToolEffects(
            frozenset(effects), ("value:entity_id", "const:remote:homeassistant"),
            ordered=name == "ha_call_service", concurrency_cap=8,
            service="homeassistant", deadline_seconds=30.0,
        )
    if name.startswith("web_"):
        return ToolEffects(
            frozenset({READ, NETWORK}), ("url:url", "const:remote:web"),
            concurrency_cap=8, service="web", deadline_seconds=60.0,
        )
    if name.startswith("mcp_") or toolset.startswith("mcp"):
        return ToolEffects(
            frozenset({READ, WRITE, NETWORK, PROCESS}),
            (f"const:mcp:{toolset}",), ordered=True, concurrency_cap=1,
            service=f"mcp:{toolset}", deadline_seconds=120.0,
        )
    if name in {"vision_analyze", "image_generate", "mixture_of_agents", "tts"}:
        return ToolEffects(
            frozenset({READ, NETWORK}), (f"const:remote:{name}",),
            concurrency_cap=4, service=name, deadline_seconds=300.0,
        )
    if name == "send_message":
        return ToolEffects(
            frozenset({WRITE, NETWORK, USER_INTERACTION}),
            ("value:platform", "value:target"), ordered=True,
            concurrency_cap=1, service="messaging", deadline_seconds=60.0,
        )
    if name == "connectors":
        return ToolEffects(
            frozenset({READ, WRITE, NETWORK}),
            ("value:connector", "value:action"),
            ordered=True, concurrency_cap=4, service="connectors",
            deadline_seconds=120.0,
        )
    # Unknown tools are safe by default: they conflict with their entire
    # toolset until an owner supplies a more precise contract.
    return ToolEffects(
        frozenset({READ, WRITE}), (f"const:toolset:{toolset}",),
        ordered=True, concurrency_cap=1, service=toolset,
    )


def resources_overlap(left: str, right: str) -> bool:
    """Return whether two normalized resources may refer to the same state."""
    if left == right:
        return True
    if left.startswith("path:") and right.startswith("path:"):
        left_path = Path(left[5:]).parts
        right_path = Path(right[5:]).parts
        common = min(len(left_path), len(right_path))
        return left_path[:common] == right_path[:common]
    return False
