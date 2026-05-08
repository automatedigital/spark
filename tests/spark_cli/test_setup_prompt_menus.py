from spark_cli import setup as setup_mod


def test_prompt_choice_uses_curses_helper(monkeypatch):
    monkeypatch.setattr(setup_mod, "_curses_prompt_choice", lambda question, choices, default=0: 1)

    idx = setup_mod.prompt_choice("Pick one", ["a", "b", "c"], default=0)

    assert idx == 1


def test_prompt_choice_falls_back_to_numbered_input(monkeypatch):
    monkeypatch.setattr(setup_mod, "_curses_prompt_choice", lambda question, choices, default=0: -1)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "2")

    idx = setup_mod.prompt_choice("Pick one", ["a", "b", "c"], default=0)

    assert idx == 1


def test_prompt_checklist_uses_shared_curses_checklist(monkeypatch):
    monkeypatch.setattr(
        "spark_cli.curses_ui.curses_checklist",
        lambda title, items, selected, cancel_returns=None, **kwargs: {0, 2},
    )

    selected = setup_mod.prompt_checklist("Pick tools", ["one", "two", "three"], pre_selected=[1])

    assert selected == [0, 2]


def test_prompt_checklist_can_enable_enter_selects_current(monkeypatch):
    call = {}

    def fake_checklist(title, items, selected, cancel_returns=None, **kwargs):
        call.update(kwargs)
        return {0}

    monkeypatch.setattr("spark_cli.curses_ui.curses_checklist", fake_checklist)

    selected = setup_mod.prompt_checklist(
        "Pick platforms",
        ["Telegram", "Discord"],
        enter_selects_current=True,
    )

    assert selected == [0]
    assert call["enter_selects_current"] is True


def test_checklist_enter_selects_current_from_empty_selection():
    from spark_cli.curses_ui import _resolve_checklist_enter

    assert _resolve_checklist_enter(set(), 0, enter_selects_current=True) == {0}


def test_checklist_enter_adds_current_to_existing_selection():
    from spark_cli.curses_ui import _resolve_checklist_enter

    assert _resolve_checklist_enter({1}, 0, enter_selects_current=True) == {0, 1}


def test_checklist_enter_keeps_existing_selected_current():
    from spark_cli.curses_ui import _resolve_checklist_enter

    assert _resolve_checklist_enter({0, 2}, 0, enter_selects_current=True) == {0, 2}


def test_checklist_enter_default_confirms_without_selecting_current():
    from spark_cli.curses_ui import _resolve_checklist_enter

    assert _resolve_checklist_enter(set(), 0) == set()
