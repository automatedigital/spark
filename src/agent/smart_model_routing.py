"""Deterministic request classification, response budgets, and model routing."""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from core.utils import is_truthy_value
from spark_cli.model_config import AUTO_ROLE_NAMES

logger = logging.getLogger(__name__)


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
    task_class: str = ""
    tool_need: bool | None = None
    context_tokens: int = 0
    risk: str = ""
    duration: str = ""
    explicit_model: str = ""
    pinned_model: bool = False
    previous_role: str = ""
    is_subagent: bool = False


@dataclass(frozen=True)
class RoutingSignals:
    """Observable, deterministic inputs to the Auto policy."""

    task_class: str
    tool_need: bool
    context_tokens: int
    has_attachments: bool
    risk: str
    duration: str
    explicit_choice: str
    is_subagent: bool


@dataclass(frozen=True)
class AutoRoutingDecision:
    role: str
    desired_role: str
    signals: RoutingSignals
    reason: str
    scores: Mapping[str, int]

    def as_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "desired_role": self.desired_role,
            "signals": asdict(self.signals),
            "reason": self.reason,
            "scores": dict(self.scores),
        }


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
        task_class=str(raw.get("task_class") or "").strip(),
        tool_need=(None if raw.get("tool_need") is None else bool(raw.get("tool_need"))),
        context_tokens=_coerce_int(raw.get("context_tokens"), 0),
        risk=str(raw.get("risk") or "").strip().lower(),
        duration=str(raw.get("duration") or "").strip().lower(),
        explicit_model=str(raw.get("explicit_model") or raw.get("explicit_choice") or "").strip(),
        pinned_model=bool(raw.get("pinned_model")),
        previous_role=str(raw.get("previous_role") or raw.get("current_role") or "").strip().lower(),
        is_subagent=bool(raw.get("is_subagent")),
    )


def classify_request(
    user_message: str,
    context: RequestContext | Mapping[str, Any] | None = None,
) -> RequestClass:
    """Classify locally with risk/format gates taking priority over convenience."""
    text = (user_message or "").strip()
    ctx = _request_context(context)
    if ctx.task_class:
        try:
            return RequestClass(ctx.task_class)
        except ValueError:
            logger.debug("Ignoring error in classify_request()", exc_info=True)
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


def classify_routing_signals(
    user_message: str,
    context: RequestContext | Mapping[str, Any] | None = None,
    *,
    context_threshold: int = 24_000,
) -> RoutingSignals:
    """Classify every policy input without model calls or provider metadata."""
    ctx = _request_context(context)
    text = (user_message or "").strip()
    request_class = classify_request(text, ctx).value
    tool_need = ctx.tool_need
    if tool_need is None:
        tool_need = bool(_DEFAULT_BUDGETS[RequestClass(request_class)][5])
        tool_need = bool(tool_need or _ACTION_RE.search(text) or _CODE_RE.search(text))
    risk = ctx.risk if ctx.risk in {"low", "medium", "high", "critical"} else "low"
    if risk == "low" and (_DESTRUCTIVE_RE.search(text) or _HIGH_STAKES_RE.search(text)):
        risk = "high"
    if risk == "low" and (ctx.ambiguous or ctx.recovery_turn):
        risk = "medium"
    context_tokens = max(0, ctx.context_tokens)
    if context_tokens >= context_threshold:
        duration = "long"
    elif ctx.duration in {"short", "medium", "long"}:
        duration = ctx.duration
    else:
        duration = "long" if len(text) >= 2_000 or len(text.split()) >= 350 else "short"
    return RoutingSignals(
        task_class=request_class,
        tool_need=bool(tool_need),
        context_tokens=context_tokens,
        has_attachments=ctx.has_attachments,
        risk=risk,
        duration=duration,
        explicit_choice=ctx.explicit_model,
        is_subagent=ctx.is_subagent,
    )


def _auto_scores(signals: RoutingSignals) -> dict[str, int]:
    scores = {"lead": 0, "balanced": 1, "fast": 0, "subagent": -100}
    if signals.task_class in {RequestClass.DIRECT_ANSWER.value, RequestClass.STATUS_PROGRESS.value}:
        scores["fast"] += 4
    elif signals.task_class in {RequestClass.EXPLANATION.value, RequestClass.COMPARISON_OPTIONS.value}:
        scores["balanced"] += 3
    else:
        scores["lead"] += 4
    if signals.tool_need:
        scores["balanced"] += 2
        scores["lead"] += 3
    if signals.has_attachments:
        scores["balanced"] += 2
        scores["lead"] += 2
    if signals.context_tokens >= 24_000 or signals.duration == "long":
        scores["lead"] += 3
    if signals.risk in {"high", "critical"}:
        scores["lead"] += 100
    elif signals.risk == "medium":
        scores["lead"] += 3
    if signals.is_subagent:
        scores["subagent"] = scores["lead"] + 2
    else:
        scores["subagent"] = -100
    return scores


def choose_auto_role(
    user_message: str,
    context: RequestContext | Mapping[str, Any] | None = None,
    *,
    hysteresis_margin: int = 2,
    context_threshold: int = 24_000,
) -> AutoRoutingDecision:
    """Choose a role with sticky hysteresis and a safety-first escalation gate."""
    ctx = _request_context(context)
    signals = classify_routing_signals(user_message, ctx, context_threshold=context_threshold)
    scores = _auto_scores(signals)
    desired = max(("lead", "balanced", "fast", "subagent"), key=lambda role: scores[role])
    previous = ctx.previous_role if ctx.previous_role in scores else ""
    if signals.is_subagent and previous in {"lead", "balanced", "fast"} and desired == "subagent":
        previous = ""
    if signals.risk in {"high", "critical"}:
        role = "lead"
        reason = "high_risk_floor"
    elif previous and previous != desired and scores[desired] - scores[previous] < max(0, hysteresis_margin):
        role = previous
        reason = "sticky_hysteresis"
    else:
        role = desired
        reason = "classified_signals"
    return AutoRoutingDecision(role, desired, signals, reason, scores)


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


def _catalog_entries(available_catalog: Any) -> list[Mapping[str, Any]]:
    """Normalize the account catalog without manufacturing availability."""
    if available_catalog is None:
        return []
    if isinstance(available_catalog, Mapping):
        if isinstance(available_catalog.get("models"), (list, tuple)):
            available_catalog = available_catalog["models"]
        else:
            flattened: list[Mapping[str, Any]] = []
            for provider, values in available_catalog.items():
                if isinstance(values, Mapping):
                    values = [values]
                if isinstance(values, (list, tuple)):
                    for value in values:
                        if isinstance(value, Mapping):
                            item = dict(value)
                            item.setdefault("provider", provider)
                            flattened.append(item)
            return flattened
    if isinstance(available_catalog, (list, tuple)):
        return [value for value in available_catalog if isinstance(value, Mapping)]
    return []


def _catalog_match(target: Any, catalog: Any, role: str) -> Mapping[str, Any] | None:
    entries = _catalog_entries(catalog)
    if not entries:
        return None
    target_provider = str(getattr(target, "provider", "") or "").strip().lower()
    target_model = str(getattr(target, "model", "") or "").strip()
    exact: list[Mapping[str, Any]] = []
    role_matches: list[Mapping[str, Any]] = []
    for entry in entries:
        provider = str(entry.get("provider") or entry.get("provider_id") or "").strip().lower()
        model = str(entry.get("model") or entry.get("slug") or entry.get("id") or "").strip()
        if target_model and model == target_model and (not target_provider or provider == target_provider):
            exact.append(entry)
        roles = entry.get("roles") or entry.get("role") or ()
        if isinstance(roles, str):
            roles = (roles,)
        if role in {str(value).strip().lower() for value in roles}:
            role_matches.append(entry)
    if exact:
        return exact[0]
    if not target_model and role_matches:
        return role_matches[0]
    return None


def resolve_auto_target(
    policy: Any,
    role: str,
    available_catalog: Any = None,
) -> dict[str, Any] | None:
    """Resolve a role target through the supplied catalog and role fallbacks."""
    from spark_cli.model_config import AutoPolicy, read_auto_policy

    policy_obj = policy if isinstance(policy, AutoPolicy) else read_auto_policy({"model": {"auto": policy}})
    visited: set[str] = set()

    def visit(role_name: str) -> dict[str, Any] | None:
        if role_name in visited or role_name not in AUTO_ROLE_NAMES:
            return None
        visited.add(role_name)
        target = policy_obj.role(role_name)
        entry = _catalog_match(target, available_catalog, role_name)
        target_has_preference = bool(target.provider or target.model)
        if target_has_preference and available_catalog is not None and entry is None:
            entry = None
        elif not target_has_preference and available_catalog is not None and entry is None:
            entry = None
        if target_has_preference and (available_catalog is None or entry is not None):
            provider = target.provider
            model = target.model
            if entry:
                provider = provider or str(entry.get("provider") or entry.get("provider_id") or "").strip().lower()
                model = model or str(entry.get("model") or entry.get("slug") or entry.get("id") or "").strip()
            effort = target.reasoning_effort
            if entry and effort:
                supported = entry.get("reasoning_efforts") or entry.get("supported_reasoning_efforts") or ()
                if supported and effort not in supported:
                    effort = str(entry.get("default_reasoning_effort") or supported[0])
            elif entry and not effort:
                effort = str(entry.get("default_reasoning_effort") or "")
            return {
                "role": role_name,
                "provider": provider,
                "model": model,
                "reasoning_effort": effort,
                "fallback": list(target.fallback),
                "base_url": target.base_url,
                "api_mode": target.api_mode,
                "catalog_entry": dict(entry) if entry else None,
            }
        for fallback in target.fallback:
            resolved = visit(fallback)
            if resolved is not None:
                resolved["fallback_from"] = role_name
                return resolved
        return None

    return visit(str(role).strip().lower())


def _auto_policy_from_routing_config(config: Mapping[str, Any]) -> Any:
    from spark_cli.model_config import read_auto_policy

    auto = config.get("auto")
    if isinstance(auto, Mapping):
        projected = {"model": {"auto": dict(auto)}, "smart_model_routing": dict(config)}
    elif config.get("policy") == "auto" or isinstance(config.get("roles"), Mapping):
        projected = {"model": {"auto": dict(config)}, "smart_model_routing": dict(config)}
    else:
        projected = {"smart_model_routing": dict(config)}
    return read_auto_policy(projected)


def _auto_route_enabled(config: Mapping[str, Any]) -> bool:
    auto = config.get("auto")
    if isinstance(auto, Mapping):
        return bool(auto.get("enabled", True))
    return config.get("policy") == "auto" or isinstance(config.get("roles"), Mapping)


def resolve_auto_route(
    user_message: str,
    routing_config: Mapping[str, Any],
    primary: dict[str, Any],
    context: RequestContext | Mapping[str, Any] | None = None,
    *,
    available_catalog: Any = None,
    explicit_model: str | None = None,
    previous_role: str | None = None,
) -> dict[str, Any]:
    """Resolve one Auto turn; explicit model choices bypass policy routing."""
    ctx = _request_context(context)
    if explicit_model is not None:
        ctx = RequestContext(**{**asdict(ctx), "explicit_model": explicit_model})
    if previous_role is not None:
        ctx = RequestContext(**{**asdict(ctx), "previous_role": previous_role})
    envelope = build_response_envelope(user_message, ctx)
    explicit = ctx.explicit_model.strip()
    if not explicit and ctx.pinned_model:
        route = _primary_route(primary, envelope, "explicit_model_pinned")
        route["role"] = "pinned"
        route["label"] = f"Pinned · {primary.get('model') or 'configured model'}"
        route["pinned"] = True
        return route
    if explicit and explicit.lower() != "auto":
        route = _primary_route(primary, envelope, "explicit_model_pinned")
        route["model"] = explicit
        route["role"] = "pinned"
        route["label"] = f"Pinned · {explicit}"
        route["pinned"] = True
        return route

    policy = _auto_policy_from_routing_config(routing_config)
    decision = choose_auto_role(
        user_message,
        ctx,
        hysteresis_margin=policy.hysteresis_margin,
        context_threshold=policy.context_threshold,
    )
    target = resolve_auto_target(policy, decision.role, available_catalog)
    if target is None:
        route = _primary_route(primary, envelope, f"auto_fallback:{decision.reason}")
        route["role"] = decision.role
        route["label"] = f"Auto · {decision.role} · primary fallback"
        route["routing_decision"] = decision.as_dict()
        return route

    same_runtime = (
        target["model"] == primary.get("model")
        and (not target["provider"] or target["provider"] == str(primary.get("provider") or "").lower())
    )
    if same_runtime or not target["provider"]:
        route = _primary_route(primary, envelope, f"auto:{decision.role}:{decision.reason}")
        route["model"] = target["model"] or primary.get("model")
        route["role"] = decision.role
        route["reasoning_effort"] = target["reasoning_effort"]
        route["fallback"] = target["fallback"]
        route["label"] = f"Auto · {decision.role}"
        route["routing_decision"] = decision.as_dict()
        return route

    from spark_cli.runtime_provider import resolve_runtime_provider

    try:
        runtime = resolve_runtime_provider(
            requested=target["provider"],
            explicit_base_url=target.get("base_url") or None,
        )
    except Exception:
        route = _primary_route(primary, envelope, f"auto_fallback:{decision.role}:runtime_unavailable")
        route["role"] = decision.role
        route["label"] = f"Auto · {decision.role} · primary fallback"
        route["routing_decision"] = decision.as_dict()
        return route
    return {
        "model": target["model"],
        "runtime": {
            "api_key": runtime.get("api_key"),
            "base_url": runtime.get("base_url"),
            "provider": runtime.get("provider"),
            "api_mode": runtime.get("api_mode"),
            "command": runtime.get("command"),
            "args": list(runtime.get("args") or []),
            "credential_pool": runtime.get("credential_pool"),
        },
        "label": f"Auto · {decision.role}",
        "role": decision.role,
        "reasoning_effort": target["reasoning_effort"],
        "fallback": target["fallback"],
        "routing_reason": f"auto:{decision.role}:{decision.reason}",
        "routing_decision": decision.as_dict(),
        "response_envelope": envelope.as_dict(),
        "signature": (
            target["model"], runtime.get("provider"), runtime.get("base_url"),
            runtime.get("api_mode"), runtime.get("command"), tuple(runtime.get("args") or ()),
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
    *,
    available_catalog: Any = None,
    explicit_model: str | None = None,
    previous_role: str | None = None,
) -> dict[str, Any]:
    cfg = routing_config or {}
    if _auto_route_enabled(cfg):
        return resolve_auto_route(
            user_message,
            cfg,
            primary,
            context,
            available_catalog=available_catalog,
            explicit_model=explicit_model,
            previous_role=previous_role,
        )
    envelope = build_response_envelope(user_message, context)
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
        "_budget_reasoning_effort": route.get("reasoning_effort")
        or envelope.get("reasoning_effort"),
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
