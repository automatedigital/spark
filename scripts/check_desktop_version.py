#!/usr/bin/env python3
"""Fail fast when desktop package versions can drift apart.

The Rust package version is passed to the bundled sidecar as
``SPARK_DESKTOP_VERSION``. The updater compares that value with the GitHub
release version, so all desktop manifests must agree.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TAURI = ROOT / "src/spark_cli/web/src-tauri/tauri.conf.json"
CARGO = ROOT / "src/spark_cli/web/src-tauri/Cargo.toml"
LOCK = ROOT / "src/spark_cli/web/src-tauri/Cargo.lock"


def cargo_package_version(path: Path, *, lock: bool = False) -> str:
    text = path.read_text()
    if lock:
        match = re.search(
            r'(?ms)^\[\[package\]\]\s+name = "spark"\s+version = "([^"]+)"',
            text,
        )
    else:
        match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
    if not match:
        raise SystemExit(f"Unable to read Spark desktop version from {path}")
    return match.group(1)


def main() -> int:
    tauri_version = json.loads(TAURI.read_text())["version"]
    versions = {
        "tauri.conf.json": tauri_version,
        "Cargo.toml": cargo_package_version(CARGO),
        "Cargo.lock": cargo_package_version(LOCK, lock=True),
    }
    if len(set(versions.values())) != 1:
        details = ", ".join(f"{name}={version}" for name, version in versions.items())
        raise SystemExit(f"Desktop version mismatch: {details}")
    print(f"Desktop version consistent: {tauri_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
