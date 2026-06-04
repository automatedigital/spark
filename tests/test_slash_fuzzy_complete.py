"""Slash-command autocomplete: fuzzy (subsequence) matching with descriptions,
prefix matches ranked first."""

from __future__ import annotations

from prompt_toolkit.document import Document

from spark_cli.commands import SlashCommandCompleter


def _completions(text: str):
    c = SlashCommandCompleter()
    doc = Document(text, len(text))
    return list(c.get_completions(doc, None))


def _displays(text: str) -> list[str]:
    out = []
    for comp in _completions(text):
        d = comp.display
        out.append(d if isinstance(d, str) else d[0][1])
    return out


def test_subseq_helper():
    m = SlashCommandCompleter._subseq_match
    assert m("hlp", "help")
    assert m("hsty", "history")
    assert not m("xyz", "help")
    assert m("", "help")  # empty needle trivially matches


def test_prefix_match_still_works_with_description():
    comps = _completions("/he")
    assert any((c.display if isinstance(c.display, str) else c.display[0][1]) == "/help" for c in comps)
    # descriptions are present in the dropdown
    help_comp = next(c for c in comps if (c.display if isinstance(c.display, str) else c.display[0][1]) == "/help")
    assert help_comp.display_meta_text


def test_fuzzy_nonprefix_resolves():
    assert "/help" in _displays("/hlp")
    assert "/history" in _displays("/hsty")
    assert "/clear" in _displays("/clr")


def test_prefix_ranked_before_fuzzy():
    # "/c" — every command containing c-subsequence could match, but the ones
    # starting with "c" must come first.
    disp = _displays("/c")
    first_prefixed = [d for d in disp if d[1:].lower().startswith("c")]
    # all prefix hits appear before the first non-prefix hit
    if first_prefixed:
        first_non_prefix = next((i for i, d in enumerate(disp) if not d[1:].lower().startswith("c")), len(disp))
        last_prefix = max(i for i, d in enumerate(disp) if d[1:].lower().startswith("c"))
        assert last_prefix < first_non_prefix or first_non_prefix == len(disp)
