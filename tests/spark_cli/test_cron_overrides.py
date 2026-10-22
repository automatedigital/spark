"""Profile-isolated HTTP -> persistence -> scheduler regression for Schedule."""
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from spark_cli.cron_routes import register_cron_routes


@pytest.fixture
def client(tmp_path, monkeypatch):
    for key in ("HOME", "USERPROFILE", "SPARK_HOME"):
        monkeypatch.setenv(key, str(tmp_path))
    import cron.jobs as jobs
    monkeypatch.setattr(jobs, "JOBS_FILE", tmp_path / "cron" / "jobs.json")
    monkeypatch.setattr(jobs, "CRON_DIR", tmp_path / "cron")
    app = FastAPI()
    register_cron_routes(app)
    return TestClient(app)


def test_overrides_round_trip_and_scheduler(client, tmp_path):
    from cron.scheduler import _build_job_prompt, run_job

    job = client.post("/api/cron/jobs", json={
        "prompt": "Summarize fixture", "schedule": "0 9 * * *",
        "model": "fixture-model", "provider": "fixture-provider",
        "skills": ["second", "first", "second"],
    }).json()
    assert job["skills"] == ["second", "first"]
    assert client.get(f"/api/cron/jobs/{job['id']}").json() == job
    with patch("tools.skills_tool.skill_view", side_effect=lambda name: json.dumps({
        "success": True, "content": f"SKILL_{name}",
    })) as view:
        prompt = _build_job_prompt(job)
    assert prompt.index("SKILL_second") < prompt.index("SKILL_first")
    assert [call.args[0] for call in view.call_args_list] == ["second", "first"]
    runtime = {"provider": "fixture-provider", "api_mode": "chat_completions",
               "base_url": "http://127.0.0.1:1/v1", "api_key": "fixture"}
    with patch("cron.scheduler._spark_home", tmp_path), \
         patch("dotenv.load_dotenv"), \
         patch("core.spark_state.SessionDB", return_value=MagicMock()), \
         patch("spark_cli.runtime_provider.resolve_runtime_provider", return_value=runtime) as resolve, \
         patch("tools.skills_tool.skill_view", return_value=json.dumps({"success": True, "content": "fixture"})), \
         patch("core.run_agent.AIAgent") as agent:
        agent.return_value.run_conversation.return_value = {"final_response": "fixture complete"}
        success, _, response, error = run_job(job)
    assert success, error
    assert response == "fixture complete"
    resolve.assert_called_once_with(requested="fixture-provider")
    assert agent.call_args.kwargs["model"] == "fixture-model"
    assert agent.call_args.kwargs["provider"] == "fixture-provider"

    edited = client.put(f"/api/cron/jobs/{job['id']}", json={"updates": {
        "model": "fixture-two", "provider": "provider-two", "skills": ["first", "second"],
    }})
    assert edited.status_code == 200
    assert edited.json()["skills"] == ["first", "second"]
    cleared = client.put(f"/api/cron/jobs/{job['id']}", json={"updates": {
        "model": None, "provider": "", "skills": [], "skill": "stale-legacy",
    }}).json()
    assert cleared["model"] is None and cleared["provider"] is None
    assert cleared["skills"] == [] and cleared["skill"] is None
    assert client.get("/api/cron/jobs").json() == [cleared]


def test_default_legacy_and_invalid_overrides(client):
    job = client.post("/api/cron/jobs", json={"prompt": "Default", "schedule": "0 9 * * *"}).json()
    assert job["model"] is None and job["provider"] is None and job["skills"] == []
    from cron.jobs import update_job
    update_job(job["id"], {"skill": "legacy", "skills": None})
    assert client.get(f"/api/cron/jobs/{job['id']}").json()["skills"] == ["legacy"]
    response = client.put(f"/api/cron/jobs/{job['id']}", json={"updates": {"skills": []}})
    assert response.json()["skill"] is None
    for updates in ({"skills": 42}, {"model": {}}, {"provider": []}):
        assert client.put(f"/api/cron/jobs/{job['id']}", json={"updates": updates}).status_code == 400
    assert client.post("/api/cron/jobs", json={
        "prompt": "Bad", "schedule": "0 9 * * *", "skills": 42,
    }).status_code == 422


def test_provider_options_resolve_saved_and_authenticated_only(client):
    def resolve(requested=None):
        if requested == "broken":
            raise ValueError("private credential details")
        return {"provider": requested or "default", "api_key": "secret"}

    with patch("spark_cli.config.load_config", return_value={
        "providers": {"saved": {"name": "Saved endpoint"}, "broken": {}},
        "custom_providers": [{"name": "Legacy endpoint"}],
    }), patch("spark_cli.models.list_available_providers", return_value=[
        {"id": "authenticated", "label": "Available", "authenticated": True},
        {"id": "unconfigured", "label": "Unavailable", "authenticated": False},
    ]), patch("spark_cli.runtime_provider.resolve_runtime_provider", side_effect=resolve):
        response = client.get("/api/cron/providers")
    assert response.status_code == 200
    options = response.json()
    assert {item["id"] for item in options} == {"default", "saved", "authenticated", "custom:legacy-endpoint"}
    assert "secret" not in response.text and "private" not in response.text


def test_real_skill_catalog_save_reload_and_scheduler(tmp_path):
    """Fresh process: real configured roots, loader, storage and prompt assembly.

    No skills mocks or provider calls; API construction never starts the runtime.
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    script = r'''
import json
import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
from spark_cli.cron_routes import register_cron_routes
from cron.scheduler import _build_job_prompt

home = Path(os.environ["SPARK_HOME"])
for folder, name, body in [
    ("folder-slug", "FriendlySkill", "REAL_FRIENDLY_INSTRUCTION"),
    ("group/first", "Duplicate", "REAL_FIRST_INSTRUCTION"),
    ("group/second", "Duplicate", "REAL_SECOND_INSTRUCTION"),
    ("one/shared", "One", "ONE"), ("two/shared", "Two", "TWO"),
]:
    directory = home / "skills" / folder
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(f"---\nname: {name}\ndescription: fixture\n---\n{body}\n")
external = home / "external"
(external / "folder-slug").mkdir(parents=True)
(external / "folder-slug/SKILL.md").write_text("---\nname: Shadow\n---\nSHADOW\n")
app = FastAPI()
register_cron_routes(app)
client = TestClient(app)
catalog = client.get("/api/cron/skills").json()
assert {item["id"] for item in catalog} == {"folder-slug", "group/first", "group/second", "one/shared", "two/shared"}, catalog
assert len([item for item in catalog if item["name"] == "Duplicate"]) == 2
job = client.post("/api/cron/jobs", json={"prompt": "fixture", "schedule": "0 9 * * *", "skills": ["group/second", "folder-slug", "group/first", "folder-slug"]}).json()
assert job["skills"] == ["group/second", "folder-slug", "group/first"], job
saved = client.get(f"/api/cron/jobs/{job['id']}").json()
assert saved["skills"] == job["skills"]
assert json.loads((home / "cron/jobs.json").read_text())["jobs"][0]["skills"] == job["skills"]
prompt = _build_job_prompt(saved)
assert prompt.index("REAL_SECOND_INSTRUCTION") < prompt.index("REAL_FRIENDLY_INSTRUCTION") < prompt.index("REAL_FIRST_INSTRUCTION"), prompt
assert "were skipped" not in prompt
# Old uniquely named strings canonicalize; old actual folder strings still run.
legacy = client.put(f"/api/cron/jobs/{job['id']}", json={"updates": {"skills": ["FriendlySkill"]}})
assert legacy.json()["skills"] == ["folder-slug"], legacy.text
assert "REAL_FRIENDLY_INSTRUCTION" in _build_job_prompt({"prompt": "old", "skill": "folder-slug"})
legacy_update = client.put(f"/api/cron/jobs/{job['id']}", json={"updates": {"skill": "FriendlySkill"}})
assert legacy_update.json()["skills"] == ["folder-slug"], legacy_update.text
for ambiguous in ("Duplicate", "shared"):
    legacy_rejected = client.put(f"/api/cron/jobs/{job['id']}", json={"updates": {"skill": ambiguous}})
    assert legacy_rejected.status_code == 400 and "Ambiguous" in legacy_rejected.text, legacy_rejected.text
    rejected = client.put(f"/api/cron/jobs/{job['id']}", json={"updates": {"skills": [ambiguous]}})
    assert rejected.status_code == 400 and "Ambiguous" in rejected.text, rejected.text
# Same relative path in another configured root cannot silently choose first match.
(home / "config.yaml").write_text("skills:\n  external_dirs:\n    - " + external.as_posix() + "\n")
catalog = client.get("/api/cron/skills").json()
collision = next(item for item in catalog if item["id"] == "folder-slug")
assert collision["enabled"] is False and "Ambiguous" in collision["reason"], catalog
rejected = client.post("/api/cron/jobs", json={"prompt": "fixture", "schedule": "0 9 * * *", "skills": ["folder-slug"]})
assert rejected.status_code == 400 and "Ambiguous" in rejected.text, rejected.text
cleared = client.put(f"/api/cron/jobs/{job['id']}", json={"updates": {"skills": [], "skill": "folder-slug", "model": None, "provider": ""}}).json()
assert cleared["skills"] == [] and cleared["skill"] is None
assert cleared["model"] is None and cleared["provider"] is None
print("PASS real catalog -> save -> disk/reload -> scheduler, duplicate labels/paths, legacy, clear")
'''
    env = {**os.environ, "HOME": str(tmp_path), "USERPROFILE": str(tmp_path),
           "SPARK_HOME": str(tmp_path), "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")}
    result = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=25)
    assert result.returncode == 0, result.stdout + result.stderr
