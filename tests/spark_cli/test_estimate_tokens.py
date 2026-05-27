"""Tests for POST /api/estimate-tokens endpoint."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from spark_cli.web_server import app
    return TestClient(app)


def test_empty_request_returns_zeros(client):
    r = client.post("/api/estimate-tokens", json={})
    assert r.status_code == 200
    data = r.json()
    assert data["prompt_tokens"] == 0
    assert data["attached_tokens"] == 0
    assert data["pinned_tokens"] == 0
    assert data["history_tokens"] == 0
    assert data["total_tokens"] == 0
    assert data["context_window"] > 0
    assert data["warning"] is None


def test_prompt_only_nonzero(client):
    r = client.post("/api/estimate-tokens", json={"prompt": "Hello world, this is a test prompt."})
    assert r.status_code == 200
    data = r.json()
    assert data["prompt_tokens"] > 0
    assert data["total_tokens"] == data["prompt_tokens"]


def test_brief_adds_pinned_tokens(client):
    r = client.post("/api/estimate-tokens", json={"brief": "This is a session brief with some context."})
    assert r.status_code == 200
    data = r.json()
    assert data["pinned_tokens"] > 0


def test_context_item_full_content_adds_tokens(client, tmp_path):
    """A full-content context item with inline content increases attached_tokens."""
    content = "x " * 500  # ~500 tokens
    r = client.post("/api/estimate-tokens", json={
        "context_items": [{
            "id": "abc",
            "type": "file",
            "inclusion_mode": "full",
            "content": content,
            "scope": "one_turn",
            "size_bytes": len(content),
        }]
    })
    assert r.status_code == 200
    data = r.json()
    assert data["attached_tokens"] > 100


def test_path_only_item_costs_only_path_tokens(client):
    r = client.post("/api/estimate-tokens", json={
        "context_items": [{
            "id": "xyz",
            "type": "file",
            "source_path": "short/path.py",
            "inclusion_mode": "path_only",
            "scope": "one_turn",
            "size_bytes": 0,
        }]
    })
    assert r.status_code == 200
    data = r.json()
    # path_only should only cost a few tokens for the path string
    assert data["attached_tokens"] < 20


def test_warning_none_for_small_payload(client):
    r = client.post("/api/estimate-tokens", json={"prompt": "hi"})
    assert r.status_code == 200
    assert r.json()["warning"] is None


def test_warning_triggered_near_limit(client):
    """A very large prompt should trigger a warning."""
    big = "word " * 180_000  # roughly 180K tokens >> 80% of 200K
    r = client.post("/api/estimate-tokens", json={"prompt": big})
    assert r.status_code == 200
    data = r.json()
    assert data["warning"] in ("compression_likely", "limit_exceeded")


def test_buckets_present(client):
    r = client.post("/api/estimate-tokens", json={"prompt": "test"})
    assert r.status_code == 200
    buckets = r.json()["buckets"]
    labels = [b["label"] for b in buckets]
    assert "Prompt" in labels
    assert "Attached" in labels
    assert "History" in labels
    assert "Brief" in labels


def test_total_equals_sum_of_buckets(client):
    r = client.post("/api/estimate-tokens", json={
        "prompt": "hello world",
        "brief": "brief text here",
    })
    assert r.status_code == 200
    d = r.json()
    assert d["total_tokens"] == d["prompt_tokens"] + d["attached_tokens"] + d["pinned_tokens"] + d["history_tokens"]
