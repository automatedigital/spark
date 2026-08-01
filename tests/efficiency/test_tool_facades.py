import json
from types import SimpleNamespace

import pytest

from core.model_tools import get_tool_definitions
from core.run_agent.prompt_cache import _PromptCacheMixin
from tools.facades import (
    facade_action_inventory,
    normalize_facade_call,
    schema_fingerprint,
    serialized_schema_chars,
)


def _names(definitions):
    return {item["function"]["name"] for item in definitions}


def test_default_schema_meets_budget_and_preserves_every_available_action(monkeypatch):
    monkeypatch.setenv("SPARK_LEGACY_TOOL_SCHEMAS", "1")
    legacy = get_tool_definitions(enabled_toolsets=["spark-cli"], quiet_mode=True)
    monkeypatch.delenv("SPARK_LEGACY_TOOL_SCHEMAS")
    compact = get_tool_definitions(enabled_toolsets=["spark-cli"], quiet_mode=True)

    inventory = facade_action_inventory()
    expanded = {
        tool
        for facade in _names(compact)
        for tool in inventory.get(facade, ())
        if tool in _names(legacy)
    }
    standalone = _names(compact) - set(inventory)
    assert _names(legacy) == expanded | standalone
    assert serialized_schema_chars(compact) <= 18_000
    assert serialized_schema_chars(compact) == len(
        json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
    )


@pytest.mark.parametrize(
    ("facade", "arguments", "legacy", "expected"),
    [
        ("files", {"action": "read", "arguments": {"path": "x.py"}}, "read_file", {"path": "x.py"}),
        ("skills", {"action": "view", "arguments": {"name": "demo"}}, "skill_view", {"name": "demo"}),
        ("preview", {"action": "click", "arguments": {"slug": "app", "selector": "#go"}}, "preview_click", {"slug": "app", "selector": "#go"}),
        ("canvas", {"action": "await", "arguments": {"canvas_id": "c", "widget_id": "w"}}, "canvas_await", {"canvas_id": "c", "widget_id": "w"}),
        ("web", {"action": "search", "arguments": {"query": "Spark"}}, "web_search", {"query": "Spark"}),
        ("browser", {"action": "navigate", "arguments": {"url": "https://example.com"}}, "browser_navigate", {"url": "https://example.com"}),
    ],
)
def test_facade_selection_and_legacy_normalization(facade, arguments, legacy, expected):
    assert normalize_facade_call(facade, arguments) == (legacy, expected)
    # Saved transcripts and API integrations keep their old names unchanged.
    assert normalize_facade_call(legacy, expected) == (legacy, expected)


def test_action_specific_validation_rejects_missing_or_invalid_arguments():
    with pytest.raises(ValueError, match="missing required"):
        normalize_facade_call("files", {"action": "read", "arguments": {}})
    with pytest.raises(ValueError, match="Unknown files action"):
        normalize_facade_call("files", {"action": "explode"})
    with pytest.raises(ValueError, match="must be an object"):
        normalize_facade_call("web", {"action": "search", "arguments": "query=bad"})


def test_fingerprint_is_order_sensitive_and_stable_across_resolution():
    first = get_tool_definitions(enabled_toolsets=["spark-cli"], quiet_mode=True)
    second = get_tool_definitions(enabled_toolsets=["spark-cli"], quiet_mode=True)
    assert schema_fingerprint(first) == schema_fingerprint(second)
    assert schema_fingerprint(first) != schema_fingerprint(list(reversed(first)))


def test_browser_activation_does_not_change_schema_fingerprint(monkeypatch):
    import tools.browser_tool as browser_tool

    monkeypatch.setattr(browser_tool, "_browser_session_active", False)
    before = get_tool_definitions(enabled_toolsets=["spark-cli"], quiet_mode=True)
    monkeypatch.setattr(browser_tool, "_browser_session_active", True)
    after = get_tool_definitions(enabled_toolsets=["spark-cli"], quiet_mode=True)
    assert schema_fingerprint(before) == schema_fingerprint(after)
    browser_schema = next(item for item in after if item["function"]["name"] == "browser")
    assert "snapshot" in browser_schema["function"]["parameters"]["properties"]["action"]["enum"]


def test_mid_epoch_schema_mutation_is_rejected():
    class Agent(_PromptCacheMixin):
        pass

    agent = Agent()
    agent.tools = get_tool_definitions(enabled_toolsets=["spark-cli"], quiet_mode=True)
    from tools.facades import canonical_schema_json
    agent._frozen_tool_schema_json = canonical_schema_json(agent.tools)
    agent._assert_tool_surface_stable()
    agent.tools = [*agent.tools, {"type": "function", "function": {"name": "late"}}]
    with pytest.raises(RuntimeError, match="inside context epoch"):
        agent._assert_tool_surface_stable()


def test_facades_keep_legacy_parallel_conflict_semantics(tmp_path):
    from core.run_agent.parallelism import _should_parallelize_tool_batch

    def call(action, path):
        return SimpleNamespace(function=SimpleNamespace(
            name="files",
            arguments=json.dumps({"action": action, "arguments": {"path": str(path)}}),
        ))

    assert _should_parallelize_tool_batch([
        call("read", tmp_path / "a.py"), call("read", tmp_path / "b.py"),
    ])
    assert not _should_parallelize_tool_batch([
        call("read", tmp_path / "same.py"), call("write", tmp_path / "same.py"),
    ])


@pytest.mark.parametrize(
    ("utterance", "expected_facade", "expected_action"),
    [
        ("read src/app.py", "files", "read"),
        ("find references to AIAgent", "files", "search"),
        ("update the skill", "skills", "manage"),
        ("check the rendered page console", "preview", "console"),
        ("search the public web", "web", "search"),
        ("navigate and click the login button", "browser", "navigate"),
        ("render a status board", "canvas", "render"),
    ],
)
def test_tool_selection_eval_fixture_has_unambiguous_action(utterance, expected_facade, expected_action):
    # The fixed fixture locks representative and ambiguous family selection.
    # Assertions prove the expected action exists in the exact emitted schema.
    definitions = get_tool_definitions(enabled_toolsets=["spark-cli"], quiet_mode=True)
    schema = next(item["function"] for item in definitions if item["function"]["name"] == expected_facade)
    assert expected_action in schema["parameters"]["properties"]["action"]["enum"], utterance


def test_legacy_profile_is_a_new_session_rollback_boundary(monkeypatch):
    compact = get_tool_definitions(enabled_toolsets=["spark-cli"], quiet_mode=True)
    monkeypatch.setenv("SPARK_LEGACY_TOOL_SCHEMAS", "1")
    legacy = get_tool_definitions(enabled_toolsets=["spark-cli"], quiet_mode=True)
    assert "files" in _names(compact)
    assert "files" not in _names(legacy)
    assert {"read_file", "write_file", "patch", "search_files"}.issubset(_names(legacy))


def test_granular_api_toolsets_keep_legacy_names():
    definitions = get_tool_definitions(enabled_toolsets=["file"], quiet_mode=True)
    assert _names(definitions) == {
        "artifact_read",
        "read_file",
        "write_file",
        "patch",
        "search_files",
    }
