"""Recovery of a damaged job snapshot through public cron operations."""

import pytest

from core.spark_constants import get_spark_home
from cron import jobs


@pytest.mark.parametrize(
    "malformed_snapshot",
    [
        b'{"updated_at": null}\n',
        b'{"jobs": ["invalid\nrow"]}\n',
    ],
    ids=["missing-jobs", "invalid-row-after-control-character-repair"],
)
def test_create_preserves_malformed_snapshot_and_recovers(monkeypatch, malformed_snapshot):
    cron_dir = get_spark_home() / "cron"
    snapshot = cron_dir / "jobs.json"
    monkeypatch.setattr(jobs, "CRON_DIR", cron_dir)
    monkeypatch.setattr(jobs, "JOBS_FILE", snapshot)
    monkeypatch.setattr(jobs, "OUTPUT_DIR", cron_dir / "output")

    original_job = jobs.create_job(prompt="Existing job", schedule="every 1h")
    backup = cron_dir / "jobs.backup.json"
    backup.write_bytes(snapshot.read_bytes())
    snapshot.write_bytes(malformed_snapshot)

    with pytest.raises(RuntimeError):
        jobs.create_job(prompt="New job", schedule="every 1h")
    assert snapshot.read_bytes() == malformed_snapshot

    # Simulate an operator restoring the file while Spark is still running.
    backup.replace(snapshot)
    assert jobs.list_jobs() == [original_job]
    new_job = jobs.create_job(prompt="New job", schedule="every 1h")
    assert jobs.list_jobs() == [original_job, new_job]
