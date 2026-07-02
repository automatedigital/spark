"""Tests for spark_cli.doctor."""

import os
import sys
import types
from argparse import Namespace
from types import SimpleNamespace

import pytest

import spark_cli.doctor as doctor
import spark_cli.gateway as gateway_cli
from core.network_tls import CABundleError
from spark_cli import doctor as doctor_mod
from spark_cli.doctor import _has_provider_env_config
from tools.connectors.base import ConnectorState, ConnectorStatus


class TestDoctorPlatformHints:
    def test_termux_package_hint(self, monkeypatch):
        monkeypatch.setenv("TERMUX_VERSION", "0.118.3")
        monkeypatch.setenv("PREFIX", "/data/data/com.termux/files/usr")
        assert doctor._is_termux() is True
        assert doctor._python_install_cmd() == "python -m pip install"
        assert doctor._system_package_install_cmd("ripgrep") == "pkg install ripgrep"

    def test_non_termux_package_hint_defaults_to_apt(self, monkeypatch):
        monkeypatch.delenv("TERMUX_VERSION", raising=False)
        monkeypatch.setenv("PREFIX", "/usr")
        monkeypatch.setattr(sys, "platform", "linux")
        assert doctor._is_termux() is False
        assert doctor._python_install_cmd() == "uv pip install"
        assert doctor._system_package_install_cmd("ripgrep") == "sudo apt install ripgrep"


class TestProviderEnvDetection:
    def test_detects_openai_api_key(self):
        content = "OPENAI_BASE_URL=http://localhost:1234/v1\nOPENAI_API_KEY=***"
        assert _has_provider_env_config(content)

    def test_detects_custom_endpoint_without_openrouter_key(self):
        content = "OPENAI_BASE_URL=http://localhost:8080/v1\n"
        assert _has_provider_env_config(content)

    def test_returns_false_when_no_provider_settings(self):
        content = "TERMINAL_ENV=local\n"
        assert not _has_provider_env_config(content)


class TestDoctorToolAvailabilityOverrides:
    def test_marks_honcho_available_when_configured(self, monkeypatch):
        monkeypatch.setattr(doctor, "_honcho_is_configured_for_doctor", lambda: True)

        available, unavailable = doctor._apply_doctor_tool_availability_overrides(
            [],
            [{"name": "honcho", "env_vars": [], "tools": ["query_user_context"]}],
        )

        assert available == ["honcho"]
        assert unavailable == []

    def test_leaves_honcho_unavailable_when_not_configured(self, monkeypatch):
        monkeypatch.setattr(doctor, "_honcho_is_configured_for_doctor", lambda: False)

        honcho_entry = {"name": "honcho", "env_vars": [], "tools": ["query_user_context"]}
        available, unavailable = doctor._apply_doctor_tool_availability_overrides(
            [],
            [honcho_entry],
        )

        assert available == []
        assert unavailable == [honcho_entry]


class TestDoctorCABundle:
    def test_reports_configured_ca_bundle(self, monkeypatch, tmp_path, capsys):
        bundle = tmp_path / "corp.pem"
        monkeypatch.setattr(doctor, "validate_ca_bundle", lambda: bundle)
        monkeypatch.setattr(doctor, "httpx_verify_value", lambda: str(bundle))

        issues = []
        assert doctor._check_ca_bundle(issues) == str(bundle)

        out = capsys.readouterr().out
        assert "Custom CA bundle" in out
        assert str(bundle) in out
        assert issues == []

    def test_reports_invalid_ca_bundle(self, monkeypatch, capsys):
        def _raise_invalid():
            raise CABundleError("network.ca_bundle path does not exist: /nope.pem")

        monkeypatch.setattr(doctor, "validate_ca_bundle", _raise_invalid)

        issues = []
        assert doctor._check_ca_bundle(issues) is None

        out = capsys.readouterr().out
        assert "Custom CA bundle" in out
        assert "does not exist" in out
        assert issues == ["network.ca_bundle path does not exist: /nope.pem"]


class TestHonchoDoctorConfigDetection:
    def test_reports_configured_when_enabled_with_api_key(self, monkeypatch):
        fake_config = SimpleNamespace(enabled=True, api_key="***")

        monkeypatch.setattr(
            "plugins.memory.honcho.client.HonchoClientConfig.from_global_config",
            lambda: fake_config,
        )

        assert doctor._honcho_is_configured_for_doctor()

    def test_reports_not_configured_without_api_key(self, monkeypatch):
        fake_config = SimpleNamespace(enabled=True, api_key="")

        monkeypatch.setattr(
            "plugins.memory.honcho.client.HonchoClientConfig.from_global_config",
            lambda: fake_config,
        )

        assert not doctor._honcho_is_configured_for_doctor()


def test_run_doctor_sets_interactive_env_for_tool_checks(monkeypatch, tmp_path):
    """Doctor should present CLI-gated tools as available in CLI context."""
    project_root = tmp_path / "project"
    spark_home = tmp_path / ".spark"
    project_root.mkdir()
    spark_home.mkdir()

    monkeypatch.setattr(doctor_mod, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(doctor_mod, "SPARK_HOME", spark_home)
    monkeypatch.delenv("SPARK_INTERACTIVE", raising=False)

    seen = {}

    def fake_check_tool_availability(*args, **kwargs):
        seen["interactive"] = os.getenv("SPARK_INTERACTIVE")
        raise SystemExit(0)

    fake_model_tools = types.SimpleNamespace(
        check_tool_availability=fake_check_tool_availability,
        TOOLSET_REQUIREMENTS={},
    )
    monkeypatch.setitem(sys.modules, "core.model_tools", fake_model_tools)

    with pytest.raises(SystemExit):
        doctor_mod.run_doctor(Namespace(fix=False))

    assert seen["interactive"] == "1"


def test_check_gateway_service_linger_warns_when_disabled(monkeypatch, tmp_path, capsys):
    unit_path = tmp_path / "spark-gateway.service"
    unit_path.write_text("[Unit]\n")

    monkeypatch.setattr(gateway_cli, "is_linux", lambda: True)
    monkeypatch.setattr(gateway_cli, "get_systemd_unit_path", lambda: unit_path)
    monkeypatch.setattr(gateway_cli, "get_systemd_linger_status", lambda: (False, ""))

    issues = []
    doctor._check_gateway_service_linger(issues)

    out = capsys.readouterr().out
    assert "Gateway Service" in out
    assert "Systemd linger disabled" in out
    assert "loginctl enable-linger" in out
    assert issues == [
        "Enable linger for the gateway user service: sudo loginctl enable-linger $USER"
    ]


def test_check_gateway_service_linger_skips_when_service_not_installed(monkeypatch, tmp_path, capsys):
    unit_path = tmp_path / "missing.service"

    monkeypatch.setattr(gateway_cli, "is_linux", lambda: True)
    monkeypatch.setattr(gateway_cli, "get_systemd_unit_path", lambda: unit_path)

    issues = []
    doctor._check_gateway_service_linger(issues)

    out = capsys.readouterr().out
    assert out == ""
    assert issues == []


# ── Memory provider section (doctor should only check the *active* provider) ──


class TestDoctorMemoryProviderSection:
    """The ◆ Memory Provider section should respect memory.provider config."""

    def _make_spark_home(self, tmp_path, provider=""):
        """Create a minimal SPARK_HOME with config.yaml."""
        home = tmp_path / ".spark"
        home.mkdir(parents=True, exist_ok=True)
        import yaml
        config = {"memory": {"provider": provider}} if provider else {"memory": {}}
        (home / "config.yaml").write_text(yaml.dump(config))
        return home

    def _run_doctor_and_capture(self, monkeypatch, tmp_path, provider=""):
        """Run doctor and capture stdout."""
        home = self._make_spark_home(tmp_path, provider)
        monkeypatch.setattr(doctor_mod, "SPARK_HOME", home)
        monkeypatch.setattr(doctor_mod, "PROJECT_ROOT", tmp_path / "project")
        monkeypatch.setattr(doctor_mod, "_DHH", str(home))
        (tmp_path / "project").mkdir(exist_ok=True)

        # Stub tool availability (returns empty) so doctor runs past it
        fake_model_tools = types.SimpleNamespace(
            check_tool_availability=lambda *a, **kw: ([], []),
            TOOLSET_REQUIREMENTS={},
        )
        monkeypatch.setitem(sys.modules, "model_tools", fake_model_tools)

        # Stub auth checks to avoid real API calls
        try:
            from spark_cli import auth as _auth_mod
            monkeypatch.setattr(_auth_mod, "get_nous_auth_status", lambda: {})
            monkeypatch.setattr(_auth_mod, "get_codex_auth_status", lambda: {})
        except Exception:
            pass

        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            doctor_mod.run_doctor(Namespace(fix=False))
        return buf.getvalue()

    def test_no_provider_shows_builtin_ok(self, monkeypatch, tmp_path):
        out = self._run_doctor_and_capture(monkeypatch, tmp_path, provider="")
        assert "Memory Provider" in out
        assert "Built-in memory active" in out
        # Should NOT mention Honcho or Mem0 errors
        assert "Honcho API key" not in out
        assert "Mem0" not in out

    def test_honcho_provider_not_installed_shows_fail(self, monkeypatch, tmp_path):
        # Make honcho import fail
        monkeypatch.setitem(
            sys.modules, "plugins.memory.honcho.client", None
        )
        out = self._run_doctor_and_capture(monkeypatch, tmp_path, provider="honcho")
        assert "Memory Provider" in out
        # Should show failure since honcho is set but not importable
        assert "Built-in memory active" not in out

    def test_mem0_provider_not_installed_shows_fail(self, monkeypatch, tmp_path):
        # Make mem0 import fail
        monkeypatch.setitem(sys.modules, "plugins.memory.mem0", None)
        out = self._run_doctor_and_capture(monkeypatch, tmp_path, provider="mem0")
        assert "Memory Provider" in out
        assert "Built-in memory active" not in out


def test_run_doctor_termux_treats_docker_and_browser_warnings_as_expected(monkeypatch, tmp_path):
    helper = TestDoctorMemoryProviderSection()
    monkeypatch.setenv("TERMUX_VERSION", "0.118.3")
    monkeypatch.setenv("PREFIX", "/data/data/com.termux/files/usr")

    real_which = doctor_mod.shutil.which

    def fake_which(cmd):
        if cmd in {"docker", "node", "npm"}:
            return None
        return real_which(cmd)

    monkeypatch.setattr(doctor_mod.shutil, "which", fake_which)

    out = helper._run_doctor_and_capture(monkeypatch, tmp_path, provider="")

    assert "Docker backend is not available inside Termux" in out
    assert "Node.js not found (browser tools are optional in the tested Termux path)" in out
    assert "Install Node.js on Termux with: pkg install nodejs" in out
    assert "Termux browser setup:" in out
    assert "1) pkg install nodejs" in out
    assert "2) npm install -g agent-browser" in out
    assert "3) agent-browser install" in out
    assert "docker not found (optional)" not in out


def test_run_doctor_termux_does_not_mark_browser_available_without_agent_browser(monkeypatch, tmp_path):
    home = tmp_path / ".spark"
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text("memory: {}\n", encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)

    monkeypatch.setenv("TERMUX_VERSION", "0.118.3")
    monkeypatch.setenv("PREFIX", "/data/data/com.termux/files/usr")
    monkeypatch.setattr(doctor_mod, "SPARK_HOME", home)
    monkeypatch.setattr(doctor_mod, "PROJECT_ROOT", project)
    monkeypatch.setattr(doctor_mod, "_DHH", str(home))
    monkeypatch.setattr(doctor_mod.shutil, "which", lambda cmd: "/data/data/com.termux/files/usr/bin/node" if cmd in {"node", "npm"} else None)

    fake_model_tools = types.SimpleNamespace(
        check_tool_availability=lambda *a, **kw: (["terminal"], [{"name": "browser", "env_vars": [], "tools": ["browser_navigate"]}]),
        TOOLSET_REQUIREMENTS={
            "terminal": {"name": "terminal"},
            "browser": {"name": "browser"},
        },
    )
    monkeypatch.setitem(sys.modules, "model_tools", fake_model_tools)
    monkeypatch.setitem(sys.modules, "core.model_tools", fake_model_tools)

    # Simulate the managed agent-browser runtime being absent (as on a fresh
    # Termux install). Without this stub the test would pass/fail depending on
    # whether the *host* machine happens to have agent-browser installed.
    from spark_cli import browser_runtime as _browser_runtime
    monkeypatch.setattr(_browser_runtime, "agent_browser_path", lambda: None)

    try:
        from spark_cli import auth as _auth_mod
        monkeypatch.setattr(_auth_mod, "get_nous_auth_status", lambda: {})
        monkeypatch.setattr(_auth_mod, "get_codex_auth_status", lambda: {})
    except Exception:
        pass

    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        doctor_mod.run_doctor(Namespace(fix=False))
    out = buf.getvalue()

    assert "✓ browser" not in out
    assert "browser" in out
    assert "system dependency not met" in out
    assert "agent-browser is not installed (expected in the tested Termux path)" in out
    assert "npm install -g agent-browser && agent-browser install" in out


def test_collect_connector_blockers_reports_configured_error(monkeypatch):
    class BrokenConnector:
        id = "notion"
        name = "Notion"
        docs_url = "https://example.com/notion"

        def status(self):
            return ConnectorStatus(
                state=ConnectorState.ERROR,
                detail="token revoked",
                extra={
                    "primary_env_var": "NOTION_API_KEY",
                    "env_vars": ["NOTION_API_KEY"],
                    "setup_steps": ["Set NOTION_API_KEY.", "Share pages with the integration."],
                },
            )

        def read_meta(self):
            return {}

    import tools.connectors

    monkeypatch.setattr(tools.connectors, "list_connectors", lambda: [BrokenConnector()])

    blockers = doctor_mod._collect_connector_blockers({"NOTION_API_KEY": "secret"})

    assert [b.summary() for b in blockers] == [
        "[connector] Notion: token revoked - Set NOTION_API_KEY. Share pages with the integration."
    ]


def test_collect_mcp_blockers_reports_disabled_missing_command_and_profile_path(monkeypatch, tmp_path):
    monkeypatch.setattr("tools.mcp_tool._MCP_AVAILABLE", True)
    monkeypatch.setattr("tools.mcp_tool._MCP_HTTP_AVAILABLE", True)
    monkeypatch.setattr(doctor_mod, "_DHH", "~/.spark/profiles/coder")

    blockers = doctor_mod._collect_mcp_blockers(
        {
            "mcp_servers": {
                "disabled-one": {"command": "npx", "enabled": False},
                "missing-transport": {},
                "missing-executable": {"command": str(tmp_path / "nope")},
            }
        }
    )

    summaries = [b.summary() for b in blockers]
    assert any("[mcp] disabled-one: disabled in config" in item for item in summaries)
    assert any(
        "[mcp] missing-transport: missing command or url - add mcp_servers.missing-transport.command or .url in ~/.spark/profiles/coder/config.yaml"
        == item
        for item in summaries
    )
    assert any("[mcp] missing-executable: missing executable" in item for item in summaries)


def test_collect_gateway_blockers_reports_enabled_platform_missing_required_token(monkeypatch):
    from gateway.config import GatewayConfig, Platform, PlatformConfig

    config = GatewayConfig(platforms={Platform.TELEGRAM: PlatformConfig(enabled=True)})
    monkeypatch.setattr("gateway.config.load_gateway_config", lambda: config)

    blockers = doctor_mod._collect_gateway_blockers({})

    assert any(
        b.area == "gateway"
        and b.name == "Telegram"
        and b.problem == "missing required TELEGRAM_BOT_TOKEN"
        and "spark gateway setup" in b.fix
        for b in blockers
    )


def test_collect_skill_blockers_reports_missing_skill_md_disabled_skill_and_external_dir(monkeypatch, tmp_path):
    spark_home = tmp_path / "spark-home"
    skills_dir = spark_home / "skills"
    disabled_dir = skills_dir / "disabled-skill"
    incomplete_dir = skills_dir / "incomplete-skill"
    disabled_dir.mkdir(parents=True)
    incomplete_dir.mkdir(parents=True)
    (disabled_dir / "SKILL.md").write_text(
        "---\nname: disabled-skill\ndescription: Disabled\n---\n# Disabled\n",
        encoding="utf-8",
    )
    (incomplete_dir / "README.md").write_text("missing skill manifest", encoding="utf-8")

    monkeypatch.setattr(doctor_mod, "SPARK_HOME", spark_home)
    monkeypatch.setattr(doctor_mod, "_DHH", "~/.spark/profiles/coder")

    blockers = doctor_mod._collect_skill_blockers(
        {
            "skills": {
                "disabled": ["disabled-skill", "missing-skill"],
                "external_dirs": [str(tmp_path / "missing-external")],
            }
        }
    )

    summaries = [b.summary() for b in blockers]
    assert any("[skill] disabled-skill: disabled in skills config" in item for item in summaries)
    assert any("[skill] missing-skill: listed in skills config but not installed" in item for item in summaries)
    assert any("[skill] incomplete-skill: skill directory is missing SKILL.md" in item for item in summaries)
    assert any("skills.external_dirs in ~/.spark/profiles/coder/config.yaml" in item for item in summaries)


def test_render_integration_blockers_adds_summary_issues(monkeypatch, capsys):
    blocker = doctor_mod.DoctorBlocker("mcp", "demo", "missing command", "add command")
    monkeypatch.setattr(doctor_mod, "_collect_integration_blockers", lambda: [blocker])

    issues = []
    doctor_mod._render_integration_blockers(issues)

    out = capsys.readouterr().out
    assert "Integration Blockers" in out
    assert "[mcp] demo: missing command" in out
    assert issues == ["[mcp] demo: missing command - add command"]
