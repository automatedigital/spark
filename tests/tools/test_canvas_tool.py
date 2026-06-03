"""Agent-facing canvas tool: widgets → display nodes, written + registered."""

from __future__ import annotations

import json

from tools import canvas_tool
from tools.registry import registry


def test_widgets_map_to_display_nodes(tmp_path, monkeypatch):
    out = canvas_tool.canvas_render(
        canvas_id="board1",
        name="Board",
        widgets=[
            {"type": "markdown", "content": "# Hi"},
            {"type": "text", "content": "plain"},
            {"type": "note", "text": "sticky"},
            {"type": "media", "url": "https://x/y.png"},
            {"type": "iframe", "url": "https://example.com"},
        ],
    )
    res = json.loads(out)
    assert res["ok"] is True
    assert res["node_count"] == 5

    from spark_cli.canvas_routes import _read_canvas

    doc = _read_canvas("global", None, "board1")
    # Stored shape matches the UI: type = engine nodeType, params top-level.
    types = [n["type"] for n in doc["nodes"]]
    assert types == [
        "display.render",
        "display.render",
        "display.note",
        "display.media",
        "display.iframe",
    ]
    assert all("label" in n["data"] for n in doc["nodes"])
    # Markdown vs text format (params are top-level)
    assert doc["nodes"][0]["params"]["format"] == "markdown"
    assert doc["nodes"][1]["params"]["format"] == "text"
    # Vertical auto-layout
    assert [n["position"]["y"] for n in doc["nodes"]] == [0, 220, 440, 660, 880]


def test_empty_widgets_rejected():
    res = json.loads(canvas_tool.canvas_render(canvas_id="x", widgets=[]))
    assert "error" in res


def test_missing_canvas_id_rejected():
    res = json.loads(canvas_tool.canvas_render(canvas_id="", widgets=[{"type": "text", "content": "a"}]))
    assert "error" in res


def test_tool_is_registered():
    assert registry._tools.get("canvas") is not None
    assert registry._tools.get("canvas_await") is not None


def test_actions_widget_maps_to_display_actions(tmp_path):
    import json

    out = json.loads(
        canvas_tool.canvas_render("b", [{"type": "actions", "prompt": "Pick", "options": ["A", "B"], "widget_id": "q1"}])
    )
    assert out["node_count"] == 1
    from spark_cli.canvas_routes import _read_canvas

    node = _read_canvas("global", None, "b")["nodes"][0]
    assert node["type"] == "display.actions"
    assert node["params"] == {"prompt": "Pick", "options": ["A", "B"], "widget_id": "q1"}


def test_await_returns_submitted_interaction():
    import json
    import threading
    import time

    from spark_cli.canvas_routes import submit_interaction

    result = {}

    def waiter():
        result["v"] = canvas_tool.canvas_await("b2", "q1", timeout=5)

    t = threading.Thread(target=waiter)
    t.start()
    time.sleep(0.2)
    submit_interaction("global", None, "b2", "q1", "chosen-value")
    t.join()
    assert json.loads(result["v"]) == {"ok": True, "widget_id": "q1", "value": "chosen-value"}


def test_await_times_out():
    import json

    res = json.loads(canvas_tool.canvas_await("b3", "missing", timeout=0.3))
    assert res.get("timeout") is True
