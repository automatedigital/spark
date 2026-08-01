"""Deterministic request classification, response budgets, and model routing."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from core.utils import is_truthy_value


class RequestClass(StrEnum):
    DIRECT_ANSWER = "direct_answer"
    STATUS_PROGRESS = "status_progress"
    ACTION_CHANGE = "action_change"
    DIAGNOSIS = "diagnosis"
    EXPLANATION = "explanation"
    COMPARISON_OPTIONS = "comparison_options"
    PLAN_REVIEW = "plan_review"
    HIGH_STAKES = "destructive_high_stakes"
    FORMAT_CONTRACT = "explicit_format_contract"


@dataclass(frozen=True)
class RequestContext:
    has_attachments: bool = False
    tools_available: bool = True
    long_context: bool = False
    recovery_turn: bool = False
    ambiguous: bool = False


@dataclass(frozen=True)
class ResponseBudgetEnvelope:
    version: str
    request_class: str
    verbosity: str
    soft_output_min_tokens: int
    soft_output_max_tokens: int
    reasoning_effort: str
    model_tier: str
    tool_needed: bool
    required_response_elements: tuple[str, ...]
    explicit_user_override: bool
    routing_reason: str

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["required_response_elements"] = list(self.required_response_elements)
        return data


_URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
_CODE_RE = re.compile(r"```|`[^`]+`|\b(?:pytest|traceback|stacktrace|exception)\b", re.I)
_DESTRUCTIVE_RE = re.compile(
    r"\b(delete|destroy|drop|erase|wipe|remove all|reset --hard|force push|publish|release|merge to main)\b",
    re.I,
)
_HIGH_STAKES_RE = re.compile(
    r"\b(medical|symptom|legal advice|lawsuit|contract|tax|investment|financial advice|prescription)\b",
    re.I,
)
_DETAIL_RE = re.compile(
    r"\b(detailed|in detail|thorough|comprehensive|step[- ]by[- ]step|walkthrough|explain fully|long[- ]form)\b",
    re.I,
)
_COMPACT_RE = re.compile(r"\b(brief|briefly|concise|short answer|one sentence|tl;?dr)\b", re.I)
_FORMAT_RE = re.compile(
    r"\b(return|respond|output|format|write)\b.{0,48}\b(json|yaml|xml|csv|markdown table|code only|exactly|template|schema)\b",
    re.I | re.S,
)
_STATUS_RE = re.compile(r"\b(status|progress|what remains|where are we|done yet|update me)\b", re.I)
_DIAGNOSIS_RE = re.compile(r"\b(debug|diagnose|investigate|root cause|why (?:is|does|did)|error|failing|broken)\b", re.I)
_PLAN_RE = re.compile(r"\b(plan|review|audit|roadmap|proposal|double[- ]check)\b", re.I)
_COMPARE_RE = re.compile(r"\b(compare|versus|vs\.?|options|trade[- ]offs?|pros and cons|which should)\b", re.I)
_EXPLAIN_RE = re.compile(r"\b(explain|how does|teach me|what is|why)\b", re.I)
_ACTION_RE = re.compile(
    r"\b(build|create|edit|change|fix|implement|refactor|update|install|run|test|verify|send|deploy|bump|commit)\b",
    re.I,
)


def _coerce_bool(value: Any, default: bool = False) -> bool:
    return bool(is_truthy_value(value, default=default))


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _request_context(value: RequestContext | Mapping[str, Any] | None) -> RequestContext:
    if isinstance(value, RequestContext):
        return value
    raw = value or {}
    return RequestContext(
        has_attachments=bool(raw.get("has_attachments")),
        tools_available=bool(raw.get("tools_available", True)),
        long_context=bool(raw.get("long_context")),
        recovery_turn=bool(raw.get("recovery_turn")),
        ambiguous=bool(raw.get("ambiguous")),
    )


def classify_request(user_message: str) -> RequestClass:
    """Classify locally with risk/format gates taking priority over convenience."""
    text = (user_message or "").strip()
    if _FORMAT_RE.search(text):
        return RequestClass.FORMAT_CONTRACT
    if _DESTRUCTIVE_RE.search(text) or _HIGH_STAKES_RE.search(text):
        return RequestClass.HIGH_STAKES
    if _STATUS_RE.search(text):
        return RequestClass.STATUS_PROGRESS
    if _DIAGNOSIS_RE.search(text):
        return RequestClass.DIAGNOSIS
    if _PLAN_RE.search(text):
        return RequestClass.PLAN_REVIEW
    if _COMPARE_RE.search(text):
        return RequestClass.COMPARISON_OPTIONS
    if _ACTION_RE.search(text):
        return RequestClass.ACTION_CHANGE
    if _EXPLAIN_RE.search(text):
        return RequestClass.EXPLANATION
    return RequestClass.DIRECT_ANSWER


_DEFAULT_BUDGETS: dict[RequestClass, tuple[str, int, int, str, str, bool, tuple[str, ...]]] = {
    RequestClass.DIRECT_ANSWER: ("compact", 48, 384, "low", "fast", False, ("answer",)),
    RequestClass.STATUS_PROGRESS: ("compact", 48, 384, "low", "fast", False, ("current_state", "next_action")),
    RequestClass.ACTION_CHANGE: ("compact", 96, 8192, "medium", "smart", True, ("outcome", "verification")),
    RequestClass.DIAGNOSIS: ("balanced", 192, 4096, "high", "smart", True, ("evidence", "cause", "next_step")),
    RequestClass.EXPLANATION: ("balanced", 192, 1536, "medium", "smart", False, ("answer", "explanation")),
    RequestClass.COMPARISON_OPTIONS: ("balanced", 192, 1536, "medium", "smart", False, ("options", "tradeoffs", "recommendation")),
    RequestClass.PLAN_REVIEW: ("detailed", 384, 8192, "high", "smart", True, ("findings", "risks", "verification")),
    RequestClass.HIGH_STAKES: ("balanced", 256, 4096, "high", "smart", True, ("risk", "confirmation_or_boundary", "safe_next_step")),
    RequestClass.FORMAT_CONTRACT: ("preserve_user", 128, 8192, "medium", "smart", False, ("requested_format",)),
}


def build_response_envelope(
    user_message: str,
    context: RequestContext | Mapping[str, Any] | None = None,
) -> ResponseBudgetEnvelope:
    request_class = classify_request(user_message)
    verbosity, minimum, maximum, effort, tier, tools, required = _DEFAULT_BUDGETS[request_class]
    text = user_message or ""
    explicit_detail = bool(_DETAIL_RE.search(text))
    explicit_compact = bool(_COMPACT_RE.search(text))
    explicit = explicit_detail or explicit_compact or request_class == RequestClass.FORMAT_CONTRACT
    ctx = _request_context(context)

    if explicit_detail:
        verbosity, minimum, maximum = "detailed", max(minimum, 384), max(maximum, 4096)
    elif explicit_compact and request_class not in {RequestClass.HIGH_STAKES, RequestClass.FORMAT_CONTRACT}:
        verbosity, minimum, maximum = "compact", min(minimum, 64), min(maximum, 512)

    blockers: list[str] = []
    if tier == "smart":
        blockers.append(f"class:{request_class.value}")
    if ctx.has_attachments:
        blockers.append("attachments")
    if ctx.long_context:
        blockers.append("long_context")
    if ctx.recovery_turn:
        blockers.append("recovery")
    if ctx.ambiguous:
        blockers.append("ambiguity")
    if _CODE_RE.search(text) or _URL_RE.search(text):
        blockers.append("code_or_url")
    if tools and not ctx.tools_available:
        blockers.append("required_tools_unavailable")
    if blockers:
        tier = "smart"
    reason = "fast_safe:" + request_class.value if tier == "fast" else "smart_required:" + ",".join(blockers or [request_class.value])
    return ResponseBudgetEnvelope(
        version="1.0",
        request_class=request_class.value,
        verbosity=verbosity,
        soft_output_min_tokens=minimum,
        soft_output_max_tokens=maximum,
        reasoning_effort=effort,
        model_tier=tier,
        tool_needed=tools,
        required_response_elements=required,
        explicit_user_override=explicit,
        routing_reason=reason,
    )


def _primary_route(primary: dict[str, Any], envelope: ResponseBudgetEnvelope, reason: str) -> dict[str, Any]:
    return {
        "model": primary.get("model"),
        "runtime": {
            "api_key": primary.get("api_key"),
            "base_url": primary.get("base_url"),
            "provider": primary.get("provider"),
            "api_mode": primary.get("api_mode"),
            "command": primary.get("command"),
            "args": list(primary.get("args") or []),
            "credential_pool": primary.get("credential_pool"),
        },
        "label": None,
        "routing_reason": reason,
        "response_envelope": envelope.as_dict(),
        "signature": (
            primary.get("model"), primary.get("provider"), primary.get("base_url"),
            primary.get("api_mode"), primary.get("command"), tuple(primary.get("args") or ()),
        ),
    }


def choose_cheap_model_route(
    user_message: str,
    routing_config: dict[str, Any] | None,
    context: RequestContext | Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    cfg = routing_config or {}
    if not _coerce_bool(cfg.get("enabled"), False):
        return None
    envelope = build_response_envelope(user_message, context)
    if envelope.model_tier != "fast":
        return None

    cheap_model = cfg.get("cheap_model") or {}
    if not isinstance(cheap_model, dict):
        return None
    provider = str(cheap_model.get("provider") or "").strip().lower()
    model = str(cheap_model.get("model") or "").strip()
    if not provider or not model:
        return None
    text = (user_message or "").strip()
    if not text:
        return None
    if len(text) > _coerce_int(cfg.get("max_simple_chars"), 160):
        return None
    if len(text.split()) > _coerce_int(cfg.get("max_simple_words"), 28):
        return None

    capabilities = cheap_model.get("capabilities") or {}
    ctx = _request_context(context)
    if ctx.has_attachments and not capabilities.get("vision", False):
        return None
    if envelope.tool_needed and not capabilities.get("tools", True):
        return None
    route = dict(cheap_model)
    route.update({
        "provider": provider,
        "model": model,
        "routing_reason": "simple_turn",
        "response_envelope": envelope.as_dict(),
    })
    return route


def resolve_turn_route(
    user_message: str,
    routing_config: dict[str, Any] | None,
    primary: dict[str, Any],
    context: RequestContext | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    envelope = build_response_envelope(user_message, context)
    cfg = routing_config or {}
    route = choose_cheap_model_route(user_message, cfg, context)
    if not route:
        reason = "adaptive_disabled" if not _coerce_bool(cfg.get("enabled"), False) else envelope.routing_reason
        return _primary_route(primary, envelope, reason)

    from spark_cli.runtime_provider import resolve_runtime_provider

    explicit_api_key = None
    api_key_env = str(route.get("api_key_env") or "").strip()
    if api_key_env:
        explicit_api_key = os.getenv(api_key_env) or None
    try:
        runtime = resolve_runtime_provider(
            requested=route.get("provider"),
            explicit_api_key=explicit_api_key,
            explicit_base_url=route.get("base_url"),
        )
    except Exception:
        return _primary_route(primary, envelope, "fast_runtime_unavailable")

    return {
        "model": route.get("model"),
        "runtime": {
            "api_key": runtime.get("api_key"), "base_url": runtime.get("base_url"),
            "provider": runtime.get("provider"), "api_mode": runtime.get("api_mode"),
            "command": runtime.get("command"), "args": list(runtime.get("args") or []),
            "credential_pool": runtime.get("credential_pool"),
        },
        "label": f"smart route → {route.get('model')} ({runtime.get('provider')})",
        "routing_reason": route["routing_reason"],
        "response_envelope": route["response_envelope"],
        "signature": (
            route.get("model"), runtime.get("provider"), runtime.get("base_url"),
            runtime.get("api_mode"), runtime.get("command"), tuple(runtime.get("args") or ()),
        ),
    }


def response_request_overrides(route: Mapping[str, Any], provider: str | None = None) -> dict[str, Any]:
    """Translate a soft envelope to provider-safe request fields.

    The cap is a generation ceiling, never post-truncation. Existing agent-loop
    continuation logic handles genuine provider truncation.
    """
    envelope = route.get("response_envelope") or {}
    maximum = envelope.get("soft_output_max_tokens")
    if not isinstance(maximum, int) or maximum <= 0:
        return {}
    return {
        "_soft_max_output_tokens": maximum,
        "_budget_reasoning_effort": envelope.get("reasoning_effort"),
    }


def merge_route_request_overrides(
    route: dict[str, Any],
    existing: Mapping[str, Any] | None = None,
    *,
    soft_caps_enabled: bool = True,
) -> dict[str, Any]:
    """Attach internal budget controls without losing service-tier overrides."""
    merged = dict(existing or {})
    envelope = route.get("response_envelope") or {}
    has_active_envelope = bool(envelope) and route.get("routing_reason") != "adaptive_disabled"
    if soft_caps_enabled and has_active_envelope:
        merged.update(response_request_overrides(route, (route.get("runtime") or {}).get("provider")))
        merged["_routing_reason"] = route.get("routing_reason")
        merged["_request_class"] = envelope.get("request_class")
    route["request_overrides"] = merged or None
    return route
