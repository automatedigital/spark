"""Run unchanged recovery assertions against freshly built temporary SPA assets.

The runtime source copy gives web_server.WEB_DIST its normal relative layout.
Neither the tracked bundle nor the installed app is read as acceptance evidence.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    web = Path(__file__).resolve().parents[1]
    root = web.parents[2]
    with tempfile.TemporaryDirectory(prefix="spark-built-recovery-") as temporary:
        runtime = Path(temporary) / "src"
        shutil.copytree(root / "src", runtime, ignore=shutil.ignore_patterns(
            "web", "web_dist", "__pycache__", "*.pyc", "*.egg-info",
        ))
        built = runtime / "spark_cli" / "web_dist"
        build = subprocess.run(
            [str(web / "node_modules/.bin/vite"), "build", str(web),
             "--outDir", str(built), "--emptyOutDir", "--logLevel", "warn"],
            cwd=web, capture_output=True, text=True, timeout=180, check=False,
        )
        (output / "build.log").write_text(build.stdout + build.stderr)
        if build.returncode:
            raise RuntimeError(f"Temporary production build failed: {build.returncode}")
        manifest = built / ".vite" / "manifest.json"
        if not manifest.is_file():
            raise AssertionError("Production manifest missing")
        shutil.copyfile(manifest, output / "manifest.json")
        os.environ["SPARK_E2E_BUILT_WEB"] = "1"
        os.environ["PYTHONPATH"] = str(runtime)
        source_origin = subprocess.check_output(
            [sys.executable, "-c", "import importlib.util; print(importlib.util.find_spec('spark_cli.web_server').origin)"],
            cwd=root, env=os.environ, text=True, timeout=30,
        ).strip()
        if not Path(source_origin).is_relative_to(runtime):
            raise AssertionError(f"Backend resolved outside temporary source: {source_origin}")
        driver = web / "e2e" / "work-recovery.py"
        spec = importlib.util.spec_from_file_location("spark_recovery_acceptance", driver)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.REPORTS = output
        # The existing suite launches the real backend with this temporary source
        # path, and uses its own normal built-web mode. Assertions are unchanged.
        asyncio.run(module.main())
        (output / "production.json").write_text(json.dumps({
            "mode": "production-built", "runtimeSource": str(runtime),
            "builtAssets": str(built), "driver": str(driver),
            "canonicalBundleTouched": False,
            "python": sys.version, "buildExit": build.returncode, "resolvedBackendSource": source_origin,
        }, indent=2) + "\n")


if __name__ == "__main__":
    main()
