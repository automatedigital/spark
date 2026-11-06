"""Selection crosses real profile, session and canonical receipt boundaries."""
from copy import deepcopy

import pytest
from fastapi import HTTPException

from core.spark_constants import get_spark_home
from core.spark_state import SessionDB
from spark_cli import web_server as web
from tools.skills_index import list_skill_index

pytestmark = pytest.mark.serial


@pytest.fixture
def selection():
    home = get_spark_home()
    directory = home / "skills" / "chosen"
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text("---\nname: chosen\ndescription: test\n---\nSELECTED_BODY")
    row = next(row for row in list_skill_index() if row["name"] == "chosen")
    db = SessionDB()
    db.create_session("target", "web")
    db.create_session("other", "web")
    db.close()
    return {"id": "skill:" + row["skill_id"], "type": "skill", "scope": "one_turn",
            "skill_id": row["skill_id"], "skill_revision": row["revision"],
            "skill_profile": str(home), "skill_thread": "target", "skill_project": None}


def test_target_profile_and_project_fences(selection):
    validated = web._validate_context_items([selection])
    web._persist_context_items("target", validated)
    assert "SELECTED_BODY" in web._build_context_augmented_message("target", "draft", validated)
    with pytest.raises(HTTPException):
        web._persist_context_items("other", validated)
    for key, value in [("skill_profile", "another-profile"), ("skill_project", "other"), ("skill_revision", "old"), ("content", "forged")]:
        bad = selection | {key: value}
        with pytest.raises(HTTPException):
            web._validate_context_items([bad])
    db = SessionDB()
    assert db._conn.execute("SELECT count(*) FROM context_items WHERE session_id='target'").fetchone()[0] == 0
    db.close()


def test_receipt_covers_selection_and_identical_retry_does_not_redispatch(selection, monkeypatch):
    body = web.ConversationMessage(message="unsent draft", context_items=[selection], submission_id="chosen-once")
    first = web._root_submission("target", body, "root.message", accept=True, route="/api/conversations/messages")
    assert first["created"]
    monkeypatch.setattr(web, "_selected_skill_context", lambda *a, **k: pytest.fail("retry must not invoke"))
    replay = web._root_submission("target", body, "root.message", route="/api/conversations/messages")
    assert replay["acceptance"]["turn_id"] == first["acceptance"]["turn_id"]
    changed = deepcopy(selection)
    changed["skill_revision"] = "another-revision"
    body.context_items = [changed]
    with pytest.raises(HTTPException) as error:
        web._root_submission("target", body, "root.message", route="/api/conversations/messages")
    assert error.value.status_code == 409
    db = SessionDB()
    assert len(db.list_web_turn_projections("target")) == 1
    assert len(db.get_messages("target")) == 1
    db.close()


def test_skill_instructions_do_not_activate_toolset_refresh(selection, monkeypatch):
    from types import SimpleNamespace

    from tools.skills_index import list_skill_index

    path = get_spark_home() / "skills/chosen/SKILL.md"
    path.write_text(path.read_text() + "\n/computer-use example inside instructions")
    selection["skill_revision"] = next(row for row in list_skill_index() if row["name"] == "chosen")["revision"]
    observed = []
    monkeypatch.setattr(web, "_refresh_web_agent_for_computer_use", lambda agent, message: observed.append(message))
    monkeypatch.setattr(web, "_maybe_capture_codex_usage_limit", lambda *args: None)
    messages = []
    agent = SimpleNamespace(session_id="target", run_conversation=lambda message: messages.append(message))
    web._run_web_agent_turn(agent, "typed words", context_items=web._validate_context_items([selection]))
    assert observed == ["typed words"]
    assert "/computer-use example inside instructions" in messages[0]
