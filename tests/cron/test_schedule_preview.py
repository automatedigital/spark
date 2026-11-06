"""SP17 frozen-clock admission, preview and durable dispatch contracts."""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cron import jobs
from spark_cli.cron_routes import register_cron_routes


@pytest.fixture
def clock(monkeypatch, tmp_path):
    now = datetime(2026, 3, 28, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(jobs, "_spark_now", lambda: now)
    monkeypatch.setattr(jobs, "CRON_DIR", tmp_path / "cron")
    monkeypatch.setattr(jobs, "JOBS_FILE", tmp_path / "cron/jobs.json")
    monkeypatch.setattr(jobs, "OUTPUT_DIR", tmp_path / "cron/output")
    return now


@pytest.mark.parametrize("schedule", ["every 0m", "0m", "every -1h", {"kind": "interval", "minutes": 0},
    {"kind": "interval", "minutes": -1}, {"kind": "interval", "minutes": True},
    {"kind": "interval", "minutes": 0.5}, {"kind": "interval", "minutes": 10**30},
    {"kind": "cron", "expr": "61 * * * *"}, {"kind": "once", "run_at": "bad"},
    {"kind": "unknown"}, [], None])
def test_invalid_at_every_boundary(clock, schedule):
    with pytest.raises(ValueError):
        jobs.preview_schedule(schedule)
    job = jobs.create_job("fixture", "every 30m")
    before = jobs.JOBS_FILE.read_bytes()
    with pytest.raises(ValueError):
        jobs.update_job(job["id"], {"schedule": schedule})
    assert jobs.JOBS_FILE.read_bytes() == before
    jobs.save_jobs([{**job, "schedule": schedule, "next_run_at": clock.isoformat()}])
    assert jobs.get_due_jobs() == []
    quarantined = jobs.get_job(job["id"])
    assert quarantined["state"] == "paused" and not quarantined["enabled"]
    assert "repair" in quarantined["paused_reason"]


@pytest.mark.parametrize("zone,expr,expected", [
    ("Europe/London", "30 1 * * *", "2026-03-30T01:30:00+01:00"),
    ("UTC", "0 9 * * *", "2026-03-29T09:00:00+00:00"),
    ("Asia/Tokyo", "0 9 * * *", "2026-03-29T09:00:00+09:00"),
])
def test_preview_create_dispatch_agree(clock, zone, expr, expected):
    preview = jobs.preview_schedule(expr, zone)
    assert len(preview["occurrences"]) == 5
    assert preview["occurrences"][0] == expected
    assert not jobs.JOBS_FILE.exists()
    job = jobs.create_job("fixture", expr, timezone=zone, model="fixture-model", skills=["fixture"])
    assert job["next_run_at"] == preview["occurrences"][0]
    jobs._spark_now = lambda: datetime.fromisoformat(expected)
    try:
        assert jobs.get_due_jobs()[0]["id"] == job["id"]
    finally:
        jobs._spark_now = lambda: clock
    changed = jobs.update_job(job["id"], {"schedule": {"kind": "interval", "minutes": 5}})
    assert changed["id"] == job["id"] and changed["model"] == "fixture-model"
    assert changed["skills"] == ["fixture"]
    with pytest.raises(ValueError, match="immutable"):
        jobs.update_job(job["id"], {"id": "replacement"})


def test_gap_fold_and_oneshot(clock, monkeypatch):
    with pytest.raises(ValueError, match="gap"):
        jobs.preview_schedule("2026-03-29T01:30", "Europe/London")
    preview = jobs.preview_schedule("2026-10-25T01:30", "Europe/London")
    assert preview["occurrences"] == ["2026-10-25T01:30:00+01:00"]
    monkeypatch.setattr(jobs, "_spark_now", lambda: datetime(2026, 10, 24, 12, tzinfo=timezone.utc))
    preview = jobs.preview_schedule("30 1 * * *", "Europe/London")
    assert preview["occurrences"][:2] == ["2026-10-25T01:30:00+01:00", "2026-10-26T01:30:00+00:00"]
    assert len({datetime.fromisoformat(x).astimezone(timezone.utc) for x in preview["occurrences"]}) == 5
    with pytest.raises(ValueError, match="timezone"):
        jobs.preview_schedule("every 1h", "Mars/Olympus")


def test_http_preview_readonly_and_structured_update(clock):
    app = FastAPI()
    register_cron_routes(app)
    client = TestClient(app)
    with patch("spark_cli.config.load_config", return_value={"model": {"default": "fixture", "provider": "custom:fixture"},
        "providers": {"fixture": {"url": "http://127.0.0.1:1/v1"}}}), \
        patch("spark_cli.runtime_provider.load_config", side_effect=lambda: {"providers": {"fixture": {"url": "http://127.0.0.1:1/v1"}}}), \
        patch("spark_cli.cron_routes._cron_skills", return_value=[]), \
        patch("spark_cli.runtime_provider.resolve_runtime_provider", side_effect=AssertionError("Execution resolver forbidden")), \
        patch("requests.sessions.Session.request", side_effect=AssertionError("Network forbidden")):
        response = client.post("/api/cron/preview", json={"schedule": "0 9 * * *", "timezone": "UTC", "skills": ["missing"]})
        assert response.status_code == 200, response.text
        assert response.json()["readiness"]["provider"] == "custom:fixture"
        assert response.json()["readiness"]["errors"] == ["Skill unavailable: missing"]
        assert not jobs.JOBS_FILE.exists()
        job = jobs.create_job("fixture", "every 1h")
        before = jobs.JOBS_FILE.read_bytes()
        assert client.post("/api/cron/preview", json={"schedule": "every 0m"}).status_code == 400
        assert jobs.JOBS_FILE.read_bytes() == before
        assert client.put(f"/api/cron/jobs/{job['id']}", json={"updates": {"schedule": {"kind": "interval", "minutes": 0}}}).status_code == 400
        saved = client.put(f"/api/cron/jobs/{job['id']}", json={"updates": {"schedule": "0 9 * * *", "timezone": "Asia/Tokyo"}}).json()
        assert saved["schedule"]["timezone"] == "Asia/Tokyo"
        cleared = client.put(f"/api/cron/jobs/{job['id']}", json={"updates": {"timezone": None}}).json()
        assert "timezone" not in cleared["schedule"]
