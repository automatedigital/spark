"""Upload response paths retain the bytes attached by each caller."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from spark_cli import workspace_routes as routes


@pytest.mark.parametrize("project_upload", [False, True])
def test_multibyte_collision_storage_name_has_portable_byte_budget(storage, project_upload):
    app, _, _ = storage
    filename = "😀" * 40 + "." + "😀" * 20
    assert len(filename.encode("utf-8")) == 241
    url = "/api/workspace/projects/proj/upload?path=files" if project_upload else "/api/workspace/files/upload"
    with TestClient(app) as client:
        first = client.post(url, files={"files": (filename, b"first")})
        second = client.post(url, files={"files": (filename, b"second")})
    assert first.status_code == second.status_code == 200
    old = first.json()["saved"][0]
    new = second.json()["saved"][0]
    assert old["filename"] == new["filename"] == filename
    assert old["absolute_path"] != new["absolute_path"]
    assert len(Path(new["absolute_path"]).name.encode("utf-8")) <= 240
    assert Path(old["absolute_path"]).read_bytes() == b"first"
    assert Path(new["absolute_path"]).read_bytes() == b"second"


@pytest.fixture
def storage(tmp_path, monkeypatch):
    for key in ("HOME", "USERPROFILE", "SPARK_HOME"):
        monkeypatch.setenv(key, str(tmp_path / key))
    root = tmp_path / "workspace"
    project = root / "proj"
    project.mkdir(parents=True)
    monkeypatch.setattr(routes, "_workspace_root", lambda: root)
    monkeypatch.setattr(routes, "_project_dir", lambda slug: project)
    app = FastAPI()
    routes.register_workspace_routes(app)
    return app, root, project


@pytest.mark.parametrize("project_upload", [False, True])
def test_same_name_uploads_preserve_bytes_across_requests_and_batch(storage, project_upload):
    app, root, project = storage
    base = project if project_upload else root
    url = "/api/workspace/projects/proj/upload?path=files/nested" if project_upload else "/api/workspace/files/upload"
    saved = []
    with TestClient(app) as client:
        for contents in ([b"first"], [b"second", b"third"]):
            response = client.post(url, files=[("files", ("report.txt", content)) for content in contents])
            assert response.status_code == 200, response.text
            saved.extend(response.json()["saved"])
        assert len({item["path"] for item in saved}) == 3
        for item, content in zip(saved, [b"first", b"second", b"third"], strict=True):
            assert item["filename"] == "report.txt"
            assert item["size"] == len(content)
            assert base / item["path"] == Path(item["absolute_path"])
            assert Path(item["absolute_path"]).read_bytes() == content
        # Project read API consumes exactly the path retained in a draft.
        if project_upload:
            response = client.get("/api/workspace/projects/proj/file", params={"path": saved[0]["path"]})
            assert response.json()["content"] == "first"


@pytest.mark.parametrize("project_upload", [False, True])
def test_concurrent_same_name_uploads_keep_each_callers_contents(storage, project_upload):
    app, _, _ = storage
    barrier = Barrier(6)
    url = "/api/workspace/projects/proj/upload?path=files" if project_upload else "/api/workspace/files/upload"

    def upload(index):
        with TestClient(app) as client:
            barrier.wait(timeout=10)
            content = f"chat-{index}".encode()
            response = client.post(url, files={"files": ("screenshot.png", content)})
            assert response.status_code == 200, response.text
            return response.json()["saved"][0], content

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(upload, range(6)))
    assert len({item["path"] for item, _ in results}) == 6
    for item, content in results:
        assert item["filename"] == "screenshot.png"
        assert Path(item["absolute_path"]).read_bytes() == content


def test_storage_collision_retry_does_not_replace_existing_candidate(tmp_path, monkeypatch):
    (tmp_path / "report.txt").write_bytes(b"original")
    (tmp_path / "report-collision.txt").write_bytes(b"prior collision")
    candidates = iter(["collision", "fresh"])

    class UploadID:
        @property
        def hex(self):
            return next(candidates)

    monkeypatch.setattr(routes.uuid, "uuid4", UploadID)
    with routes._upload_directory(tmp_path, "") as directory:
        stored_name = routes._save_new_upload(directory, "report.txt", b"new")
    dest = tmp_path / stored_name
    assert dest.name == "report-fresh.txt"
    assert dest.read_bytes() == b"new"
    assert (tmp_path / "report.txt").read_bytes() == b"original"
    assert (tmp_path / "report-collision.txt").read_bytes() == b"prior collision"


@pytest.mark.parametrize("path", ["", "files"])
def test_project_response_path_with_aliased_storage_root(storage, tmp_path, monkeypatch, path):
    app, root, project = storage
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(root, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks are unavailable on this platform")
    monkeypatch.setattr(routes, "_project_dir", lambda slug: alias / project.name)
    with TestClient(app) as client:
        response = client.post("/api/workspace/projects/proj/upload", params={"path": path}, files={"files": ("report.txt", b"original")})
    assert response.status_code == 200, response.text
    saved = response.json()["saved"][0]
    assert saved["path"] == (f"{path}/report.txt" if path else "report.txt")
    assert Path(saved["absolute_path"]).read_bytes() == b"original"


def test_exhausted_collisions_do_not_overwrite(tmp_path, monkeypatch):
    (tmp_path / "report.txt").write_bytes(b"original")
    (tmp_path / "report-collision.txt").write_bytes(b"prior collision")

    class CollisionID:
        hex = "collision"

    monkeypatch.setattr(routes.uuid, "uuid4", CollisionID)
    with routes._upload_directory(tmp_path, "") as directory:
        with pytest.raises(routes.HTTPException) as error:
            routes._save_new_upload(directory, "report.txt", b"new")
    assert error.value.status_code == 409
    assert (tmp_path / "report.txt").read_bytes() == b"original"
    assert (tmp_path / "report-collision.txt").read_bytes() == b"prior collision"


def test_explicit_project_put_can_replace_file(storage):
    app, _, project = storage
    with TestClient(app) as client:
        saved = client.post("/api/workspace/projects/proj/upload", files={"files": ("report.txt", b"original")}).json()["saved"][0]
        response = client.put("/api/workspace/projects/proj/file", params={"path": saved["path"]}, json={"content": "deliberate edit"})
    assert response.status_code == 200, response.text
    assert (project / saved["path"]).read_bytes() == b"deliberate edit"
