"""Multipart upload containment, using only disposable profile/home storage."""

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

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
    stored_directory = dest

    async def swapped_read(self, *args):
        nonlocal stored_directory
        content = await original_read(self, *args)
        try:
            dest.rename(dest.with_name("pinned"))
        except PermissionError:
            # Windows may deny renames while directory handles are pinned.
            assert os.name == "nt"
        else:
            stored_directory = dest.with_name("pinned")
            dest.symlink_to(outside, target_is_directory=True)
        return content

    monkeypatch.setattr(UploadFile, "read", swapped_read)
    response = post(client, scope, path="nested")
    assert response.status_code in (200, 400)
    assert {p.relative_to(outside): p.read_bytes() for p in outside.rglob("*")} == {
        Path("note.txt"): b"original",
    }
    assert (outside / "note.txt").read_bytes() == b"original"
    if response.status_code == 200:
        stored = Path(response.json()["saved"][0]["absolute_path"]).name
        assert (stored_directory / stored).read_bytes() == b"new"
    if collision:
        assert (stored_directory / "note.txt").read_bytes() == b"earlier attachment"


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


@pytest.mark.parametrize("directory,create_new,access,share,disposition", [
    (True, False, 0x81, 1, 3),
    (False, True, 0x40000080, 1, 1),
    (False, False, 0x80, 3, 3),
])
def test_windows_upload_handle_access_contract(
    tmp_path, monkeypatch, directory, create_new, access, share, disposition,
):
    """Portable API contract only; native tests below prove OS enforcement."""
    import ctypes

    path = tmp_path / "target"

    def attributes(handle, kind, output, size):
        output._obj.attributes = 0x10 if directory else 0
        return True

    kernel = SimpleNamespace(
        CreateFileW=Mock(return_value=42), CloseHandle=Mock(),
        GetFileInformationByHandleEx=Mock(side_effect=attributes),
    )
    monkeypatch.setattr(ctypes, "WinDLL", Mock(return_value=kernel), raising=False)
    with monkeypatch.context() as platform_patch:
        platform_patch.setattr(routes.sys, "platform", "win32")
        assert routes._windows_upload_handle(
            path, directory=directory, create_new=create_new,
        ) == 42
    kernel.CreateFileW.assert_called_once_with(
        str(path), access, share, None, disposition, 0x02200000, None,
    )
    kernel.CloseHandle.assert_not_called()


@pytest.mark.skipif(os.name != "nt", reason="native Windows directory sharing contract")
@pytest.mark.parametrize("operation", ["rename", "write_handle"])
def test_windows_directory_handle_blocks_other_process_until_closed(tmp_path, operation):
    """Rename needs DELETE; generic-write opens also conflict with the pin."""
    import ctypes
    from ctypes import wintypes

    directory = tmp_path / "directory"
    directory.mkdir()
    moved = tmp_path / "moved"
    script = """
import ctypes
import os
import sys
from ctypes import wintypes
try:
    if sys.argv[1] == "rename":
        os.rename(sys.argv[2], sys.argv[3])
    else:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                           wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        create.restype = wintypes.HANDLE
        handle = create(sys.argv[2], 0x40000000, 7, None, 3, 0x02200000, None)
        if handle == wintypes.HANDLE(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        close = kernel.CloseHandle
        close.argtypes = [wintypes.HANDLE]
        close.restype = wintypes.BOOL
        assert close(handle)
except OSError as exc:
    print(exc.winerror)
else:
    print(0)
"""

    def attempt():
        result = subprocess.run(
            [sys.executable, "-c", script, operation, str(directory), str(moved)],
            check=True, capture_output=True, text=True, timeout=10,
        )
        return int(result.stdout.strip())

    handle = routes._windows_upload_handle(directory, directory=True)
    close = ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    try:
        assert attempt() == 32  # ERROR_SHARING_VIOLATION, not an unrelated denial.
        assert directory.is_dir()
        assert not moved.exists()
    finally:
        assert close(handle)
    assert attempt() == 0  # Same caller/operation must succeed once unpinned.
    assert (moved if operation == "rename" else directory).is_dir()


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

    def swap_then_open(path, *, directory, create_new=False, **kwargs):
        nonlocal swapped
        if not directory and create_new and not swapped:
            (dest / "note.txt").symlink_to(sentinel)
            swapped = True
        return real_open(path, directory=directory, create_new=create_new, **kwargs)

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


def _set_windows_mount_point(directory, target):
    """Actual metadata-only FSCTL contender; no mklink or GENERIC_WRITE shortcut."""
    import ctypes
    import struct
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    control = kernel.DeviceIoControl
    control.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                        wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                        wintypes.LPVOID]
    control.restype = wintypes.BOOL
    # MountPointReparseBuffer: substitute and print offsets are relative to
    # PathBuffer; lengths exclude the UTF-16 terminators. No symlink privilege.
    substitute = ("\\??\\" + str(target.resolve())).encode("utf-16-le")
    printed = str(target.resolve()).encode("utf-16-le")
    names = substitute + b"\0\0" + printed + b"\0\0"
    data = struct.pack("<HHHH", 0, len(substitute), len(substitute) + 2, len(printed)) + names
    payload = struct.pack("<IHH", 0xA0000003, len(data), 0) + data
    buffer = ctypes.create_string_buffer(payload)
    handle = create(str(directory), 0x100, 1, None, 3, 0x02200000, None)
    # Prove the FILE_WRITE_ATTRIBUTES-only contender was actually acquired.
    assert handle != wintypes.HANDLE(-1).value, ctypes.get_last_error()
    try:
        returned = wintypes.DWORD()
        if control(handle, 0x900A4, buffer, len(payload), None, 0,
                   ctypes.byref(returned), None):
            return 0
        return ctypes.get_last_error()
    finally:
        assert close(handle)


def _prove_windows_mount_point_control(tmp_path, outside):
    control = tmp_path / "fsctl-control"
    control.mkdir()
    try:
        assert _set_windows_mount_point(control, outside) == 0
        assert (control / "sentinel.txt").read_bytes() == b"outside"
    finally:
        control.rmdir()  # Remove the junction itself, never the target tree.


@pytest.mark.skipif(os.name != "nt", reason="native metadata-only reparse FSCTL")
def test_windows_metadata_only_reparse_contender(tmp_path):
    import ctypes
    from ctypes import wintypes

    directory = tmp_path / "directory"
    directory.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "sentinel.txt").write_bytes(b"outside")
    _prove_windows_mount_point_control(tmp_path, outside)
    close = ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    handle = routes._windows_upload_handle(directory, directory=True)
    try:
        result = _set_windows_mount_point(directory, outside)
        # Some filesystems may deny the FSCTL. Both successful mutation and a
        # concrete access/sharing denial are exercised, never skipped silently.
        assert result in (0, 5, 32), result
    finally:
        assert close(handle)
    if result == 0:
        assert (directory / "sentinel.txt").read_bytes() == b"outside"
    directory.rmdir()
    assert {p.name: p.read_bytes() for p in outside.iterdir()} == {"sentinel.txt": b"outside"}


@pytest.mark.skipif(os.name != "nt", reason="native metadata-only reparse upload boundary")
@pytest.mark.parametrize("scope", ["project", "global"])
@pytest.mark.parametrize("boundary", ["read", "final_open", "descent"])
def test_windows_metadata_reparse_cannot_escape(uploads, tmp_path, monkeypatch, scope, boundary):
    client, root, project = uploads
    dest = project / "nested" if scope == "project" else root / "files"
    dest.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "sentinel.txt").write_bytes(b"outside")
    _prove_windows_mount_point_control(tmp_path, outside)
    original_read = UploadFile.read
    original_open = routes._windows_upload_handle
    attempted = []

    def mutate():
        result = _set_windows_mount_point(dest, outside)
        assert result in (0, 5, 32), result
        attempted.append(result)

    async def read(self, *args):
        content = await original_read(self, *args)
        if boundary == "read":
            mutate()
        return content

    def open_handle(path, *, directory, create_new=False, **kwargs):
        if not attempted and (
            (boundary == "final_open" and create_new)
            or (boundary == "descent" and kwargs.get("open_if"))
        ):
            mutate()
        return original_open(path, directory=directory, create_new=create_new, **kwargs)

    monkeypatch.setattr(UploadFile, "read", read)
    monkeypatch.setattr(routes, "_windows_upload_handle", open_handle)
    response = post(client, scope, path="nested")
    assert len(attempted) == 1
    assert response.status_code in (200, 400), response.text
    assert {p.relative_to(outside): p.read_bytes() for p in outside.rglob("*")} == {
        Path("sentinel.txt"): b"outside",
    }
    if attempted[0] == 0:
        assert response.status_code == 400
        assert "saved" not in response.json()
    else:
        assert response.status_code == 200
        item = response.json()["saved"][0]
        assert Path(item["absolute_path"]).read_bytes() == b"new"


@pytest.mark.parametrize("directory,create_new,open_if,access,share,disposition,options", [
    (True, False, True, 0x100081, 1, 3, 0x200021),
    (True, False, False, 0x100081, 1, 1, 0x200021),
    (False, True, False, 0x40100080, 1, 2, 0x200060),
    (False, False, False, 0x100080, 3, 1, 0x200060),
])
def test_windows_relative_open_contract(
    monkeypatch, directory, create_new, open_if, access, share, disposition, options,
):
    import ctypes

    def create(result, desired, attributes, io, allocation, attrs, sharing, mode, flags, ea, size):
        obj = attributes._obj
        assert obj.RootDirectory == 123
        assert obj.ObjectName.contents.Buffer == "child"
        assert obj.ObjectName.contents.Length == 10
        assert obj.Attributes == 0x40
        assert (desired, sharing, mode, flags) == (access, share, disposition, options)
        result._obj.value = 42
        return 0

    def attributes(handle, kind, output, size):
        output._obj.attributes = 0x10 if directory else 0
        return True

    kernel = SimpleNamespace(
        CreateFileW=Mock(), CloseHandle=Mock(),
        GetFileInformationByHandleEx=Mock(side_effect=attributes),
    )
    native = SimpleNamespace(NtCreateFile=Mock(side_effect=create))
    monkeypatch.setattr(ctypes, "WinDLL", Mock(side_effect=[kernel, native]), raising=False)
    with monkeypatch.context() as patch:
        patch.setattr(routes.sys, "platform", "win32")
        assert routes._windows_upload_handle(
            Path("child"), directory=directory, create_new=create_new,
            open_if=open_if, root_handle=123,
        ) == 42
    kernel.CreateFileW.assert_not_called()
    kernel.CloseHandle.assert_not_called()
    native.NtCreateFile.assert_called_once()
