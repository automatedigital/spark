"""Unit tests for the TokenJuice tool-output normalization pipeline."""

import json

import pytest

from tools.normalize import (
    CompiledRules,
    TINY_OUTPUT_MAX_CHARS,
    compact_tool_output,
    load_rules,
    _parse_rule,
)


def _padded(s: str) -> str:
    """Pad text past the tiny-output passthrough threshold."""
    if len(s) >= TINY_OUTPUT_MAX_CHARS:
        return s
    return s + "\n" + ("x" * (TINY_OUTPUT_MAX_CHARS + 1))


def _rule(**overrides):
    base = {
        "id": "test.rule",
        "match": {},
        "transforms": {},
        "filters": {},
    }
    base.update(overrides)
    return _parse_rule(base)


def test_tiny_output_passes_through():
    text = "hello world"
    rules = CompiledRules(rules=[_rule(transforms={"strip_ansi": True})])
    out, stats = compact_tool_output(text, "any_tool", rules=rules)
    assert out == text
    assert stats.rules_applied == []


def test_strip_ansi():
    raw = _padded("\x1b[31mred\x1b[0m line\nplain line\n")
    rules = CompiledRules(rules=[_rule(transforms={"strip_ansi": True})])
    out, stats = compact_tool_output(raw, "any_tool", rules=rules)
    assert "\x1b" not in out
    assert "red line" in out
    assert "test.rule" in stats.rules_applied


def test_dedupe_adjacent():
    raw = _padded("alpha\nalpha\nbeta\nbeta\nbeta\ngamma\n")
    rules = CompiledRules(rules=[_rule(transforms={"dedupe_adjacent": True})])
    out, _ = compact_tool_output(raw, "any_tool", rules=rules)
    # Each unique line should appear once in the dedup'd section
    assert out.split("\n").count("alpha") == 1
    assert out.split("\n").count("beta") == 1


def test_json_pretty_print():
    # Pretty-print only fires when the whole body is valid JSON; pad inside
    # a string field so the document still parses.
    raw = json.dumps({"a": 1, "b": [1, 2, 3], "c": "x" * (TINY_OUTPUT_MAX_CHARS + 1)})
    rules = CompiledRules(rules=[_rule(transforms={"pretty_print_json": True})])
    out, _ = compact_tool_output(raw, "any_tool", rules=rules)
    assert out.startswith("{\n  ")


def test_head_tail_summarize_inserts_marker():
    lines = [f"line {i}" for i in range(100)]
    raw = "\n".join(lines)
    assert len(raw) > TINY_OUTPUT_MAX_CHARS
    rules = CompiledRules(rules=[_rule(summarize={"head": 5, "tail": 3})])
    out, _ = compact_tool_output(raw, "any_tool", rules=rules)
    out_lines = out.split("\n")
    assert out_lines[:5] == [f"line {i}" for i in range(5)]
    assert out_lines[-3:] == [f"line {i}" for i in range(97, 100)]
    marker = [ln for ln in out_lines if "lines elided" in ln]
    assert marker, "expected elision marker"
    assert "92" in marker[0]  # 100 - 5 - 3 = 92


def test_rule_with_non_matching_tool_name_is_skipped():
    raw = _padded("\x1b[31mred\x1b[0m")
    rules = CompiledRules(rules=[
        _rule(match={"tool_names": ["other_tool"]},
              transforms={"strip_ansi": True})
    ])
    out, stats = compact_tool_output(raw, "wrong_tool", rules=rules)
    assert "\x1b" in out  # unchanged because tool_name didn't match
    assert stats.rules_applied == []


def test_user_rule_overrides_builtin_by_id(tmp_path):
    """Later layers override earlier layers by rule id."""
    user_dir = tmp_path / "norm"
    user_dir.mkdir()
    (user_dir / "override.json").write_text(json.dumps({
        "rules": [{
            "id": "generic.ansi",  # same id as a builtin rule
            "match": {"tool_names": ["impossible_tool_name_xyz"]},
            "transforms": {},
        }]
    }))
    rules = load_rules(user_dir=user_dir)
    matching = [r for r in rules.rules if r.id == "generic.ansi"]
    assert len(matching) == 1
    # The override restricts to a fake tool name, so it should NOT match
    # the default test tool — proving the user version replaced the builtin.
    assert matching[0].match.tool_names == ["impossible_tool_name_xyz"]


def test_filters_skip_patterns():
    raw = _padded("KEEP this line\nDROP me please\nKEEP another\n")
    rules = CompiledRules(rules=[
        _rule(filters={"skip_patterns": ["^DROP"]})
    ])
    out, _ = compact_tool_output(raw, "any_tool", rules=rules)
    assert "DROP me please" not in out
    assert "KEEP this line" in out


def test_builtin_rules_load_successfully():
    """Smoke test: shipped builtin.json parses without error."""
    from tools.normalize import default_rules
    rules = default_rules()
    assert rules.rules, "expected builtin rules to load"
    ids = {r.id for r in rules.rules}
    assert "generic.ansi" in ids
    assert "git.status" in ids
