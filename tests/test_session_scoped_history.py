"""↑/↓ history recall is scoped to the current session, but still persisted."""

from __future__ import annotations

from pathlib import Path

from prompt_toolkit.history import FileHistory

from core.cli import _SessionScopedFileHistory


def test_prior_session_entries_not_preloaded(tmp_path: Path):
    hist_file = tmp_path / ".spark_history"
    FileHistory(str(hist_file)).store_string("old-session-cmd")

    h = _SessionScopedFileHistory(str(hist_file))
    assert list(h.load_history_strings()) == []  # nothing preloaded for ↑/↓


def test_session_entries_are_navigable(tmp_path: Path):
    hist_file = tmp_path / ".spark_history"
    h = _SessionScopedFileHistory(str(hist_file))
    h.append_string("first")
    h.append_string("second")
    assert h.get_strings() == ["first", "second"]


def test_entries_still_persist_to_file(tmp_path: Path):
    hist_file = tmp_path / ".spark_history"
    FileHistory(str(hist_file)).store_string("old-session-cmd")

    h = _SessionScopedFileHistory(str(hist_file))
    h.append_string("this-session-cmd")

    contents = hist_file.read_text()
    assert "old-session-cmd" in contents  # prior entries preserved
    assert "this-session-cmd" in contents  # new entry persisted
