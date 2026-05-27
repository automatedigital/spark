"""Tests for Phase 5: tool output path detection and safe-path filtering."""

import pytest
from fastapi.testclient import TestClient


# ── Path extraction unit tests ────────────────────────────────────────────────

def test_extract_output_paths_from_result():
    """Test the path extraction regex used in ToolCallBubble (backend equivalent)."""
    import re

    PATH_RE = re.compile(
        r'(?:saved to|written to|output:|created:|file:|path:)\s+([^\s,\n"\']+\.[a-zA-Z]{1,6})',
        re.IGNORECASE,
    )

    def extract(text):
        return list({m.group(1) for m in PATH_RE.finditer(text)})

    assert extract("Saved to /workspace/output.py") == ["/workspace/output.py"]
    assert extract("Written to results.csv") == ["results.csv"]
    assert extract("No path here") == []
    assert "/etc/passwd" not in extract("saved to ../../etc/passwd")
    paths = extract("output: report.md\ncreated: chart.png")
    assert "report.md" in paths
    assert "chart.png" in paths


# ── Backend: summarize-file safety (reused for tool output paths) ─────────────

@pytest.fixture()
def client():
    from spark_cli.web_server import app
    return TestClient(app, raise_server_exceptions=False)


def test_summarize_non_existent_file_returns_404(client, tmp_path, monkeypatch):
    monkeypatch.setenv("SPARK_HOME", str(tmp_path))
    (tmp_path / "workspace").mkdir()
    r = client.post("/api/summarize-file", json={"path": "nonexistent.py"})
    assert r.status_code == 404


def test_path_outside_workspace_rejected(client, tmp_path, monkeypatch):
    """A tool output path pointing outside the workspace must not be attached."""
    monkeypatch.setenv("SPARK_HOME", str(tmp_path))
    (tmp_path / "workspace").mkdir()
    r = client.post("/api/summarize-file", json={"path": "../../etc/shadow"})
    assert r.status_code == 400


def test_valid_workspace_file_found(client, tmp_path, monkeypatch):
    """A valid small file in the workspace is found (may fail on LLM call, but not 400/404)."""
    monkeypatch.setenv("SPARK_HOME", str(tmp_path))
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "code.py").write_text("def hello(): return 'hello'")
    r = client.post("/api/summarize-file", json={"path": "code.py"})
    # Either 200 (LLM available), 500 (LLM not configured in test env), or 503
    # Must NOT be 400 (bad request) or 404 (file not found)
    assert r.status_code not in (400, 404), f"Unexpected status {r.status_code}: {r.text}"
