"""Regression tests for the OpenAI Codex interactive model flow."""

from __future__ import annotations


def test_openai_codex_model_flow_uses_local_catalog_for_picker(monkeypatch):
    """The picker should not block on live Codex model discovery."""
    from spark_cli import main

    monkeypatch.setattr(
        "spark_cli.auth.get_codex_auth_status",
        lambda: {"logged_in": True, "api_key": "codex-token"},
    )

    def fake_get_codex_model_ids(*, access_token=None):
        assert access_token is None
        return ["gpt-5.4-mini", "gpt-5.4"]

    monkeypatch.setattr(
        "spark_cli.codex_models.get_codex_model_ids",
        fake_get_codex_model_ids,
    )
    monkeypatch.setattr(
        "spark_cli.auth._prompt_model_selection",
        lambda model_ids, current_model="": None,
    )

    main._model_flow_openai_codex({"model": {}}, current_model="gpt-5.4-mini")


def test_openai_codex_fast_slot_defaults_to_mini(monkeypatch):
    """The FAST Codex picker should start on gpt-5.4-mini when available."""
    from spark_cli import main

    monkeypatch.setattr(
        "spark_cli.auth.get_codex_auth_status",
        lambda: {"logged_in": True, "api_key": "codex-token"},
    )
    monkeypatch.setattr(
        "spark_cli.auth.get_model_routing_slot_selection",
        lambda: "fast",
    )
    monkeypatch.setattr(
        "spark_cli.codex_models.get_codex_model_ids",
        lambda: ["gpt-5.5", "gpt-5.4-mini", "gpt-5.4"],
    )

    seen = {}

    def fake_prompt_model_selection(model_ids, current_model=""):
        seen["model_ids"] = model_ids
        seen["current_model"] = current_model
        return None

    monkeypatch.setattr(
        "spark_cli.auth._prompt_model_selection",
        fake_prompt_model_selection,
    )

    main._model_flow_openai_codex({"model": {}}, current_model="gpt-5.5")

    assert seen == {
        "model_ids": ["gpt-5.5", "gpt-5.4-mini", "gpt-5.4"],
        "current_model": "gpt-5.4-mini",
    }
