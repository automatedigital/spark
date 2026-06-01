"""Tests for core/cli/parsing.py helpers (Phase 3 extraction)."""

import json


def test_load_prefill_messages_relative_path_resolves_under_spark_home(tmp_path, monkeypatch):
    """A relative --prefill path resolves under SPARK_HOME.

    Regression: the extracted parsing module originally referenced an
    undefined module global `_spark_home` on this branch; it now uses
    get_spark_home().
    """
    monkeypatch.setenv("SPARK_HOME", str(tmp_path))
    (tmp_path / "pf.json").write_text(
        json.dumps([{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}])
    )

    from core.cli.parsing import _load_prefill_messages

    msgs = _load_prefill_messages("pf.json")  # relative -> the previously-broken branch
    assert [m["role"] for m in msgs] == ["user", "assistant"]


def test_load_prefill_messages_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("SPARK_HOME", str(tmp_path))
    from core.cli.parsing import _load_prefill_messages

    assert _load_prefill_messages("does-not-exist.json") == []


def test_load_prefill_messages_empty_arg_returns_empty():
    from core.cli.parsing import _load_prefill_messages

    assert _load_prefill_messages("") == []


def test_parse_reasoning_config_roundtrip():
    from core.cli.parsing import _parse_reasoning_config

    # A known effort produces a dict; an empty value yields None.
    assert _parse_reasoning_config("high") is not None
    assert _parse_reasoning_config("") is None
