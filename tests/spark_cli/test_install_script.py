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
    assert "sync_running_dashboard_skill_homes" in content
    assert "dashboard SPARK_HOME" in content


def test_installer_migrates_config_and_checks_dashboard_health():
    content = INSTALL_SCRIPT.read_text(encoding="utf-8")

    assert "run_config_migration()" in content
    assert "migrate_config(interactive=False" in content
    assert "gateway_runtime_required()" in content
    assert "API_SERVER_ENABLED API_SERVER_KEY" in content
    assert 'dash.get("enabled_with_gateway", True)' in content
    assert "Spark uses the gateway for messaging, API server access, and the embedded Web UI." in content
    assert "verify_dashboard_health()" in content
    assert 'SPARK_DASHBOARD_HEALTH_WAIT_SECONDS:-45' in content
    assert '-m spark_cli.dashboard_health --wait "$wait_seconds"' in content
    assert "Dashboard health check failed after gateway restart" in content
    assert "build_web_ui_bundle()" in content
    assert "Web UI dashboard bundle built" in content
    assert "gateway install --force" in content
    assert "verify_dashboard_health || true" not in content


def test_installer_discards_generated_web_assets_before_autostash():
    content = INSTALL_SCRIPT.read_text(encoding="utf-8")

    function_start = content.index("discard_generated_web_assets()")
    clone_start = content.index("clone_repo()", function_start)
    clone_end = content.index("setup_venv()", clone_start)
    function_body = content[function_start:clone_start]
    clone_body = content[clone_start:clone_end]

    assert "git restore --source=HEAD --staged --worktree -- src/spark_cli/web_dist" in function_body
    assert "git clean -fd -- src/spark_cli/web_dist" in function_body
    assert clone_body.index("discard_generated_web_assets") < clone_body.index(
        "git stash push --include-untracked"
    )


def test_legacy_setup_script_syncs_missing_bundled_skills():
    content = SETUP_SCRIPT.read_text(encoding="utf-8")

    assert "-m tools.skills_sync" in content
    assert "tools/skills_sync.py" not in content
    assert "find \"$SCRIPT_DIR/skills\" -name SKILL.md" in content
    assert "Missing bundled skills copied" in content


def test_installer_prompts_before_computer_use_install():
    content = INSTALL_SCRIPT.read_text(encoding="utf-8")
    start = content.index("maybe_install_cua_driver()")
    end = content.index("run_setup_wizard()", start)
    function_body = content[start:end]

    assert "maybe_install_cua_driver()" in function_body
    assert '[ "$OS" = "macos" ] || return 0' in function_body
    assert "Enable computer use for this Mac? [Y/n]" in function_body
    assert "read -p" in function_body
    assert "Skipped computer_use." in function_body
    assert "raw.githubusercontent.com/trycua/cua/main/libs/cua-driver/scripts/install.sh" in function_body
    assert "pip install cua-driver" not in function_body
