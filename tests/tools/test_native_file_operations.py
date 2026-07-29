"""Native local file operations, including atomic writes and task CWD paths."""

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
