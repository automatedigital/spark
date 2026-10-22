"""Real filesystem/API contracts for saved output browsing, without a scheduler."""
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from spark_cli.cron_output_routes import MAX_READ_BYTES, saved_output_capability
from spark_cli.cron_routes import register_cron_routes

posix_output = pytest.mark.skipif(
    not saved_output_capability()["supported"], reason="Requires POSIX descriptor-relative no-follow output access"
)

JOB = "abcdef123456"
NEW = "2026-10-22_09-00-00.md"
OLD = "2026-10-21_09-00-00.md"


@pytest.fixture
def output_api(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("SPARK_HOME", str(tmp_path / "profile"))
    directory = tmp_path / "profile" / "cron" / "output" / JOB
    directory.mkdir(parents=True)
    app = FastAPI()
    register_cron_routes(app)
    return TestClient(app), directory


@posix_output
def test_newest_first_keyset_paging_and_pruning(output_api):
    client, directory = output_api
    (directory / NEW).write_text("# New\n✓", encoding="utf-8")
    (directory / OLD).write_text("Old")
    (directory / "notes.md").write_text("not a saved output")
    (directory / "2026-99-99_00-00-00.md").write_text("invalid date")
    base = f"/api/cron/jobs/{JOB}/outputs"
    assert client.get(base + "?limit=1").json() == {"files": [NEW], "next_before": NEW}
    assert client.get(base + f"?before={NEW}").json() == {"files": [OLD], "next_before": None}
    assert client.get(base + "/" + NEW).json()["content"] == "# New\n✓"
    (directory / OLD).unlink()
    assert client.get(base + "/" + OLD).status_code == 404
    assert client.get(base + f"?before={NEW}").json()["files"] == []
    directory.rename(directory.with_name("pruned"))
    assert client.get(base).json()["files"] == []
    assert client.get(base + "/" + NEW).status_code == 404


@pytest.mark.parametrize("query", ["limit=0", "limit=51", "limit=no", "before=../secret.md", "before=2026-99-99_00-00-00.md"])
def test_invalid_paging(output_api, query):
    client, _ = output_api
    assert client.get(f"/api/cron/jobs/{JOB}/outputs?{query}").status_code in (400, 422)


@pytest.mark.parametrize("job_id", ["ABCDEF123456", "abc", "not-a-job", "..", "abcdef123456x"])
def test_invalid_job_ids(output_api, job_id):
    client, _ = output_api
    assert client.get(f"/api/cron/jobs/{job_id}/outputs").status_code in (400, 404)


@posix_output
def test_bounded_read_and_plain_text(output_api):
    client, directory = output_api
    (directory / NEW).write_bytes(b"<script>alert(1)</script>" + b"a" * MAX_READ_BYTES)
    result = client.get(f"/api/cron/jobs/{JOB}/outputs/{NEW}").json()
    assert result["truncated"] is True
    assert len(result["content"].encode()) == MAX_READ_BYTES
    assert result["max_bytes"] == MAX_READ_BYTES


@pytest.mark.parametrize("level", ["file", "job", "output", "cron"])
@posix_output
def test_symlinks_are_never_followed(output_api, tmp_path, level):
    client, directory = output_api
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / NEW).write_text("private")
    if level == "file":
        (directory / NEW).symlink_to(outside / NEW)
    else:
        target = {"job": directory, "output": directory.parent, "cron": directory.parent.parent}[level]
        target.rename(target.with_name(target.name + "-old"))
        target.symlink_to(outside, target_is_directory=True)
    base = f"/api/cron/jobs/{JOB}/outputs"
    assert client.get(base + "/" + NEW).status_code == 403
    listing = client.get(base)
    assert listing.status_code == 403 or listing.json()["files"] == []


@posix_output
def test_profile_isolation_at_request_time(output_api, tmp_path, monkeypatch):
    client, directory = output_api
    (directory / NEW).write_text("profile one")
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setenv("SPARK_HOME", str(other))
    assert client.get(f"/api/cron/jobs/{JOB}/outputs").json()["files"] == []
    assert client.get(f"/api/cron/jobs/{JOB}/outputs/{NEW}").status_code == 404


def test_exact_filename_validation(output_api):
    client, directory = output_api
    base = f"/api/cron/jobs/{JOB}/outputs/"
    for name in ("notes.md", "2026-10-22_09-00-00.md.bak", "2026-99-99_00-00-00.md", "%2e%2e%2fsecret.md"):
        assert client.get(base + name).status_code in (400, 404)


@posix_output
def test_nonregular_files(output_api):
    client, directory = output_api
    base = f"/api/cron/jobs/{JOB}/outputs/"
    (directory / NEW).mkdir()
    assert client.get(base + NEW).status_code == 403
    (directory / NEW).rmdir()
    os.mkfifo(directory / NEW)
    assert client.get(base + NEW).status_code == 403


def test_output_capability_matches_host_and_fails_closed(output_api):
    client, _ = output_api
    expected = saved_output_capability()
    assert client.get("/api/cron/output-capability").json() == expected
    if os.name == "nt":
        assert expected["supported"] is False
    if not expected["supported"]:
        for suffix in ("", "/" + NEW):
            response = client.get(f"/api/cron/jobs/{JOB}/outputs" + suffix)
            assert response.status_code == 503
            assert response.json()["detail"] == expected["reason"]


@pytest.mark.parametrize("missing", ["dir_fd", "nofollow", "scandir_fd", "directory", "nonblock"])
def test_unsupported_output_capability_and_no_access(output_api, monkeypatch, missing):
    client, directory = output_api
    (directory / NEW).write_text("must not be opened")
    if missing == "dir_fd":
        monkeypatch.setattr(os, "supports_dir_fd", set())
    elif missing == "scandir_fd":
        monkeypatch.setattr(os, "supports_fd", set())
    else:
        flag = {"nofollow": "O_NOFOLLOW", "directory": "O_DIRECTORY", "nonblock": "O_NONBLOCK"}[missing]
        monkeypatch.delattr(os, flag, raising=False)
    capability = client.get("/api/cron/output-capability").json()
    assert capability == {"supported": False, "reason": "Safe saved output access is unavailable on this platform"}
    for suffix in ("", "/" + NEW):
        response = client.get(f"/api/cron/jobs/{JOB}/outputs" + suffix)
        assert response.status_code == 503
        assert response.json()["detail"] == capability["reason"]
