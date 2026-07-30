"""Regression coverage for the packaged desktop updater version contract."""

import json
import re
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_desktop_manifests_use_one_version():
    tauri = json.loads(
        (ROOT / "src/spark_cli/web/src-tauri/tauri.conf.json").read_text()
    )["version"]
    cargo = re.search(
        r'(?m)^version\s*=\s*"([^"]+)"',
        (ROOT / "src/spark_cli/web/src-tauri/Cargo.toml").read_text(),
    ).group(1)
    lock = re.search(
        r'(?ms)^\[\[package\]\]\s+name = "spark"\s+version = "([^"]+)"',
        (ROOT / "src/spark_cli/web/src-tauri/Cargo.lock").read_text(),
    ).group(1)
    assert {tauri, cargo, lock} == {tauri}
