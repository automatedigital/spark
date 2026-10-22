"""Bounded dashboard-only SKILL.md snapshots, separate from agent mutations.

One profile-wide file retains at most 20 edits (two <=1 MiB texts each).
The lock serializes dashboard read/save/append across threads and processes.
External editors and agent tools do not participate in this lock or history.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from core.spark_constants import get_spark_home

MAX_EDITS = 20
MAX_CONTENT_BYTES = 1_048_576
MAX_STORE_BYTES = MAX_EDITS * (MAX_CONTENT_BYTES * 12 + 1024)
_COVERAGE = "Dashboard SKILL.md edits only. External editors, agent edits and supporting files are excluded."
_THREAD_LOCK = threading.Lock()


@contextmanager
def _locked():
    home = get_spark_home()
    home.mkdir(parents=True, exist_ok=True)
    with _THREAD_LOCK, (home / "skill-history.lock").open("a+b") as lock:
        if os.name == "nt":
            import msvcrt
            lock.seek(0)
            deadline = time.monotonic() + 10
            while True:
                try:
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.05)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            if os.name == "nt" and os.fstat(lock.fileno()).st_size == 0:
                # Windows permits locks beyond EOF. Initialize only after
                # acquisition so simultaneous first writers cannot race, and
                # never read a byte another process may have locked.
                lock.write(b"0")
                lock.flush()
            yield home / "skill-history.json"
        finally:
            if os.name == "nt":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    if path.stat().st_size > MAX_STORE_BYTES:
        raise ValueError("Skill history exceeds its storage limit.")
    entries = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(entries, list) or len(entries) > MAX_EDITS:
        raise ValueError("Invalid skill history store.")
    for entry in entries:
        if (not isinstance(entry, dict)
                or not all(isinstance(entry.get(key), str) for key in ("id", "skill_id", "saved_at", "before", "after"))
                or any(len(entry[key].encode("utf-8")) > MAX_CONTENT_BYTES for key in ("before", "after"))):
            raise ValueError("Invalid skill history entry.")
    return entries


def _write(path: Path, entries: list[dict]) -> None:
    fd, name = tempfile.mkstemp(prefix=".skill-history-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(entries, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def read_history(skill_id: str) -> dict:
    with _locked() as path:
        entries = _read(path)
    return {"entries": [entry for entry in reversed(entries) if entry["skill_id"] == skill_id],
            "retention": MAX_EDITS, "coverage": _COVERAGE}


def save_with_history(skill_id: str, skill_dir: Path, content: str) -> dict:
    from tools.skill_manager_tool import save_skill_content

    with _locked() as path:
        # Fail before mutation when existing history is unreadable or too large.
        entries = _read(path)
        target = skill_dir / "SKILL.md"
        if target.stat().st_size > MAX_CONTENT_BYTES:
            return {"success": False, "error": "Existing SKILL.md exceeds the 1 MiB history limit."}
        before = target.read_text(encoding="utf-8")
        result = save_skill_content(skill_dir, content)
        if not result.get("success") or before == content:
            return result
        entry = {"id": uuid4().hex, "skill_id": skill_id,
                 "saved_at": datetime.now(UTC).isoformat(),
                 "before": before, "after": content}
        try:
            _write(path, (entries + [entry])[-MAX_EDITS:])
        except OSError:
            # A successful skill save must not be reported as failed/retryable.
            result["history_warning"] = "Skill saved, but its history snapshot could not be stored."
        return result
