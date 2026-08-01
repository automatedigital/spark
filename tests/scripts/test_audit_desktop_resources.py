import json

from scripts.audit_desktop_resources import audit_resources


def _web_dist(tmp_path):
    web = tmp_path / "web_dist"
    (web / ".vite").mkdir(parents=True)
    (web / "assets").mkdir()
    (web / "index.html").write_text("<main></main>", encoding="utf-8")
    (web / "assets" / "index.js").write_text("export {};", encoding="utf-8")
    (web / ".vite" / "manifest.json").write_text(
        json.dumps({"index.html": {"file": "assets/index.js"}}),
        encoding="utf-8",
    )
    return web


def test_clean_desktop_resources_pass(tmp_path):
    sidecar = tmp_path / "sidecar"
    sidecar.mkdir()
    (sidecar / "spark-server").write_bytes(b"binary")
    report = audit_resources(sidecar, _web_dist(tmp_path))
    assert report["problems"] == []
    assert report["web_manifest_assets"] == 1


def test_cache_optional_module_and_missing_asset_fail(tmp_path):
    sidecar = tmp_path / "sidecar"
    leaked = sidecar / "_internal" / "torch" / "__pycache__"
    leaked.mkdir(parents=True)
    (leaked / "module.pyc").write_bytes(b"x")
    web = _web_dist(tmp_path)
    (web / "assets" / "index.js").unlink()
    report = audit_resources(sidecar, web)
    assert any("forbidden cache" in problem for problem in report["problems"])
    assert any("excluded optional module torch" in problem for problem in report["problems"])
    assert any("missing web asset" in problem for problem in report["problems"])
