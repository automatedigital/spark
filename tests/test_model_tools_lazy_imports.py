"""Fresh-process coverage for optional model-tool imports."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_IMPORT_PROBE = """
import sys
import core.model_tools
print(int("tools.mcp_tool" in sys.modules))
"""


def _probe_mcp_import(spark_home: Path) -> bool:
    env = os.environ.copy()
    env["SPARK_HOME"] = str(spark_home)
    result = subprocess.run(
        [sys.executable, "-c", _IMPORT_PROBE],
        check=True,
        capture_output=True,
        env=env,
        text=True,
        timeout=30,
    )
    return result.stdout.strip().splitlines()[-1] == "1"


def test_unconfigured_profile_does_not_import_mcp_sdk(tmp_path):
    spark_home = tmp_path / "unconfigured"
    spark_home.mkdir()

    assert _probe_mcp_import(spark_home) is False


def test_configured_profile_keeps_eager_mcp_discovery(tmp_path):
    spark_home = tmp_path / "configured"
    spark_home.mkdir()
    (spark_home / "config.yaml").write_text(
        "mcp_servers:\n"
        "  disabled-test-server:\n"
        "    enabled: false\n"
        "    command: echo\n",
        encoding="utf-8",
    )

    assert _probe_mcp_import(spark_home) is True
