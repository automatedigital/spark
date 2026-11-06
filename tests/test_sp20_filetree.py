"""SP20 real-filesystem paging and canonical-root contracts."""
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from spark_cli import workspace_routes as routes


def test_pages_are_stable_bounded_and_reach_all_entries(tmp_path):
    tmp_path = tmp_path / "repo"
    tmp_path.mkdir()
    for name in ["a", "b", ".hidden", *[f"file-{i:04}" for i in range(410)]]:
        (tmp_path / name).touch()
    (tmp_path / "folder").mkdir()
    cursor = ""
    found = []
    while True:
        page = routes._directory_page(tmp_path, "", True, 200, cursor)
        assert len(page["entries"]) <= 200
        found.extend(item["name"] for item in page["entries"])
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert found[0] == "folder"
    assert len(found) == len(set(found)) == 414
    assert ".hidden" not in [e["name"] for e in routes._directory_page(tmp_path, "", False, 200, "")["entries"]]


def test_linked_root_and_links_are_visible_without_traversal(tmp_path):
    root = tmp_path / "real"
    root.mkdir()
    (root / "nested").mkdir()
    (root / "nested" / "deep").touch()
    (root / "cycle").symlink_to(root, target_is_directory=True)
    (root / "external").symlink_to(tmp_path, target_is_directory=True)
    linked = tmp_path / "linked"
    linked.symlink_to(root, target_is_directory=True)
    page = routes._directory_page(linked, "", True, 200, "")
    assert len(page["entries"]) == 3
    assert all("children" not in entry for entry in page["entries"])
    assert {e["name"] for e in page["entries"] if e["symlink"]} == {"cycle", "external"}
    with pytest.raises(routes.HTTPException, match="400"):
        routes._directory_page(linked, "external", True, 200, "")
    assert routes._directory_page(linked, "nested", True, 200, "")["entries"][0]["path"] == "nested/deep"
    legacy = routes._tree_node(root / "external", root, 1, True)
    assert legacy["type"] == "file" and "children" not in legacy


def test_revision_cursor_rejects_changed_directory(tmp_path):
    for i in range(3):
        (tmp_path / str(i)).touch()
    page = routes._directory_page(tmp_path, "", False, 1, "")
    (tmp_path / "new").touch()
    with pytest.raises(routes.HTTPException) as error:
        routes._directory_page(tmp_path, "", False, 1, page["next_cursor"])
    assert error.value.status_code == 409


def test_route_bounds_and_traversal(tmp_path, monkeypatch):
    tmp_path = tmp_path / "repo"
    tmp_path.mkdir()
    monkeypatch.setattr(routes, "_project_dir", lambda slug: tmp_path)
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as client:
        prefix = "/api/workspace/projects/project/list"
        assert client.get(prefix, params={"paged": "true", "limit": 201}).status_code == 422
        assert client.get(prefix, params={"paged": "true", "path": "../"}).status_code == 400
        response = client.get(prefix, params={"paged": "true"})
        assert response.status_code == 200
        assert response.json()["entries"] == []


@pytest.mark.slow
def test_100k_initial_page_never_descends(tmp_path, monkeypatch):
    tmp_path = tmp_path / "repo"
    tmp_path.mkdir()
    for directory in range(100):
        folder = tmp_path / f"folder-{directory:03}"
        folder.mkdir()
        for file in range(1000):
            (folder / f"file-{file:04}").touch()
    original = routes.os.scandir
    reads = []

    def tracked(path):
        reads.append(Path(path))
        assert Path(path) == tmp_path
        return original(path)

    monkeypatch.setattr(routes.os, "scandir", tracked)
    page = routes._directory_page(tmp_path, "", False, 200, "")
    assert len(page["entries"]) == 100
    assert reads == [tmp_path]


def test_ignored_files_remain_reachable_and_malformed_cursor_is_rejected(tmp_path):
    (tmp_path / ".gitignore").write_text("ignored.txt\n")
    (tmp_path / "ignored.txt").touch()
    assert "ignored.txt" in [e["name"] for e in routes._directory_page(tmp_path, "", False, 200, "")["entries"]]
    with pytest.raises(routes.HTTPException) as error:
        routes._directory_page(tmp_path, "", False, 200, "!!!")
    assert error.value.status_code == 400
