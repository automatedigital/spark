"""Tests for src/core/dream.py — the /dream pipeline + scheduler hook."""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def dream_mod():
    """Import the dream module fresh per test (uses isolated SPARK_HOME)."""
    from core import dream
    return dream


def _populate_sessions(spark_home: Path) -> None:
    """Insert two sessions with a few messages into the SessionDB."""
    from core.spark_state import SessionDB

    db = SessionDB(db_path=spark_home / "state.db")
    now = time.time()
    for i, sid in enumerate(("sesn_a", "sesn_b")):
        db._conn.execute(
            "INSERT INTO sessions (id, source, started_at, message_count, title) "
            "VALUES (?, ?, ?, ?, ?)",
            (sid, "cli", now - 100 + i, 2, f"session-{i}"),
        )
        for role, content in (("user", f"hi from {sid}"), ("assistant", f"hello back {sid}")):
            db._conn.execute(
                "INSERT INTO messages (session_id, role, content, timestamp) "
                "VALUES (?, ?, ?, ?)",
                (sid, role, content, now - 100 + i),
            )
    db._conn.commit()
    db._conn.close()


def _populate_facts(spark_home: Path) -> list[int]:
    """Insert a few facts into the holographic store. Returns fact ids."""
    from plugins.memory.holographic.store import MemoryStore

    store = MemoryStore(db_path=spark_home / "memory_store.db")
    ids = [
        store.add_fact("User prefers concise responses", category="preference"),
        store.add_fact("User is building Spark agent", category="project"),
        store.add_fact("User likes terse responses",     category="preference"),
    ]
    store.close()
    return ids


def _mock_llm(payload: dict):
    """Return a mock replacement for _call_synthesis_llm that returns the parsed payload dict."""
    def _fake_synth(*args, **kwargs):
        return payload

    return _fake_synth


# ---------------------------------------------------------------------------
# State + schedule
# ---------------------------------------------------------------------------

def test_first_run_state_initialized(dream_mod):
    state = dream_mod.get_state()
    assert state["first_run_completed"] is False
    assert state["last_run_at"] is None
    assert state["total_runs"] == 0


def test_configure_schedule_persists(dream_mod):
    dream_mod.configure_schedule(True, hour=4)
    sched = dream_mod.get_schedule()
    assert sched["enabled"] is True
    assert sched["hour"] == 4

    dream_mod.configure_schedule(False)
    assert dream_mod.get_schedule()["enabled"] is False


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def test_run_dream_dry_run_does_not_write(dream_mod, tmp_path, monkeypatch):
    spark_home = Path(tmp_path / "spark_test")
    _populate_sessions(spark_home)
    _populate_facts(spark_home)

    payload = {
        "insights": [{"content": "User uses zsh", "category": "fact", "tags": "shell", "confidence": 0.9}],
        "consolidations": [],
        "stale": [],
        "summary": "A short summary.",
    }
    with patch.object(dream_mod, "_call_synthesis_llm", _mock_llm(payload)):
        result = dream_mod.run_dream(dry_run=True)

    assert result.error is None
    assert result.sessions_scanned == 2
    assert result.facts_scanned == 3
    assert result.insights_added == 1  # counted from payload, but not actually written
    assert result.wiki_entry is None  # no write on dry run

    # State unchanged
    assert dream_mod.get_state()["first_run_completed"] is False


def test_run_dream_writes_wiki_entry_and_state(dream_mod, tmp_path, monkeypatch):
    spark_home = Path(tmp_path / "spark_test")
    _populate_sessions(spark_home)
    _populate_facts(spark_home)

    payload = {
        "insights": [
            {"content": "User prefers concise output", "category": "preference", "tags": "style", "confidence": 0.9},
            {"content": "User runs macOS", "category": "fact", "tags": "env", "confidence": 0.95},
        ],
        "consolidations": [],
        "stale": [],
        "summary": "## What I learned\n\nThe user values brevity.",
    }
    with patch.object(dream_mod, "_call_synthesis_llm", _mock_llm(payload)):
        result = dream_mod.run_dream()

    assert result.error is None
    assert result.insights_added == 2
    assert result.wiki_entry is not None
    assert result.wiki_entry.exists()

    entry = result.wiki_entry.read_text()
    assert entry.startswith("---")
    assert "title: Dream" in entry
    assert "User prefers concise output" in entry
    assert "What I learned" in entry

    # dreams/index.md should have a one-liner
    idx = result.wiki_entry.parent / "index.md"
    assert idx.exists()
    assert "insights" in idx.read_text()

    # State updated
    state = dream_mod.get_state()
    assert state["first_run_completed"] is True
    assert state["total_runs"] == 1
    assert state["last_run_at"] is not None


def test_run_dream_inserts_facts_with_dream_category(dream_mod, tmp_path, monkeypatch):
    spark_home = Path(tmp_path / "spark_test")
    _populate_sessions(spark_home)

    payload = {
        "insights": [
            {"content": "User cares about cache hit rate", "category": "preference", "tags": "perf", "confidence": 0.9},
        ],
        "consolidations": [],
        "stale": [],
        "summary": "ok",
    }
    with patch.object(dream_mod, "_call_synthesis_llm", _mock_llm(payload)):
        dream_mod.run_dream()

    from plugins.memory.holographic.store import MemoryStore
    store = MemoryStore(db_path=spark_home / "memory_store.db")
    facts = store.list_facts(limit=100)
    contents = [f["content"] for f in facts]
    tags = [f["tags"] for f in facts]
    store.close()

    assert any("cache hit rate" in c for c in contents)
    # Tag should include "dream" regardless of what category the LLM chose
    assert any("dream" in t for t in tags)


def test_consolidation_merges_facts(dream_mod, tmp_path):
    spark_home = Path(tmp_path / "spark_test")
    _populate_sessions(spark_home)
    fact_ids = _populate_facts(spark_home)

    # Merge "concise responses" + "terse responses" -> single fact
    a, _, c = fact_ids
    payload = {
        "insights": [],
        "consolidations": [
            {
                "merge_fact_ids": [a, c],
                "new_content": "User prefers concise, terse responses",
                "confidence": 0.9,
            }
        ],
        "stale": [],
        "summary": "merged duplicates",
    }
    with patch.object(dream_mod, "_call_synthesis_llm", _mock_llm(payload)):
        result = dream_mod.run_dream()

    assert result.consolidations_applied == 1

    from plugins.memory.holographic.store import MemoryStore
    store = MemoryStore(db_path=spark_home / "memory_store.db")
    facts = store.list_facts(limit=100)
    contents = [f["content"] for f in facts]
    store.close()

    assert any("concise, terse" in c for c in contents)
    # The two source facts should be merged — only one of them remains
    assert sum(1 for c in contents if c in ("User prefers concise responses", "User likes terse responses")) <= 1


def test_low_confidence_consolidations_skipped(dream_mod, tmp_path):
    spark_home = Path(tmp_path / "spark_test")
    _populate_sessions(spark_home)
    fact_ids = _populate_facts(spark_home)

    payload = {
        "insights": [],
        "consolidations": [
            {"merge_fact_ids": fact_ids[:2], "new_content": "merged", "confidence": 0.3}
        ],
        "stale": [],
        "summary": "low-conf",
    }
    with patch.object(dream_mod, "_call_synthesis_llm", _mock_llm(payload)):
        result = dream_mod.run_dream()

    assert result.consolidations_applied == 0


def test_stale_facts_queued_not_deleted(dream_mod, tmp_path):
    spark_home = Path(tmp_path / "spark_test")
    _populate_sessions(spark_home)
    fact_ids = _populate_facts(spark_home)

    payload = {
        "insights": [],
        "consolidations": [],
        "stale": [{"fact_id": fact_ids[1], "reason": "contradicted by recent sessions"}],
        "summary": "flagged",
    }
    with patch.object(dream_mod, "_call_synthesis_llm", _mock_llm(payload)):
        result = dream_mod.run_dream()

    assert result.stale_queued == 1

    # Fact still exists
    from plugins.memory.holographic.store import MemoryStore
    store = MemoryStore(db_path=spark_home / "memory_store.db")
    contents = [f["content"] for f in store.list_facts(limit=100)]
    store.close()
    assert "User is building Spark agent" in contents

    # Removal queued to file
    pending = json.loads(dream_mod._pending_removals_path().read_text())
    assert len(pending) == 1
    assert pending[0]["fact_id"] == fact_ids[1]


# ---------------------------------------------------------------------------
# JSON parsing robustness
# ---------------------------------------------------------------------------

def test_parse_llm_json_strips_fences(dream_mod):
    raw = '```json\n{"insights": [], "consolidations": [], "stale": [], "summary": "ok"}\n```'
    out = dream_mod._parse_llm_json(raw)
    assert out["summary"] == "ok"


def test_parse_llm_json_extracts_from_prose(dream_mod):
    raw = "Here is the JSON:\n{\"insights\": [], \"consolidations\": [], \"stale\": [], \"summary\": \"x\"}\nThanks!"
    out = dream_mod._parse_llm_json(raw)
    assert out["summary"] == "x"


def test_parse_llm_json_returns_defaults_on_garbage(dream_mod):
    out = dream_mod._parse_llm_json("not json at all")
    assert out["insights"] == []
    assert out["consolidations"] == []


# ---------------------------------------------------------------------------
# Scheduler tick
# ---------------------------------------------------------------------------

def test_scheduler_tick_noop_when_disabled(dream_mod):
    dream_mod.configure_schedule(False)
    with patch.object(dream_mod, "run_dream") as run:
        fired = dream_mod.scheduler_tick()
    assert fired is False
    run.assert_not_called()


def test_scheduler_tick_fires_when_due(dream_mod):
    dream_mod.configure_schedule(True, hour=0)  # any hour qualifies
    # never-run state — fires immediately
    fake_result = SimpleNamespace(error=None, insights_added=0, consolidations_applied=0, wiki_entry=None)
    with patch.object(dream_mod, "run_dream", return_value=fake_result) as run:
        fired = dream_mod.scheduler_tick()
    assert fired is True
    run.assert_called_once()


def test_scheduler_tick_does_not_fire_within_23h(dream_mod):
    dream_mod.configure_schedule(True, hour=0)
    state = dream_mod.get_state()
    state["last_run_at"] = time.time() - 3600  # 1 hour ago
    dream_mod._save_state(state)

    with patch.object(dream_mod, "run_dream") as run:
        fired = dream_mod.scheduler_tick()
    assert fired is False
    run.assert_not_called()


# ---------------------------------------------------------------------------
# Guard: Dream is explicit-only — it must NEVER auto-fire at session end
# (Phase 2b). It runs only via /dream or an opt-in daily schedule.
# ---------------------------------------------------------------------------

def test_dream_disabled_by_default(dream_mod):
    """A fresh install has no Dream schedule — it never runs unprompted."""
    assert dream_mod.get_schedule()["enabled"] is False


def test_memory_session_end_does_not_invoke_dream(dream_mod):
    """The memory provider's on_session_end must not trigger Dream.

    Session end auto-updates memory (holographic auto-extract + MEMORY.md flush),
    but Dream — the heavy synthesis pass — stays explicit. Guards against a future
    regression wiring run_dream/scheduler_tick into the session-end path.
    """
    from unittest.mock import MagicMock

    from plugins.memory.holographic import HolographicMemoryProvider

    provider = HolographicMemoryProvider(config={})
    provider._store = MagicMock()

    messages = [{"role": "user", "content": "I prefer concise replies"}]
    with patch.object(dream_mod, "run_dream") as run, \
         patch.object(dream_mod, "scheduler_tick") as tick:
        provider.on_session_end(messages)

    run.assert_not_called()
    tick.assert_not_called()


# ---------------------------------------------------------------------------
# Tool/skill usage feed into Dream synthesis (Phase 2b telemetry)
# ---------------------------------------------------------------------------

def test_format_tool_usage_empty(dream_mod):
    assert dream_mod._format_tool_usage([]) == "(no tool/skill usage recorded)"


def test_format_tool_usage_sorted_and_capped(dream_mod):
    usage = [{"tool_name": "read_file", "count": 9}, {"tool_name": "terminal", "count": 20}]
    out = dream_mod._format_tool_usage(usage, top=1)
    # Already sorted by caller, but format keeps order and caps to `top`
    assert "read_file: 9" in out
    assert "terminal" not in out  # capped at top=1


def test_gather_tool_usage_non_fatal(dream_mod):
    """A broken session db yields [] rather than raising."""
    assert dream_mod._gather_tool_usage(object(), None) == []


def test_run_dream_passes_usage_block_to_synthesis(dream_mod, tmp_path, monkeypatch):
    """run_dream feeds a tool-usage block into the synthesis LLM call."""
    monkeypatch.setenv("SPARK_HOME", str(tmp_path))
    _populate_sessions(tmp_path)
    _populate_facts(tmp_path)

    captured = {}

    def _fake_synth(facts_block, transcripts, usage_block="", memory_md_block=""):
        captured["usage_block"] = usage_block
        captured["memory_md_block"] = memory_md_block
        return {"insights": [], "consolidations": [], "stale": [], "summary": "ok"}

    monkeypatch.setattr(dream_mod, "_call_synthesis_llm", _fake_synth)
    dream_mod.run_dream(dry_run=True)

    assert "usage_block" in captured  # synthesis received the third argument
    assert "memory_md_block" in captured  # and the MEMORY.md block (fourth)


# ---------------------------------------------------------------------------
# MEMORY.md compaction proposal (Phase 2b) — proposal only, never auto-applied
# ---------------------------------------------------------------------------

def test_format_memory_md_empty(dream_mod):
    assert dream_mod._format_memory_md([]) == "(MEMORY.md is empty)"


def test_unified_memory_diff_shows_changes(dream_mod):
    before = ["uses zsh", "likes tabs", "likes tabs over spaces"]
    after = ["uses zsh", "prefers tabs over spaces"]
    diff = dream_mod._unified_memory_diff(before, after)
    joined = "\n".join(diff)
    assert any(line.startswith("-") for line in diff)
    assert any(line.startswith("+") for line in diff)
    assert "prefers tabs over spaces" in joined


def test_compaction_proposal_written_to_wiki_not_memory(dream_mod, tmp_path, monkeypatch):
    """A compaction proposal lands in the wiki entry; MEMORY.md is untouched."""
    monkeypatch.setenv("SPARK_HOME", str(tmp_path))
    _populate_sessions(tmp_path)
    _populate_facts(tmp_path)

    # Seed MEMORY.md with redundant entries
    mem_dir = tmp_path / "memories"
    mem_dir.mkdir(parents=True, exist_ok=True)
    memory_file = mem_dir / "MEMORY.md"
    original = "likes tabs\n§\nlikes tabs over spaces\n§\nuses zsh"
    memory_file.write_text(original)

    payload = {
        "insights": [], "consolidations": [], "stale": [],
        "memory_compaction": {
            "proposed": ["prefers tabs over spaces", "uses zsh"],
            "rationale": "Merged duplicate tab preferences.",
        },
        "summary": "compacted",
    }
    monkeypatch.setattr(dream_mod, "_call_synthesis_llm", _mock_llm(payload))

    result = dream_mod.run_dream()
    assert result.error is None
    # MEMORY.md itself is NOT rewritten by Dream
    assert memory_file.read_text() == original
    # The proposal + diff are in the wiki entry
    wiki_text = Path(result.wiki_entry).read_text()
    assert "MEMORY.md compaction (proposed" in wiki_text
    assert "prefers tabs over spaces" in wiki_text
    assert "Merged duplicate tab preferences." in wiki_text
