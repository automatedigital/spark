"""Memory writes emit a memory.updated event (Web toast wiring, 2.3.4)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from tools.memory_tool import MemoryStore


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.memory_tool.get_memory_dir", lambda: tmp_path)
    s = MemoryStore(memory_char_limit=500, user_char_limit=300)
    s.load_from_disk()
    return s


def test_add_emits_memory_updated(store):
    events = []
    with patch("spark_cli.web_server._publish_event", lambda topic, data: events.append((topic, data))):
        result = store.add("memory", "Python 3.12 project")
    assert result["success"] is True
    assert any(t == "memory.updated" for t, _ in events)


def test_remove_emits_memory_updated(store):
    store.add("memory", "temporary fact")
    events = []
    with patch("spark_cli.web_server._publish_event", lambda topic, data: events.append((topic, data))):
        store.remove("memory", "temporary fact")
    assert any(t == "memory.updated" for t, _ in events)
