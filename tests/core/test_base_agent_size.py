"""Regression tests for the base agent's cold-boot footprint.

These guard the slim defaults introduced to keep the system prompt small:

* the 10 browser sub-tools live behind ``browser_open`` activation
* ``text_to_speech`` and ``cronjob`` are opt-in toolsets
* ``build_skills_system_prompt(lazy=True)`` collapses the skill index

Failures here mean someone undid a bloat reduction — investigate before
bumping the budget.
"""

import json
from pathlib import Path

import pytest

from core.toolsets import _SPARK_CORE_TOOLS, resolve_toolset


GATED_BROWSER_SUBTOOLS = {
    "browser_navigate",
    "browser_snapshot",
    "browser_click",
    "browser_type",
    "browser_scroll",
    "browser_back",
    "browser_press",
    "browser_get_images",
    "browser_vision",
    "browser_console",
}

OPT_IN_TOOLS = {"text_to_speech", "cronjob"}


def test_default_toolset_omits_browser_subtools():
    defaults = set(_SPARK_CORE_TOOLS)
    leaked = defaults & GATED_BROWSER_SUBTOOLS
    assert not leaked, (
        f"Browser sub-tools leaked into default toolset: {leaked}. "
        "They should be gated behind browser_open."
    )
    assert "browser_open" in defaults, "browser_open starter missing from defaults"


def test_default_toolset_omits_opt_in_tools():
    defaults = set(_SPARK_CORE_TOOLS)
    leaked = defaults & OPT_IN_TOOLS
    assert not leaked, (
        f"Opt-in tools leaked into default toolset: {leaked}. "
        "Users opt in via /toolset tts or /toolset cronjob."
    )


def test_browser_toolset_still_exposes_all_subtools():
    tools = set(resolve_toolset("browser"))
    assert GATED_BROWSER_SUBTOOLS <= tools
    assert "browser_open" in tools


def test_browser_open_check_fn_does_not_require_activation():
    """browser_open should be visible whenever browser deps are installed;
    only the sub-tools are gated by session activation."""
    from tools import browser_tool

    browser_tool._reset_browser_session()
    assert not browser_tool.check_browser_active()


def test_skills_lazy_prompt_is_short(tmp_path, monkeypatch):
    from agent import prompt_builder

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    # Drop a couple of dummy skills so the count is non-zero
    for name in ("alpha", "beta"):
        d = skills_dir / name
        d.mkdir()
        (d / "SKILL.md").write_text(
            "---\nname: " + name + "\ndescription: test\n---\nbody\n"
        )

    monkeypatch.setattr(prompt_builder, "get_skills_dir", lambda: skills_dir)
    monkeypatch.setattr(prompt_builder, "get_all_skills_dirs", lambda: [skills_dir])

    lazy = prompt_builder.build_skills_system_prompt(lazy=True)
    eager = prompt_builder.build_skills_system_prompt(lazy=False)

    assert "skills_list" in lazy
    assert "<available_skills>" not in lazy
    assert len(lazy) < 600, f"lazy prompt unexpectedly large: {len(lazy)} chars"
    # Eager output mentions individual skill names; lazy must not.
    assert "alpha" in eager
    assert "alpha" not in lazy


def test_default_tool_schema_token_budget():
    """The serialised default-tool schemas should fit comfortably under the
    pre-slimming baseline (~8.4k tokens for 27 tools)."""
    try:
        import tiktoken
    except Exception:
        pytest.skip("tiktoken not installed")

    import core.model_tools  # noqa: F401 — trigger tool discovery
    from tools.registry import registry

    enc = tiktoken.get_encoding("cl100k_base")
    total = 0
    missing = []
    for name in _SPARK_CORE_TOOLS:
        schema = registry.get_schema(name)
        if schema is None:
            missing.append(name)
            continue
        total += len(enc.encode(json.dumps(schema, ensure_ascii=False)))

    # We don't fail on missing tools — some are gated by env (HASS, send_message)
    # and may not be registered in a clean test env.
    # Snapshot at slim-defaults landing: 8142 tokens across 25 tools (was
    # ~10100 across 36 before this work). Budget leaves headroom for one
    # average-size tool before tripping.
    assert total < 8500, (
        f"Default tool schemas are {total} tokens (missing: {missing}). "
        "Snapshot baseline at slim-defaults landing was 8142. If a new tool "
        "legitimately bumps this, raise the budget — don't silently regress."
    )
