#!/usr/bin/env python3
"""Fail desktop packaging when caches or excluded optional runtimes leak in."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

FORBIDDEN_PARTS = {
    ".git",
    ".venv",
    ".venv-desktop",
    "node_modules",
    "__pycache__",
    ".cache",
    ".mypy_cache",
    ".pytest_cache",
}
EXCLUDED_OPTIONAL_MODULES = {
    "torch",
    "tensorflow",
    "transformers",
    "matplotlib",
    "wandb",
    "faster_whisper",
    "ctranslate2",
    "onnxruntime",
    "tinker",
    "atroposlib",
}


def _manifest_assets(web_dist: Path) -> list[str]:
    manifest_path = web_dist / ".vite" / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"Missing Vite manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assets: set[str] = set()
    for entry in manifest.values():
        if not isinstance(entry, dict):
            continue
        for key in ("file", "css", "assets"):
            value = entry.get(key)
            if isinstance(value, str):
                assets.add(value)
            elif isinstance(value, list):
                assets.update(item for item in value if isinstance(item, str))
    return sorted(assets)


def audit_resources(sidecar_dir: Path, web_dist: Path) -> dict:
    problems: list[str] = []
    sidecar_files = [path for path in sidecar_dir.rglob("*") if path.is_file()]
    if not sidecar_files:
        problems.append(f"missing or empty sidecar directory: {sidecar_dir}")
    if not any(path.name in {"spark-server", "spark-server.exe"} for path in sidecar_files):
        problems.append("missing frozen spark-server executable")
    for path in sidecar_files:
        relative = path.relative_to(sidecar_dir)
        if FORBIDDEN_PARTS.intersection(relative.parts):
            problems.append(f"forbidden cache/source path: {relative}")
        lowered_parts = {part.casefold().removesuffix(".pyc") for part in relative.parts}
        leaked = EXCLUDED_OPTIONAL_MODULES.intersection(lowered_parts)
        if leaked:
            problems.append(f"excluded optional module {sorted(leaked)[0]}: {relative}")

    assets = _manifest_assets(web_dist)
    missing_assets = [asset for asset in assets if not (web_dist / asset).is_file()]
    problems.extend(f"missing web asset: {asset}" for asset in missing_assets)
    if not (web_dist / "index.html").is_file():
        problems.append("missing web index.html")

    report = {
        "sidecar_files": len(sidecar_files),
        "sidecar_bytes": sum(path.stat().st_size for path in sidecar_files),
        "web_manifest_assets": len(assets),
        "web_dist_bytes": sum(
            path.stat().st_size for path in web_dist.rglob("*") if path.is_file()
        ),
        "problems": problems,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sidecar-dir", type=Path, required=True)
    parser.add_argument("--web-dist", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = audit_resources(args.sidecar_dir.resolve(), args.web_dist.resolve())
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            f"Desktop resource audit: {report['sidecar_files']} sidecar files, "
            f"{report['web_manifest_assets']} web assets, {len(report['problems'])} problems"
        )
        for problem in report["problems"]:
            print(f"- {problem}")
    return 1 if report["problems"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
