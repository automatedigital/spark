"""Tests for the Artifacts REST API (src/spark_cli/artifacts_routes.py)."""

from __future__ import annotations

import pytest

from spark_cli.config import get_spark_home


@pytest.fixture
def client():
    fastapi = pytest.importorskip("fastapi")
    from starlette.testclient import TestClient

    from spark_cli.artifacts_routes import register_artifacts_routes

    app = fastapi.FastAPI()
    register_artifacts_routes(app)
    return TestClient(app)


def _make_project(slug: str):
    project = get_spark_home() / "workspace" / slug
    project.mkdir(parents=True, exist_ok=True)
    return project


def test_empty_state_zero_counts(client):
    body = client.get("/api/artifacts").json()
    assert body == {"artifacts": [], "counts": {"all": 0, "images": 0, "files": 0, "links": 0}}


def test_mixed_files_classified(client):
    project = _make_project("myproj")
    (project / "logo.png").write_bytes(b"\x89PNG")
    (project / "notes.txt").write_text("hello")
    (project / "assets").mkdir()
    (project / "assets" / "pic.JPG").write_bytes(b"jpg")
    (project / "site.url").write_text("[InternetShortcut]\nURL=https://example.com\n")

    body = client.get("/api/artifacts").json()
    assert body["counts"] == {"all": 4, "images": 2, "files": 1, "links": 1}

    by_name = {a["name"]: a for a in body["artifacts"]}
    assert by_name["logo.png"]["type"] == "image"
    assert by_name["logo.png"]["mime"] == "image/png"
    assert by_name["pic.JPG"]["type"] == "image"
    assert by_name["pic.JPG"]["path"] == "assets/pic.JPG"
    assert by_name["notes.txt"]["type"] == "file"
    assert by_name["site.url"]["type"] == "link"
    assert by_name["site.url"]["url"] == "https://example.com"

    # File/image urls point at the workspace raw-file endpoint
    assert by_name["logo.png"]["url"] == "/api/workspace/projects/myproj/raw-file?path=logo.png"
    assert (
        by_name["pic.JPG"]["url"]
        == "/api/workspace/projects/myproj/raw-file?path=assets%2Fpic.JPG"
    )

    # Common fields present
    art = by_name["notes.txt"]
    assert art["id"] == "myproj:notes.txt"
    assert art["project_slug"] == "myproj"
    assert art["project_name"] == "myproj"
    assert art["size"] == 5
    assert art["mtime"] > 0


def test_type_filter(client):
    project = _make_project("p1")
    (project / "a.png").write_bytes(b"png")
    (project / "b.txt").write_text("x")

    images = client.get("/api/artifacts", params={"type": "images"}).json()
    assert [a["name"] for a in images["artifacts"]] == ["a.png"]

    files = client.get("/api/artifacts", params={"type": "files"}).json()
    assert [a["name"] for a in files["artifacts"]] == ["b.txt"]

    links = client.get("/api/artifacts", params={"type": "links"}).json()
    assert links["artifacts"] == []


def test_counts_independent_of_filter(client):
    project = _make_project("p2")
    (project / "a.png").write_bytes(b"png")
    (project / "b.txt").write_text("x")

    expected = {"all": 2, "images": 1, "files": 1, "links": 0}
    for type_ in ("all", "images", "files", "links"):
        body = client.get("/api/artifacts", params={"type": type_}).json()
        assert body["counts"] == expected, type_


def test_limit_offset_and_mtime_sort(client):
    import os

    project = _make_project("p3")
    for i in range(5):
        f = project / f"f{i}.txt"
        f.write_text(str(i))
        os.utime(f, (1000 + i, 1000 + i))  # f4 newest

    body = client.get("/api/artifacts", params={"limit": 2}).json()
    assert [a["name"] for a in body["artifacts"]] == ["f4.txt", "f3.txt"]
    assert body["counts"]["all"] == 5

    body = client.get("/api/artifacts", params={"limit": 2, "offset": 2}).json()
    assert [a["name"] for a in body["artifacts"]] == ["f2.txt", "f1.txt"]
    # Counts still reflect the full set despite paging
    assert body["counts"]["all"] == 5

    body = client.get("/api/artifacts", params={"offset": 10}).json()
    assert body["artifacts"] == []


def test_dotfiles_and_junk_dirs_excluded(client):
    project = _make_project("p4")
    (project / ".hidden.png").write_bytes(b"png")
    (project / ".secrets").mkdir()
    (project / ".secrets" / "key.txt").write_text("k")
    for junk in ("node_modules", "__pycache__", ".git", "dist"):
        d = project / junk
        d.mkdir()
        (d / "junk.js").write_text("x")
    (project / "real.txt").write_text("ok")
    # Dot-directories at the workspace root are skipped too
    hidden_proj = get_spark_home() / "workspace" / ".trash"
    hidden_proj.mkdir(parents=True)
    (hidden_proj / "gone.png").write_bytes(b"png")

    body = client.get("/api/artifacts").json()
    assert [a["name"] for a in body["artifacts"]] == ["real.txt"]
    assert body["counts"] == {"all": 1, "images": 0, "files": 1, "links": 0}


def test_webloc_link_parsing(client):
    import plistlib

    project = _make_project("p5")
    (project / "ref.webloc").write_bytes(plistlib.dumps({"URL": "https://spark.dev"}))
    # Unparseable link file falls back to the raw-file url
    (project / "broken.url").write_text("not a shortcut")

    body = client.get("/api/artifacts", params={"type": "links"}).json()
    by_name = {a["name"]: a for a in body["artifacts"]}
    assert by_name["ref.webloc"]["url"] == "https://spark.dev"
    assert (
        by_name["broken.url"]["url"]
        == "/api/workspace/projects/p5/raw-file?path=broken.url"
    )
    assert body["counts"]["links"] == 2
