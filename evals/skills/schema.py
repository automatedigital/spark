"""Contracts for the SKILL-08 paired skills evaluation harness.

The evaluator intentionally uses only stdlib types so its fake adapter can run in
CI without loading Spark, model SDKs, credentials, or network clients.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "1.0.0"
CONDITIONS = ("baseline", "candidate")
DIMENSIONS = ("correctness", "autonomy", "actionability", "safety", "concision")
WEIGHTS = {
    "correctness": 0.35,
    "autonomy": 0.25,
    "actionability": 0.20,
    "safety": 0.10,
    "concision": 0.10,
}
CASE_CATEGORIES = {
    "discovery",
    "direct_invocation",
    "isolation",
    "provenance",
    "prompt_index_cost",
    "safety",
    "persistent_stop",
}
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]+$")


class SchemaError(ValueError):
    """Raised when an evaluation artifact does not satisfy its contract."""


def canonical_json(value: Any) -> str:
    """Return stable JSON for hashes, run keys, and reproducible packets."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise SchemaError(f"{field_name} must be a list of non-empty strings")
    return tuple(value)


@dataclass(frozen=True)
class RuntimePin:
    """The model/provider/reasoning contract shared by both conditions."""

    provider: str = "fixture"
    model: str = "skill-eval-fixture-v1"
    reasoning_effort: str = "medium"

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) and value.strip() for value in self.as_dict().values()):
            raise SchemaError("runtime pin values must be non-empty strings")

    def as_dict(self) -> dict[str, str]:
        return {
            "provider": self.provider,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> RuntimePin:
        return cls(
            provider=str(value.get("provider", "")),
            model=str(value.get("model", "")),
            reasoning_effort=str(value.get("reasoning_effort", "")),
        )


@dataclass(frozen=True)
class EvaluationCase:
    """One public, synthetic task evaluated identically under both conditions."""

    id: str
    category: str
    prompt: str
    oracle: Mapping[str, Any]
    fixtures: Mapping[str, Mapping[str, Any]]
    privacy: str = "synthetic"

    def __post_init__(self) -> None:
        if not _ID_RE.fullmatch(self.id):
            raise SchemaError(f"invalid case id: {self.id!r}")
        if self.category not in CASE_CATEGORIES:
            raise SchemaError(f"unknown case category: {self.category!r}")
        if not self.prompt.strip():
            raise SchemaError(f"{self.id}: prompt must not be empty")
        if self.privacy != "synthetic":
            raise SchemaError(f"{self.id}: only synthetic fixtures are allowed")
        if not isinstance(self.oracle, Mapping):
            raise SchemaError(f"{self.id}: oracle must be an object")
        for key in ("required_markers", "forbidden_markers", "required_actions"):
            _string_tuple(self.oracle.get(key), f"{self.id}.oracle.{key}")
        if not isinstance(self.fixtures, Mapping) or set(self.fixtures) != set(CONDITIONS):
            raise SchemaError(f"{self.id}: fixtures must contain baseline and candidate")
        for condition in CONDITIONS:
            fixture = self.fixtures[condition]
            if not isinstance(fixture, Mapping) or not isinstance(fixture.get("response"), str):
                raise SchemaError(f"{self.id}.{condition}: fixture response must be a string")
            usage = fixture.get("usage", {})
            if not isinstance(usage, Mapping):
                raise SchemaError(f"{self.id}.{condition}: usage must be an object")
            for key in ("input_tokens", "output_tokens"):
                if not isinstance(usage.get(key, 0), int) or usage.get(key, 0) < 0:
                    raise SchemaError(f"{self.id}.{condition}: {key} must be a non-negative integer")
            cost = fixture.get("cost_usd", 0.0)
            if not isinstance(cost, int | float) or cost < 0:
                raise SchemaError(f"{self.id}.{condition}: cost_usd must be non-negative")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> EvaluationCase:
        return cls(
            id=str(value.get("id", "")),
            category=str(value.get("category", "")),
            prompt=str(value.get("prompt", "")),
            oracle=value.get("oracle", {}),
            fixtures=value.get("fixtures", {}),
            privacy=str(value.get("privacy", "")),
        )

    def as_dict(self, *, include_fixtures: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "category": self.category,
            "prompt": self.prompt,
            "oracle": dict(self.oracle),
            "privacy": self.privacy,
        }
        if include_fixtures:
            result["fixtures"] = {condition: dict(self.fixtures[condition]) for condition in CONDITIONS}
        return result


@dataclass(frozen=True)
class AdapterResult:
    """Normalized adapter output recorded by the runner."""

    response: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    tool_calls: int = 0
    follow_up_turns: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)
    reported_runtime: RuntimePin | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.response, str):
            raise SchemaError("adapter response must be a string")
        if any(
            not isinstance(value, int) or value < 0
            for value in (self.input_tokens, self.output_tokens, self.tool_calls, self.follow_up_turns)
        ):
            raise SchemaError("adapter usage counters must be non-negative integers")
        if not isinstance(self.cost_usd, int | float) or self.cost_usd < 0:
            raise SchemaError("adapter cost_usd must be non-negative")

    @property
    def usage_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "response": self.response,
            "usage": {
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "total_tokens": self.usage_tokens,
            },
            "cost_usd": float(self.cost_usd),
            "tool_calls": self.tool_calls,
            "follow_up_turns": self.follow_up_turns,
            "metadata": dict(self.metadata),
        }
        if self.reported_runtime is not None:
            result["reported_runtime"] = self.reported_runtime.as_dict()
        return result


def validate_case_values(cases: list[EvaluationCase]) -> list[str]:
    """Validate collection-level invariants and return CLI-friendly errors."""

    errors: list[str] = []
    seen: set[str] = set()
    for case in cases:
        if case.id in seen:
            errors.append(f"duplicate case id: {case.id}")
        seen.add(case.id)
    if not cases:
        errors.append("at least one evaluation case is required")
    categories = {case.category for case in cases}
    missing = CASE_CATEGORIES - categories
    if missing:
        errors.append(f"missing representative categories: {sorted(missing)}")
    return errors
