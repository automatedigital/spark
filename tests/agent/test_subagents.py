import json

import pytest

from agent.subagents import (
    SUBAGENT_EVENT_SCHEMA,
    SUBAGENT_LIFECYCLE_CALLBACK_EVENT,
    SUBAGENT_NAME_POOL,
    make_run_record,
    make_subagent_event,
    subagent_identity,
)


def test_subagent_identity_is_deterministic():
    assert subagent_identity(0, 3) == {
        "subagent_id": "subagent-1",
        "task_index": 0,
        "task_number": 1,
        "task_count": 3,
        "display_name": "Subagent 1",
        "short_name": "S1",
    }


def test_make_subagent_event_is_json_safe_and_bounded():
    event = make_subagent_event(
        "tool_started",
        task_index=1,
        task_count=2,
        goal="Inspect logs",
        tool_name="terminal",
        preview="x" * 1000,
        args={
            "cmd": "echo hi",
            "items": list(range(50)),
            "not_json": object(),
        },
    )

    encoded = json.dumps(event, ensure_ascii=False, allow_nan=False)
    decoded = json.loads(encoded)

    assert decoded["schema"] == SUBAGENT_EVENT_SCHEMA
    assert decoded["type"] == "subagent.tool_started"
    assert decoded["event"] == "tool_started"
    assert decoded["subagent_id"] == "subagent-2"
    assert len(decoded["payload"]["preview"]) <= 500
    assert decoded["payload"]["args"]["items"][-1]["_truncated"] is True
    assert isinstance(decoded["payload"]["args"]["not_json"], str)


def test_make_subagent_event_rejects_unknown_event():
    with pytest.raises(ValueError):
        make_subagent_event("bogus", task_index=0)


def test_status_and_tool_output_events_are_supported():
    status_event = make_subagent_event(
        "status",
        task_index=0,
        payload={"status": "stopping", "preview": "Interrupt requested"},
    )
    output_event = make_subagent_event(
        "tool_output",
        task_index=0,
        tool_name="terminal",
        preview="line from child",
    )

    assert status_event["type"] == "subagent.status"
    assert status_event["payload"]["status"] == "stopping"
    assert output_event["type"] == "subagent.tool_output"
    assert output_event["payload"]["tool"] == "terminal"


def test_make_run_record_uses_same_identity_fields():
    record = make_run_record(
        parent_session_id="parent",
        child_session_id="child",
        task_index=2,
        task_count=4,
        task="Summarize findings",
        context="context",
        model="model",
        provider="provider",
        toolsets=["terminal"],
    )

    assert record["subagent_id"] == "subagent-3"
    assert record["display_name"] in SUBAGENT_NAME_POOL
    assert record["short_name"] == record["display_name"][:1].upper()
    assert record["task"] == "Summarize findings"
    assert record["toolsets"] == ["terminal"]


def test_lifecycle_callback_event_name_is_stable():
    assert SUBAGENT_LIFECYCLE_CALLBACK_EVENT == "subagent.lifecycle"
