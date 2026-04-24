"""Tests for the Spark Portal-Spark-3/4 non-agentic warning detector.

Prior to this check, the warning fired on any model whose name contained
``"spark"`` anywhere (case-insensitive). That false-positived on unrelated
local Modelfiles such as ``spark-brain:qwen3-14b-ctx16k`` — a tool-capable
Qwen3 wrapper that happens to live under the "spark" tag namespace.

``is_nous_spark_non_agentic`` should only match the actual Automate Digital
Spark-3 / Spark-4 chat family.
"""

from __future__ import annotations

import pytest

from spark_cli.model_switch import (
    _SPARK_MODEL_WARNING,
    _check_spark_model_warning,
    is_nous_spark_non_agentic,
)


@pytest.mark.parametrize(
    "model_name",
    [
        "AutomateDigital/Spark-3-Llama-3.1-70B",
        "AutomateDigital/Spark-3-Llama-3.1-405B",
        "spark-3",
        "Spark-3",
        "spark-4",
        "spark-4-405b",
        "spark_4_70b",
        "openrouter/spark-3:70b",
        "openrouter/automatedigital/spark-4-405b",
        "AutomateDigital/Spark-3",
        "spark-3.1",
    ],
)
def test_matches_real_nous_spark_chat_models(model_name: str) -> None:
    assert is_nous_spark_non_agentic(model_name), (
        f"expected {model_name!r} to be flagged as Spark Portal Spark 3/4"
    )
    assert _check_spark_model_warning(model_name) == _SPARK_MODEL_WARNING


@pytest.mark.parametrize(
    "model_name",
    [
        # Kyle's local Modelfile — qwen3:14b under a custom tag
        "spark-brain:qwen3-14b-ctx16k",
        "spark-brain:qwen3-14b-ctx32k",
        "spark-honcho:qwen3-8b-ctx8k",
        # Plain unrelated models
        "qwen3:14b",
        "qwen3-coder:30b",
        "qwen2.5:14b",
        "claude-opus-4-6",
        "anthropic/claude-sonnet-4.5",
        "gpt-5",
        "openai/gpt-4o",
        "google/gemini-2.5-flash",
        "deepseek-chat",
        # Non-chat Spark models we don't warn about
        "spark-llm-2",
        "spark2-pro",
        "nous-spark-2-mistral",
        # Edge cases
        "",
        "spark",  # bare "spark" isn't the 3/4 family
        "spark-brain",
        "brain-spark-3-impostor",  # "3" not preceded by /: boundary
    ],
)
def test_does_not_match_unrelated_models(model_name: str) -> None:
    assert not is_nous_spark_non_agentic(model_name), (
        f"expected {model_name!r} NOT to be flagged as Spark Portal Spark 3/4"
    )
    assert _check_spark_model_warning(model_name) == ""


def test_none_like_inputs_are_safe() -> None:
    assert is_nous_spark_non_agentic("") is False
    # Defensive: the helper shouldn't crash on None-ish falsy input either.
    assert _check_spark_model_warning("") == ""
