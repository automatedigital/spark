from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tools.registry import ToolRegistry


def _manifest_entry(**overrides):
    item = {
        "name": "lazy_test",
        "toolset": "test",
        "schema": {"name": "lazy_test", "description": "test", "parameters": {"type": "object"}},
        "handler_module": "spark_fake_lazy_feature",
        "requires_env": [],
        "is_async": False,
        "check_spec": "always",
        "extra": "fake-feature",
    }
    item.update(overrides)
    return item


def test_manifest_schema_does_not_import_handler(monkeypatch):
    reg = ToolRegistry()
    reg.register_manifest([_manifest_entry()])
    imported = []
    monkeypatch.setattr(importlib, "import_module", lambda name: imported.append(name))

    definitions = reg.get_definitions({"lazy_test"})

    assert definitions[0]["function"]["name"] == "lazy_test"
    assert imported == []


def test_concurrent_first_use_imports_and_registers_once(monkeypatch):
    reg = ToolRegistry()
    reg.register_manifest([_manifest_entry()])
    imports = []

    def fake_import(name):
        imports.append(name)
        reg.register(
            name="lazy_test",
            toolset="test",
            schema=_manifest_entry()["schema"],
            handler=lambda args, **kwargs: json.dumps({"value": args["value"]}),
        )

    monkeypatch.setattr(importlib, "import_module", fake_import)
    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(lambda value: reg.dispatch("lazy_test", {"value": value}), range(64)))

    assert [json.loads(result)["value"] for result in results] == list(range(64))
    assert imports == ["spark_fake_lazy_feature"]
    assert reg.get_module_load_count("spark_fake_lazy_feature") == 1


def test_missing_optional_dependency_names_extra(monkeypatch):
    reg = ToolRegistry()
    reg.register_manifest([_manifest_entry()])

    def missing(_name):
        error = ModuleNotFoundError("No module named 'fake_sdk'")
        error.name = "fake_sdk"
        raise error

    monkeypatch.setattr(importlib, "import_module", missing)
    payload = json.loads(reg.dispatch("lazy_test", {}))
    assert "fake_sdk" in payload["error"]
    assert "fake-feature" in payload["error"]


def test_generated_manifest_matches_isolated_handler_imports():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "scripts/generate_tool_manifest.py", "--check"],
        cwd=root,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "isolated modules" in result.stdout


def test_real_builtin_first_use_is_exactly_once_in_fresh_process():
    root = Path(__file__).resolve().parents[2]
    code = """
from concurrent.futures import ThreadPoolExecutor
import sys
import core.model_tools
from tools.registry import registry
assert registry.get_entry('artifact_read').handler is None
assert 'tools.artifact_tool' not in sys.modules
with ThreadPoolExecutor(max_workers=16) as pool:
    results=list(pool.map(lambda _: registry.dispatch('artifact_read', {'handle':'artifact://missing'}, task_id='t'), range(64)))
assert all('missing' in result or 'expired' in result for result in results)
assert registry.get_module_load_count('tools.artifact_tool') == 1
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root / "src")
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
