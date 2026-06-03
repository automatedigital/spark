"""Near-duplicate dedup on memory write (holographic store)."""

from __future__ import annotations

import os
import tempfile

from plugins.memory.holographic.store import MemoryStore, _normalize_for_dedup


def test_normalize_collapses_variants():
    n = _normalize_for_dedup
    assert n("Joe likes coffee.") == n("joe likes  coffee")  # case, whitespace, trailing dot
    assert n("Remember this!") == n("remember this")
    assert n("Distinct fact") != n("Different fact")


def _store():
    db = os.path.join(tempfile.mkdtemp(), "m.db")
    return MemoryStore(db)


def test_near_duplicate_returns_existing_id():
    s = _store()
    a = s.add_fact("Joe likes coffee.", category="general")
    b = s.add_fact("joe likes  coffee", category="general")
    assert a == b  # deduped


def test_distinct_facts_get_new_ids():
    s = _store()
    a = s.add_fact("Joe likes coffee", category="general")
    c = s.add_fact("Joe likes tea", category="general")
    assert a != c


def test_dedup_is_global_by_content():
    # Matches the existing UNIQUE(content) scope: same content dedups regardless
    # of category.
    s = _store()
    a = s.add_fact("Joe likes coffee", category="general")
    d = s.add_fact("joe likes coffee.", category="prefs")
    assert a == d
