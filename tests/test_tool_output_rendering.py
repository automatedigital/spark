"""Tool-output status glyphs + collapsed line-count affordance (TUI)."""

from __future__ import annotations

from core.cli.callbacks_mixin import (
    _count_output_lines,
    _format_completed_tool_line,
    _tool_status_glyph,
)


def test_status_glyphs():
    assert _tool_status_glyph(False) == "✓"
    assert _tool_status_glyph(True) == "✗"


def test_count_output_lines_ignores_blank():
    assert _count_output_lines(None) == 0
    assert _count_output_lines("") == 0
    assert _count_output_lines("a\n\n  \nb") == 2


def test_completed_line_ok_no_collapse_for_short_output():
    line = _format_completed_tool_line("ran ls", is_error=False, result_lines=3)
    assert line.startswith("✓ ran ls")
    assert "▸" not in line  # under threshold → no collapse hint


def test_completed_line_collapses_long_output():
    line = _format_completed_tool_line("read file", is_error=False, result_lines=42)
    assert line.startswith("✓ read file")
    assert "▸ 42 lines" in line


def test_completed_line_error_glyph():
    line = _format_completed_tool_line("run cmd", is_error=True, result_lines=0)
    assert line.startswith("✗ run cmd")
