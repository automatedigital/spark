from __future__ import annotations

from core.cli import SparkCLI


def _make_cli_stub() -> SparkCLI:
    cli = SparkCLI.__new__(SparkCLI)
    cli._show_welcome_logo = False
    cli._welcome_logo_ansi = None
    cli._welcome_logo_loaded = False
    cli.conversation_history = []
    return cli


def test_get_welcome_logo_ansi_runs_chafa_and_caches(monkeypatch, tmp_path):
    cli = _make_cli_stub()
    logo_path = tmp_path / "tui-logo.png"
    logo_path.write_bytes(b"png")
    cli._resolve_welcome_logo_path = lambda: logo_path
    cli._welcome_logo_size_arg = lambda: "40x"

    calls = []

    class _Result:
        returncode = 0
        stdout = "logo\n"

    def _fake_run(cmd, capture_output, text, check):
        calls.append((cmd, capture_output, text, check))
        return _Result()

    monkeypatch.setattr("subprocess.run", _fake_run)

    assert cli._get_welcome_logo_ansi() == "logo"
    assert cli._get_welcome_logo_ansi() == "logo"
    assert calls == [
        (
            [
                "chafa",
                "--bg=black",
                "--format=symbols",
                "--polite=on",
                "--size=40x",
                str(logo_path),
            ],
            True,
            True,
            False,
        )
    ]


def test_get_welcome_logo_ansi_strips_cursor_visibility_sequences(
    monkeypatch, tmp_path
):
    cli = _make_cli_stub()
    logo_path = tmp_path / "tui-logo.png"
    logo_path.write_bytes(b"png")
    cli._resolve_welcome_logo_path = lambda: logo_path
    cli._welcome_logo_size_arg = lambda: "40x"

    class _Result:
        returncode = 0
        stdout = "\x1b[?25lLOGO\n\x1b[?25h"

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: _Result())

    assert cli._get_welcome_logo_ansi() == "LOGO"


def test_extra_tui_widgets_hidden_when_logo_flag_disabled():
    cli = _make_cli_stub()
    cli._get_welcome_logo_ansi = lambda: "logo"

    assert cli._get_extra_tui_widgets() == []


def test_extra_tui_widgets_hidden_after_conversation_started():
    cli = _make_cli_stub()
    cli._show_welcome_logo = True
    cli.conversation_history = [{"role": "user", "content": "hello"}]
    cli._get_welcome_logo_ansi = lambda: "logo"

    assert cli._get_extra_tui_widgets() == []


def test_should_show_welcome_splash_false_when_history_exists():
    cli = _make_cli_stub()
    cli._show_welcome_logo = True
    cli.conversation_history = [{"role": "assistant", "content": "hi"}]

    assert cli._should_show_welcome_splash() is False


def test_dismiss_welcome_logo_hides_logo_flag():
    cli = _make_cli_stub()
    cli._show_welcome_logo = True

    cli._dismiss_welcome_logo()

    assert cli._show_welcome_logo is False
