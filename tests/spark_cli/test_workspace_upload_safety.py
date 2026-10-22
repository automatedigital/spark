"""Multipart upload containment, using only disposable profile/home storage."""

import os
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile

from spark_cli import workspace_routes as routes


@pytest.mark.skipif(os.name == "nt", reason="POSIX search-only ancestor permissions")
def test_upload_under_search_only_ancestor(tmp_path):
    ancestor = tmp_path / "search-only"
    project = ancestor / "project"
    project.mkdir(parents=True)
    ancestor.chmod(0o111)
    try:
        # Establish that the OS permits the original pathname operation.
        (project / "before.txt").write_bytes(b"before")
        with routes._upload_directory(project, "") as directory:
            routes._write_upload(directory, "after.txt", b"after")
        assert (project / "before.txt").read_bytes() == b"before"
        assert (project / "after.txt").read_bytes() == b"after"
    finally:
        ancestor.chmod(0o700)


@pytest.mark.skipif(os.name == "nt", reason="POSIX substitution at root-open boundary")
def test_upload_root_ancestor_swap_is_rejected(uploads, tmp_path, monkeypatch):
    client, root, project = uploads
    outside = tmp_path / "outside"
    (outside / "proj").mkdir(parents=True)
    sentinel = outside / "proj" / "note.txt"
    sentinel.write_bytes(b"outside")
    moved = root.with_name("pinned-workspace")
    real_open = os.open
    swapped = False

    def swap_ancestor(path, flags, *args, **kwargs):
        nonlocal swapped
        if Path(path) == project and not swapped:
            root.rename(moved)
            root.symlink_to(outside, target_is_directory=True)
            swapped = True
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", swap_ancestor)
    try:
        response = post(client, "project")
        assert response.status_code == 400
        assert swapped
        assert sentinel.read_bytes() == b"outside"
        assert not (moved / "proj" / "note.txt").exists()
    finally:
        if swapped:
            root.unlink()
            moved.rename(root)


@pytest.fixture
def uploads(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    root = routes.get_spark_home() / "workspace"
    project = root / "proj"
    project.mkdir(parents=True)
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as client:
        yield client, root, project


def post(client, scope, filename="note.txt", path="", content=b"new"):
    url = "/api/workspace/files/upload" if scope == "global" else (
        "/api/workspace/projects/proj/upload"
    )
    return client.post(url, params={"path": path}, files={"files": (filename, content)})


@pytest.mark.parametrize("scope", ["project", "global"])
@pytest.mark.parametrize("target_kind", ["external", "internal", "dangling"])
def test_rejects_final_symlink(uploads, tmp_path, scope, target_kind):
    client, root, project = uploads
    dest = project if scope == "project" else root / "files"
    dest.mkdir(exist_ok=True)
    target = (dest if target_kind == "internal" else tmp_path) / "sentinel.txt"
    if target_kind != "dangling":
        target.write_bytes(b"original")
    (dest / "note.txt").symlink_to(target)
    response = post(client, scope)
    assert response.status_code == 400
    assert "saved" not in response.json()
    if target_kind == "dangling":
        assert not target.exists()
    else:
        assert target.read_bytes() == b"original"


@pytest.mark.parametrize("scope", ["project", "global"])
@pytest.mark.parametrize("internal", [False, True])
def test_rejects_directory_symlink(uploads, tmp_path, scope, internal):
    client, root, project = uploads
    target = (project if internal else tmp_path) / "target"
    target.mkdir()
    (target / "note.txt").write_bytes(b"original")
    link = project / "linked" if scope == "project" else root / "files"
    link.symlink_to(target, target_is_directory=True)
    response = post(client, scope, path="linked")
    assert response.status_code == 400
    assert "saved" not in response.json()
    assert (target / "note.txt").read_bytes() == b"original"


@pytest.mark.parametrize("scope", ["project", "global"])
def test_normal_upload_keeps_existing_attachment(uploads, scope):
    client, root, project = uploads
    saved = []
    for content in (b"first", b"second"):
        response = post(client, scope, path="nested/deeper", content=content)
        assert response.status_code == 200
        item = response.json()["saved"][0]
        saved.append(item)
        assert item["filename"] == "note.txt"
        assert Path(item["absolute_path"]).read_bytes() == content
        base = project.resolve() if scope == "project" else root.resolve()
        assert base / item["path"] == Path(item["absolute_path"])
    assert saved[0]["path"] != saved[1]["path"]
    assert Path(saved[0]["absolute_path"]).read_bytes() == b"first"


@pytest.mark.parametrize("scope", ["project", "global"])
def test_filename_traversal_is_reduced_to_basename(uploads, tmp_path, scope):
    client, root, project = uploads
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_bytes(b"original")
    response = post(client, scope, filename="../../sentinel.txt")
    assert response.status_code == 200
    assert sentinel.read_bytes() == b"original"
    dest = project if scope == "project" else root / "files"
    assert (dest / "sentinel.txt").read_bytes() == b"new"


def test_directory_traversal_rejected(uploads, tmp_path):
    client, _, _ = uploads
    response = post(client, "project", path="../../escape")
    assert response.status_code == 400
    assert not (tmp_path / "escape").exists()


@pytest.mark.parametrize("scope", ["project", "global"])
def test_final_symlink_swapped_during_upload_read(uploads, tmp_path, monkeypatch, scope):
    client, root, project = uploads
    dest = project if scope == "project" else root / "files"
    dest.mkdir(exist_ok=True)
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_bytes(b"original")
    original_read = UploadFile.read

    async def swapped_read(self, *args):
        content = await original_read(self, *args)
        (dest / "note.txt").symlink_to(sentinel)
        return content

    monkeypatch.setattr(UploadFile, "read", swapped_read)
    response = post(client, scope)
    assert response.status_code == 400
    assert "saved" not in response.json()
    assert sentinel.read_bytes() == b"original"


@pytest.mark.parametrize("scope", ["project", "global"])
@pytest.mark.parametrize("collision", [False, True])
def test_directory_swap_at_write_cannot_redirect_upload(uploads, tmp_path, monkeypatch, scope, collision):
    client, root, project = uploads
    dest = project / "nested" if scope == "project" else root / "files"
    dest.mkdir()
    if collision:
        (dest / "note.txt").write_bytes(b"earlier attachment")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "note.txt").write_bytes(b"original")
    original_read = UploadFile.read

    async def swapped_read(self, *args):
        content = await original_read(self, *args)
        try:
            dest.rename(dest.with_name("pinned"))
        except PermissionError:
            # Windows directory handles deny renames for the upload lifetime.
            assert os.name == "nt"
        else:
            dest.symlink_to(outside, target_is_directory=True)
        return content

    monkeypatch.setattr(UploadFile, "read", swapped_read)
    response = post(client, scope, path="nested")
    assert response.status_code in (200, 400)
    assert (outside / "note.txt").read_bytes() == b"original"
    if response.status_code == 200:
        actual = dest if os.name == "nt" else dest.with_name("pinned")
        stored = Path(response.json()["saved"][0]["absolute_path"]).name
        assert (actual / stored).read_bytes() == b"new"
    if collision:
        actual = dest if os.name == "nt" else dest.with_name("pinned")
        assert (actual / "note.txt").read_bytes() == b"earlier attachment"


@pytest.mark.parametrize("scope", ["project", "global"])
@pytest.mark.skipif(os.name == "nt", reason="POSIX syscall boundary; Windows equivalent below")
def test_symlink_swap_at_final_open_is_rejected(uploads, tmp_path, monkeypatch, scope):
    client, root, project = uploads
    dest = project if scope == "project" else root / "files"
    dest.mkdir(exist_ok=True)
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_bytes(b"original")
    real_open = os.open
    swapped = False

    def swap_then_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if path == "note.txt" and flags & os.O_WRONLY:
            swapped = True
            (dest / "note.txt").symlink_to(sentinel)
        return real_open(path, flags, *args, **kwargs)

    # Keep the capability catalog accurate while instrumenting the syscall.
    monkeypatch.setattr(os, "supports_dir_fd", os.supports_dir_fd | {swap_then_open})
    monkeypatch.setattr(os, "open", swap_then_open)
    response = post(client, scope)
    assert swapped
    assert response.status_code == 400
    assert "saved" not in response.json()
    assert sentinel.read_bytes() == b"original"


@pytest.mark.parametrize("component", ["workspace", "project", "intermediate"])
def test_root_links_are_boundaries_but_nested_links_are_rejected(uploads, tmp_path, component):
    client, root, project = uploads
    target = tmp_path / "outside"
    target.mkdir()
    path = ""
    if component == "workspace":
        project.rmdir()
        root.rmdir()
        root.symlink_to(target, target_is_directory=True)
        (target / "proj").mkdir()
    elif component == "project":
        project.rmdir()
        project.symlink_to(target, target_is_directory=True)
    else:
        (project / "linked").symlink_to(target, target_is_directory=True)
        path = "linked/new/nested"
    response = post(client, "project", path=path)
    if component == "intermediate":
        assert response.status_code == 400
        assert "saved" not in response.json()
        assert not list(target.rglob("note.txt"))
        assert not (target / "new").exists()
    else:
        assert response.status_code == 200
        actual = target / "proj" if component == "workspace" else target
        assert (actual / "note.txt").read_bytes() == b"new"
        # Even an intentional linked root must not permit a link below it.
        outside = tmp_path / "sentinel.txt"
        outside.write_bytes(b"original")
        (actual / "escape.txt").symlink_to(outside)
        assert post(client, "project", filename="escape.txt").status_code == 400
        assert outside.read_bytes() == b"original"


@pytest.mark.parametrize("scope", ["project", "global"])
def test_intentionally_linked_profile_home(uploads, tmp_path, monkeypatch, scope):
    client, root, project = uploads
    home = root.parent
    actual = tmp_path / "actual-profile"
    home.rename(actual)
    home.symlink_to(actual, target_is_directory=True)
    assert post(client, scope, path="nested").status_code == 200
    dest = actual / "workspace" / ("proj/nested" if scope == "project" else "files")
    assert (dest / "note.txt").read_bytes() == b"new"


@pytest.mark.skipif(os.name != "nt", reason="native Windows handle contract")
@pytest.mark.parametrize("scope", ["project", "global"])
def test_windows_final_handle_rejects_swap(uploads, tmp_path, monkeypatch, scope):
    client, root, project = uploads
    dest = project if scope == "project" else root / "files"
    dest.mkdir(exist_ok=True)
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_bytes(b"original")
    real_open = routes._windows_upload_handle
    swapped = False

    def swap_then_open(path, *, directory, create_new=False):
        nonlocal swapped
        if not directory and create_new and not swapped:
            (dest / "note.txt").symlink_to(sentinel)
            swapped = True
        return real_open(path, directory=directory, create_new=create_new)

    monkeypatch.setattr(routes, "_windows_upload_handle", swap_then_open)
    assert post(client, scope).status_code == 400
    assert swapped
    assert sentinel.read_bytes() == b"original"


@pytest.mark.skipif(os.name != "nt", reason="native Windows junction contract")
def test_windows_nested_junction_rejected(uploads, tmp_path):
    client, _, project = uploads
    outside = tmp_path / "outside"
    outside.mkdir()
    subprocess.run(["cmd", "/c", "mklink", "/J", str(project / "linked"), str(outside)],
                   check=True, capture_output=True)
    assert post(client, "project", path="linked").status_code == 400
    assert not (outside / "note.txt").exists()


@pytest.mark.skipif(os.name != "nt", reason="native Windows ordinary upload without dir_fd")
def test_windows_does_not_require_posix_flags(uploads, monkeypatch):
    client, _, project = uploads
    monkeypatch.setattr(os, "supports_dir_fd", set())
    monkeypatch.delattr(os, "O_NOFOLLOW", raising=False)
    assert post(client, "project", path="nested").status_code == 200
    assert (project / "nested/note.txt").read_bytes() == b"new"


@pytest.mark.skipif(os.name != "nt", reason="native Windows drive/stream path syntax")
@pytest.mark.parametrize("path", ["C:escape", "C:/escape", "\\escape", ".. /escape", "nested.", "dir:stream"])
def test_windows_drive_and_root_relative_paths_rejected(uploads, path):
    client, _, _ = uploads
    assert post(client, "project", path=path).status_code == 400


@pytest.mark.skipif(os.name != "nt", reason="native Windows alternate data streams")
def test_windows_stream_filename_rejected(uploads):
    client, _, _ = uploads
    assert post(client, "project", filename="note.txt:stream").status_code == 400


@pytest.mark.parametrize("scope", ["project", "global"])
def test_directory_cannot_be_replaced_by_file_upload(uploads, scope):
    client, root, project = uploads
    dest = project if scope == "project" else root / "files"
    dest.mkdir(exist_ok=True)
    (dest / "note.txt").mkdir()
    (dest / "note.txt/keep.txt").write_bytes(b"original")
    response = post(client, scope)
    assert response.status_code == 400
    assert "saved" not in response.json()
    assert (dest / "note.txt/keep.txt").read_bytes() == b"original"


@pytest.mark.skipif(os.name == "nt", reason="POSIX FIFO contract")
@pytest.mark.parametrize("scope", ["project", "global"])
def test_fifo_is_rejected_without_blocking(uploads, scope):
    client, root, project = uploads
    dest = project if scope == "project" else root / "files"
    dest.mkdir(exist_ok=True)
    os.mkfifo(dest / "note.txt")
    # A reader lets the nonblocking write open succeed, exercising fstat before
    # truncation/write rather than merely rejecting an unopened pipe.
    reader = os.open(dest / "note.txt", os.O_RDONLY | os.O_NONBLOCK)
    try:
        response = post(client, scope)
        assert response.status_code == 400
        assert "saved" not in response.json()
        assert os.read(reader, 100) == b""
    finally:
        os.close(reader)


@pytest.mark.parametrize("scope", ["project", "global"])
def test_collision_retry_rejects_generated_symlink(uploads, tmp_path, monkeypatch, scope):
    client, root, project = uploads
    dest = project if scope == "project" else root / "files"
    dest.mkdir(exist_ok=True)
    (dest / "note.txt").write_bytes(b"earlier attachment")
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_bytes(b"outside")

    class CollisionID:
        hex = "collision"

    monkeypatch.setattr(routes.uuid, "uuid4", CollisionID)
    (dest / "note-collision.txt").symlink_to(sentinel)
    response = post(client, scope)
    assert response.status_code == 400
    assert "saved" not in response.json()
    assert (dest / "note.txt").read_bytes() == b"earlier attachment"
    assert sentinel.read_bytes() == b"outside"


@pytest.mark.parametrize("scope", ["project", "global"])
@pytest.mark.skipif(os.name == "nt", reason="POSIX final syscall race")
def test_collision_retry_final_swap_still_uses_exclusive_nofollow(uploads, tmp_path, monkeypatch, scope):
    client, root, project = uploads
    dest = project if scope == "project" else root / "files"
    dest.mkdir(exist_ok=True)
    (dest / "note.txt").write_bytes(b"earlier attachment")
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_bytes(b"outside")
    real_open = os.open
    swapped = False

    def swap_candidate(path, flags, *args, **kwargs):
        nonlocal swapped
        if str(path).startswith("note-") and flags & os.O_WRONLY:
            assert flags & os.O_EXCL
            assert kwargs["dir_fd"] is not None
            (dest / path).symlink_to(sentinel)
            swapped = True
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", swap_candidate)
    response = post(client, scope)
    assert swapped
    assert response.status_code == 400
    assert "saved" not in response.json()
    assert (dest / "note.txt").read_bytes() == b"earlier attachment"
    assert sentinel.read_bytes() == b"outside"


@pytest.mark.parametrize("scope", ["project", "global"])
@pytest.mark.skipif(os.name == "nt", reason="POSIX directory rename at final syscall")
def test_collision_retry_directory_swap_writes_only_pinned_inode(uploads, tmp_path, monkeypatch, scope):
    client, root, project = uploads
    dest = project / "nested" if scope == "project" else root / "files"
    dest.mkdir()
    (dest / "note.txt").write_bytes(b"earlier attachment")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "note.txt").write_bytes(b"outside")
    pinned = dest.with_name("pinned")
    real_open = os.open
    created = []

    def swap_directory(path, flags, *args, **kwargs):
        if str(path).startswith("note-") and flags & os.O_WRONLY:
            assert flags & os.O_EXCL
            dest.rename(pinned)
            dest.symlink_to(outside, target_is_directory=True)
            created.append(path)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", swap_directory)
    response = post(client, scope, path="nested")
    assert response.status_code == 400  # No false saved path through the new link.
    assert "saved" not in response.json()
    assert len(created) == 1
    assert (pinned / created[0]).read_bytes() == b"new"
    assert (pinned / "note.txt").read_bytes() == b"earlier attachment"
    assert list(outside.iterdir()) == [outside / "note.txt"]
    assert (outside / "note.txt").read_bytes() == b"outside"
