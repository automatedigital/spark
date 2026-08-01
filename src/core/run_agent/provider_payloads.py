"""Pure provider-payload adapters used by the stable AIAgent facade."""

from __future__ import annotations

from typing import Any


def normalize_responses_tool(tool: Any, index: int) -> dict:
    """Validate one OpenAI Responses function definition deterministically."""
    if not isinstance(tool, dict):
        raise ValueError(f"Codex Responses tools[{index}] must be an object.")
    if tool.get("type") != "function":
        raise ValueError(
            f"Codex Responses tools[{index}] has unsupported type {tool.get('type')!r}."
        )
    name = tool.get("name")
    parameters = tool.get("parameters")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"Codex Responses tools[{index}] is missing a valid name.")
    if not isinstance(parameters, dict):
        raise ValueError(f"Codex Responses tools[{index}] is missing valid parameters.")
    description = tool.get("description", "")
    if description is None:
        description = ""
    return {
        "type": "function",
        "name": name.strip(),
        "description": description if isinstance(description, str) else str(description),
        "strict": bool(tool.get("strict", False)),
        "parameters": parameters,
    }
