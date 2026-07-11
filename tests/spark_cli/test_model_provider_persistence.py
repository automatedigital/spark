"""Tests that provider selection via `spark model` always persists correctly.

Regression tests for the bug where _save_model_choice could save config.model
as a plain string, causing subsequent provider writes (which check
isinstance(model, dict)) to silently fail — leaving the provider unset and
falling back to auto-detection.
"""

from unittest.mock import patch

import pytest


@pytest.fixture
def config_home(tmp_path, monkeypatch):
    """Isolated SPARK_HOME with a minimal string-format config."""
    home = tmp_path / "spark"
    home.mkdir()
    config_yaml = home / "config.yaml"
    # Start with model as a plain string — the format that triggered the bug
    config_yaml.write_text("model: some-old-model\n")
    env_file = home / ".env"
    env_file.write_text("")
    monkeypatch.setenv("SPARK_HOME", str(home))
    # Clear env vars that could interfere
    monkeypatch.delenv("SPARK_MODEL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("SPARK_INFERENCE_PROVIDER", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    return home


class TestSaveModelChoiceAlwaysDict:
    def test_string_model_becomes_dict(self, config_home):
        """When config.model is a plain string, _save_model_choice must
        convert it to a dict so provider can be set afterwards."""
        from spark_cli.auth import _save_model_choice

        _save_model_choice("kimi-k2.5")

        import yaml
        config = yaml.safe_load((config_home / "config.yaml").read_text()) or {}
        model = config.get("model")
        assert isinstance(model, dict), (
            f"Expected model to be a dict after save, got {type(model)}: {model}"
        )
        assert model["default"] == "kimi-k2.5"

    def test_dict_model_stays_dict(self, config_home):
        """When config.model is already a dict, _save_model_choice preserves it."""
        import yaml
        (config_home / "config.yaml").write_text(
            "model:\n  default: old-model\n  provider: openrouter\n"
        )
        from spark_cli.auth import _save_model_choice

        _save_model_choice("new-model")

        config = yaml.safe_load((config_home / "config.yaml").read_text()) or {}
        model = config.get("model")
        assert isinstance(model, dict)
        assert model["default"] == "new-model"
        assert model["provider"] == "openrouter"  # preserved

    def test_spark_model_reasoning_sets_agent_effort(self, config_home, capsys):
        """`spark model reasoning <level>` should persist agent.reasoning_effort."""
        import yaml

        from spark_cli.main import cmd_model_reasoning

        assert cmd_model_reasoning("high") is None

        config = yaml.safe_load((config_home / "config.yaml").read_text())
        assert config["agent"]["reasoning_effort"] == "high"
        assert "Reasoning effort set to: high" in capsys.readouterr().out

    def test_spark_model_reasoning_accepts_friendly_phase_names(self, config_home):
        import yaml

        from spark_cli.main import cmd_model_reasoning

        cmd_model_reasoning("light")
        config = yaml.safe_load((config_home / "config.yaml").read_text())
        assert config["agent"]["reasoning_effort"] == "low"

        cmd_model_reasoning("hard")
        config = yaml.safe_load((config_home / "config.yaml").read_text())
        assert config["agent"]["reasoning_effort"] == "high"

    def test_spark_model_reasoning_rejects_invalid_effort(self, config_home, capsys):
        import yaml

        from spark_cli.main import cmd_model_reasoning

        cmd_model_reasoning("banana")

        config = yaml.safe_load((config_home / "config.yaml").read_text())
        assert "agent" not in config
        assert "Invalid reasoning effort" in capsys.readouterr().out


class TestProviderPersistsAfterModelSave:
    def test_simple_ollama_selection_disables_routing_and_persists(self, config_home):
        """`spark model` Simple + Ollama should update the universal config."""
        import yaml
        from types import SimpleNamespace

        (config_home / "config.yaml").write_text(
            "model:\n"
            "  default: gpt-5.4-mini\n"
            "  provider: openai-codex\n"
            "smart_model_routing:\n"
            "  enabled: true\n"
            "  cheap_model:\n"
            "    provider: openai-codex\n"
            "    model: gpt-5.4-mini\n"
        )

        from spark_cli.main import select_provider_and_model

        with patch("spark_cli.main._prompt_provider_choice", side_effect=[0, 0]), \
             patch(
                 "spark_cli.models.CANONICAL_PROVIDERS",
                 [SimpleNamespace(slug="ollama", tui_desc="Ollama")],
             ), \
             patch("spark_cli.models.probe_api_models", return_value={"models": ["qwen3:6.7b"]}), \
             patch("spark_cli.main._save_custom_provider"), \
             patch("spark_cli.auth.deactivate_provider"), \
             patch("builtins.input", side_effect=["", ""]):
            select_provider_and_model()

        config = yaml.safe_load((config_home / "config.yaml").read_text()) or {}
        assert config["smart_model_routing"]["enabled"] is False
        assert config["model"]["default"] == "qwen3:6.7b"
        assert config["model"]["provider"] == "ollama"
        assert config["model"]["base_url"] == "http://localhost:11434/v1"

    def test_api_key_provider_saved_when_model_was_string(self, config_home, monkeypatch):
        """_model_flow_api_key_provider must persist the provider even when
        config.model started as a plain string."""
        from spark_cli.auth import PROVIDER_REGISTRY

        pconfig = PROVIDER_REGISTRY.get("kimi-coding")
        if not pconfig:
            pytest.skip("kimi-coding not in PROVIDER_REGISTRY")

        # Simulate: user has a Kimi API key, model was a string
        monkeypatch.setenv("KIMI_API_KEY", "sk-kimi-test-key")

        from spark_cli.main import _model_flow_api_key_provider
        from spark_cli.config import load_config

        # Mock the model selection prompt to return "kimi-k2.5"
        # Also mock input() for the base URL prompt and builtins.input
        with patch("spark_cli.auth._prompt_model_selection", return_value="kimi-k2.5"), \
             patch("spark_cli.auth.deactivate_provider"), \
             patch("builtins.input", return_value=""):
            _model_flow_api_key_provider(load_config(), "kimi-coding", "old-model")

        import yaml
        config = yaml.safe_load((config_home / "config.yaml").read_text()) or {}
        model = config.get("model")
        assert isinstance(model, dict), f"model should be dict, got {type(model)}"
        assert model.get("provider") == "kimi-coding", (
            f"provider should be 'kimi-coding', got {model.get('provider')}"
        )
        assert model.get("default") == "kimi-k2.5"

    def test_copilot_provider_saved_when_selected(self, config_home):
        """_model_flow_copilot should persist provider/base_url/model together."""
        from spark_cli.main import _model_flow_copilot
        from spark_cli.config import load_config

        with patch(
            "spark_cli.auth.resolve_api_key_provider_credentials",
            return_value={
                "provider": "copilot",
                "api_key": "gh-cli-token",
                "base_url": "https://api.githubcopilot.com",
                "source": "gh auth token",
            },
        ), patch(
            "spark_cli.models.fetch_github_model_catalog",
            return_value=[
                {
                    "id": "gpt-4.1",
                    "capabilities": {"type": "chat", "supports": {}},
                    "supported_endpoints": ["/chat/completions"],
                },
                {
                    "id": "gpt-5.4",
                    "capabilities": {"type": "chat", "supports": {"reasoning_effort": ["low", "medium", "high"]}},
                    "supported_endpoints": ["/responses"],
                },
            ],
        ), patch(
            "spark_cli.auth._prompt_model_selection",
            return_value="gpt-5.4",
        ), patch(
            "spark_cli.main._prompt_reasoning_effort_selection",
            return_value="high",
        ), patch(
            "spark_cli.auth.deactivate_provider",
        ):
            _model_flow_copilot(load_config(), "old-model")

        import yaml

        config = yaml.safe_load((config_home / "config.yaml").read_text()) or {}
        model = config.get("model")
        assert isinstance(model, dict), f"model should be dict, got {type(model)}"
        assert model.get("provider") == "copilot"
        assert model.get("base_url") == "https://api.githubcopilot.com"
        assert model.get("default") == "gpt-5.4"
        assert model.get("api_mode") == "codex_responses"
        assert config["agent"]["reasoning_effort"] == "high"

    def test_copilot_acp_provider_saved_when_selected(self, config_home):
        """_model_flow_copilot_acp should persist provider/base_url/model together."""
        from spark_cli.main import _model_flow_copilot_acp
        from spark_cli.config import load_config

        with patch(
            "spark_cli.auth.get_external_process_provider_status",
            return_value={
                "resolved_command": "/usr/local/bin/copilot",
                "command": "copilot",
                "base_url": "acp://copilot",
            },
        ), patch(
            "spark_cli.auth.resolve_external_process_provider_credentials",
            return_value={
                "provider": "copilot-acp",
                "api_key": "copilot-acp",
                "base_url": "acp://copilot",
                "command": "/usr/local/bin/copilot",
                "args": ["--acp", "--stdio"],
                "source": "process",
            },
        ), patch(
            "spark_cli.auth.resolve_api_key_provider_credentials",
            return_value={
                "provider": "copilot",
                "api_key": "gh-cli-token",
                "base_url": "https://api.githubcopilot.com",
                "source": "gh auth token",
            },
        ), patch(
            "spark_cli.models.fetch_github_model_catalog",
            return_value=[
                {
                    "id": "gpt-4.1",
                    "capabilities": {"type": "chat", "supports": {}},
                    "supported_endpoints": ["/chat/completions"],
                },
                {
                    "id": "gpt-5.4",
                    "capabilities": {"type": "chat", "supports": {"reasoning_effort": ["low", "medium", "high"]}},
                    "supported_endpoints": ["/responses"],
                },
            ],
        ), patch(
            "spark_cli.auth._prompt_model_selection",
            return_value="gpt-5.4",
        ), patch(
            "spark_cli.auth.deactivate_provider",
        ):
            _model_flow_copilot_acp(load_config(), "old-model")

        import yaml

        config = yaml.safe_load((config_home / "config.yaml").read_text()) or {}
        model = config.get("model")
        assert isinstance(model, dict), f"model should be dict, got {type(model)}"
        assert model.get("provider") == "copilot-acp"
        assert model.get("base_url") == "acp://copilot"
        assert model.get("default") == "gpt-5.4"
        assert model.get("api_mode") == "chat_completions"

    def test_opencode_go_models_are_selectable_and_persist_normalized(self, config_home, monkeypatch):
        from spark_cli.main import _model_flow_api_key_provider
        from spark_cli.config import load_config

        monkeypatch.setenv("OPENCODE_GO_API_KEY", "test-key")

        with patch("spark_cli.models.fetch_api_models", return_value=["opencode-go/kimi-k2.5", "opencode-go/minimax-m2.7"]), \
             patch("spark_cli.auth._prompt_model_selection", return_value="kimi-k2.5"), \
             patch("spark_cli.auth.deactivate_provider"), \
             patch("builtins.input", return_value=""):
            _model_flow_api_key_provider(load_config(), "opencode-go", "opencode-go/kimi-k2.5")

        import yaml
        config = yaml.safe_load((config_home / "config.yaml").read_text()) or {}
        model = config.get("model")
        assert isinstance(model, dict)
        assert model.get("provider") == "opencode-go"
        assert model.get("default") == "kimi-k2.5"
        assert model.get("api_mode") == "chat_completions"

    def test_opencode_go_same_provider_switch_recomputes_api_mode(self, config_home, monkeypatch):
        from spark_cli.main import _model_flow_api_key_provider
        from spark_cli.config import load_config

        monkeypatch.setenv("OPENCODE_GO_API_KEY", "test-key")
        (config_home / "config.yaml").write_text(
            "model:\n"
            "  default: kimi-k2.5\n"
            "  provider: opencode-go\n"
            "  base_url: https://opencode.ai/zen/go/v1\n"
            "  api_mode: chat_completions\n"
        )

        with patch("spark_cli.models.fetch_api_models", return_value=["opencode-go/kimi-k2.5", "opencode-go/minimax-m2.5"]), \
             patch("spark_cli.auth._prompt_model_selection", return_value="minimax-m2.5"), \
             patch("spark_cli.auth.deactivate_provider"), \
             patch("builtins.input", return_value=""):
            _model_flow_api_key_provider(load_config(), "opencode-go", "kimi-k2.5")

        import yaml
        config = yaml.safe_load((config_home / "config.yaml").read_text()) or {}
        model = config.get("model")
        assert isinstance(model, dict)
        assert model.get("provider") == "opencode-go"
        assert model.get("default") == "minimax-m2.5"
        assert model.get("api_mode") == "anthropic_messages"


class TestBaseUrlValidation:
    """Reject non-URL values in the base URL prompt (e.g. shell commands)."""

    def test_invalid_base_url_rejected(self, config_home, monkeypatch, capsys):
        """Typing a non-URL string should not be saved as the base URL."""
        from spark_cli.auth import PROVIDER_REGISTRY

        pconfig = PROVIDER_REGISTRY.get("zai")
        if not pconfig:
            pytest.skip("zai not in PROVIDER_REGISTRY")

        monkeypatch.setenv("GLM_API_KEY", "test-key")

        from spark_cli.main import _model_flow_api_key_provider
        from spark_cli.config import load_config, get_env_value

        # User types a shell command instead of a URL at the base URL prompt
        with patch("spark_cli.auth._prompt_model_selection", return_value="glm-5"), \
             patch("spark_cli.auth.deactivate_provider"), \
             patch("builtins.input", return_value="nano ~/.spark/.env"):
            _model_flow_api_key_provider(load_config(), "zai", "old-model")

        # The garbage value should NOT have been saved
        saved = get_env_value("GLM_BASE_URL") or ""
        assert not saved or saved.startswith(("http://", "https://")), \
            f"Non-URL value was saved as GLM_BASE_URL: {saved}"
        captured = capsys.readouterr()
        assert "Invalid URL" in captured.out

    def test_valid_base_url_accepted(self, config_home, monkeypatch):
        """A proper URL should be saved normally."""
        from spark_cli.auth import PROVIDER_REGISTRY

        pconfig = PROVIDER_REGISTRY.get("zai")
        if not pconfig:
            pytest.skip("zai not in PROVIDER_REGISTRY")

        monkeypatch.setenv("GLM_API_KEY", "test-key")

        from spark_cli.main import _model_flow_api_key_provider
        from spark_cli.config import load_config, get_env_value

        with patch("spark_cli.auth._prompt_model_selection", return_value="glm-5"), \
             patch("spark_cli.auth.deactivate_provider"), \
             patch("builtins.input", return_value="https://custom.z.ai/api/paas/v4"):
            _model_flow_api_key_provider(load_config(), "zai", "old-model")

        saved = get_env_value("GLM_BASE_URL") or ""
        assert saved == "https://custom.z.ai/api/paas/v4"

    def test_empty_base_url_keeps_default(self, config_home, monkeypatch):
        """Pressing Enter (empty) should not change the base URL."""
        from spark_cli.auth import PROVIDER_REGISTRY

        pconfig = PROVIDER_REGISTRY.get("zai")
        if not pconfig:
            pytest.skip("zai not in PROVIDER_REGISTRY")

        monkeypatch.setenv("GLM_API_KEY", "test-key")
        monkeypatch.delenv("GLM_BASE_URL", raising=False)

        from spark_cli.main import _model_flow_api_key_provider
        from spark_cli.config import load_config, get_env_value

        with patch("spark_cli.auth._prompt_model_selection", return_value="glm-5"), \
             patch("spark_cli.auth.deactivate_provider"), \
             patch("builtins.input", return_value=""):
            _model_flow_api_key_provider(load_config(), "zai", "old-model")

        saved = get_env_value("GLM_BASE_URL") or ""
        assert saved == "", "Empty input should not save a base URL"
