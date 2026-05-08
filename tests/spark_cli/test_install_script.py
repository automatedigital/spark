import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_SCRIPT = REPO_ROOT / "scripts" / "install.sh"
SETUP_SCRIPT = REPO_ROOT / "scripts" / "setup-spark.sh"


def test_install_scripts_are_valid_shell():
    for script in (INSTALL_SCRIPT, SETUP_SCRIPT):
        result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


def test_installer_syncs_bundled_skills_via_module():
    content = INSTALL_SCRIPT.read_text(encoding="utf-8")

    assert 'SPARK_HOME="${SPARK_HOME:-$HOME/.spark}"' in content
    assert "-m tools.skills_sync" in content
    assert "tools/skills_sync.py" not in content
    assert "find \"$INSTALL_DIR/skills\" -name SKILL.md" in content
    assert "Missing bundled skills copied" in content
    assert "seed_profile_skills" in content


def test_legacy_setup_script_syncs_missing_bundled_skills():
    content = SETUP_SCRIPT.read_text(encoding="utf-8")

    assert "-m tools.skills_sync" in content
    assert "tools/skills_sync.py" not in content
    assert "find \"$SCRIPT_DIR/skills\" -name SKILL.md" in content
    assert "Missing bundled skills copied" in content
