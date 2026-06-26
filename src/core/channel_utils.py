"""
Shared channel/target-ref parsing helpers.

Lives in core so both tools.send_message_tool and cron.scheduler can import
without risk of a circular dependency.
"""

import re

_TELEGRAM_TOPIC_TARGET_RE = re.compile(r"^\s*(-?\d+)(?::(\d+))?\s*$")
_FEISHU_TARGET_RE = re.compile(
    r"^\s*((?:oc|ou|on|chat|open)_[-A-Za-z0-9]+)(?::([-A-Za-z0-9_]+))?\s*$"
)
_WEIXIN_TARGET_RE = re.compile(
    r"^\s*((?:wxid|gh|v\d+|wm|wb)_[A-Za-z0-9_-]+|[A-Za-z0-9._-]+@chatroom|filehelper)\s*$"
)
_NUMERIC_TOPIC_RE = _TELEGRAM_TOPIC_TARGET_RE


def parse_target_ref(
    platform_name: str, target_ref: str
) -> tuple[str | None, str | None, bool]:
    """Parse a send-message target into (chat_id, thread_id, is_explicit)."""
    if platform_name == "telegram":
        match = _TELEGRAM_TOPIC_TARGET_RE.fullmatch(target_ref)
        if match:
            return match.group(1), match.group(2), True
    if platform_name == "feishu":
        match = _FEISHU_TARGET_RE.fullmatch(target_ref)
        if match:
            return match.group(1), match.group(2), True
    if platform_name == "discord":
        match = _NUMERIC_TOPIC_RE.fullmatch(target_ref)
        if match:
            return match.group(1), match.group(2), True
    if platform_name == "weixin":
        match = _WEIXIN_TARGET_RE.fullmatch(target_ref)
        if match:
            return match.group(1), None, True
    if target_ref.lstrip("-").isdigit():
        return target_ref, None, True
    return None, None, False
