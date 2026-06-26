"""Gateway authorization and pairing helpers."""

from __future__ import annotations

import inspect
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from gateway.config import Platform
from gateway.platforms.base import MessageEvent
from gateway.session import SessionSource

_ALLOW_TRUE_VALUES = {"true", "1", "yes"}

PLATFORM_ALLOWED_USERS_ENV: dict[Platform, str] = {
    Platform.TELEGRAM: "TELEGRAM_ALLOWED_USERS",
    Platform.DISCORD: "DISCORD_ALLOWED_USERS",
    Platform.WHATSAPP: "WHATSAPP_ALLOWED_USERS",
    Platform.SLACK: "SLACK_ALLOWED_USERS",
    Platform.SIGNAL: "SIGNAL_ALLOWED_USERS",
    Platform.EMAIL: "EMAIL_ALLOWED_USERS",
    Platform.SMS: "SMS_ALLOWED_USERS",
    Platform.MATTERMOST: "MATTERMOST_ALLOWED_USERS",
    Platform.MATRIX: "MATRIX_ALLOWED_USERS",
    Platform.DINGTALK: "DINGTALK_ALLOWED_USERS",
    Platform.FEISHU: "FEISHU_ALLOWED_USERS",
    Platform.WECOM: "WECOM_ALLOWED_USERS",
    Platform.WECOM_CALLBACK: "WECOM_CALLBACK_ALLOWED_USERS",
    Platform.WEIXIN: "WEIXIN_ALLOWED_USERS",
    Platform.BLUEBUBBLES: "BLUEBUBBLES_ALLOWED_USERS",
    Platform.QQBOT: "QQ_ALLOWED_USERS",
}

PLATFORM_ALLOW_ALL_ENV: dict[Platform, str] = {
    Platform.TELEGRAM: "TELEGRAM_ALLOW_ALL_USERS",
    Platform.DISCORD: "DISCORD_ALLOW_ALL_USERS",
    Platform.WHATSAPP: "WHATSAPP_ALLOW_ALL_USERS",
    Platform.SLACK: "SLACK_ALLOW_ALL_USERS",
    Platform.SIGNAL: "SIGNAL_ALLOW_ALL_USERS",
    Platform.EMAIL: "EMAIL_ALLOW_ALL_USERS",
    Platform.SMS: "SMS_ALLOW_ALL_USERS",
    Platform.MATTERMOST: "MATTERMOST_ALLOW_ALL_USERS",
    Platform.MATRIX: "MATRIX_ALLOW_ALL_USERS",
    Platform.DINGTALK: "DINGTALK_ALLOW_ALL_USERS",
    Platform.FEISHU: "FEISHU_ALLOW_ALL_USERS",
    Platform.WECOM: "WECOM_ALLOW_ALL_USERS",
    Platform.WECOM_CALLBACK: "WECOM_CALLBACK_ALLOW_ALL_USERS",
    Platform.WEIXIN: "WEIXIN_ALLOW_ALL_USERS",
    Platform.BLUEBUBBLES: "BLUEBUBBLES_ALLOW_ALL_USERS",
    Platform.QQBOT: "QQ_ALLOW_ALL_USERS",
}


def normalize_whatsapp_identifier(value: str) -> str:
    """Strip WhatsApp JID/LID syntax down to its stable numeric identifier."""
    return (
        str(value or "")
        .strip()
        .replace("+", "", 1)
        .split(":", 1)[0]
        .split("@", 1)[0]
    )


def expand_whatsapp_auth_aliases(identifier: str, spark_home: Path) -> set[str]:
    """Resolve WhatsApp phone/LID aliases using bridge session mapping files."""
    normalized = normalize_whatsapp_identifier(identifier)
    if not normalized:
        return set()

    session_dir = spark_home / "whatsapp" / "session"
    resolved: set[str] = set()
    queue = [normalized]

    while queue:
        current = queue.pop(0)
        if not current or current in resolved:
            continue

        resolved.add(current)
        for suffix in ("", "_reverse"):
            mapping_path = session_dir / f"lid-mapping-{current}{suffix}.json"
            if not mapping_path.exists():
                continue
            try:
                mapped = normalize_whatsapp_identifier(
                    json.loads(mapping_path.read_text(encoding="utf-8"))
                )
            except Exception:
                continue
            if mapped and mapped not in resolved:
                queue.append(mapped)

    return resolved


def is_user_authorized(
    source: SessionSource,
    *,
    pairing_store: Any,
    spark_home: Path,
) -> bool:
    """Return whether a gateway session source may use the bot."""
    if source.platform in (Platform.HOMEASSISTANT, Platform.WEBHOOK):
        return True

    user_id = source.user_id
    if not user_id:
        return False

    platform_allow_all_var = PLATFORM_ALLOW_ALL_ENV.get(source.platform, "")
    if platform_allow_all_var and os.getenv(platform_allow_all_var, "").lower() in _ALLOW_TRUE_VALUES:
        return True

    platform_name = source.platform.value if source.platform else ""
    if pairing_store.is_approved(platform_name, user_id):
        return True

    platform_allowlist = os.getenv(PLATFORM_ALLOWED_USERS_ENV.get(source.platform, ""), "").strip()
    global_allowlist = os.getenv("GATEWAY_ALLOWED_USERS", "").strip()

    if not platform_allowlist and not global_allowlist:
        return os.getenv("GATEWAY_ALLOW_ALL_USERS", "").lower() in _ALLOW_TRUE_VALUES

    allowed_ids: set[str] = set()
    if platform_allowlist:
        allowed_ids.update(uid.strip() for uid in platform_allowlist.split(",") if uid.strip())
    if global_allowlist:
        allowed_ids.update(uid.strip() for uid in global_allowlist.split(",") if uid.strip())

    if "*" in allowed_ids:
        return True

    check_ids = {user_id}
    if "@" in user_id:
        check_ids.add(user_id.split("@")[0])

    if source.platform == Platform.WHATSAPP:
        normalized_allowed_ids: set[str] = set()
        for allowed_id in allowed_ids:
            normalized_allowed_ids.update(expand_whatsapp_auth_aliases(allowed_id, spark_home))
        if normalized_allowed_ids:
            allowed_ids = normalized_allowed_ids

        check_ids.update(expand_whatsapp_auth_aliases(user_id, spark_home))
        normalized_user_id = normalize_whatsapp_identifier(user_id)
        if normalized_user_id:
            check_ids.add(normalized_user_id)

    return bool(check_ids & allowed_ids)


def get_unauthorized_dm_behavior(config: Any, platform: Platform | None) -> str:
    """Return how unauthorized DMs should be handled for a platform."""
    if config and hasattr(config, "get_unauthorized_dm_behavior"):
        return config.get_unauthorized_dm_behavior(platform)
    return "pair"


async def check_inbound_authorization(
    event: MessageEvent,
    *,
    is_authorized: Callable[[SessionSource], bool],
    get_dm_behavior: Callable[[Platform | None], str],
    pairing_store: Any,
    adapters: dict[Platform, Any],
    logger: Any,
) -> bool:
    """Authorize an inbound event and handle unauthorized DM pairing replies."""
    source = event.source

    if getattr(event, "internal", False):
        return True

    if source.user_id is None:
        logger.debug("Ignoring message with no user_id from %s", source.platform.value)
        return False

    if is_authorized(source):
        return True

    logger.warning("Unauthorized user: %s (%s) on %s", source.user_id, source.user_name, source.platform.value)
    if pairing_store is None:
        return False
    if source.chat_type != "dm" or get_dm_behavior(source.platform) != "pair":
        return False

    platform_name = source.platform.value if source.platform else "unknown"
    if pairing_store._is_rate_limited(platform_name, source.user_id):
        return False

    code = pairing_store.generate_code(platform_name, source.user_id, source.user_name or "")
    adapter = adapters.get(source.platform)
    if code:
        if adapter:
            send_result = adapter.send(
                source.chat_id,
                f"Hi~ I don't recognize you yet!\n\n"
                f"Here's your pairing code: `{code}`\n\n"
                f"Ask the bot owner to run:\n"
                f"`spark pairing approve {platform_name} {code}`",
            )
            if inspect.isawaitable(send_result):
                await send_result
    else:
        if adapter:
            send_result = adapter.send(
                source.chat_id,
                "Too many pairing requests right now~ Please try again later!",
            )
            if inspect.isawaitable(send_result):
                await send_result
        pairing_store._record_rate_limit(platform_name, source.user_id)

    return False
