"""Native local file operations, including atomic writes and task CWD paths."""

import os
import stat
import subprocess

import pytest

from tools.file_operations import NativeFileOperations


class _LocalEnv:
    shell_family = "powershell"

    def __init__(self, cwd):
        self.cwd = str(cwd)


def test_native_write_is_atomic_and_reports_exact_bytes(tmp_path):
    ops = NativeFileOperations(_LocalEnv(tmp_path))
    content = "héllo\r\n"
    result = ops.write_file("nested folder/✓.txt", content)
    target = tmp_path / "nested folder" / "✓.txt"
    assert result.error is None
    assert result.bytes_written == len(content.encode("utf-8"))
    assert result.dirs_created is True
    assert target.read_bytes() == content.encode("utf-8")
    assert not list(target.parent.glob(".*.tmp"))


def test_native_relative_read_move_delete_uses_task_cwd(tmp_path):
    ops = NativeFileOperations(_LocalEnv(tmp_path))
    ops.write_file("source.txt", "one\ntwo\n")
    read = ops.read_file("source.txt")
    assert "one" in read.content and "two" in read.content
    moved = ops.move_file("source.txt", "destination.txt")
    assert moved.error is None
    assert (tmp_path / "destination.txt").exists()
    assert ops.delete_file("destination.txt").error is None


def test_native_symlink_escape_is_blocked(tmp_path):
    outside = tmp_path.parent / "spark-native-outside"
    outside.mkdir(exist_ok=True)
    link = tmp_path / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        return  # Symlinks may be unavailable on restricted Windows runners.
    result = NativeFileOperations(_LocalEnv(tmp_path)).write_file("link/escape.txt", "blocked")
    assert result.error and "escapes" in result.error


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
@pytest.mark.parametrize("mode", [0o755, 0o644])
@pytest.mark.parametrize("operation", ["write", "patch"])
def test_native_edit_preserves_mode(tmp_path, mode, operation):
    target = tmp_path / "run.sh"
    target.write_text("#!/bin/sh\nprintf 'old\\n'\n")
    target.chmod(mode)
    ops = NativeFileOperations(_LocalEnv(tmp_path))
    if operation == "write":
        result = ops.write_file("run.sh", "#!/bin/sh\nprintf 'new\\n'\n")
    else:
        result = ops.patch_replace("run.sh", "old", "new")
    assert result.error is None
    assert target.read_text() == "#!/bin/sh\nprintf 'new\\n'\n"
    assert stat.S_IMODE(target.stat().st_mode) == mode
    assert not list(tmp_path.glob(".*.tmp"))
    if mode == 0o755:
        executed = subprocess.run([str(target)], capture_output=True, text=True, check=True)
        assert executed.stdout == "new\n"


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
def test_native_new_file_keeps_private_default(tmp_path):
    result = NativeFileOperations(_LocalEnv(tmp_path)).write_file("new.txt", "new")
    assert result.error is None
    assert stat.S_IMODE((tmp_path / "new.txt").stat().st_mode) == 0o600


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
@pytest.mark.parametrize("failure", ["fchmod", "replace"])
def test_native_atomic_failure_preserves_target_and_cleans_temp(tmp_path, monkeypatch, failure):
    target = tmp_path / "run.sh"
    target.write_text("original")
    target.chmod(0o755)
    original_entries = set(tmp_path.iterdir())

    def fail(*args):
        raise OSError("injected failure")

    monkeypatch.setattr(f"tools.file_operations.os.{failure}", fail)
    result = NativeFileOperations(_LocalEnv(tmp_path)).write_file("run.sh", "replacement")
    assert "injected failure" in result.error
    assert target.read_text() == "original"
    assert stat.S_IMODE(target.stat().st_mode) == 0o755
    assert set(tmp_path.iterdir()) == original_entries
