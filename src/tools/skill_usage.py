"""Skill usage tracking — lightweight sidecar for ~/.spark/skills/.usage.json.

Records every time a skill is loaded into the system prompt (use), viewed by
the agent (view), or patched (patch). Also tracks provenance (agent-created
vs. bundled/hub) and lifecycle state (active / stale / archived).

All writes are atomic (tempfile + os.replace) with cross-process file locking
so concurrent gateway workers don't corrupt the sidecar.

Public interface:
    bump_use(name)        — called when a skill appears in the system prompt
    bump_view(name)       — called when skill_view() succeeds
    bump_patch(name)      — called when skill_manage patch/edit succeeds
    mark_agent_created(name)  — called when skill_manage create succeeds
    set_state(name, state)    — set lifecycle state (STATE_ACTIVE/STALE/ARCHIVED)
    set_pinned(name, bool)    — pin a skill to prevent curator auto-transitions
    archive_skill(name)       — shortcut: set state=archived
    is_agent_created(name)    — True if the skill was created by the agent
    agent_created_report()    — list of dicts for curator
    get_skill_record(name)    — raw record dict or None
    all_records()             — all records as {name: record}
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

STATE_ACTIVE = "active"
STATE_STALE = "stale"
STATE_ARCHIVED = "archived"

_SIDECAR_FILENAME = ".usage.json"
_LOCK_FILENAME = ".usage.json.lock"


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _skills_dir() -> Path:
    from core.spark_constants import get_spark_home
    return get_spark_home() / "skills"


def _sidecar_path() -> Path:
    return _skills_dir() / _SIDECAR_FILENAME


def _lock_path() -> Path:
    return _skills_dir() / _LOCK_FILENAME


# ---------------------------------------------------------------------------
# Cross-process file locking
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def _file_lock():
    """Acquire an exclusive cross-process lock on the sidecar file."""
    lock_file = _lock_path()
    try:
        lock_file.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    try:
        fd = open(str(lock_file), "w")
    except OSError:
        yield  # best-effort: proceed without lock rather than crashing
        return

    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(fd.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    except OSError:
        yield  # best-effort
    finally:
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(fd.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            fd.close()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Raw load / save
# ---------------------------------------------------------------------------

def _load_raw() -> Dict[str, Any]:
    path = _sidecar_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as e:
        logger.debug("skill_usage: failed to read sidecar: %s", e)
        return {}


def _save_raw(data: Dict[str, Any]) -> None:
    path = _sidecar_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=str(path.parent), prefix=".usage_", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, sort_keys=True, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception as e:
        logger.debug("skill_usage: failed to write sidecar: %s", e, exc_info=True)


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_record() -> Dict[str, Any]:
    return {
        "created_by": None,
        "state": STATE_ACTIVE,
        "pinned": False,
        "use_count": 0,
        "view_count": 0,
        "patch_count": 0,
        "created_at": None,
        "last_used_at": None,
        "last_viewed_at": None,
        "last_patched_at": None,
        "archived_at": None,
    }


def _ensure_record(data: Dict[str, Any], name: str) -> Dict[str, Any]:
    """Return the record for *name*, creating a default one if missing."""
    if name not in data or not isinstance(data[name], dict):
        data[name] = _default_record()
    return data[name]


# ---------------------------------------------------------------------------
# Activity helpers (for curator)
# ---------------------------------------------------------------------------

def activity_count(record: Dict[str, Any]) -> int:
    return (
        int(record.get("use_count") or 0)
        + int(record.get("view_count") or 0)
        + int(record.get("patch_count") or 0)
    )


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None


def latest_activity_at(record: Dict[str, Any]) -> Optional[datetime]:
    """Return the most recent activity timestamp (use/view/patch), not created_at."""
    candidates = [
        _parse_iso(record.get("last_used_at")),
        _parse_iso(record.get("last_viewed_at")),
        _parse_iso(record.get("last_patched_at")),
    ]
    valid = [t for t in candidates if t is not None]
    return max(valid) if valid else None


# ---------------------------------------------------------------------------
# Public write API (all best-effort, never raise)
# ---------------------------------------------------------------------------

def _bump(name: str, field_count: str, field_ts: str) -> None:
    """Generic bump for use/view/patch counters."""
    if not name:
        return
    try:
        with _file_lock():
            data = _load_raw()
            rec = _ensure_record(data, name)
            rec[field_count] = int(rec.get(field_count) or 0) + 1
            rec[field_ts] = _now_iso()
            _save_raw(data)
    except Exception as e:
        logger.debug("skill_usage.bump failed for %s: %s", name, e)


def bump_use(name: str) -> None:
    """Record that *name* was included in the agent's system prompt."""
    _bump(name, "use_count", "last_used_at")


def bump_view(name: str) -> None:
    """Record that the agent called skill_view(*name*)."""
    _bump(name, "view_count", "last_viewed_at")


def bump_patch(name: str) -> None:
    """Record that skill_manage patch/edit was applied to *name*."""
    _bump(name, "patch_count", "last_patched_at")


def mark_agent_created(name: str) -> None:
    """Mark *name* as agent-created and seed its initial record."""
    if not name:
        return
    try:
        with _file_lock():
            data = _load_raw()
            rec = _ensure_record(data, name)
            rec["created_by"] = "agent"
            if not rec.get("created_at"):
                rec["created_at"] = _now_iso()
            _save_raw(data)
    except Exception as e:
        logger.debug("skill_usage.mark_agent_created failed for %s: %s", name, e)


def set_state(name: str, state: str) -> None:
    """Set the lifecycle state for *name*. Use STATE_* constants."""
    if not name:
        return
    try:
        with _file_lock():
            data = _load_raw()
            rec = _ensure_record(data, name)
            rec["state"] = state
            if state == STATE_ARCHIVED and not rec.get("archived_at"):
                rec["archived_at"] = _now_iso()
            _save_raw(data)
    except Exception as e:
        logger.debug("skill_usage.set_state failed for %s: %s", name, e)


def set_pinned(name: str, pinned: bool) -> None:
    """Pin or unpin a skill to protect it from curator auto-transitions."""
    if not name:
        return
    try:
        with _file_lock():
            data = _load_raw()
            rec = _ensure_record(data, name)
            rec["pinned"] = bool(pinned)
            _save_raw(data)
    except Exception as e:
        logger.debug("skill_usage.set_pinned failed for %s: %s", name, e)


def archive_skill(name: str) -> Tuple[bool, str]:
    """Shortcut: set state to archived. Returns (ok, message)."""
    try:
        set_state(name, STATE_ARCHIVED)
        return True, f"skill '{name}' archived"
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Public read API
# ---------------------------------------------------------------------------

def get_skill_record(name: str) -> Optional[Dict[str, Any]]:
    """Return the usage record for *name*, or None if not tracked."""
    data = _load_raw()
    return data.get(name)


def all_records() -> Dict[str, Any]:
    """Return all tracked records as {name: record}."""
    return _load_raw()


def is_agent_created(name: str) -> bool:
    """True when the skill was created by the agent (not bundled/hub)."""
    rec = get_skill_record(name)
    if rec is None:
        return False
    return rec.get("created_by") == "agent"


def agent_created_report() -> List[Dict[str, Any]]:
    """Return a list of dicts for all agent-created skills.

    Each dict has: name, state, pinned, activity_count, use_count,
    view_count, patch_count, created_at, last_activity_at.
    Used by the curator to build its candidate list.
    """
    data = _load_raw()
    results = []
    for name, rec in data.items():
        if not isinstance(rec, dict):
            continue
        if rec.get("created_by") != "agent":
            continue
        lat = latest_activity_at(rec)
        results.append({
            "name": name,
            "state": rec.get("state", STATE_ACTIVE),
            "pinned": bool(rec.get("pinned")),
            "activity_count": activity_count(rec),
            "use_count": int(rec.get("use_count") or 0),
            "view_count": int(rec.get("view_count") or 0),
            "patch_count": int(rec.get("patch_count") or 0),
            "created_at": rec.get("created_at"),
            "last_activity_at": lat.isoformat() if lat else None,
        })
    return sorted(results, key=lambda r: r["name"])


def top_skills(limit: int = 20) -> List[Dict[str, Any]]:
    """Return top *limit* skills by total activity, regardless of provenance."""
    data = _load_raw()
    results = []
    for name, rec in data.items():
        if not isinstance(rec, dict):
            continue
        lat = latest_activity_at(rec)
        results.append({
            "name": name,
            "state": rec.get("state", STATE_ACTIVE),
            "created_by": rec.get("created_by"),
            "activity_count": activity_count(rec),
            "use_count": int(rec.get("use_count") or 0),
            "view_count": int(rec.get("view_count") or 0),
            "patch_count": int(rec.get("patch_count") or 0),
            "last_activity_at": lat.isoformat() if lat else None,
        })
    results.sort(key=lambda r: r["activity_count"], reverse=True)
    return results[:limit]


def lifecycle_counts() -> Dict[str, int]:
    """Return {active, stale, archived} skill counts for all tracked skills."""
    data = _load_raw()
    counts: Dict[str, int] = {STATE_ACTIVE: 0, STATE_STALE: 0, STATE_ARCHIVED: 0}
    for rec in data.values():
        if isinstance(rec, dict):
            state = rec.get("state", STATE_ACTIVE)
            if state in counts:
                counts[state] += 1
            else:
                counts[STATE_ACTIVE] += 1
    return counts
