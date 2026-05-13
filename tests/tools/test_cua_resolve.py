"""Tests for cua-driver binary resolution (computer_use availability)."""

import sys

import pytest


@pytest.fixture
def darwin(monkeypatch):
    import platform

    monkeypatch.setattr(platform, "system", lambda: "Darwin")


def test_is_available_finds_cua_in_dot_local_bin(tmp_path, monkeypatch, darwin):
    monkeypatch.delenv("SPARK_CUA_DRIVER_BIN", raising=False)
    home = tmp_path / "home"
    home.mkdir()
    bin_dir = home / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    cua = bin_dir / "cua-driver"
    cua.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
    cua.chmod(0o755)
    monkeypatch.setenv("HOME", str(home))

    fake_py = tmp_path / "venv" / "bin" / "python3"
    fake_py.parent.mkdir(parents=True)
    fake_py.touch()
    monkeypatch.setattr(sys, "executable", str(fake_py))

    import tools.computer_use.cua_backend as cb

    monkeypatch.setattr(cb.shutil, "which", lambda _n: None)

    from tools.computer_use.cua_backend import is_available

    assert is_available() is True


def test_resolution_hint_uses_running_python_for_install(tmp_path, monkeypatch, darwin):
    fake_py = tmp_path / "conda" / "bin" / "python3"
    fake_py.parent.mkdir(parents=True)
    fake_py.touch()
    monkeypatch.setattr(sys, "executable", str(fake_py))

    import tools.computer_use.cua_backend as cb

    monkeypatch.setattr(cb.shutil, "which", lambda _n: None)

    hint = cb.cua_driver_resolution_hint()

    assert f"Spark Python: {fake_py}" in hint
    assert f"Install for this Spark: {fake_py} -m pip install cua-driver" in hint
