"""Tests for universal model config sync in the gateway."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.session import SessionEntry, SessionSource, build_session_key


def _make_source() -> SessionSource:
    return SessionSource(
        platform=Platform.TELEGRAM,
        user_id="u1",
        chat_id="c1",
        user_name="tester",
        chat_type="dm",
    )


def _make_event(text: str):
    from gateway.platforms.base import MessageEvent

    return MessageEvent(text=text, source=_make_source(), message_id="m1")


def _make_runner():
    """Create a minimal GatewayRunner with stubbed internals."""
    from gateway.run import GatewayRunner

    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(
        platforms={Platform.TELEGRAM: PlatformConfig(enabled=True, token="tok")}
    )
    adapter = MagicMock()
    adapter.send = AsyncMock()
    runner.adapters = {Platform.TELEGRAM: adapter}
    runner._voice_mode = {}
    runner.hooks = SimpleNamespace(emit=AsyncMock(), loaded_hooks=False)
    runner._session_model_overrides = {}
    runner._pending_model_notes = {}
    runner._background_tasks = set()
    runner._running_agents = {}
    runner._pending_messages = {}
    runner._pending_approvals = {}
    runner._session_db = None
    runner._agent_cache = {}
    runner._agent_cache_lock = None
    runner._effective_model = None
    runner._effective_provider = None
    runner._last_config_fingerprint = None
    runner.session_store = MagicMock()
    session_key = build_session_key(_make_source())
    session_entry = SessionEntry(
        session_key=session_key,
        session_id="sess-1",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        platform=Platform.TELEGRAM,
        chat_type="dm",
    )
    runner.session_store.get_or_create_session.return_value = session_entry
    runner.session_store._generate_session_key.return_value = session_key
    runner.session_store._entries = {session_key: session_entry}
    return runner


def test_session_model_override_is_ignored():
    """Stale per-session overrides must not beat universal config/runtime."""
    runner = _make_runner()
    sk = build_session_key(_make_source())
    runtime = {
        "provider": "anthropic",
        "api_key": "ant-key",
        "base_url": "https://api.anthropic.com",
        "api_mode": "anthropic_messages",
    }
    runner._session_model_overrides[sk] = {
        "model": "stale-session-model",
        "provider": "openrouter",
        "api_key": "or-key",
        "base_url": "https://openrouter.ai/api/v1",
        "api_mode": "chat_completions",
    }

    model, resolved = runner._apply_session_model_override(
        sk,
        "claude-current",
        dict(runtime),
    )

    assert model == "claude-current"
    assert resolved == runtime
    assert runner._is_intentional_model_switch(sk, "stale-session-model") is False


def test_live_config_refresh_clears_stale_session_model_overrides():
    """A `spark model` config change must beat old Telegram /model overrides."""
    runner = _make_runner()
    sk = build_session_key(_make_source())

    runner._last_config_fingerprint = runner._gateway_config_fingerprint(
        {"model": {"default": "old-model", "provider": "openrouter"}}
    )
    runner._session_model_overrides[sk] = {
        "model": "stale-session-model",
        "provider": "openrouter",
        "api_key": "key",
        "base_url": "https://openrouter.ai/api/v1",
        "api_mode": "chat_completions",
    }
    runner._pending_model_notes[sk] = "stale note"
    runner._agent_cache[sk] = (object(), "old-signature")

    runner._refresh_live_config_state(
        {"model": {"default": "new-universal-model", "provider": "anthropic"}}
    )

    assert runner._session_model_overrides == {}
    assert runner._pending_model_notes == {}
    assert runner._agent_cache == {}


def test_gateway_runtime_resolution_defers_to_config_provider(monkeypatch):
    """Gateway should not pass stale SPARK_INFERENCE_PROVIDER into resolution."""
    from gateway.run import _resolve_runtime_agent_kwargs

    captured = {}

    def fake_resolve_runtime_provider(*, requested=None):
        captured["requested"] = requested
        return {
            "api_key": "key",
            "base_url": "https://example.test/v1",
            "provider": "anthropic",
            "api_mode": "anthropic_messages",
        }

    monkeypatch.setenv("SPARK_INFERENCE_PROVIDER", "openrouter")
    monkeypatch.setattr(
        "spark_cli.runtime_provider.resolve_runtime_provider",
        fake_resolve_runtime_provider,
    )

    runtime = _resolve_runtime_agent_kwargs()

    assert captured["requested"] is None
    assert runtime["provider"] == "anthropic"


@pytest.mark.asyncio
async def test_model_command_persists_globally_and_clears_cache(monkeypatch):
    """Telegram /model should save config.yaml, not a session override."""
    from spark_cli.model_switch import ModelSwitchResult

    runner = _make_runner()
    sk = build_session_key(_make_source())
    runner._agent_cache[sk] = (object(), "old")

    monkeypatch.setattr(
        "gateway.run._load_gateway_config",
        lambda: {"model": {"default": "old", "provider": "openrouter"}},
    )
    monkeypatch.setattr(
        "spark_cli.model_switch.switch_model",
        lambda **_kw: ModelSwitchResult(
            success=True,
            new_model="new-global",
            target_provider="anthropic",
            api_key="key",
            base_url="https://api.anthropic.com",
            api_mode="anthropic_messages",
            provider_label="Anthropic",
        ),
    )
    saved = {}

    def fake_write(result):
        saved["model"] = result.new_model
        return {
            "model": {
                "default": result.new_model,
                "provider": result.target_provider,
            }
        }

    monkeypatch.setattr("spark_cli.model_config.write_model_switch_result", fake_write)

    response = await runner._handle_model_command(_make_event("/model sonnet"))

    assert "Saved to config.yaml" in response
    assert saved["model"] == "new-global"
    assert runner._session_model_overrides == {}
    assert runner._agent_cache == {}
