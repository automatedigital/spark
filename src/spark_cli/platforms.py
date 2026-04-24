"""
Shared platform registry for Spark Agent.

Single source of truth for platform metadata consumed by both
skills_config (label display) and tools_config (default toolset
resolution).  Import ``PLATFORMS`` from here instead of maintaining
duplicate dicts in each module.
"""

from collections import OrderedDict
from typing import NamedTuple


class PlatformInfo(NamedTuple):
    """Metadata for a single platform entry."""
    label: str
    default_toolset: str


# Ordered so that TUI menus are deterministic.
PLATFORMS: OrderedDict[str, PlatformInfo] = OrderedDict([
    ("cli",            PlatformInfo(label="🖥️  CLI",            default_toolset="spark-cli")),
    ("telegram",       PlatformInfo(label="📱 Telegram",        default_toolset="spark-telegram")),
    ("discord",        PlatformInfo(label="💬 Discord",         default_toolset="spark-discord")),
    ("slack",          PlatformInfo(label="💼 Slack",           default_toolset="spark-slack")),
    ("whatsapp",       PlatformInfo(label="📱 WhatsApp",        default_toolset="spark-whatsapp")),
    ("signal",         PlatformInfo(label="📡 Signal",          default_toolset="spark-signal")),
    ("bluebubbles",    PlatformInfo(label="💙 BlueBubbles",     default_toolset="spark-bluebubbles")),
    ("email",          PlatformInfo(label="📧 Email",           default_toolset="spark-email")),
    ("homeassistant",  PlatformInfo(label="🏠 Home Assistant",  default_toolset="spark-homeassistant")),
    ("mattermost",     PlatformInfo(label="💬 Mattermost",      default_toolset="spark-mattermost")),
    ("matrix",         PlatformInfo(label="💬 Matrix",          default_toolset="spark-matrix")),
    ("dingtalk",       PlatformInfo(label="💬 DingTalk",        default_toolset="spark-dingtalk")),
    ("feishu",         PlatformInfo(label="🪽 Feishu",          default_toolset="spark-feishu")),
    ("wecom",          PlatformInfo(label="💬 WeCom",           default_toolset="spark-wecom")),
    ("wecom_callback", PlatformInfo(label="💬 WeCom Callback",  default_toolset="spark-wecom-callback")),
    ("weixin",         PlatformInfo(label="💬 Weixin",          default_toolset="spark-weixin")),
    ("qqbot",          PlatformInfo(label="💬 QQBot",           default_toolset="spark-qqbot")),
    ("webhook",        PlatformInfo(label="🔗 Webhook",         default_toolset="spark-webhook")),
    ("api_server",     PlatformInfo(label="🌐 API Server",      default_toolset="spark-api-server")),
])


def platform_label(key: str, default: str = "") -> str:
    """Return the display label for a platform key, or *default*."""
    info = PLATFORMS.get(key)
    return info.label if info is not None else default
