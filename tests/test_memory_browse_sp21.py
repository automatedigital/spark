"""SP21 browsing must not initialize, migrate, retrieve, or write memory."""
import hashlib
import sqlite3
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from spark_cli.memory_read import browse_facts, dream_reviews, read_dream
from spark_cli.memory_routes import register_memory_routes


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SPARK_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def client(home):
    app = FastAPI()
    register_memory_routes(app)
    return TestClient(app)


def database(home, count=45):
    path = home / "memory_store.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE facts(fact_id INTEGER PRIMARY KEY, content TEXT, category TEXT, created_at TEXT)")
        db.executemany("INSERT INTO facts VALUES (?, ?, ?, ?)", [(i, f"fact {i} literal % _ <script>alert(1)</script>", "work", "2026-11-06") for i in range(1, count + 1)])
    return path


def test_empty_and_markdown_only(client, home):
    assert client.get("/api/memory/facts").json()["status"] == "missing"
    assert not (home / "memory_store.db").exists()
    (home / "memories").mkdir()
    (home / "memories/MEMORY.md").write_text("Markdown fact")
    assert client.get("/api/memory").json()["targets"]["memory"]["entries"] == ["Markdown fact"]
    assert client.get("/api/memory/reviews").json()["status"] == "missing"


def test_bounded_pages_no_writes_or_provider_import(client, home, monkeypatch):
    path = database(home)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setitem(sys.modules, "plugins.memory.holographic", None)
    monkeypatch.setitem(sys.modules, "plugins.memory.mem0", None)
    first = client.get("/api/memory/facts").json()
    assert len(first["items"]) == 20
    assert first["items"][0]["source"] is None
    assert first["items"][0]["updated_at"] is None
    second = client.get(f'/api/memory/facts?after={first["next_after"]}').json()
    assert second["items"][0]["fact_id"] == 21
    assert len(second["items"]) == 20
    final = client.get(f'/api/memory/facts?after={second["next_after"]}').json()
    assert len(final["items"]) == 5 and final["next_after"] is None
    assert client.get("/api/memory/facts/1").json()["items"][0]["category"] == "work"
    assert client.get("/api/memory/facts/99").status_code == 404
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert not list(home.glob("memory_store.db-*"))
    assert not (home / "memories").exists()


@pytest.mark.parametrize("query", ["%", "_", "<script>", "' OR 1=1 --", '" MATCH ('])
def test_literal_queries(client, home, query):
    database(home)
    result = client.get("/api/memory/facts", params={"q": query}).json()
    assert result["status"] == "available"
    assert all(query.lower() in item["content"].lower() for item in result["items"])


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 51}, {"after": -1}, {"after": "bad"}, {"after": str(2**64)}, {"q": "a" * 201}])
def test_invalid_bounds(client, params):
    assert client.get("/api/memory/facts", params=params).status_code == 422


def test_older_empty_unavailable(home):
    path = database(home, 0)
    assert browse_facts()["items"] == []
    with sqlite3.connect(path) as db:
        db.execute("DROP TABLE facts")
        db.execute("CREATE TABLE facts(fact_id INTEGER PRIMARY KEY, content TEXT)")
        db.execute("INSERT INTO facts VALUES(1, 'old fact')")
    assert browse_facts()["items"][0]["category"] is None
    path.write_bytes(b"unavailable database")
    before = path.read_bytes()
    assert browse_facts()["status"] == "unavailable"
    assert path.read_bytes() == before
    path.unlink()
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE old_schema(foo TEXT)")
    assert browse_facts()["status"] == "unavailable"


def test_profile_and_custom_path_containment(home, tmp_path, monkeypatch):
    database(home)
    other = home / "other-profile"
    other.mkdir()
    monkeypatch.setenv("SPARK_HOME", str(other))
    assert browse_facts()["status"] == "missing"
    (other / "memory_store.db").symlink_to(home / "memory_store.db")
    assert browse_facts()["status"] == "unavailable"
    (other / "memory_store.db").unlink()
    (other / "config.yaml").write_text(f"plugins:\n  spark-memory-store:\n    db_path: {home / 'memory_store.db'}\n")
    assert browse_facts()["status"] == "unavailable"
    (other / "config.yaml").write_text("plugins:\n  spark-memory-store:\n    db_path: $SPARK_HOME/custom.db\n")
    path = database(other)
    path.rename(other / "custom.db")
    assert browse_facts()["status"] == "available"


def test_real_reviews_safe_paths_and_limits(client, home):
    root = home / "workspace/wiki/dreams"
    root.mkdir(parents=True)
    (root / "index.md").write_text("index")
    (root / "2026-review.md").write_text("# Explicit Dream\n<script>evil</script>")
    result = client.get("/api/memory/reviews").json()
    assert result["items"] == [{"name": "2026-review.md"}]
    assert client.get("/api/memory/reviews/2026-review.md").json()["content"].startswith("# Explicit Dream")
    with pytest.raises(Exception, match="Invalid review"):
        read_dream("../config.yaml")
    outside = home.parent / f"{home.name}-outside.md"
    outside.write_text("private")
    (root / "outside.md").symlink_to(outside)
    assert client.get("/api/memory/reviews/outside.md").status_code == 404
    (root / "outside.md").unlink()
    private = home / "private-config.md"
    private.write_text("synthetic private configuration")
    (root / "linked-review.md").symlink_to(private)
    assert client.get("/api/memory/reviews/linked-review.md").status_code == 404
    assert dream_reviews()["items"] == [{"name": "2026-review.md"}]
    (root / "linked-review.md").unlink()
    (root / "huge.md").write_text("a" * 65537)
    assert client.get("/api/memory/reviews/huge.md").status_code == 404
    for i in range(25):
        (root / f"review-{i:02}.md").write_text("review")
    first = dream_reviews()
    assert len(first["items"]) == 20
    assert len(dream_reviews(first["next_after"])["items"]) == 7


def test_payload_limit_stored_source_and_optional_provider(home):
    path = database(home, 0)
    (home / "config.yaml").write_text("memory:\n  provider: unavailable_optional_sdk\n")
    with sqlite3.connect(path) as db:
        db.execute("ALTER TABLE facts ADD COLUMN source TEXT")
        db.execute("INSERT INTO facts VALUES(1, ?, 'dream', NULL, 'stored-source')", ("x" * 20000,))
    page = browse_facts()
    assert len(page["items"][0]["content"]) == 16384
    assert page["items"][0]["content_truncated"]
    assert page["items"][0]["source"] == "stored-source"
    with sqlite3.connect(path) as db:
        db.execute("UPDATE facts SET content=?", ("x" * 1048577,))
    assert browse_facts()["status"] == "unavailable"


def test_markdown_symlink_rejected(client, home):
    outside = home.parent / f"{home.name}-memory.md"
    outside.write_text("outside profile")
    (home / "memories").mkdir()
    (home / "memories/MEMORY.md").symlink_to(outside)
    assert client.get("/api/memory").status_code == 403
