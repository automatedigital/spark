"""Windows-native shell contract tests (run on non-Windows via controlled mocks)."""

import base64
from unittest.mock import MagicMock, patch

from tools.environments import local as local_module
from tools.environments.base import BaseEnvironment


def test_windows_shell_prefers_pwsh_and_never_bash(monkeypatch):
    monkeypatch.setattr(local_module, "_IS_WINDOWS", True)
    monkeypatch.setattr(local_module.shutil, "which", lambda name: r"C:\Program Files\PowerShell\7\pwsh.exe" if name == "pwsh" else None)
    assert local_module._find_shell().lower().endswith("pwsh.exe")


def test_windows_shell_falls_back_to_inbox_powershell(monkeypatch, tmp_path):
    monkeypatch.setattr(local_module, "_IS_WINDOWS", True)
    monkeypatch.setattr(local_module.shutil, "which", lambda _name: None)
    candidate = tmp_path / "powershell.exe"
    candidate.write_bytes(b"")
    monkeypatch.setenv("WINDIR", str(tmp_path))
    # The resolver constructs System32/WindowsPowerShell/v1.0/powershell.exe.
    nested = tmp_path / "System32" / "WindowsPowerShell" / "v1.0"
    nested.mkdir(parents=True)
    candidate.rename(nested / "powershell.exe")
    assert local_module._find_windows_shell().endswith("powershell.exe")


def test_windows_workdir_accepts_drive_unc_and_spaces(monkeypatch):
    monkeypatch.setattr(local_module, "_IS_WINDOWS", True)
    from tools import terminal_tool
    monkeypatch.setattr(terminal_tool.platform, "system", lambda: "Windows")
    assert terminal_tool._validate_workdir(r"C:\Users\Test User\project") is None
    assert terminal_tool._validate_workdir(r"\\server\share\project folder") is None
    assert terminal_tool._validate_workdir(r"C:\Users\Test User\project; whoami")


class _PowerShellEnvironment(BaseEnvironment):
    shell_family = "powershell"

    def _run_bash(self, *args, **kwargs):
        raise AssertionError("not needed for wrapper tests")

    def cleanup(self):
        pass


def test_powershell_wrapper_persists_cwd_and_env_without_posix_commands(tmp_path):
    env = _PowerShellEnvironment(str(tmp_path), 30)
    env._snapshot_ready = True
    script = env._wrap_command("Set-Location 'next'; $env:SPARK_TEST='✓'; Write-Output 'λ'", str(tmp_path))
    assert "Set-Location -LiteralPath" in script
    assert "ConvertFrom-Json" in script
    assert "source " not in script
    assert "export " not in script
    assert "pwd" not in script
    assert env._cwd_marker in script
    env.cleanup()


def test_windows_command_launch_uses_encoded_utf16(monkeypatch, tmp_path):
    monkeypatch.setattr(local_module, "_IS_WINDOWS", True)
    monkeypatch.setattr(local_module, "_find_windows_shell", lambda: r"C:\Program Files\PowerShell\7\pwsh.exe")
    env = local_module.LocalEnvironment(cwd=str(tmp_path), timeout=10)
    # init_session is intentionally mocked out; inspect a direct launch.
    proc = MagicMock()
    proc.pid = 123
    with patch.object(local_module.subprocess, "Popen", return_value=proc) as popen:
        env._run_bash("Write-Output '✓'", timeout=10)
    args = popen.call_args.args[0]
    assert "-EncodedCommand" in args
    encoded = args[args.index("-EncodedCommand") + 1]
    assert base64.b64decode(encoded).decode("utf-16le") == "Write-Output '✓'"
    env.cleanup()
