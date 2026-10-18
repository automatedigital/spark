"""A sibling's capabilities must never authorize controls on another child."""

import threading
from types import SimpleNamespace

from core.orchestration.capabilities import child_capabilities


def test_mixed_children_have_independent_control_support():
    runtime = SimpleNamespace(
        _active_children_lock=threading.Lock(),
        _active_children=[SimpleNamespace(session_id="live-session", interrupt=lambda: None)],
    )
    runs = [
        {"id": "live", "child_session_id": "live-session", "status": "running", "execution_mode": "async"},
        {"id": "orphan", "child_session_id": "gone", "status": "running", "execution_mode": "async"},
        {"id": "failed", "status": "failed", "execution_mode": "async"},
        {"id": "unknown", "status": "uncertain", "execution_mode": "async"},
        {"id": "sync", "status": "failed", "execution_mode": "sync"},
    ]
    snapshot = child_capabilities(runtime, runs, {"async_enabled": True})
    assert snapshot["controls"]["interrupt"]["supported"] is True
    assert snapshot["controls"]["retry"]["supported"] is True
    children = snapshot["children"]
    assert {key for key, value in children.items() if value["controls"]["interrupt"]["supported"]} == {"live"}
    assert {key for key, value in children.items() if value["controls"]["retry"]["supported"]} == {"failed"}
    assert "review" in children["unknown"]["controls"]["retry"]["reason"]
    assert all(child["controls"]["inspect"]["supported"] for child in children.values())
    unavailable = child_capabilities(None, runs, {"async_enabled": True})
    assert not any(child["controls"][control]["supported"]
                   for child in unavailable["children"].values() for control in ("interrupt", "retry"))
