"""Gateway-side Kanban notification and wake workflow."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from core.spark_constants import get_spark_home
from gateway.config import GatewayConfig, Platform
from gateway.delivery import DeliveryRouter, DeliveryTarget
from gateway.platforms.base import MessageEvent, MessageType
from gateway.session import SessionSource

logger = logging.getLogger(__name__)

_STATUS_EVENT_KINDS = frozenset({"status", "completed", "blocked", "unblocked"})
_WORKFLOW_EVENT_KINDS = _STATUS_EVENT_KINDS | {"comment"}


def _truthy(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
        return default
    return bool(value)


def _cursor_path() -> Path:
    return get_spark_home() / "kanban_workflow_cursor.json"


def _load_cursor() -> int:
    path = _cursor_path()
    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return int(data.get("last_event_id", 0) or 0)
    except Exception:
        logger.debug("Ignoring unreadable Kanban workflow cursor at %s", path)
        return 0


def _save_cursor(event_id: int) -> None:
    path = _cursor_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"last_event_id": int(event_id)}, indent=2), encoding="utf-8")
    tmp.replace(path)


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    raw = event.get("payload_json")
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(str(raw))
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _task_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    task = payload.get("task")
    return task if isinstance(task, dict) else {}


def _origin_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    origin = payload.get("origin")
    return origin if isinstance(origin, dict) else {}


def _select_delivery_target(
    *,
    payload: dict[str, Any],
    gateway_config: GatewayConfig,
    adapters: dict[Platform, Any],
) -> tuple[DeliveryTarget | None, str | None]:
    task = _task_from_payload(payload)
    platform_name = str(task.get("owner_platform") or "").strip()
    chat_id = str(task.get("owner_channel") or "").strip()
    thread_id = str(task.get("owner_thread_id") or "").strip() or None

    platform: Platform | None = None
    if platform_name:
        try:
            platform = Platform(platform_name)
        except ValueError:
            return None, f"unknown owner platform {platform_name!r}"

    if platform is None:
        for candidate in adapters:
            home = gateway_config.get_home_channel(candidate)
            if home:
                platform = candidate
                chat_id = home.chat_id
                break

    if platform is None:
        return None, "no configured owner platform or home channel"

    if not chat_id:
        home = gateway_config.get_home_channel(platform)
        if home:
            chat_id = home.chat_id

    if platform != Platform.LOCAL and not chat_id:
        return None, f"no chat id for {platform.value}"

    return (
        DeliveryTarget(
            platform=platform,
            chat_id=chat_id or None,
            thread_id=thread_id,
            is_explicit=bool(chat_id),
        ),
        None,
    )


def _format_notification(event: dict[str, Any], payload: dict[str, Any]) -> str:
    task = _task_from_payload(payload)
    title = task.get("title") or event.get("task_id") or "Kanban card"
    task_id = task.get("id") or event.get("task_id") or ""
    kind = str(event.get("kind") or "")
    lines = [
        "Kanban card changed",
        f"Task: {title} ({task_id})",
    ]
    if kind in _STATUS_EVENT_KINDS:
        before = payload.get("from") or "unknown"
        after = payload.get("to") or payload.get("status") or "unknown"
        lines.append(f"Status: {before} -> {after}")
    elif kind == "comment":
        author = payload.get("author") or "someone"
        body = str(payload.get("body") or "").strip()
        preview = body if len(body) <= 300 else body[:297] + "..."
        lines.append(f"Comment from {author}: {preview}")
    else:
        lines.append(f"Event: {kind}")
    return "\n".join(lines)


async def _notify_owner(
    *,
    event: dict[str, Any],
    payload: dict[str, Any],
    gateway_config: GatewayConfig,
    adapters: dict[Platform, Any],
    delivery_router: DeliveryRouter,
) -> dict[str, Any]:
    target, error = _select_delivery_target(
        payload=payload,
        gateway_config=gateway_config,
        adapters=adapters,
    )
    if not target:
        return {"sent": False, "reason": error or "no target"}

    content = _format_notification(event, payload)
    result = await delivery_router.deliver(
        content,
        [target],
        job_id=f"kanban-{event.get('id')}",
        job_name="Kanban workflow",
        metadata={"event_id": event.get("id"), "task_id": event.get("task_id")},
    )
    target_result = result.get(target.to_string(), {})
    return {
        "sent": bool(target_result.get("success")),
        "target": target.to_string(),
        "result": target_result,
    }


def _creator_source(payload: dict[str, Any]) -> tuple[str | None, SessionSource | None]:
    task = _task_from_payload(payload)
    session_key = str(task.get("creator_session_key") or "").strip()
    raw_source = task.get("creator_session_source_json") or "{}"
    if isinstance(raw_source, dict):
        source_data = raw_source
    else:
        try:
            source_data = json.loads(str(raw_source))
        except json.JSONDecodeError:
            source_data = {}
    if not session_key or not source_data:
        return session_key or None, None
    try:
        return session_key, SessionSource.from_dict(source_data)
    except Exception as exc:
        logger.debug("Invalid Kanban creator session source: %s", exc)
        return session_key, None


async def _wake_creator(
    *,
    event: dict[str, Any],
    payload: dict[str, Any],
    adapters: dict[Platform, Any],
) -> dict[str, Any]:
    origin = _origin_from_payload(payload)
    creator_key, source = _creator_source(payload)
    if not creator_key or not source:
        return {"woke": False, "reason": "missing creator session"}
    if origin.get("session_key") == creator_key:
        return {"woke": False, "reason": "self wake suppressed"}
    if origin.get("internal") or origin.get("kind") == "kanban_workflow":
        return {"woke": False, "reason": "internal workflow event suppressed"}

    adapter = adapters.get(source.platform)
    if not adapter:
        return {"woke": False, "reason": f"no adapter for {source.platform.value}"}

    task = _task_from_payload(payload)
    title = task.get("title") or event.get("task_id") or "Kanban card"
    task_id = task.get("id") or event.get("task_id") or ""
    event_kind = event.get("kind") or "event"
    text = (
        "[Kanban wake]\n"
        f"Task: {title} ({task_id})\n"
        f"Event: {event_kind}\n"
        "Continue only if the card change requires action. "
        "Do not update the card just to acknowledge this wake event."
    )
    wake_event = MessageEvent(
        text=text,
        message_type=MessageType.TEXT,
        source=source,
        message_id=f"kanban:{event.get('id')}",
        internal=True,
    )
    await adapter.handle_message(wake_event)
    return {"woke": True, "session_key": creator_key}


async def run_workflow_tick(
    *,
    gateway_config: GatewayConfig,
    adapters: dict[Platform, Any],
    delivery_router: DeliveryRouter,
    kanban_config: dict[str, Any],
    max_events: int = 100,
) -> dict[str, Any]:
    """Process profile-local Kanban events after the saved cursor."""
    from core import kanban_db as kb

    notify_enabled = _truthy(kanban_config.get("notify_on_changes"), False)
    wake_enabled = _truthy(kanban_config.get("wake_creator_on_changes"), False)

    since = _load_cursor()
    events = kb.append_events_since(since, limit=max_events)
    processed = 0
    notified = 0
    woke = 0
    skipped = 0
    last_seen = since

    for event in events:
        event_id = int(event.get("id") or 0)
        last_seen = max(last_seen, event_id)
        kind = str(event.get("kind") or "")
        if kind not in _WORKFLOW_EVENT_KINDS:
            skipped += 1
            _save_cursor(last_seen)
            continue

        payload = _payload(event)
        origin = _origin_from_payload(payload)
        if origin.get("internal") or origin.get("kind") == "kanban_workflow":
            skipped += 1
            _save_cursor(last_seen)
            continue

        task = _task_from_payload(payload)
        should_notify = notify_enabled or _truthy(task.get("notify_on_changes"), False)
        should_wake = wake_enabled or _truthy(task.get("wake_on_changes"), False)

        if should_notify:
            result = await _notify_owner(
                event=event,
                payload=payload,
                gateway_config=gateway_config,
                adapters=adapters,
                delivery_router=delivery_router,
            )
            if result.get("sent"):
                notified += 1

        if should_wake:
            result = await _wake_creator(event=event, payload=payload, adapters=adapters)
            if result.get("woke"):
                woke += 1

        processed += 1
        _save_cursor(last_seen)

    if not events and last_seen != since:
        _save_cursor(last_seen)

    return {
        "ok": True,
        "processed": processed,
        "notified": notified,
        "woke": woke,
        "skipped": skipped,
        "last_event_id": last_seen,
    }
