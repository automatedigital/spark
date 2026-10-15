"""HTTP controls over real replay-driven child execution; no live providers."""

import json

from tests.run_agent.test_async_delegation import replay_runtime as replay_runtime
from tests.run_agent.test_async_delegation import wait_terminal
from tests.spark_cli.test_web_server_events import web_client as web_client
from tools.delegate_tool import delegate_task


def test_async_inspect_interrupt_and_retry_keep_existing_routes(web_client, replay_runtime):
    from spark_cli import web_server

    r = replay_runtime
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
        cancelled = web_client.post(base + "/" + handle + "/interrupt", json={"request_id": "cancel"})
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "stopping"
        assert wait_terminal(r.db, handle)["status"] == "interrupted"
        assert web_client.post(base + "/" + handle + "/interrupt", json={"request_id": "cancel"}).json() == cancelled.json()
        retried = web_client.post(base + "/" + handle + "/retry", json={"request_id": "retry"})
        assert retried.status_code == 200
        replacement = retried.json()["handles"][0]["id"]
        assert replacement != handle
        r.controls["http-child"]["release"].set()
        assert wait_terminal(r.db, replacement)["status"] == "completed"
        assert web_client.get(base + "/" + handle + "/messages").status_code == 200
        web_server._web_agents.pop(parent.session_id)
        web_server._clear_web_turn(parent.session_id)
        # Receipt-backed HTTP retries work after the owning runtime disappears.
        assert web_client.post(base + "/" + handle + "/retry", json={"request_id": "retry"}).json() == retried.json()
        assert web_client.get(base + "/capabilities").json()["controls"]["interrupt"]["supported"] is False
    finally:
        web_server._clear_web_turn(parent.session_id)
        web_server._web_agents.pop(parent.session_id, None)
