"""Session export: redacted, shareable JSON file (/export)."""

from __future__ import annotations

import json

from core.spark_state import SessionDB
from spark_cli import session_export


def test_redact_session_strips_secrets():
    session = {
        "id": "s1",
        "messages": [
            {"role": "user", "content": "token sk-ant-api03-ABCDEF1234567890SECRETTOKENvalue1234"},
            {"role": "assistant", "content": "ok", "reasoning": "key sk-ant-api03-XYZ9876543210REASONSECRETtokenvalue99"},
        ],
    }
    out = session_export.redact_session(session)
    blob = json.dumps(out)
    assert "SECRETTOKEN" not in blob  # content redacted
    assert "REASONSECRET" not in blob  # reasoning field also redacted
    assert len(out["messages"]) == 2


def test_export_session_writes_redacted_file(tmp_path, monkeypatch):
    db = SessionDB()
    sid = "exp_sess"
    db.create_session(sid, "cli")
    db.append_message(sid, "user", "my key sk-ant-api03-ABCDEF1234567890SECRETTOKENvalue1234")
    db.append_message(sid, "assistant", "noted")
    try:
        res = session_export.export_session_redacted(sid, db=db)
    finally:
        db.close()
    assert res["ok"] is True
    assert res["messages"] == 2
    content = open(res["path"]).read()
    assert "SECRETTOKEN" not in content


def test_publish_export_without_gh(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)
    res = session_export.publish_export("/tmp/x.json")
    assert "error" in res and "gh" in res["error"].lower()


def test_publish_export_success(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/gh")

    class _Proc:
        returncode = 0
        stdout = "https://gist.github.com/abc123\n"
        stderr = ""

    monkeypatch.setattr("subprocess.run", lambda *a, **k: _Proc())
    res = session_export.publish_export("/tmp/x.json")
    assert res == {"ok": True, "url": "https://gist.github.com/abc123"}


def test_publish_export_failure(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/gh")

    class _Proc:
        returncode = 1
        stdout = ""
        stderr = "auth required"

    monkeypatch.setattr("subprocess.run", lambda *a, **k: _Proc())
    res = session_export.publish_export("/tmp/x.json")
    assert "error" in res


def test_export_missing_session_errors():
    db = SessionDB()
    try:
        res = session_export.export_session_redacted("does-not-exist", db=db)
    finally:
        db.close()
    assert "error" in res
