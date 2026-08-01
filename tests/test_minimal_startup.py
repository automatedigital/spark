from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

_BLOCKED_ROOTS = {
    "anthropic", "browser_use", "discord", "edge_tts", "elevenlabs",
    "fal_client", "firecrawl", "googleapiclient", "mcp", "playwright",
    "slack_sdk", "telegram", "torch", "transformers",
}

_BLOCKER = textwrap.dedent(
    f"""
    import importlib.abc,sys
    blocked={_BLOCKED_ROOTS!r}
    class Blocker(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname.partition('.')[0] in blocked:
                raise ModuleNotFoundError('blocked optional dependency: '+fullname, name=fullname)
            return None
    sys.meta_path.insert(0, Blocker())
    """
)


def _run(code: str, tmp_path: Path) -> subprocess.CompletedProcess:
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root / "src")
    env["SPARK_HOME"] = str(tmp_path / "spark-home")
    return subprocess.run(
        [sys.executable, "-c", _BLOCKER + code],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )


def test_no_tool_chat_import_without_optional_extras(tmp_path):
    result = _run(
        "\nfrom core.run_agent import AIAgent\n"
        "from core.model_tools import get_tool_definitions\n"
        "assert AIAgent.__name__ == 'AIAgent'\n"
        "assert get_tool_definitions(enabled_toolsets=[], quiet_mode=True) == []\n",
        tmp_path,
    )
    assert result.returncode == 0, result.stderr


def test_import_keeps_feature_routes_unloaded(tmp_path):
    result = _run(
        "\nimport sys\nimport core.run_agent\n"
        "blocked={'tools.browser_tool','tools.image_generation_tool','tools.tts_tool',"
        "'tools.cronjob_tools','tools.send_message_tool','tools.google_tools',"
        "'tools.computer_use.tool','tools.mcp_tool','spark_cli.models'}\n"
        "assert not (blocked & set(sys.modules)), blocked & set(sys.modules)\n",
        tmp_path,
    )
    assert result.returncode == 0, result.stderr


def test_cli_help_import_without_optional_extras(tmp_path):
    result = _run(
        "\nimport sys\nsys.argv=['spark','--help']\n"
        "from spark_cli.main import main\n"
        "try: main()\nexcept SystemExit as exc: assert exc.code == 0\n",
        tmp_path,
    )
    assert result.returncode == 0, result.stderr


def test_doctor_module_import_without_optional_extras(tmp_path):
    result = _run("\nfrom spark_cli.doctor import run_doctor\nassert callable(run_doctor)\n", tmp_path)
    assert result.returncode == 0, result.stderr
