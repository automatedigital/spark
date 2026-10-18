"""HTTP controls over real replay-driven child execution; no live providers."""

import json

from core.spark_state import SessionDB
from tests.run_agent.test_async_delegation import replay_runtime as replay_runtime
from tests.run_agent.test_async_delegation import wait_terminal
from tests.spark_cli.test_web_server_events import web_client as web_client
from tools.delegate_tool import delegate_task


def test_async_inspect_interrupt_and_retry_keep_existing_routes(web_client, replay_runtime):
    from core.spark_constants import get_spark_home
    from spark_cli import web_server

    r = replay_runtime
    # The tool fixture opts in separately; the HTTP capability endpoint must
    # observe the same actual profile setting rather than defaulting to false.
    (get_spark_home() / "config.yaml").write_text("delegation:\n  async_enabled: true\n")
    parent = r.parent("http-parent", "web")
    parent.subagent_event_callback = lambda event: web_server._persist_and_publish_subagent_event(parent.session_id, event)
    web_server._web_agents[parent.session_id] = parent
    web_server._mark_web_turn_active(parent.session_id)
    try:
        accepted = json.loads(delegate_task(tasks=[r.task("http-child")], mode="async", request_id="dispatch", parent_agent=parent))
        handle = accepted["handles"][0]["id"]
        assert r.controls["http-child"]["entered"].wait(5)
        base = f"/api/conversations/{parent.session_id}/subagents"
        assert web_client.get(base).json()["subagents"][0]["id"] == handle
        assert web_client.get(base + "/" + handle).json()["subagent"]["attempt_id"] == accepted["handles"][0]["attempt_id"]
        assert web_client.get(base + "/capabilities").json()["controls"]["interrupt"]["supported"] is True
        child_controls = web_client.get(base + "/capabilities").json()["children"][handle]["controls"]
        assert child_controls["interrupt"]["supported"] is True
        assert child_controls["retry"]["supported"] is False
        cancelled = web_client.post(base + "/" + handle + "/interrupt", json={"request_id": "cancel"})
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "stopping"
        assert wait_terminal(r.db, handle)["status"] == "interrupted"
        stopped_controls = web_client.get(base + "/capabilities").json()["children"][handle]["controls"]
        assert stopped_controls["interrupt"]["supported"] is False
        assert stopped_controls["retry"]["supported"] is True
        assert web_client.post(base + "/" + handle + "/interrupt", json={"request_id": "cancel"}).json() == cancelled.json()
        retried = web_client.post(base + "/" + handle + "/retry", json={"request_id": "retry"})
        assert retried.status_code == 200
        replacement = retried.json()["handles"][0]["id"]
        assert replacement != handle
        r.controls["http-child"]["release"].set()
        assert wait_terminal(r.db, replacement)["status"] == "completed"
        final_controls = web_client.get(base + "/capabilities").json()["children"]
        assert final_controls[handle]["controls"]["retry"]["supported"] is True
        assert final_controls[replacement]["controls"]["retry"]["supported"] is False
        assert web_client.get(base + "/" + handle + "/messages").status_code == 200
        web_server._web_agents.pop(parent.session_id)
        web_server._clear_web_turn(parent.session_id)
        # Receipt-backed HTTP retries work after the owning runtime disappears.
        assert web_client.post(base + "/" + handle + "/retry", json={"request_id": "retry"}).json() == retried.json()
        assert web_client.get(base + "/capabilities").json()["controls"]["interrupt"]["supported"] is False
    finally:
        web_server._clear_web_turn(parent.session_id)
        web_server._web_agents.pop(parent.session_id, None)


def test_child_history_pages_beyond_one_thousand_without_full_transcript_reads(web_client, monkeypatch):
    db = SessionDB()
    try:
        db.create_session("history-parent", "web")
        db.create_session("history-child", "delegate", parent_session_id="history-parent")
        db.create_session("other-parent", "web")
        db.create_subagent_run({"id": "history-run", "parent_session_id": "history-parent",
                                "child_session_id": "history-child", "status": "completed"})
        count = 2101
        db.append_iteration("history-child", [{"role": "user", "content": f"message-{i}"} for i in range(count)])
        for i in range(count):
            db.append_subagent_event("history-run", "status", {"index": i})
    finally:
        db.close()

    def unbounded_read(*args, **kwargs):
        raise AssertionError("Child transcript endpoint must not load the full transcript")

    monkeypatch.setattr(SessionDB, "get_messages", unbounded_read)
    base = "/api/conversations/history-parent/subagents/history-run"
    event_ids, message_ids, contents = [], [], []
    cursor = None
    while True:
        response = web_client.get(base, params={"event_limit": 137, **({"event_after_id": cursor} if cursor else {})})
        assert response.status_code == 200
        page = response.json()
        assert 0 < len(page["events"]) <= 137
        event_ids.extend(event["id"] for event in page["events"])
        if not page["has_more_events"]:
            break
        cursor = page["next_event_after_id"]
        assert cursor == event_ids[-1]
    cursor = None
    while True:
        response = web_client.get(base + "/messages", params={"limit": 137, **({"before_id": cursor} if cursor else {})})
        assert response.status_code == 200
        page = response.json()
        assert page["total"] == count
        assert 0 < len(page["messages"]) <= 137
        message_ids = [message["id"] for message in page["messages"]] + message_ids
        contents = [message["content"] for message in page["messages"]] + contents
        if not page["has_earlier"]:
            break
        cursor = page["next_before_id"]
        assert cursor == message_ids[0]
    assert len(event_ids) == len(set(event_ids)) == count
    assert len(message_ids) == len(set(message_ids)) == count
    assert contents == [f"message-{i}" for i in range(count)]
    assert web_client.get(base, params={"event_after_id": -1}).status_code == 400
    foreign = "/api/conversations/other-parent/subagents/history-run"
    assert web_client.get(foreign).status_code == 404
    assert web_client.get(foreign + "/messages").status_code == 404
