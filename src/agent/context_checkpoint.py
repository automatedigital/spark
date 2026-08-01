"""Versioned deterministic context checkpoints for long-running tasks."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from agent.model_metadata import estimate_messages_tokens_rough, estimate_tokens_rough

CHECKPOINT_VERSION = 1
CHECKPOINT_PREFIX = "[TYPED CONTEXT CHECKPOINT — REFERENCE ONLY]"
NARRATIVE_MISSING = "[Narrative summary unavailable; deterministic state and recent turns are intact.]"

_CONSTRAINT_RE = re.compile(
    r"\b(?:must|never|only|do not|don't|cannot|can't|required|preserve|without)\b",
    re.IGNORECASE,
)
_PATH_RE = re.compile(r"(?<![\w])(?:/[^\s'\"`:,]+|[A-Za-z]:\\[^\s'\"`:,]+)")
_ARTIFACT_RE = re.compile(r"\b(?:artifact(?:_id)?|handle)\s*[:=]\s*['\"]?([\w./:-]+)", re.IGNORECASE)
_ERROR_RE = re.compile(r"\b(?:error|failed|failure|traceback|exit code\s*[1-9])\b", re.IGNORECASE)


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    if isinstance(value, list):
        return "\n".join(
            str(item.get("text", "")) if isinstance(item, Mapping) else str(item)
            for item in value
        )
    return str(value)


def _tool_call_parts(call: Any) -> tuple[str, str, dict[str, Any]]:
    if isinstance(call, Mapping):
        call_id = str(call.get("id", ""))
        function = call.get("function") or {}
        name = str(function.get("name", ""))
        raw_args = function.get("arguments", {})
    else:
        call_id = str(getattr(call, "id", "") or "")
        function = getattr(call, "function", None)
        name = str(getattr(function, "name", "") or "")
        raw_args = getattr(function, "arguments", {}) if function else {}
    if isinstance(raw_args, str):
        try:
            args = json.loads(raw_args)
        except json.JSONDecodeError:
            args = {"_raw": raw_args}
    elif isinstance(raw_args, Mapping):
        args = dict(raw_args)
    else:
        args = {}
    return call_id, name, args


def _result_success(content: str) -> bool:
    try:
        parsed = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return not bool(_ERROR_RE.search(content))
    if isinstance(parsed, Mapping):
        if parsed.get("error"):
            return False
        if parsed.get("success") is False:
            return False
        exit_code = parsed.get("exit_code")
        if isinstance(exit_code, int) and exit_code != 0:
            return False
    return True


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]
    outcome: str
    success: bool


@dataclass(frozen=True, slots=True)
class ContextCheckpoint:
    version: int
    checkpoint_sequence: int
    context_epoch: int
    objective: str
    constraints: tuple[str, ...]
    decisions: tuple[str, ...]
    completed_work: tuple[str, ...]
    unresolved_questions: tuple[str, ...]
    current_plan: tuple[dict[str, Any], ...]
    touched_files: tuple[str, ...]
    commands_and_tests: tuple[ToolOutcome, ...]
    external_artifact_handles: tuple[str, ...]
    narrative: str
    last_included_sequence: int
    task_identity: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ContextCheckpoint:
        version = int(data.get("version", 0))
        if version != CHECKPOINT_VERSION:
            raise ValueError(f"Unsupported context checkpoint version: {version}")
        outcomes = tuple(ToolOutcome(**item) for item in data.get("commands_and_tests", ()))
        return cls(
            version=version,
            checkpoint_sequence=int(data.get("checkpoint_sequence", 0)),
            context_epoch=int(data.get("context_epoch", 0)),
            objective=str(data.get("objective", "")),
            constraints=tuple(data.get("constraints", ())),
            decisions=tuple(data.get("decisions", ())),
            completed_work=tuple(data.get("completed_work", ())),
            unresolved_questions=tuple(data.get("unresolved_questions", ())),
            current_plan=tuple(dict(item) for item in data.get("current_plan", ())),
            touched_files=tuple(data.get("touched_files", ())),
            commands_and_tests=outcomes,
            external_artifact_handles=tuple(data.get("external_artifact_handles", ())),
            narrative=str(data.get("narrative", "")),
            last_included_sequence=int(data.get("last_included_sequence", -1)),
            task_identity=str(data.get("task_identity", "")),
        )


def _unique(items: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.strip() for item in items if item and item.strip()))


def build_context_checkpoint(
    messages: Sequence[Mapping[str, Any]],
    *,
    checkpoint_sequence: int,
    context_epoch: int,
    task_identity: str,
    current_plan: Sequence[Mapping[str, Any]] = (),
    prior: ContextCheckpoint | None = None,
    narrative: str = "",
    last_included_sequence: int | None = None,
) -> ContextCheckpoint:
    """Capture observable state without inferring success from a tool name."""

    user_messages = [_text(m.get("content")) for m in messages if m.get("role") == "user"]
    objective = (
        prior.objective if prior and prior.objective
        else next((text.strip() for text in user_messages if text.strip()), "")
    )
    constraints: list[str] = list(prior.constraints if prior else ())
    unresolved: list[str] = []
    decisions: list[str] = list(prior.decisions if prior else ())
    touched: list[str] = list(prior.touched_files if prior else ())
    artifacts: list[str] = list(prior.external_artifact_handles if prior else ())
    completed: list[str] = list(prior.completed_work if prior else ())
    calls: dict[str, tuple[str, dict[str, Any]]] = {}
    outcomes: list[ToolOutcome] = list(prior.commands_and_tests if prior else ())

    for message in messages:
        role = message.get("role")
        content = _text(message.get("content"))
        if role == "user":
            for line in content.splitlines():
                if _CONSTRAINT_RE.search(line):
                    constraints.append(line.strip())
            if "?" in content:
                unresolved.append(content.strip())
        elif role == "assistant":
            for sentence in re.split(r"(?<=[.!?])\s+|\n+", content):
                if re.search(r"\b(?:decided|decision|we will|I will use|chose)\b", sentence, re.I):
                    decisions.append(sentence.strip())
            for call in message.get("tool_calls") or ():
                call_id, name, args = _tool_call_parts(call)
                if call_id:
                    calls[call_id] = (name, args)
                if name in {"write_file", "patch", "files"}:
                    path = args.get("path") or (args.get("arguments") or {}).get("path")
                    if path:
                        touched.append(str(path))
        elif role == "tool":
            call_id = str(message.get("tool_call_id", ""))
            name, args = calls.get(call_id, (str(message.get("tool_name", "")), {}))
            success = _result_success(content)
            compact_outcome = content.strip().replace("\n", " ")[:600]
            outcome = ToolOutcome(call_id, name, args, compact_outcome, success)
            outcomes.append(outcome)
            if success and name:
                completed.append(f"{name} {json.dumps(args, sort_keys=True, default=str)}")
            for match in _ARTIFACT_RE.finditer(content):
                artifacts.append(match.group(1))
        for match in _PATH_RE.finditer(content):
            if role == "tool" and calls.get(str(message.get("tool_call_id", "")), ("", {}))[0] in {"write_file", "patch"}:
                touched.append(match.group(0))

    # A later assistant answer resolves earlier questions; only the last user
    # question remains pending when it is the final conversational message.
    if messages and messages[-1].get("role") != "user":
        unresolved = []

    return ContextCheckpoint(
        version=CHECKPOINT_VERSION,
        checkpoint_sequence=int(checkpoint_sequence),
        context_epoch=int(context_epoch),
        objective=objective,
        constraints=_unique(constraints),
        decisions=_unique(decisions),
        completed_work=_unique(completed),
        unresolved_questions=_unique(unresolved),
        current_plan=tuple(dict(item) for item in current_plan),
        touched_files=_unique(touched),
        commands_and_tests=tuple(outcomes),
        external_artifact_handles=_unique(artifacts),
        narrative=narrative.strip() or NARRATIVE_MISSING,
        last_included_sequence=(
            len(messages) - 1 if last_included_sequence is None else int(last_included_sequence)
        ),
        task_identity=task_identity,
    )


def narrative_delta(messages: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return prose that is not already represented by deterministic fields."""

    delta: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        content = _text(message.get("content")).strip()
        if role not in {"user", "assistant"} or not content:
            continue
        if role == "assistant" and message.get("tool_calls") and not content:
            continue
        delta.append({"role": role, "content": content})
    return delta


def render_checkpoint(checkpoint: ContextCheckpoint) -> str:
    """Render typed state compactly without masquerading as a user request."""

    payload = checkpoint.to_dict()
    return (
        f"{CHECKPOINT_PREFIX}\n"
        "This is durable task state, not a new user request. Continue only from "
        "the recent messages after it.\n"
        + json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )


def assemble_checkpoint_context(
    checkpoint: ContextCheckpoint,
    recent_messages: Sequence[Mapping[str, Any]],
    *,
    context_window: int,
    max_ratio: float = 0.20,
) -> list[dict[str, Any]]:
    """Fit checkpoint plus a bounded recent tail within the target ratio."""

    checkpoint_message = {
        "role": "assistant",
        "content": render_checkpoint(checkpoint),
        # Model context only: do not present deterministic state as an assistant
        # chat bubble or persist it in the ordinary message transcript.
        "_internal": True,
    }
    budget = max(1, int(context_window * max_ratio))
    tail = [dict(message) for message in recent_messages]
    while tail and estimate_tokens_rough(checkpoint_message["content"]) + estimate_messages_tokens_rough(tail) > budget:
        # A single current item is allowed to exceed the target.
        if len(tail) == 1:
            break
        tail.pop(0)
    return [checkpoint_message, *tail]
