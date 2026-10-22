"""Read-only, profile-local saved cron documents (not execution receipts)."""

from __future__ import annotations

import errno
import heapq
import os
import re
import stat
from contextlib import contextmanager
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from core.spark_constants import get_spark_home

router = APIRouter()
MAX_READ_BYTES = 256 * 1024
_ID = re.compile(r"[0-9a-f]{12}")
_NAME = re.compile(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.md")


def saved_output_capability() -> dict:
    supported = (
        all(hasattr(os, flag) for flag in ("O_NOFOLLOW", "O_DIRECTORY", "O_NONBLOCK"))
        and os.open in os.supports_dir_fd
        and os.scandir in os.supports_fd
    )
    return {"supported": supported, "reason": None if supported else
            "Safe saved output access is unavailable on this platform"}


@router.get("/output-capability")
def get_output_capability():
    return saved_output_capability()


def _filename(value: str) -> str:
    if not _NAME.fullmatch(value):
        raise HTTPException(400, "Invalid saved output filename")
    try:
        datetime.strptime(value, "%Y-%m-%d_%H-%M-%S.md")
    except ValueError as exc:
        raise HTTPException(400, "Invalid saved output timestamp") from exc
    return value


@contextmanager
def _directory(job_id: str):
    if not _ID.fullmatch(job_id):
        raise HTTPException(400, "Invalid job ID")
    # Anchor every lookup to opened directories; reject symlinks at every level,
    # including replacements between listing and reading. Do not import jobs.py:
    # its paths are import-time constants, whereas this API follows the profile.
    descriptors = []
    try:
        capability = saved_output_capability()
        if not capability["supported"]:
            raise HTTPException(503, capability["reason"])
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        descriptors.append(os.open(get_spark_home(), flags))
        for part in ("cron", "output", job_id):
            descriptors.append(os.open(part, flags, dir_fd=descriptors[-1]))
        yield descriptors[-1]
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            raise HTTPException(404, "Saved output is missing or was pruned") from exc
        if exc.errno in (errno.ELOOP, errno.ENOTDIR, errno.EACCES, errno.EISDIR):
            raise HTTPException(403, "Saved output path is not accessible") from exc
        raise HTTPException(503, "Saved output is temporarily unavailable") from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


@router.get("/jobs/{job_id}/outputs")
def list_saved_outputs(job_id: str, limit: int = Query(20, ge=1, le=50), before: str | None = None):
    if before is not None:
        _filename(before)
    try:
        with _directory(job_id) as directory:
            def candidates():
                with os.scandir(directory) as entries:
                    for entry in entries:
                        try:
                            _filename(entry.name)
                            if (before is None or entry.name < before) and entry.is_file(follow_symlinks=False):
                                yield entry.name
                        except (HTTPException, FileNotFoundError):
                            continue
            # Bounded memory even when many saved files exist. Timestamps sort
            # lexically in newest-first order; keyset paging tolerates pruning.
            names = heapq.nlargest(limit + 1, candidates())
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        names = []
    return {"files": names[:limit], "next_before": names[limit - 1] if len(names) > limit else None}


@router.get("/jobs/{job_id}/outputs/{filename}")
def read_saved_output(job_id: str, filename: str):
    _filename(filename)
    with _directory(job_id) as directory:
        descriptor = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(descriptor, "rb") as document:
            if not stat.S_ISREG(os.fstat(document.fileno()).st_mode):
                raise HTTPException(403, "Saved output is not a regular file")
            data = document.read(MAX_READ_BYTES + 1)
    truncated = len(data) > MAX_READ_BYTES
    return {"filename": filename, "content": data[:MAX_READ_BYTES].decode("utf-8", errors="replace"),
            "truncated": truncated, "max_bytes": MAX_READ_BYTES}
