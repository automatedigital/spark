import json
import os
import re
import subprocess

import pytest
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from tools.artifact_store import (
    clear_artifacts,
    get_artifact,
    page_content,
    register_artifact,
    search_content,
    semantic_preview,
)
from tools.artifact_tool import _handle_artifact
from tools.budget_config import BudgetConfig
from tools.tool_result_storage import maybe_persist_tool_result


def setup_function():
    clear_artifacts()


def test_artifact_record_is_opaque_and_task_scoped():
    record = register_artifact(
        content="secret transport path is hidden",
        locator="/tmp/backend-only.txt",
        origin_tool="terminal",
        task_id="one",
    )
    assert record.handle.startswith("artifact://")
    assert record.backend_locator not in record.public_metadata().values()
    assert get_artifact(record.handle, "one") == record
    assert get_artifact(record.handle, "two") is None


def test_expired_artifact_is_removed(monkeypatch):
    now = int(time.time())
    monkeypatch.setattr("tools.artifact_store.time.time", lambda: now)
    record = register_artifact(
        content="x", locator="/tmp/x", origin_tool="terminal", ttl_seconds=1
    )
    monkeypatch.setattr("tools.artifact_store.time.time", lambda: now + 2)
    assert get_artifact(record.handle) is None


def test_unicode_pages_reassemble_exactly():
    content = "alpha\n" + "猫🙂" * 10_000 + "\nomega"
    chunks = []
    cursor = 0
    while True:
        page = page_content(content, cursor, 777)
        chunks.append(page["content"])
        if page["next_cursor"] is None:
            break
        cursor = page["next_cursor"]
    assert "".join(chunks) == content
    assert page["content_hash"].startswith("sha256:")


def test_empty_and_long_line_pagination_metadata():
    assert page_content("", 0, 10)["next_cursor"] is None
    page = page_content("z" * 50_000, 32_000, 32_000)
    assert page["offset"] == 32_000
    assert page["total_size"] == 50_000
    assert page["truncated"] is False


def test_search_returns_offsets_and_bounded_context():
    result = search_content("before ERROR one after\nERROR two", "error", limit=1, context=4)
    assert result["total_matches"] == 2
    assert len(result["matches"]) == 1
    assert result["matches"][0]["offset"] == 7


def test_semantic_preview_keeps_error_and_tail():
    content = "HEAD\n" + "noise\n" * 1_000 + "ERROR important\n" + "TAIL"
    preview, truncated = semantic_preview(content, 300)
    assert truncated is True
    assert "HEAD" in preview
    assert "ERROR important" in preview
    assert "TAIL" in preview


def test_artifact_pages_are_pinned_against_repersistence():
    page = "x" * 100_000
    result = maybe_persist_tool_result(
        page,
        "artifact_read",
        "page-1",
        env=object(),
        config=BudgetConfig(result_budget_tokens=1),
    )
    assert result == page


def test_binary_metadata_and_concurrent_pages_reassemble():
    content = json.dumps(
        {"mime": "application/octet-stream", "bytes": [0, 255], "note": "猫"},
        ensure_ascii=False,
    ) * 1_000
    offsets = list(range(0, len(content), 511))
    with ThreadPoolExecutor(max_workers=8) as pool:
        pages = list(pool.map(lambda offset: page_content(content, offset, 511), offsets))
    assert "".join(page["content"] for page in pages) == content
    assert len({page["content_hash"] for page in pages}) == 1


def test_artifact_handler_pages_and_searches_without_transport_path(monkeypatch):
    content = "header\n" + "noise\n" * 2_000 + "ERROR needle\ntail"
    record = register_artifact(
        content=content,
        locator="/backend/private/result.txt",
        origin_tool="terminal",
        task_id="task",
    )
    file_ops = SimpleNamespace(
        read_file_raw=lambda path: SimpleNamespace(content=content, error=None)
    )
    monkeypatch.setattr("tools.file_tools._get_file_ops", lambda task_id: file_ops)

    first = json.loads(_handle_artifact({"handle": record.handle, "limit": 100}, task_id="task"))
    second = json.loads(
        _handle_artifact(
            {"handle": record.handle, "offset": first["next_cursor"], "limit": 100},
            task_id="task",
        )
    )
    search = json.loads(
        _handle_artifact({"handle": record.handle, "query": "needle"}, task_id="task")
    )
    assert first["offset"] == 0
    assert second["offset"] == 100
    assert search["total_matches"] == 1
    assert "/backend/private" not in json.dumps(first)


def test_large_result_fixture_reduces_p95_inline_tokens_by_sixty_percent():
    class Env:
        def execute(self, command, timeout=30):
            return {"returncode": 0, "output": ""}

        def get_temp_dir(self):
            return "/tmp"

    env = Env()
    raw_results = [("line\n" * size) for size in range(9_000, 10_000, 10)]
    compact = [
        maybe_persist_tool_result(result, "terminal", f"r-{index}", env=env)
        for index, result in enumerate(raw_results)
    ]
    raw_p95 = sorted(len(item) for item in raw_results)[94]
    compact_p95 = sorted(len(item) for item in compact)[94]
    assert compact_p95 <= raw_p95 * 0.40
    assert all("Artifact handle:" in item for item in compact)


@pytest.mark.skipif(os.name == "nt", reason="POSIX sandbox shell transport")
@pytest.mark.parametrize("suffix", ["", "\n", "\n\n", "\r\n"])
def test_real_sandbox_artifact_round_trip_preserves_exact_content(tmp_path, monkeypatch, suffix):
    content = "猫 'quoted' %s $HOME $(touch injected) `touch injected`\nSPARK_PERSIST_EOF" + suffix
    class Env:
        def get_temp_dir(self):
            return str(tmp_path / "temp folder")
        def execute(self, command, timeout):
            result = subprocess.run(command, shell=True, cwd=tmp_path, capture_output=True, timeout=timeout)
            return {"returncode": result.returncode}
    persisted = maybe_persist_tool_result(content, "terminal", "round-trip", env=Env(), threshold=1)
    handle = re.search(r"Artifact handle: (artifact://[0-9a-f]+)", persisted).group(1)
    record = get_artifact(handle)
    assert record is not None
    from pathlib import Path
    assert Path(record.backend_locator).read_bytes() == content.encode("utf-8")
    assert not (tmp_path / "injected").exists()
    ops = SimpleNamespace(read_file_raw=lambda path: SimpleNamespace(
        content=Path(path).read_bytes().decode("utf-8"), error=None
    ))
    monkeypatch.setattr("tools.file_tools._get_file_ops", lambda task_id: ops)
    page = json.loads(_handle_artifact({"handle": handle, "limit": 32000}))
    assert page["content"] == content
    assert page["total_size"] == len(content)
    assert page["content_hash"] == record.content_hash


@pytest.mark.parametrize("query", [None, "replacement"])
def test_artifact_handler_rejects_changed_backing_content(monkeypatch, query):
    record = register_artifact(content="original", locator="/private/backend", origin_tool="terminal")
    ops = SimpleNamespace(read_file_raw=lambda path: SimpleNamespace(content="replacement", error=None))
    monkeypatch.setattr("tools.file_tools._get_file_ops", lambda task_id: ops)
    payload = json.loads(_handle_artifact({"handle": record.handle, "query": query}))
    assert "error" in payload
    assert "content" not in payload
    assert "matches" not in payload
    assert "/private/backend" not in json.dumps(payload)
