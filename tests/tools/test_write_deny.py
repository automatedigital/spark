"""Tests for _is_write_denied() — verifies deny list blocks sensitive paths on all platforms."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.file_operations import _is_write_denied


@pytest.mark.parametrize("credential", ["default_home", "changed_profile"])
def test_spark_credentials_remain_denied_across_profiles(tmp_path, credential):
    """Import under a synthetic profile without reloading shared app modules."""
    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    env["USERPROFILE"] = env["HOME"]
    env["SPARK_HOME"] = str(tmp_path / "initial-profile")
    env.pop("SPARK_WRITE_SAFE_ROOT", None)
    result = subprocess.run(
        [sys.executable, "-c", """
import json
import os
from pathlib import Path

assert Path.home() == Path(os.environ["HOME"])

from tools.file_operations import _is_write_denied

initial = Path(os.environ["SPARK_HOME"])
default = Path.home() / ".spark"
changed = initial.parent / "changed-profile"
os.environ["SPARK_HOME"] = str(changed)
credentials = {
    "default_home": default / ".env",
    "initial_profile": initial / ".env",
    "changed_profile": changed / ".env",
}
print(json.dumps({
    "denied": {name: _is_write_denied(path) for name, path in credentials.items()},
    "allowed": {
        str(path): not _is_write_denied(path)
        for path in [default / "config.yaml", changed / "config.yaml",
                     initial.parent / "project" / ".env"]
    },
    "credentials_exist": any(path.exists() for path in credentials.values()),
}))
"""],
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    state = json.loads(result.stdout)
    assert state["credentials_exist"] is False
    assert all(state["allowed"].values()), state
    assert state["denied"]["initial_profile"] is True
    assert state["denied"][credential] is True, state


class TestWriteDenyExactPaths:
    def test_etc_shadow(self):
        assert _is_write_denied("/etc/shadow") is True

    def test_etc_passwd(self):
        assert _is_write_denied("/etc/passwd") is True

    def test_etc_sudoers(self):
        assert _is_write_denied("/etc/sudoers") is True

    def test_ssh_authorized_keys(self):
        assert _is_write_denied("~/.ssh/authorized_keys") is True

    def test_ssh_id_rsa(self):
        path = os.path.join(str(Path.home()), ".ssh", "id_rsa")
        assert _is_write_denied(path) is True

    def test_ssh_id_ed25519(self):
        path = os.path.join(str(Path.home()), ".ssh", "id_ed25519")
        assert _is_write_denied(path) is True

    def test_netrc(self):
        path = os.path.join(str(Path.home()), ".netrc")
        assert _is_write_denied(path) is True

    def test_spark_env(self):
        path = os.path.join(str(Path.home()), ".spark", ".env")
        assert _is_write_denied(path) is True

    def test_shell_profiles(self):
        home = str(Path.home())
        for name in [".bashrc", ".zshrc", ".profile", ".bash_profile", ".zprofile"]:
            assert _is_write_denied(os.path.join(home, name)) is True, f"{name} should be denied"

    def test_package_manager_configs(self):
        home = str(Path.home())
        for name in [".npmrc", ".pypirc", ".pgpass"]:
            assert _is_write_denied(os.path.join(home, name)) is True, f"{name} should be denied"


class TestWriteDenyPrefixes:
    def test_ssh_prefix(self):
        path = os.path.join(str(Path.home()), ".ssh", "some_key")
        assert _is_write_denied(path) is True

    def test_aws_prefix(self):
        path = os.path.join(str(Path.home()), ".aws", "credentials")
        assert _is_write_denied(path) is True

    def test_gnupg_prefix(self):
        path = os.path.join(str(Path.home()), ".gnupg", "secring.gpg")
        assert _is_write_denied(path) is True

    def test_kube_prefix(self):
        path = os.path.join(str(Path.home()), ".kube", "config")
        assert _is_write_denied(path) is True

    def test_sudoers_d_prefix(self):
        assert _is_write_denied("/etc/sudoers.d/custom") is True

    def test_systemd_prefix(self):
        assert _is_write_denied("/etc/systemd/system/evil.service") is True


class TestWriteAllowed:
    def test_tmp_file(self):
        assert _is_write_denied("/tmp/safe_file.txt") is False

    def test_project_file(self):
        assert _is_write_denied("/home/user/project/main.py") is False

    def test_spark_config_not_env(self):
        path = os.path.join(str(Path.home()), ".spark", "config.yaml")
        assert _is_write_denied(path) is False
