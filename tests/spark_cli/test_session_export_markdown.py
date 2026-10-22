"""F03/B01 local CLI export acceptance with synthetic sessions only."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.spark_state import SessionDB
from spark_cli.session_export import export_session_redacted, redact_session
from spark_cli.session_export_markdown import render_session_markdown

FAKE_SECRET = "sk-syntheticFAKEcredential0123456789"


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    for key in ("HOME", "USERPROFILE", "SPARK_HOME"):
        monkeypatch.setenv(key, str(tmp_path))


def payload():
    return {
        "id": "child", "parent_session_id": "parent", "title": "Café 日本語",
        "messages": [
            {"role": "system", "content": "Follow instructions", "timestamp": 0},
            {"role": "user", "content": "Unicode: café 日本語\n```python\nprint('hi')\n```\n`````"},
            {"role": "assistant", "content": [{"type": "text", "text": FAKE_SECRET}],
             "reasoning": FAKE_SECRET, "tool_calls": [
                 {"id": "call_1", "function": {"name": "read", "arguments": json.dumps({
                     "nested": [{"apiKey": 'unprefixed"password\\value', "key": FAKE_SECRET}],
                     "count": 4, "enabled": True, "empty": None})}},
                 {"type": "function_call", "call_id": "call_2", "name": "write",
                  "arguments": {"token": "unprefixed-secret", "items": [FAKE_SECRET]}},
             ]},
            {"role": "tool", "tool_call_id": "call_1", "content": {
                "output": [FAKE_SECRET, {"password": "output-secret"}], "ok": True}},
        ],
    }


def test_nested_redaction_preserves_input_and_types_with_logs_disabled(monkeypatch):
    monkeypatch.setattr("agent.redact._REDACT_ENABLED", False)
    source = payload()
    before = copy.deepcopy(source)
    result = redact_session(source)
    encoded = json.dumps(result)
    for secret in (FAKE_SECRET, "unprefixed-secret", "output-secret", "unprefixed"):
        assert secret not in encoded
    assert source == before
    arguments = json.loads(result["messages"][2]["tool_calls"][0]["function"]["arguments"])
    assert arguments["count"] == 4
    assert arguments["enabled"] is True
    assert arguments["empty"] is None
    assert result["messages"][2]["tool_calls"][0]["id"] == "call_1"
    result["messages"][0]["content"] = "changed"
    assert source == before


def test_force_redaction_keeps_log_opt_out_independent(monkeypatch):
    from agent.redact import redact_sensitive_text

    monkeypatch.setattr("agent.redact._REDACT_ENABLED", False)
    assert redact_sensitive_text(FAKE_SECRET) == FAKE_SECRET
    assert FAKE_SECRET not in redact_sensitive_text(FAKE_SECRET, force=True)


def test_ordinary_nested_data_and_serialized_arguments_are_preserved():
    source = {"messages": [{"role": "assistant", "tool_calls": [{
        "id": "call_ordinary", "arguments": '{ "name": "Café", "count": 2 }',
        "output": [None, False, 2, {"name": "日本語"}],
    }]}]}
    assert redact_session(source) == source


def test_unknown_role_and_html_stay_literal():
    text = render_session_markdown({"messages": [{
        "role": "custom\n# injected", "timestamp": "2026-10-22T12:00:00Z",
        "content": "</details><script>fake()</script>\n``````\n# injected",
    }]})
    assert "### 1. Message" in text
    assert "```````text\n</details>" in text
    assert '"role": "custom\\n# injected"' in text


@pytest.mark.parametrize("format,suffix", [("json", ".json"), ("markdown", ".md")])
def test_final_export_bytes(format, suffix):
    source = payload()
    db = SimpleNamespace(export_session=lambda sid: source)
    result = export_session_redacted("child", db, format=format)
    path = Path(result["path"])
    assert path.suffix == suffix
    assert result["messages"] == 4
    text = path.read_text()
    assert FAKE_SECRET not in text
    assert "unprefixed-secret" not in text
    assert "output-secret" not in text
    assert "café" in text and "日本語" in text
    assert "parent" in text
    if format == "markdown":
        assert "### 1. System" in text
        assert "### 2. User" in text
        assert "### 3. Assistant" in text
        assert "### 4. Tool" in text
        assert "1970-01-01T00:00:00+00:00" in text
        assert "``````text\nUnicode:" in text
        assert "#### Tool calls" in text
        assert "#### Reasoning" in text
    else:
        assert json.loads(text)["parent_session_id"] == "parent"


def test_export_default_errors_and_empty_session(tmp_path, monkeypatch):
    db = Mock()
    assert "error" in export_session_redacted("s", db, format="html")
    assert "error" in export_session_redacted("../s", db)
    db.export_session.assert_not_called()
    db.export_session.return_value = {"id": "s", "messages": []}
    assert export_session_redacted("s", db)["path"].endswith(".json")
    assert "No messages" in render_session_markdown({"messages": []})
    db.export_session.return_value = None
    assert "Session not found" in export_session_redacted("s", db)["error"]
    db.export_session.return_value = {"id": "s", "messages": []}
    monkeypatch.setattr(Path, "write_text", Mock(side_effect=OSError("fixture denied")))
    assert "fixture denied" in export_session_redacted("s", db)["error"]


@pytest.mark.parametrize("command", [
    "/export --format", "/export --format html", "/export --unknown",
    "/export one two", '/export "unterminated',
])
def test_cli_invalid_format_never_exports(command, monkeypatch):
    from core.cli.session_ops_mixin import _SessionOpsMixin

    export = Mock()
    output = Mock()
    monkeypatch.setattr("spark_cli.session_export.export_session_redacted", export)
    monkeypatch.setattr("core.cli.render._cprint", output)
    _SessionOpsMixin()._handle_export_command(command)
    export.assert_not_called()
    output.assert_called_once()


def test_cli_real_db_local_and_opt_in_publisher(tmp_path, monkeypatch):
    """Exercise actual slash dispatch -> SQLite export -> bytes -> fake publisher."""
    from core.cli.session_ops_mixin import _SessionOpsMixin

    monkeypatch.setattr("agent.redact._REDACT_ENABLED", False)
    output = []
    monkeypatch.setattr("core.cli.render._cprint", output.append)
    published = []

    def publish(path):
        text = Path(path).read_text()
        assert FAKE_SECRET not in text
        assert "plain-fake-password" not in text
        published.append(path)
        return {"ok": True, "url": "https://example.invalid/synthetic-gist"}

    monkeypatch.setattr("spark_cli.session_export.publish_export", publish)
    db = SessionDB(db_path=tmp_path / "fixture.db")
    try:
        db.create_session("parent", "cli")
        db.create_session("child", "cli", parent_session_id="parent")
        db.append_message("child", "user", "Café ```code``` " + FAKE_SECRET)
        db.append_message("child", "assistant", None, tool_calls=[{
            "id": "call_fixture", "function": {"name": "test", "arguments": json.dumps({
                "nested": [{"token": "plain-fake-password", "value": FAKE_SECRET}]
            })}
        }], reasoning=FAKE_SECRET)
        db.append_message("child", "tool", FAKE_SECRET, tool_call_id="call_fixture")
        before = db.export_session("child")
        cli = _SessionOpsMixin()
        cli.session_id = "child"
        cli._session_db = db
        cli._handle_export_command("/export --format markdown")
        assert not published
        md = tmp_path / "exports/child.md"
        assert "Tool calls" in md.read_text()
        assert "parent" in md.read_text()
        cli._handle_export_command("/export")
        assert not published
        assert (tmp_path / "exports/child.json").is_file()
        cli._handle_export_command("/export child --format=json --publish")
        assert published == [str(tmp_path / "exports/child.json")]
        cli._handle_export_command("/export child --format=markdown --publish")
        assert published[-1] == str(md)
        assert any("Exported 3 messages" in line for line in output)
        assert db.export_session("child") == before
    finally:
        db.close()
