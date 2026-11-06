"""Read-only routing explanations and validation for existing settings paths.

Never classify a historical prompt again: only the route recorded by its owner
can explain a turn. Credentials and runtime internals are never returned.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit, urlunsplit

if TYPE_CHECKING:
    from core.spark_state import SessionDB

from spark_cli.model_config import AUTO_ROLE_NAMES, read_auto_policy, read_global_model_config
from spark_cli.onboarding_validation import normalize_http_base_url, normalize_model_name
from spark_cli.provider_catalog import provider_catalog


def _public_endpoint(value: str) -> str:
    try:
        parts = urlsplit(value)
        # Authentication belongs in credential storage, never this read API.
        return urlunsplit((parts.scheme, parts.netloc.rsplit("@", 1)[-1], parts.path, "", ""))
    except ValueError:
        return ""


def routing_settings(config: dict[str, Any]) -> dict[str, Any]:
    providers = {entry["id"]: entry for entry in provider_catalog(config)["providers"]}
    roles = {}
    for name, target in read_auto_policy(config).roles.items():
        provider = providers.get(target.provider)
        credential = provider["credential"] if provider else None
        present = bool(credential and credential["configured"])
        roles[name] = {
            **target.as_dict(),
            "base_url": _public_endpoint(target.base_url),
            "credential_presence": "present" if present else "not_detected" if credential else "unknown",
            "credential_required": bool(credential and credential["mechanism"] == "api_key"),
            "availability": "unknown",
            "capabilities": {"tools": "unknown", "vision": "unknown", "reasoning": "unknown"},
        }
    return {"schema_version": 1, "selection": read_global_model_config(config).selection,
            "roles": roles, "applies_to": "future_turn"}


def validate_role_settings(value: Any) -> dict[str, Any]:
    """Validate editable role routes with the existing model/endpoint validators.

    Preserve policy parameters and unknown metadata; this editor does not tune
    weights, fallback policy, response budgets or provider resolution.
    """
    if not isinstance(value, dict) or not isinstance(value.get("roles"), dict):
        raise ValueError("Auto roles must be an object")
    result = deepcopy(value)
    for name, target in result["roles"].items():
        if name not in AUTO_ROLE_NAMES or not isinstance(target, dict):
            raise ValueError("Unknown Auto role or invalid route")
        if target.get("model"):
            target["model"] = normalize_model_name(target["model"], field_name=f"{name} model")
        if target.get("base_url"):
            target["base_url"] = normalize_http_base_url(target["base_url"], field_name=f"{name} base URL")
        for field in ("provider", "reasoning_effort", "api_mode"):
            if field in target and (not isinstance(target[field], str) or len(target[field]) > 256
                                    or any(ord(c) < 32 for c in target[field])):
                raise ValueError(f"Invalid {name} {field}")
    return result


def _text(value: Any, limit: int = 512) -> str | None:
    return value[:limit] if isinstance(value, str) and value else None


def recorded_turn_route(row: Mapping[str, Any]) -> dict[str, Any]:
    projection = row.get("projection")
    projection = projection if isinstance(projection, Mapping) else {}
    summary = projection.get("timing_summary")
    summary = summary if isinstance(summary, Mapping) else {}
    stored = projection.get("route")
    stored = stored if isinstance(stored, Mapping) else {}
    # SP15 owns the optional timing_summary fields. Older stored routes remain
    # readable; absence means unknown, never a prediction using today's config.
    decision = summary.get("routing_decision") or stored.get("routing_decision") or projection.get("routing_decision")
    decision = decision if isinstance(decision, Mapping) else {}
    reason = _text(summary.get("routing_reason")) or _text(stored.get("routing_reason")) or _text(projection.get("routing_reason"))
    runtime = stored.get("runtime")
    runtime = runtime if isinstance(runtime, Mapping) else {}
    signals = decision.get("signals")
    signals = signals if isinstance(signals, Mapping) else {}
    safe_signals = {
        str(key)[:80]: value[:500] if isinstance(value, str) else value
        for key, value in list(signals.items())[:32]
        if (isinstance(value, (bool, int)) and abs(value) < 1_000_000)
        or (key in {"task_class", "risk", "duration", "explicit_choice"} and isinstance(value, str))
    }
    safe_decision = None
    if decision:
        scores = decision.get("scores")
        safe_decision = {
            "role": _text(decision.get("role")), "desired_role": _text(decision.get("desired_role")),
            "reason": _text(decision.get("reason")), "signals": safe_signals,
            "scores": {str(key)[:80]: score for key, score in (list(scores.items())[:32] if isinstance(scores, Mapping) else [])
                       if isinstance(score, (bool, int)) and abs(score) < 1_000_000},
        }
    return {"turn_id": row["turn_id"], "session_id": row["session_id"],
            "status": "recorded" if reason or safe_decision else "unknown",
            "model": _text(summary.get("model")) or _text(stored.get("model")) or _text(projection.get("model")),
            "provider": _text(summary.get("provider")) or _text(runtime.get("provider")) or _text(projection.get("provider")),
            "role": _text(summary.get("role")) or _text(stored.get("role")) or _text(projection.get("role")),
            "routing_reason": reason, "routing_decision": safe_decision}


def read_recorded_routes(db: SessionDB, session_id: str) -> list[dict[str, Any]]:
    """Bound row retrieval without adding a second durable writer/schema.

    Project just the route fields inside SQLite, so transcript/tool output and
    runtime credentials never cross this read boundary, even for large turns.
    """
    lineage = db.resolve_compression_chain(session_id)
    placeholders = ",".join("?" for _ in lineage)
    with db._lock:
        rows = db._conn.execute(
            f"""SELECT turn_id, session_id,
                json_object(
                    'timing_summary', json_object(
                        'routing_decision', json_extract(projection_json, '$.timing_summary.routing_decision'),
                        'routing_reason', json_extract(projection_json, '$.timing_summary.routing_reason'),
                        'model', json_extract(projection_json, '$.timing_summary.model'),
                        'role', json_extract(projection_json, '$.timing_summary.role'),
                        'provider', json_extract(projection_json, '$.timing_summary.provider')),
                    'route', json_object(
                        'routing_decision', json_extract(projection_json, '$.route.routing_decision'),
                        'routing_reason', json_extract(projection_json, '$.route.routing_reason'),
                        'model', json_extract(projection_json, '$.route.model'),
                        'role', json_extract(projection_json, '$.route.role'),
                        'runtime', json_object('provider', json_extract(projection_json, '$.route.runtime.provider'))),
                    'routing_decision', json_extract(projection_json, '$.routing_decision'),
                    'routing_reason', json_extract(projection_json, '$.routing_reason'),
                    'model', json_extract(projection_json, '$.model'),
                    'role', json_extract(projection_json, '$.role'),
                    'provider', json_extract(projection_json, '$.provider')
                ) AS route_json
                FROM web_turn_projections WHERE session_id IN ({placeholders})
                ORDER BY updated_at DESC, turn_id DESC LIMIT 50""",
            lineage,
        ).fetchall()
    return [recorded_turn_route({"turn_id": row["turn_id"], "session_id": row["session_id"],
                                 "projection": json.loads(row["route_json"])}) for row in reversed(rows)]
