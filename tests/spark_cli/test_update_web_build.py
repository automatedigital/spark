from types import SimpleNamespace

from spark_cli import main as spark_main


def test_fatal_web_build_provisions_compatible_node(monkeypatch, tmp_path):
    web_dir = tmp_path / "web"
    web_dir.mkdir()
    (web_dir / "package.json").write_text("{}", encoding="utf-8")
    npm = tmp_path / "managed-node" / "bin" / "npm"
    npm.parent.mkdir(parents=True)
    npm.write_text("#!/bin/sh\n", encoding="utf-8")
    calls = []

    monkeypatch.setattr(
        spark_main, "_find_npm", lambda *, require_compatible=False: None
    )
    monkeypatch.setattr(spark_main, "_install_managed_node", lambda: str(npm))

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(spark_main.subprocess, "run", fake_run)

    assert spark_main._build_web_ui(web_dir, fatal=True) is True
    assert calls[0][0] == [str(npm), "install", "--silent"]
    assert calls[1][0] == [str(npm), "run", "build"]
    assert calls[0][1]["env"]["PATH"].split(":")[0] == str(npm.parent)


def test_fatal_web_build_fails_when_node_cannot_be_provisioned(
    monkeypatch, tmp_path
):
    web_dir = tmp_path / "web"
    web_dir.mkdir()
    (web_dir / "package.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        spark_main, "_find_npm", lambda *, require_compatible=False: None
    )
    monkeypatch.setattr(spark_main, "_install_managed_node", lambda: None)

    assert spark_main._build_web_ui(web_dir, fatal=True) is False
