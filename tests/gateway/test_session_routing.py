"""Channel→workspace routing for the gateway (multi-agent isolation)."""

from __future__ import annotations

import enum

import gateway.session as gs
from gateway.session import build_session_key, resolve_agent_name

# Resolve the Platform enum + a telegram member without hard-coding internals.
_PlatformEnum = next(
    v for v in vars(gs).values()
    if isinstance(v, type) and issubclass(v, enum.Enum)
    and any(e.name.lower() == "telegram" for e in v)
)
_TG = next(e for e in _PlatformEnum if e.name.lower() == "telegram")


def _src(chat_id="123", chat_type="dm"):
    return gs.SessionSource(platform=_TG, chat_id=chat_id, chat_type=chat_type, user_id="u1")


def test_default_key_unchanged():
    # Backward compatible: no routing → agent:main prefix.
    assert build_session_key(_src()) == "agent:main:telegram:dm:123"


def test_named_agent_prefix():
    assert build_session_key(_src(), agent_name="proj-a") == "agent:proj-a:telegram:dm:123"


def test_resolve_specific_rule_wins():
    routing = {"telegram:dm:123": "proj-a", "telegram": "tg", "default": "fallback"}
    assert resolve_agent_name(_src(), routing) == "proj-a"


def test_resolve_platform_level():
    routing = {"telegram": "tg-default"}
    assert resolve_agent_name(_src(chat_id="999", chat_type="group"), routing) == "tg-default"


def test_resolve_default_and_none():
    assert resolve_agent_name(_src(), {"default": "fallback"}) == "fallback"
    assert resolve_agent_name(_src(), None) == "main"
    assert resolve_agent_name(_src(), {}) == "main"


def test_routing_changes_session_key_isolation():
    routing = {"telegram:dm:123": "proj-a"}
    name = resolve_agent_name(_src(), routing)
    key = build_session_key(_src(), agent_name=name)
    assert key.startswith("agent:proj-a:")
    # A different chat with no rule stays on main → isolated workspaces.
    other = _src(chat_id="555")
    other_name = resolve_agent_name(other, routing)
    assert build_session_key(other, agent_name=other_name).startswith("agent:main:")
