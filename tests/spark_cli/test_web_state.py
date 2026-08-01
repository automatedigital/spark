from __future__ import annotations

import json
from pathlib import Path

import pytest

from spark_cli.web_state import (
    WEB_STATE_PROJECTION_VERSION,
    WEB_STATE_SCHEMA_VERSION,
    WebStateJournal,
    validate_web_event_envelope,
)


def test_v1_envelope_matches_checked_in_schema_contract():
    schema = json.loads(
        (Path(__file__).parents[2] / "src/spark_cli/web_state_schema.json").read_text()
    )
    assert schema["properties"]["schema_version"]["const"] == WEB_STATE_SCHEMA_VERSION
    assert (
        schema["properties"]["projection_version"]["const"]
        == WEB_STATE_PROJECTION_VERSION
    )
    journal = WebStateJournal(server_epoch="test")
    event = journal.append("sessions.changed", {"action": "updated"}, "s1")
    assert validate_web_event_envelope(event) is event
    assert event["entity_id"] == event["session_id"] == "s1"
    assert event["payload"] == event["data"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", 2),
        ("projection_version", 2),
        ("sequence", 0),
        ("topic", ""),
        ("payload", []),
        ("server_epoch", None),
    ],
)
def test_runtime_validation_rejects_contract_drift(field, value):
    event = WebStateJournal(server_epoch="test").append("chat.status", {}, "s1")
    event[field] = value
    with pytest.raises(ValueError):
        validate_web_event_envelope(event)


def test_resume_is_ordered_and_filters_selected_detail():
    journal = WebStateJournal(server_epoch="epoch")
    first = journal.append("sessions.changed", {"n": 1}, "s1")
    journal.append("chat.token", {"t": "other"}, "s2")
    third = journal.append("chat.turn_done", {"n": 3}, "s1")

    resumed = journal.resume(
        first["sequence"],
        projection_version=1,
        server_epoch="epoch",
        entity_ids=("s1",),
    )
    assert not resumed.requires_snapshot
    assert [event["sequence"] for event in resumed.events] == [third["sequence"]]


def test_resume_requires_snapshot_for_restart_version_gap_and_retention():
    journal = WebStateJournal(max_events=2, retention_seconds=100, server_epoch="epoch")
    journal.append("chat.status", {"n": 1}, "s")
    journal.append("chat.status", {"n": 2}, "s")
    journal.append("chat.status", {"n": 3}, "s")

    assert journal.resume(0, projection_version=2, server_epoch="epoch").reason == "projection_version_changed"
    assert journal.resume(0, projection_version=1, server_epoch="old").reason == "server_restarted"
    assert journal.resume(0, projection_version=1, server_epoch="epoch").reason == "retention_expired"
    assert journal.resume(99, projection_version=1, server_epoch="epoch").reason == "invalid_sequence"


def test_large_history_event_payload_is_bounded_by_shell_detail_split():
    journal = WebStateJournal(max_events=128, server_epoch="epoch")
    for index in range(10_000):
        journal.append("sessions.changed", {"message_count": index}, f"s{index % 50}")
    assert journal.latest_sequence == 10_000
    resumed = journal.resume(9_950, projection_version=1, server_epoch="epoch")
    assert len(resumed.events) == 50
    assert len(json.dumps(resumed.events)) < 25_000
