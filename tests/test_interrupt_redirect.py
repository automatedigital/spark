"""Interrupt → redirect → resume contract tests.

Exercises the agent-side interrupt API (used by both the TUI Esc/Ctrl+C handler
and the typed-message redirect path) without spinning up a real model loop.
"""

from __future__ import annotations

import threading

import pytest

from core.run_agent import AIAgent
from tools.interrupt import is_interrupted, set_interrupt


def _bare_agent() -> AIAgent:
    """Minimal AIAgent with just the interrupt-relevant state initialised."""
    agent = AIAgent.__new__(AIAgent)
    agent._interrupt_requested = False
    agent._interrupt_message = None
    agent._active_children = []
    agent._active_children_lock = threading.Lock()
    agent._execution_thread_id = threading.current_thread().ident
    agent.quiet_mode = True
    return agent


@pytest.fixture(autouse=True)
def _clear_thread_interrupt():
    set_interrupt(False)
    yield
    set_interrupt(False)


def test_interrupt_with_message_sets_redirect():
    agent = _bare_agent()
    agent.interrupt("actually, do X instead")
    assert agent._interrupt_requested is True
    assert agent._interrupt_message == "actually, do X instead"
    assert agent.is_interrupted is True


def test_soft_interrupt_without_message_is_pure_pause():
    # Esc soft-interrupt passes no message: turn pauses, nothing redirected.
    agent = _bare_agent()
    agent.interrupt()
    assert agent._interrupt_requested is True
    assert agent._interrupt_message is None
    assert agent.is_interrupted is True


def test_interrupt_propagates_to_child_agents():
    parent = _bare_agent()
    child = _bare_agent()
    parent._active_children = [child]
    parent.interrupt("redirect")
    assert child._interrupt_requested is True
    assert child._interrupt_message == "redirect"


def test_clear_interrupt_resets_state_for_resume():
    agent = _bare_agent()
    agent.interrupt("redirect")
    agent.clear_interrupt()
    assert agent._interrupt_requested is False
    assert agent._interrupt_message is None
    assert agent.is_interrupted is False
    # Thread-level tool interrupt is cleared too, so the next turn runs clean.
    assert is_interrupted() is False


def test_redirect_message_surfaces_in_result_shape():
    # Mirrors run_agent's result assembly (__init__.py:10267): when interrupted
    # with a message, the result carries interrupt_message for the CLI/gateway
    # to re-submit as the next turn.
    agent = _bare_agent()
    agent.interrupt("do X instead")
    result: dict = {}
    interrupted = agent._interrupt_requested
    if interrupted and agent._interrupt_message:
        result["interrupt_message"] = agent._interrupt_message
    assert result.get("interrupt_message") == "do X instead"
    # CLI mapping (__init__.py:1711): pending_message falls back to the queued msg.
    pending_message = result.get("interrupt_message") or "queued-fallback"
    assert pending_message == "do X instead"
