"""Committed cron notifications must never announce rejected mutations."""
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_cron_notifications_follow_persistence(tmp_path, monkeypatch):
    import cron.jobs as jobs
    from spark_cli import cron_routes, web_server

    monkeypatch.setenv("SPARK_HOME", str(tmp_path))
    monkeypatch.setattr(jobs, "JOBS_FILE", tmp_path / "cron" / "jobs.json")
    monkeypatch.setattr(jobs, "CRON_DIR", tmp_path / "cron")
    observed = []

    def publish(topic, payload):
        assert topic == "bus.cron_changed"
        assert payload == {}
        observed.append(jobs.list_jobs(include_disabled=True))

    monkeypatch.setattr(web_server, "_publish_event", publish)
    app = FastAPI()
    cron_routes.register_cron_routes(app)
    client = TestClient(app)
    created = client.post("/api/cron/jobs", json={"prompt": "Fixture", "schedule": "0 9 * * *"})
    assert created.status_code == 200
    job_id = created.json()["id"]
    assert observed[-1][0]["id"] == job_id
    assert client.post(f"/api/cron/jobs/{job_id}/pause").status_code == 200
    assert observed[-1][0]["enabled"] is False
    assert client.put(f"/api/cron/jobs/{job_id}", json={"updates": {"name": "Changed"}}).status_code == 200
    assert observed[-1][0]["name"] == "Changed"
    assert client.delete(f"/api/cron/jobs/{job_id}").status_code == 200
    assert observed[-1] == []
    count = len(observed)
    assert client.post(f"/api/cron/jobs/{job_id}/pause").status_code == 404
    assert client.post("/api/cron/jobs", json={"prompt": "Fixture", "schedule": "invalid"}).status_code == 400
    assert len(observed) == count
