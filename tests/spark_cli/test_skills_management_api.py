"""Focused security and mutation tests for the Skills management API."""

from pathlib import Path

import pytest

from core.spark_constants import get_spark_home


def _skill(root: Path, name: str, body: str = "Do the safe thing.") -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Test skill\n---\n\n{body}\n",
        encoding="utf-8",
    )
    (directory / "references").mkdir()
    (directory / "references" / "notes.md").write_text("supporting", encoding="utf-8")
    return directory


@pytest.fixture()
def client(monkeypatch):
    from starlette.testclient import TestClient

    import spark_cli.web_server as web_server
    import tools.skills_sync as skills_sync

    monkeypatch.setattr(skills_sync, "sync_skills", lambda quiet=True: {})
    return TestClient(web_server.app)


def test_skill_detail_save_and_security_boundaries(client):
    directory = _skill(get_spark_home() / "skills", "api-demo")
    response = client.get("/api/skills")
    assert response.status_code == 200
    row = next(item for item in response.json() if item["name"] == "api-demo")
    skill_id = row["skill_id"]
    assert row["provenance"] == "local"
    assert row["capabilities"]["editable"] is True
    assert str(directory) not in response.text

    detail = client.get(f"/api/skills/{skill_id}")
    assert detail.status_code == 200
    assert detail.json()["content"].startswith("---")
    assert detail.json()["supporting_files"][0]["path"] == "references/notes.md"

    invalid = client.put(f"/api/skills/{skill_id}", json={"content": "not frontmatter"})
    assert invalid.status_code == 422
    assert "not frontmatter" not in directory.joinpath("SKILL.md").read_text(encoding="utf-8")

    valid_content = "---\nname: api-demo\ndescription: Updated\n---\n\nUpdated safely.\n"
    saved = client.put(f"/api/skills/{skill_id}", json={"content": valid_content})
    assert saved.status_code == 200
    assert directory.joinpath("SKILL.md").read_text(encoding="utf-8") == valid_content

    traversal = client.put("/api/skills/%252e%252e%252fetc%252fpasswd", json={"content": "x"})
    assert traversal.status_code in {404, 405}
    assert "root:x:" not in traversal.text


def test_external_skill_is_view_only(client, monkeypatch, tmp_path):
    external = tmp_path / "external"
    _skill(external, "external-demo")
    import agent.skill_utils as skill_utils

    monkeypatch.setattr(skill_utils, "get_external_skills_dirs", lambda: [external])
    response = client.get("/api/skills")
    row = next(item for item in response.json() if item["name"] == "external-demo")
    assert row["provenance"] == "external"
    assert row["capabilities"]["editable"] is False
    assert client.put(f"/api/skills/{row['skill_id']}", json={"content": "---\nname: external-demo\ndescription: x\n---\n\nchanged"}).status_code == 403
    assert client.delete(f"/api/skills/{row['skill_id']}").status_code == 409


def test_hub_skill_uses_lock_uninstall_path(client):
    directory = _skill(get_spark_home() / "skills", "hub-demo")
    from tools.skills_hub import HubLockFile

    lock = HubLockFile(path=get_spark_home() / "skills" / ".hub" / "lock.json")
    lock.record_install(
        name="hub-demo",
        source="github",
        identifier="example/hub-demo",
        trust_level="trusted",
        scan_verdict="pass",
        skill_hash="",
        install_path="hub-demo",
        files=["SKILL.md"],
    )
    response = client.get("/api/skills")
    row = next(item for item in response.json() if item["name"] == "hub-demo")
    assert row["provenance"] == "hub_installed"
    assert row["capabilities"]["removal_mode"] == "hub_uninstall"
    removed = client.delete(f"/api/skills/{row['skill_id']}")
    assert removed.status_code == 200
    assert not directory.exists()
    assert lock.get_installed("hub-demo") is None
