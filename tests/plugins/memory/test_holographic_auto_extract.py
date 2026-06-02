"""Holographic memory: auto-extract is ON by default (Phase 2a Auto-memory)."""

from unittest.mock import MagicMock

from plugins.memory.holographic import HolographicMemoryProvider


def _provider(config):
    p = HolographicMemoryProvider(config=config)
    p._store = MagicMock()
    p._auto_extract_facts = MagicMock()
    return p


_MESSAGES = [{"role": "user", "content": "I prefer dark mode and tabs over spaces"}]


def test_auto_extract_on_by_default():
    """With no auto_extract configured, session end extracts facts."""
    p = _provider({})
    p.on_session_end(_MESSAGES)
    p._auto_extract_facts.assert_called_once_with(_MESSAGES)


def test_auto_extract_opt_out_bool():
    """auto_extract: false disables extraction."""
    p = _provider({"auto_extract": False})
    p.on_session_end(_MESSAGES)
    p._auto_extract_facts.assert_not_called()


def test_auto_extract_opt_out_string():
    """A string 'false' from YAML is coerced and disables extraction."""
    p = _provider({"auto_extract": "false"})
    p.on_session_end(_MESSAGES)
    p._auto_extract_facts.assert_not_called()


def test_auto_extract_explicit_true():
    """auto_extract: true keeps extraction on."""
    p = _provider({"auto_extract": True})
    p.on_session_end(_MESSAGES)
    p._auto_extract_facts.assert_called_once_with(_MESSAGES)


def test_no_extraction_without_messages():
    """Empty history is a no-op even when enabled."""
    p = _provider({})
    p.on_session_end([])
    p._auto_extract_facts.assert_not_called()
