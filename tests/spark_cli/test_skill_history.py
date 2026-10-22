"""Dashboard-only snapshot retention and actual save route regressions."""
from concurrent.futures import ThreadPoolExecutor

import pytest
from starlette.testclient import TestClient

from core.spark_constants import get_spark_home
from spark_cli import skill_history as history


def content(body):
    return f"---\nname: history-demo\ndescription: Fixture\n---\n\n{body}\n"


@pytest.fixture
def skill(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    directory = get_spark_home() / "skills" / "history-demo"
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(content("initial"))
    return directory


def test_two_saves_external_gap_and_profile_isolation(skill, monkeypatch, tmp_path):
    assert history.read_history("demo")["entries"] == []
    for body in ("first", "second"):
        assert history.save_with_history("demo", skill, content(body))["success"]
    result = history.read_history("demo")
    assert [(e["before"], e["after"]) for e in result["entries"]] == [
        (content("first"), content("second")), (content("initial"), content("first"))]
    assert len({e["id"] for e in result["entries"]}) == 2
    (skill / "SKILL.md").write_text(content("external"))
    assert history.read_history("demo") == result
    assert history.save_with_history("demo", skill, content("third"))["success"]
    assert history.read_history("demo")["entries"][0]["before"] == content("external")
    monkeypatch.setenv("SPARK_HOME", str(tmp_path / "other-profile"))
    assert history.read_history("demo")["entries"] == []
    assert "agent edits" in result["coverage"]


def test_concurrent_saves_form_a_chain_and_bound_retention(skill):
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda n: history.save_with_history("demo", skill, content(str(n))), range(25)))
    assert all(r["success"] for r in results)
    entries = history.read_history("demo")["entries"]
    assert len(entries) == history.MAX_EDITS
    assert (skill / "SKILL.md").read_text() == entries[0]["after"]
    assert all(newer["before"] == older["after"] for newer, older in zip(entries, entries[1:]))
    assert history.read_history("different-id")["entries"] == []


def test_failed_save_noop_and_atomic_append_failure(skill, monkeypatch):
    assert not history.save_with_history("demo", skill, "invalid")["success"]
    assert history.save_with_history("demo", skill, content("initial"))["success"]
    assert history.read_history("demo")["entries"] == []
    history.save_with_history("demo", skill, content("first"))
    old = history.read_history("demo")
    def fail(*args):
        raise OSError("disk full")
    monkeypatch.setattr(history.os, "replace", fail)
    # Isolate history publication failure from the existing skill writer.
    import tools.skill_manager_tool as manager
    def save(directory, text):
        (directory / "SKILL.md").write_text(text)
        return {"success": True}
    monkeypatch.setattr(manager, "save_skill_content", save)
    result = history.save_with_history("demo", skill, content("second"))
    assert result["success"] and "history_warning" in result
    assert history.read_history("demo") == old
    assert not list(get_spark_home().glob(".skill-history-*"))


def test_route_history_and_corrupt_store_fail_before_save(skill, monkeypatch):
    import spark_cli.web_server as server
    from tools.skills_metadata import iter_skill_records
    row = next(r for r in iter_skill_records() if r["name"] == "history-demo")
    client = TestClient(server.app)
    url = f"/api/skills/{row['skill_id']}"
    for body in ("one", "two"):
        assert client.put(url, json={"content": content(body)}).status_code == 200
    response = client.get(url + "/history")
    assert response.status_code == 200
    assert response.json()["entries"][0]["after"] == content("two")
    assert client.get("/api/skills/unknown/history").status_code == 404
    (get_spark_home() / "skill-history.json").write_text("broken")
    assert client.get(url + "/history").status_code == 503
    assert client.put(url, json={"content": content("three")}).status_code == 503
    assert (skill / "SKILL.md").read_text() == content("two")


def test_process_saves_use_same_lock_and_snapshot_sequence(skill):
    import os
    import subprocess
    import sys

    code = '''from pathlib import Path
import sys
from spark_cli.skill_history import save_with_history
result = save_with_history("demo", Path(sys.argv[1]), sys.argv[2])
assert result["success"], result
'''
    children = [subprocess.Popen([sys.executable, "-c", code, str(skill), content(f"process-{n}")], env=os.environ.copy()) for n in range(3)]
    assert [child.wait(timeout=20) for child in children] == [0, 0, 0]
    entries = history.read_history("demo")["entries"]
    assert len(entries) == 3
    assert all(newer["before"] == older["after"] for newer, older in zip(entries, entries[1:]))
    assert entries[-1]["before"] == content("initial")
    assert entries[0]["after"] == (skill / "SKILL.md").read_text()


def test_equal_timestamps_do_not_identify_or_order_edits(skill, monkeypatch):
    class Clock:
        @staticmethod
        def now(_timezone):
            from datetime import datetime
            return datetime(2026, 1, 1)
    monkeypatch.setattr(history, "datetime", Clock)
    for body in ("one", "two"):
        assert history.save_with_history("demo", skill, content(body))["success"]
    entries = history.read_history("demo")["entries"]
    assert entries[0]["saved_at"] == entries[1]["saved_at"]
    assert entries[0]["id"] != entries[1]["id"]
    assert entries[0]["after"] == content("two")


def test_oversized_before_and_malformed_store_are_rejected(skill):
    target = skill / "SKILL.md"
    target.write_text("x" * (history.MAX_CONTENT_BYTES + 1))
    result = history.save_with_history("demo", skill, content("next"))
    assert not result["success"] and "limit" in result["error"]
    assert target.stat().st_size > history.MAX_CONTENT_BYTES
    (get_spark_home() / "skill-history.json").write_text('[{"id":"bad"}]')
    with pytest.raises(ValueError, match="Invalid skill history entry"):
        history.read_history("demo")
