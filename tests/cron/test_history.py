"""Real SQLite receipts and replay at external execution/delivery boundaries."""
from concurrent.futures import ThreadPoolExecutor

import pytest

from cron.history import History


@pytest.fixture
def ledger(tmp_path):
    return History(tmp_path)


def job(n=0):
    return {"id": "abcdef123456", "next_run_at": str(n)}


@pytest.mark.parametrize("delivery", ["sent", "error", "silent", "suppressed", "no_target", "empty"])
def test_outcomes_and_duplicate_callbacks(ledger, delivery):
    attempt = ledger.accept(job())
    assert ledger.start(attempt)
    assert not ledger.start(attempt)
    assert ledger.executed(attempt, "success")
    assert ledger.finish(attempt, delivery, "send failed" if delivery == "error" else None)
    assert not ledger.finish(attempt, "sent")
    assert not ledger.executed(attempt, "error")
    assert ledger.accept(job()) is None
    row = ledger.page()["attempts"][0]
    assert row["delivery"] == delivery
    assert row["execution"] == "success"


@pytest.mark.parametrize("phase", ["accepted", "running", "executed", "delivered"])
def test_crash_replay_never_reruns_or_infers_delivery(ledger, phase):
    attempt = ledger.accept(job())
    if phase != "accepted":
        ledger.start(attempt)
    if phase in {"executed", "delivered"}:
        ledger.executed(attempt, "success")
    # 'delivered' models remote acceptance before local acknowledgement commit.
    restarted = History(ledger.home)
    restarted.reconcile()
    assert restarted.accept(job()) is None
    row = restarted.page()["attempts"][0]
    assert row["execution"] == ("success" if phase in {"executed", "delivered"} else "interrupted")
    assert row["delivery"] == "unknown"
    assert not restarted.finish(attempt, "sent")


def test_manual_profile_output_pruning_and_paging(ledger, tmp_path, monkeypatch):
    ledger.manual(job()["id"], "0")
    output = ledger.home / "cron/output/abcdef123456/2026-11-06_12-00-00.md"
    output.parent.mkdir(parents=True)
    output.write_text("legacy or prunable document")
    attempt = ledger.accept(job())
    ledger.executed(attempt, "cancelled", output=output)
    ledger.finish(attempt, "suppressed")
    output.unlink()
    for n in range(1, 25):
        attempt = ledger.accept(job(n))
        ledger.executed(attempt, "success")
        ledger.finish(attempt, "silent")
    first = ledger.page(limit=20)
    second = ledger.page(before=first["next_before"])
    assert len(first["attempts"]) == 20 and len(second["attempts"]) == 5
    assert second["attempts"][-1]["cause"] == "manual"
    assert second["attempts"][-1]["output_ref"] == "abcdef123456/2026-11-06_12-00-00.md"
    assert History(tmp_path / "other-profile").page()["attempts"] == []
    with ThreadPoolExecutor(4) as pool:
        assert all(len(page["attempts"]) == 20 for page in pool.map(lambda _: ledger.page(), range(12)))
    monkeypatch.setattr("cron.history.MAX_HISTORY", 3)
    ledger.prune()
    assert len(ledger.page()["attempts"]) == 3


def test_safe_output_reference(ledger):
    attempt = ledger.accept(job())
    with pytest.raises(ValueError):
        ledger.executed(attempt, "success", output=ledger.home / "secret")
    with pytest.raises(ValueError):
        ledger.executed(attempt, "success", output=ledger.home / "cron/output/123456abcdef/2026-11-06_12-00-00.md")


@pytest.mark.parametrize("response,success,error,delivery_error,expected", [
    ("done", True, None, "offline", ("success", "error")),
    ("[SILENT]", True, None, None, ("success", "silent")),
    ("paused", True, None, None, ("success", "suppressed")),
    ("local", True, None, None, ("success", "no_target")),
    ("", False, "execution failed", "offline", ("error", "error")),
    ("", False, "RuntimeError: Cron job cancelled", None, ("cancelled", "suppressed")),
])
def test_scheduler_replay(tmp_path, monkeypatch, response, success, error, delivery_error, expected):
    monkeypatch.setenv("SPARK_HOME", str(tmp_path))
    from cron import scheduler
    from core import dream

    record = {**job(), "name": "fixture", "deliver": "local" if response == "local" else "telegram:123"}
    monkeypatch.setattr(scheduler, "_spark_home", tmp_path)
    monkeypatch.setattr(scheduler, "_LOCK_DIR", tmp_path)
    monkeypatch.setattr(scheduler, "_LOCK_FILE", tmp_path / ".tick.lock")
    monkeypatch.setattr(dream, "scheduler_tick", lambda: None)
    monkeypatch.setattr(scheduler, "get_due_jobs", lambda: [record])
    monkeypatch.setattr(scheduler, "get_job", lambda _: {**record, "state": "paused"} if response == "paused" else record)
    monkeypatch.setattr(scheduler, "advance_next_run", lambda _: None)
    monkeypatch.setattr(scheduler, "run_job", lambda *a, **kw: (success, "document", response, error))
    output = tmp_path / "cron/output/abcdef123456/2026-11-06_12-00-00.md"
    monkeypatch.setattr(scheduler, "save_job_output", lambda *a: output)
    sends = []
    monkeypatch.setattr(scheduler, "_deliver_result", lambda *a, **kw: sends.append(1) or delivery_error)
    import sys
    from types import SimpleNamespace

    notifications = []
    def notify(*args):
        assert History(tmp_path).page()["attempts"][0]["delivery"] == expected[1]
        notifications.append(args)
    monkeypatch.setitem(sys.modules, "spark_cli.web_server", SimpleNamespace(push_job_notification=notify))
    marks = []
    monkeypatch.setattr(scheduler, "mark_job_run", lambda *a, **kw: marks.append(a))
    assert scheduler.tick(False) == 1
    assert scheduler.tick(False) == 0
    row = History(tmp_path).page()["attempts"][0]
    assert (row["execution"], row["delivery"]) == expected
    assert len(sends) == (0 if expected[1] in {"silent", "suppressed"} else 1)
    assert len(notifications) == (0 if expected[1] == "suppressed" else 1)


def test_read_api_legacy_files_removed_job_and_invalid_pages(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from spark_cli.cron_routes import register_cron_routes

    monkeypatch.setenv("SPARK_HOME", str(tmp_path))
    output = tmp_path / "cron/output/abcdef123456/2026-11-06_12-00-00.md"
    output.parent.mkdir(parents=True)
    output.write_text("legacy body")
    app = FastAPI()
    register_cron_routes(app)
    with TestClient(app) as client:
        assert client.get("/api/cron/history").json()["attempts"] == []
        assert client.get("/api/cron/jobs/abcdef123456/outputs/2026-11-06_12-00-00.md").json()["content"] == "legacy body"
        for query in ("limit=0", "limit=51", "before=-1"):
            assert client.get(f"/api/cron/history?{query}").status_code == 400
        ledger = History(tmp_path)
        attempt = ledger.accept(job())
        ledger.executed(attempt, "success")
        ledger.attach_output(attempt, output)
        ledger.finish(attempt, "no_target")
        output.unlink()
        page = client.get("/api/cron/history").json()
        assert page["attempts"][0]["job_id"] == job()["id"]
        assert "legacy body" not in str(page)
        assert client.get("/api/cron/jobs/abcdef123456/outputs/2026-11-06_12-00-00.md").status_code == 404


def test_pruning_keeps_dispatch_guard_and_reconcile_keeps_confirmed_delivery(ledger, monkeypatch):
    attempt = ledger.accept(job())
    ledger.executed(attempt, "success")
    ledger.finish(attempt, "sent")
    ledger.reconcile()
    assert ledger.page()["attempts"][0]["delivery"] == "sent"
    monkeypatch.setattr("cron.history.MAX_HISTORY", 0)
    ledger.prune({job()["id"]})
    assert ledger.page()["attempts"] == []
    assert ledger.accept(job()) is None
