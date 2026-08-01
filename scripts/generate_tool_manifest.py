#!/usr/bin/env python3
"""Generate or verify Spark's lightweight built-in tool manifest."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUT = SRC / "tools" / "generated_manifest.py"
sys.path.insert(0, str(SRC))

from tools.manifest_spec import (  # noqa: E402
    BUILTIN_TOOL_MODULES,
    MODULE_EXTRAS,
    check_spec,
)


_PROBE = r"""
import importlib,json,sys
from tools.registry import registry
module_name=sys.argv[1]
importlib.import_module(module_name)
items=[]
for name in registry.get_all_tool_names():
    entry=registry.get_entry(name)
    if entry.handler is None or entry.handler.__module__ != module_name:
        continue
    check=entry.check_fn
    items.append({
        'name': entry.name,
        'toolset': entry.toolset,
        'schema': entry.schema,
        'handler_module': module_name,
        'handler_name': getattr(entry.handler, '__name__', ''),
        'check_path': None if check is None else f'{check.__module__}:{getattr(check, "__name__", "")}',
        'requires_env': entry.requires_env,
        'is_async': entry.is_async,
        'description': entry.description,
        'emoji': entry.emoji,
        'max_result_size_chars': ('infinity' if entry.max_result_size_chars == float('inf') else entry.max_result_size_chars),
        'normalize': entry.normalize,
        'screen': entry.screen,
    })
print(json.dumps(items, ensure_ascii=False, sort_keys=True))
"""


def _probe(module_name: str) -> list[dict]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    env["SPARK_MANIFEST_BUILD"] = "1"
    completed = subprocess.run(
        [sys.executable, "-c", _PROBE, module_name],
        cwd=ROOT,
        env=env,
        check=False,
        text=True,
        capture_output=True,
        timeout=30,
    )
    if completed.returncode:
        raise RuntimeError(
            f"Manifest probe failed for {module_name}:\n{completed.stderr.strip()}"
        )
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Manifest probe for {module_name} emitted non-JSON output: {completed.stdout!r}"
        ) from exc


def generate() -> list[dict]:
    entries: list[dict] = []
    for module_name in BUILTIN_TOOL_MODULES:
        module_entries = _probe(module_name)
        if not module_entries:
            raise RuntimeError(f"Built-in module {module_name} registered no tools")
        for entry in module_entries:
            entry["check_spec"] = check_spec(entry.pop("check_path"), entry["requires_env"])
            entry["extra"] = MODULE_EXTRAS.get(module_name)
        entries.extend(module_entries)
    names = [entry["name"] for entry in entries]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise RuntimeError(f"Duplicate built-in tool names: {duplicates}")
    return sorted(entries, key=lambda item: item["name"])


def render(entries: list[dict]) -> str:
    payload = json.dumps(entries, ensure_ascii=False, indent=2, sort_keys=True)
    return (
        '"""Generated built-in tool schema manifest. Do not edit by hand.\n\n'
        'Run ``python scripts/generate_tool_manifest.py`` to regenerate.\n'
        '"""\n\nimport json\n\n'
        f"BUILTIN_TOOL_MANIFEST = json.loads({payload!r})\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail when the committed manifest drifts")
    args = parser.parse_args()
    rendered = render(generate())
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != rendered:
            print("Tool manifest drift detected; run scripts/generate_tool_manifest.py", file=sys.stderr)
            return 1
        print(f"Tool manifest valid: {len(generate())} tools across {len(BUILTIN_TOOL_MODULES)} isolated modules")
        return 0
    OUTPUT.write_text(rendered, encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
