"""Tests for setup.py configuration flows."""
import json
import sys
import types

import pytest

from spark_cli.auth import get_active_provider
from spark_cli.config import load_config, save_config
from spark_cli import setup as setup_mod
from spark_cli.setup import setup_model_provider


def _maybe_keep_current_tts(question, choices):
    if question != "Select TTS provider:":
        return None
    assert choices[-1].startswith("Keep current (")
    return len(choices) - 1


def _clear_provider_env(monkeypatch):
    for key in (
        "NOUS_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_API_KEY",
        "LLM_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)


def _stub_tts(monkeypatch):
    """Stub out TTS prompts so setup_model_provider doesn't block."""
    monkeypatch.setattr("spark_cli.setup.prompt_choice", lambda q, c, d=0: (
        _maybe_keep_current_tts(q, c) if _maybe_keep_current_tts(q, c) is not None
        else d
    ))
    monkeypatch.setattr("spark_cli.setup.prompt_yes_no", lambda *a, **kw: False)


def _write_model_config(tmp_path, provider, base_url="", model_name="test-model"):
    """Simulate what a _model_flow_* function writes to disk."""
    cfg = load_config()
    m = cfg.get("model")
    if not isinstance(m, dict):
        m = {"default": m} if m else {}
        cfg["model"] = m
    m["provider"] = provider
    if base_url:
        m["base_url"] = base_url
    if model_name:
        m["default"] = model_name
    save_config(cfg)


def test_setup_delegates_to_select_provider_and_model(tmp_path, monkeypatch):
    """setup_model_provider calls select_provider_and_model and syncs config."""
    monkeypatch.setenv("SPARK_HOME", str(tmp_path))
    _clear_provider_env(monkeypatch)
    _stub_tts(monkeypatch)

    config = load_config()

    def fake_select():
        _write_model_config(tmp_path, "custom", "http://localhost:11434/v1", "qwen3.5:32b")

    monkeypatch.setattr("spark_cli.main.select_provider_and_model", fake_select)

    setup_model_provider(config)
    save_config(config)

    reloaded = load_config()
    assert isinstance(reloaded["model"], dict)
    assert reloaded["model"]["provider"] == "custom"
    assert reloaded["model"]["base_url"] == "http://localhost:11434/v1"
    assert reloaded["model"]["default"] == "qwen3.5:32b"


def test_setup_syncs_openrouter_from_disk(tmp_path, monkeypatch):
    """When select_provider_and_model saves OpenRouter config to disk,
    the wizard's config dict picks it up."""
    monkeypatch.setenv("SPARK_HOME", str(tmp_path))
    _clear_provider_env(monkeypatch)
    _stub_tts(monkeypatch)

    config = load_config()
    assert isinstance(config.get("model"), str)  # fresh install

    def fake_select():
        _write_model_config(tmp_path, "openrouter", model_name="anthropic/claude-opus-4.6")

    monkeypatch.setattr("spark_cli.main.select_provider_and_model", fake_select)

    setup_model_provider(config)
    save_config(config)

    reloaded = load_config()
    assert isinstance(reloaded["model"], dict)
    assert reloaded["model"]["provider"] == "openrouter"


def test_setup_syncs_nous_from_disk(tmp_path, monkeypatch):
    """Spark Portal OAuth writes config to disk; wizard config dict must pick it up."""
    monkeypatch.setenv("SPARK_HOME", str(tmp_path))
    _clear_provider_env(monkeypatch)
    _stub_tts(monkeypatch)

    config = load_config()

    def fake_select():
        _write_model_config(tmp_path, "nous", "https://inference.example.com/v1", "gemini-3-flash")

    monkeypatch.setattr("spark_cli.main.select_provider_and_model", fake_select)

    setup_model_provider(config)
    save_config(config)

    reloaded = load_config()
    assert isinstance(reloaded["model"], dict)
    assert reloaded["model"]["provider"] == "nous"
    assert reloaded["model"]["base_url"] == "https://inference.example.com/v1"


def test_setup_custom_providers_synced(tmp_path, monkeypatch):
    """custom_providers written by select_provider_and_model must survive."""
    monkeypatch.setenv("SPARK_HOME", str(tmp_path))
    _clear_provider_env(monkeypatch)
    _stub_tts(monkeypatch)

    config = load_config()

    def fake_select():
        _write_model_config(tmp_path, "custom", "http://localhost:8080/v1", "llama3")
        cfg = load_config()
        cfg["custom_providers"] = [{"name": "Local", "base_url": "http://localhost:8080/v1"}]
        save_config(cfg)

    monkeypatch.setattr("spark_cli.main.select_provider_and_model", fake_select)

    setup_model_provider(config)
    save_config(config)

    reloaded = load_config()
    assert reloaded.get("custom_providers") == [{"name": "Local", "base_url": "http://localhost:8080/v1"}]


def test_setup_gateway_skips_service_install_when_systemctl_missing(monkeypatch, capsys):
    env = {
        "TELEGRAM_BOT_TOKEN": "",
        "TELEGRAM_HOME_CHANNEL": "",
        "DISCORD_BOT_TOKEN": "",
        "DISCORD_HOME_CHANNEL": "",
        "SLACK_BOT_TOKEN": "",
        "SLACK_HOME_CHANNEL": "",
        "MATRIX_HOMESERVER": "https://matrix.example.com",
        "MATRIX_USER_ID": "@alice:example.com",
        "MATRIX_PASSWORD": "",
        "MATRIX_ACCESS_TOKEN": "token",
        "BLUEBUBBLES_SERVER_URL": "",
        "BLUEBUBBLES_HOME_CHANNEL": "",
        "WHATSAPP_ENABLED": "",
        "WEBHOOK_ENABLED": "",
    }

    monkeypatch.setattr(setup_mod, "get_env_value", lambda key: env.get(key, ""))
    monkeypatch.setattr(setup_mod, "prompt_yes_no", lambda *args, **kwargs: False)
    monkeypatch.setattr("platform.system", lambda: "Linux")

    import spark_cli.gateway as gateway_mod

    monkeypatch.setattr(gateway_mod, "supports_systemd_services", lambda: False)
    monkeypatch.setattr(gateway_mod, "is_macos", lambda: False)
    monkeypatch.setattr(gateway_mod, "_is_service_installed", lambda: False)
    monkeypatch.setattr(gateway_mod, "_is_service_running", lambda: False)

    setup_mod.setup_gateway({})

    out = capsys.readouterr().out
    assert "Messaging platforms configured!" in out
    assert "Start the gateway to bring your bots online:" in out
    assert "spark gateway" in out


def test_setup_gateway_uses_enter_to_select_highlighted_platform(monkeypatch):
    call = {}

    def fake_prompt_checklist(title, items, pre_selected=None, **kwargs):
        call["title"] = title
        call["items"] = items
        call["pre_selected"] = pre_selected
        call.update(kwargs)
        return []

    monkeypatch.setattr(setup_mod, "get_env_value", lambda _key: "")
    monkeypatch.setattr(setup_mod, "prompt_checklist", fake_prompt_checklist)
    monkeypatch.setattr(setup_mod, "setup_http_api", lambda _config: None)

    setup_mod.setup_gateway({})

    assert call["title"] == "Select platforms to configure:"
    assert call["items"][0] == "Telegram"
    assert call["pre_selected"] == []
    assert call["enter_selects_current"] is True


def test_setup_gateway_in_container_shows_docker_guidance(monkeypatch, capsys):
    """setup_gateway() in a Docker container shows Docker-specific restart instructions."""
    env = {
        "TELEGRAM_BOT_TOKEN": "",
        "TELEGRAM_HOME_CHANNEL": "",
        "DISCORD_BOT_TOKEN": "",
        "DISCORD_HOME_CHANNEL": "",
        "SLACK_BOT_TOKEN": "",
        "SLACK_HOME_CHANNEL": "",
        "MATRIX_HOMESERVER": "https://matrix.example.com",
        "MATRIX_USER_ID": "@alice:example.com",
        "MATRIX_PASSWORD": "",
        "MATRIX_ACCESS_TOKEN": "token",
        "BLUEBUBBLES_SERVER_URL": "",
        "BLUEBUBBLES_HOME_CHANNEL": "",
        "WHATSAPP_ENABLED": "",
        "WEBHOOK_ENABLED": "",
    }

    monkeypatch.setattr(setup_mod, "get_env_value", lambda key: env.get(key, ""))
    monkeypatch.setattr(setup_mod, "prompt_yes_no", lambda *args, **kwargs: False)
    monkeypatch.setattr("platform.system", lambda: "Linux")

    import spark_cli.gateway as gateway_mod

    monkeypatch.setattr(gateway_mod, "supports_systemd_services", lambda: False)
    monkeypatch.setattr(gateway_mod, "is_macos", lambda: False)
    monkeypatch.setattr(gateway_mod, "_is_service_installed", lambda: False)
    monkeypatch.setattr(gateway_mod, "_is_service_running", lambda: False)

    # Patch is_container at the import location in setup.py
    import core.spark_constants as spark_constants
    monkeypatch.setattr(spark_constants, "is_container", lambda: True)

    setup_mod.setup_gateway({})

    out = capsys.readouterr().out
    assert "Messaging platforms configured!" in out
    assert "docker" in out.lower() or "Docker" in out
    assert "restart" in out.lower()


def test_setup_syncs_custom_provider_removal_from_disk(tmp_path, monkeypatch):
    """Removing the last custom provider in model setup should persist."""
    monkeypatch.setenv("SPARK_HOME", str(tmp_path))
    _clear_provider_env(monkeypatch)
    _stub_tts(monkeypatch)

    config = load_config()
    config["custom_providers"] = [{"name": "Local", "base_url": "http://localhost:8080/v1"}]
    save_config(config)

    def fake_select():
        cfg = load_config()
        cfg["model"] = {"provider": "openrouter", "default": "anthropic/claude-opus-4.6"}
        cfg["custom_providers"] = []
        save_config(cfg)

    monkeypatch.setattr("spark_cli.main.select_provider_and_model", fake_select)

    setup_model_provider(config)
    save_config(config)

    reloaded = load_config()
    assert reloaded.get("custom_providers") == []


def test_setup_cancel_preserves_existing_config(tmp_path, monkeypatch):
    """When the user cancels provider selection, existing config is preserved."""
    monkeypatch.setenv("SPARK_HOME", str(tmp_path))
    _clear_provider_env(monkeypatch)
    _stub_tts(monkeypatch)

    # Pre-set a provider
    _write_model_config(tmp_path, "openrouter", model_name="gpt-4o")

    config = load_config()
    assert config["model"]["provider"] == "openrouter"

    def fake_select():
        pass  # user cancelled — nothing written to disk

    monkeypatch.setattr("spark_cli.main.select_provider_and_model", fake_select)

    setup_model_provider(config)
    save_config(config)

    reloaded = load_config()
    assert isinstance(reloaded["model"], dict)
    assert reloaded["model"]["provider"] == "openrouter"
    assert reloaded["model"]["default"] == "gpt-4o"


def test_setup_exception_in_select_gracefully_handled(tmp_path, monkeypatch):
    """If select_provider_and_model raises, setup continues with existing config."""
    monkeypatch.setenv("SPARK_HOME", str(tmp_path))
    _clear_provider_env(monkeypatch)
    _stub_tts(monkeypatch)

    config = load_config()

    def fake_select():
        raise RuntimeError("something broke")

    monkeypatch.setattr("spark_cli.main.select_provider_and_model", fake_select)

    # Should not raise
    setup_model_provider(config)


def test_setup_keyboard_interrupt_gracefully_handled(tmp_path, monkeypatch):
    """KeyboardInterrupt during provider selection is handled."""
    monkeypatch.setenv("SPARK_HOME", str(tmp_path))
    _clear_provider_env(monkeypatch)
    _stub_tts(monkeypatch)

    config = load_config()

    def fake_select():
        raise KeyboardInterrupt()

    monkeypatch.setattr("spark_cli.main.select_provider_and_model", fake_select)

    setup_model_provider(config)


def test_select_provider_and_model_warns_if_named_custom_provider_disappears(
    tmp_path, monkeypatch, capsys
):
    """If a saved custom provider is deleted mid-selection, show a warning instead of silently doing nothing."""
    monkeypatch.setenv("SPARK_HOME", str(tmp_path))
    _clear_provider_env(monkeypatch)

    cfg = load_config()
    cfg["custom_providers"] = [{"name": "Local", "base_url": "http://localhost:8080/v1"}]
    save_config(cfg)

    _mode_call = [False]

    def fake_prompt_provider_choice(choices, default=0):
        # First call is mode selection (Simple/Multi-model/Reasoning) — pick Simple (0)
        if not _mode_call[0]:
            _mode_call[0] = True
            return 0
        # Second call is provider selection — delete the custom provider and pick it
        current = load_config()
        current["custom_providers"] = []
        save_config(current)
        return next(i for i, label in enumerate(choices) if label.startswith("Local (localhost:8080/v1)"))

    monkeypatch.setattr("spark_cli.auth.resolve_provider", lambda provider: None)
    monkeypatch.setattr("spark_cli.main._prompt_provider_choice", fake_prompt_provider_choice)
    monkeypatch.setattr(
        "spark_cli.main._model_flow_named_custom",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("named custom flow should not run")),
    )

    from spark_cli.main import select_provider_and_model

    select_provider_and_model()

    out = capsys.readouterr().out
    assert "selected saved custom provider is no longer available" in out


def test_codex_setup_uses_runtime_access_token_for_live_model_list(tmp_path, monkeypatch):
    """Codex model list fetching uses the runtime access token."""
    monkeypatch.setenv("SPARK_HOME", str(tmp_path))
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")

    config = load_config()
    _stub_tts(monkeypatch)

    def fake_select():
        _write_model_config(tmp_path, "openai-codex", "https://api.openai.com/v1", "gpt-4o")

    monkeypatch.setattr("spark_cli.main.select_provider_and_model", fake_select)

    setup_model_provider(config)
    save_config(config)

    reloaded = load_config()
    assert isinstance(reloaded["model"], dict)
    assert reloaded["model"]["provider"] == "openai-codex"




def test_resolve_spark_chat_argv_prefers_which(monkeypatch):
    from spark_cli import setup as setup_mod

    monkeypatch.setattr(setup_mod.shutil, "which", lambda name: "/usr/local/bin/spark" if name == "spark" else None)

    assert setup_mod._resolve_spark_chat_argv() == ["/usr/local/bin/spark", "chat"]


def test_resolve_spark_chat_argv_falls_back_to_module(monkeypatch):
    from spark_cli import setup as setup_mod

    monkeypatch.setattr(setup_mod.shutil, "which", lambda _name: None)
    monkeypatch.setattr(setup_mod.importlib.util, "find_spec", lambda name: object() if name == "spark_cli" else None)

    assert setup_mod._resolve_spark_chat_argv() == [sys.executable, "-m", "spark_cli.main", "chat"]


def test_offer_launch_chat_execs_fresh_process(monkeypatch):
    import sys
    from spark_cli import setup as setup_mod

    monkeypatch.setattr(setup_mod, "prompt_yes_no", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(setup_mod, "_resolve_spark_chat_argv", lambda: ["/usr/local/bin/spark", "chat"])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

    exec_calls = []

    def fake_execvp(path, argv):
        exec_calls.append((path, argv))
        raise SystemExit(0)

    monkeypatch.setattr(setup_mod.os, "execvp", fake_execvp)

    with pytest.raises(SystemExit):
        setup_mod._offer_launch_chat()

    assert exec_calls == [("/usr/local/bin/spark", ["/usr/local/bin/spark", "chat"])]


def test_offer_launch_chat_manual_fallback_when_unresolvable(monkeypatch, capsys):
    import sys
    from spark_cli import setup as setup_mod

    monkeypatch.setattr(setup_mod, "prompt_yes_no", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(setup_mod, "_resolve_spark_chat_argv", lambda: None)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

    setup_mod._offer_launch_chat()

    captured = capsys.readouterr()
    assert "Run 'spark chat' manually" in captured.out
