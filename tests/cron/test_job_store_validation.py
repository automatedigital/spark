"""Shape validation and repair of persisted cron job snapshots."""

import json
import logging
import traceback

import pytest

from cron import jobs


@pytest.fixture
def snapshot(monkeypatch, tmp_path, caplog):
    cron_dir = tmp_path / "cron"
    snapshot = cron_dir / "jobs.json"
    cron_dir.mkdir()
    monkeypatch.setattr(jobs, "CRON_DIR", cron_dir)
    monkeypatch.setattr(jobs, "JOBS_FILE", snapshot)
    monkeypatch.setattr(jobs, "OUTPUT_DIR", cron_dir / "output")
    caplog.set_level(logging.DEBUG, logger=jobs.__name__)
    return snapshot


def test_missing_and_explicitly_empty_store(snapshot):
    assert jobs.load_jobs() == []
    assert not snapshot.exists()

    original = b'{"jobs": [], "updated_at": null}\n'
    snapshot.write_bytes(original)
    assert jobs.load_jobs() == []
    assert snapshot.read_bytes() == original


def test_legacy_records_load_without_rewriting(snapshot):
    rows = [
        {"id": "legacy", "skill": "old-skill"},
        {
            "id": "single-skill",
            "skills": "other-skill",
            "schedule": {"kind": "once", "run_at": "2026-04-10T12:00:00"},
            "next_run_at": "2026-04-10T12:00:00",
            "repeat": {"times": None},
            "origin": None,
            "extension": {"version": 1},
        },
    ]
    original = json.dumps({"jobs": rows}).encode()
    snapshot.write_bytes(original)

    assert jobs.load_jobs() == rows
    assert [job["skills"] for job in jobs.list_jobs()] == [["old-skill"], ["other-skill"]]
    assert snapshot.read_bytes() == original


@pytest.mark.parametrize(
    ("original", "location"),
    [
        (b"null", "the root"),
        (b"[]", "the root"),
        (b'{"updated_at": null}', "jobs"),
        (b'{"jobs": null}', "jobs"),
        (b'{"jobs": {"private-value": []}}', "jobs"),
        (b'{"jobs": [{"id": "valid"}, "private-value"]}', "jobs[1]"),
        (b'{"jobs": [{}]}', "jobs[0].id"),
        (b'{"jobs": [{"id": "  "}]}', "jobs[0].id"),
        (b'{"jobs": [{"id": ["private-value"]}]}', "jobs[0].id"),
        (b'{"jobs": [{"id": "private-value"}, {"id": "private-value"}]}', "jobs[1].id"),
        (b'{"jobs": [{"id": "private-value", "prompt": {}}]}', "jobs[0].prompt"),
        (b'{"jobs": [{"id": "private-value", "enabled": 1}]}', "jobs[0].enabled"),
        (b'{"jobs": [{"id": "private-value", "origin": []}]}', "jobs[0].origin"),
        (b'{"jobs": [{"id": "private-value", "skills": {}}]}', "jobs[0].skills"),
        (b'{"jobs": [{"id": "private-value", "skills": [null]}]}', "jobs[0].skills"),
        (b'{"jobs": [{"id": "private-value", "repeat": []}]}', "jobs[0].repeat"),
        (b'{"jobs": [{"id": "private-value", "repeat": {"times": true}}]}', "jobs[0].repeat.times"),
        (
            b'{"jobs": [{"id": "private-value", "repeat": {"completed": -1}}]}',
            "jobs[0].repeat.completed",
        ),
    ],
)
def test_rejects_invalid_shape_without_disclosure(snapshot, caplog, original, location):
    snapshot.write_bytes(original)

    with pytest.raises(RuntimeError) as caught:
        jobs.load_jobs()

    assert f"{location} must be" in str(caught.value)
    assert "Correct or restore jobs.json" in str(caught.value)
    assert "private-value" not in "".join(traceback.format_exception(caught.value))
    assert "private-value" not in caplog.text
    assert snapshot.read_bytes() == original


@pytest.mark.parametrize(
    "original", [b'{"jobs": ["private-value"', b'{"jobs": ["private-value\xff"]}']
)
def test_reports_json_and_encoding_errors_without_content(snapshot, caplog, original):
    snapshot.write_bytes(original)

    with pytest.raises(RuntimeError, match="Correct or restore jobs.json") as caught:
        jobs.load_jobs()

    assert caught.value.__cause__ is None
    assert "private-value" not in "".join(traceback.format_exception(caught.value))
    assert "private-value" not in caplog.text
    assert snapshot.read_bytes() == original


def test_permissive_parse_repairs_valid_snapshot(snapshot, caplog):
    original = b'{"jobs": [{"id": "legacy", "prompt": "line\nbreak"}], "extension": "keep"}'
    snapshot.write_bytes(original)

    assert jobs.load_jobs() == [{"id": "legacy", "prompt": "line\nbreak"}]
    assert json.loads(snapshot.read_bytes()) == json.loads(original, strict=False)
    assert "Auto-repaired jobs.json" in caplog.text
    assert "line\nbreak" not in caplog.text


def test_permissive_parse_checks_every_row_before_replacing(snapshot, caplog):
    original = b'{"jobs": [{"id": "legacy", "prompt": "line\nbreak"}, {"prompt": "private-value"}]}'
    snapshot.write_bytes(original)

    with pytest.raises(RuntimeError) as caught:
        jobs.load_jobs()

    assert "jobs[1].id must be" in str(caught.value)
    assert "private-value" not in "".join(traceback.format_exception(caught.value))
    assert "Auto-repaired" not in caplog.text
    assert snapshot.read_bytes() == original
    assert not list(snapshot.parent.glob(".jobs_*.tmp"))


def test_invalid_snapshot_is_rejected_before_writing(snapshot):
    original = b'{"jobs": [{"id": "valid"}]}\n'
    snapshot.write_bytes(original)

    with pytest.raises(RuntimeError, match=r"jobs\[0\]\.enabled must be a boolean"):
        jobs.save_jobs([{"id": "legacy", "enabled": "false"}])

    assert snapshot.read_bytes() == original


@pytest.mark.parametrize("schedule", [{"kind": "once", "run_at": "private-value"}, "private-value"])
def test_bad_schedule_remains_eligible_for_job_level_repair(snapshot, caplog, schedule):
    snapshot.write_text(
        json.dumps({"jobs": [{"id": "legacy", "schedule": schedule}]}),
        encoding="utf-8",
    )

    assert jobs.get_due_jobs() == []

    job = jobs.load_jobs()[0]
    assert job["state"] == "paused"
    assert job["schedule"] == schedule
    assert "repair" in job["paused_reason"]
    assert "private-value" not in job["paused_reason"]
    assert "private-value" not in caplog.text

    repaired = jobs.update_job("legacy", {"schedule": "every 10m"})
    assert repaired["schedule"]["minutes"] == 10
    assert jobs.resume_job("legacy")["enabled"] is True
