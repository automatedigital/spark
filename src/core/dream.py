"""
Dream — offline reflective pass over past sessions and memory.

Inspired by Claude's Managed Agents "Dreams" feature. A dream reads recent
session transcripts plus the existing holographic memory store, runs a
single-shot LLM synthesis pass, and writes:

  1. New consolidated facts into the holographic store (category="dream")
  2. A human-readable summary entry into the llm-wiki under dreams/

The wiki entry is the review surface — open it in Obsidian/VS Code.

State:
  ~/.spark/dreams/state.json     — last_run_at, first_run_completed, total_runs
  ~/.spark/dreams/schedule.json  — enabled, frequency, hour
  ~/.spark/dreams/pending-removals.json — facts the LLM flagged stale, queued
                                          for confirmation (never auto-deleted)

The 60-second gateway tick calls scheduler_tick(); it no-ops unless a daily
dream is enabled and due.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from core.spark_constants import get_spark_home

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _dream_dir() -> Path:
    d = get_spark_home() / "dreams"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state_path() -> Path:
    return _dream_dir() / "state.json"


def _schedule_path() -> Path:
    return _dream_dir() / "schedule.json"


def _pending_removals_path() -> Path:
    return _dream_dir() / "pending-removals.json"


# ---------------------------------------------------------------------------
# State + schedule
# ---------------------------------------------------------------------------

_DEFAULT_STATE: dict = {
    "last_run_at": None,
    "first_run_completed": False,
    "total_runs": 0,
}

_DEFAULT_SCHEDULE: dict = {
    "enabled": False,
    "frequency": "daily",  # only "daily" supported for now
    "hour": 3,             # local-time hour to fire
}


def _read_json(path: Path, default: dict) -> dict:
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            return dict(default)
        return {**default, **data}
    except FileNotFoundError:
        return dict(default)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read %s: %s — using defaults", path, e)
        return dict(default)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


def get_state() -> dict:
    """Return current dream state. Always returns a dict with default keys."""
    return _read_json(_state_path(), _DEFAULT_STATE)


def _save_state(state: dict) -> None:
    _write_json(_state_path(), state)


def get_schedule() -> dict:
    """Return current schedule config."""
    return _read_json(_schedule_path(), _DEFAULT_SCHEDULE)


def configure_schedule(enabled: bool, frequency: str = "daily", hour: int = 3) -> dict:
    """Enable or disable the daily dream schedule."""
    sched = {"enabled": bool(enabled), "frequency": frequency, "hour": int(hour)}
    _write_json(_schedule_path(), sched)
    return sched


# ---------------------------------------------------------------------------
# Wiki path resolution
# ---------------------------------------------------------------------------

def _resolve_wiki_path() -> Path:
    """Return the llm-wiki directory: always $SPARK_HOME/workspace/wiki."""
    return get_spark_home() / "workspace" / "wiki"


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class DreamResult:
    sessions_scanned: int = 0
    facts_scanned: int = 0
    insights_added: int = 0
    consolidations_applied: int = 0
    stale_queued: int = 0
    wiki_entry: Path | None = None
    dry_run: bool = False
    error: str | None = None
    raw_summary: str = ""
    sources: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "sessions_scanned": self.sessions_scanned,
            "facts_scanned": self.facts_scanned,
            "insights_added": self.insights_added,
            "consolidations_applied": self.consolidations_applied,
            "stale_queued": self.stale_queued,
            "wiki_entry": str(self.wiki_entry) if self.wiki_entry else None,
            "dry_run": self.dry_run,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

# Cap raw transcript characters fed into the synthesis prompt. ~80k tokens
# at ~4 chars/token is a generous ceiling; we trim further at the LLM layer.
_MAX_TRANSCRIPT_CHARS = 320_000
_MAX_FACTS_TO_INSPECT = 500
_MAX_SESSIONS = 50

_SYSTEM_PROMPT = """You are running a "dream" pass for the Spark agent — an \
offline reflective consolidation over recent conversation transcripts and the \
existing memory store. Your job is to surface durable insights, merge \
semantically-duplicate facts, and flag stale or contradicted entries.

You will receive two inputs:
  1. A list of existing FACTS (each with id, content, trust_score)
  2. Recent SESSION transcripts

Produce STRICT JSON matching this schema exactly — no prose, no markdown \
fences. Every field is required (use empty arrays where applicable):

{
  "insights": [
    { "content": "<one-sentence fact>", "category": "<short tag, e.g. 'preference', 'project', 'fact'>", "tags": "<comma-separated>", "confidence": <0..1> }
  ],
  "consolidations": [
    { "merge_fact_ids": [<int>, <int>, ...], "new_content": "<merged statement>", "confidence": <0..1> }
  ],
  "stale": [
    { "fact_id": <int>, "reason": "<why this looks stale or contradicted>" }
  ],
  "summary": "<markdown narrative, 3-6 short paragraphs, suitable as a wiki entry body>"
}

Rules:
  - Only emit consolidations with confidence >= 0.7 — be conservative.
  - Insights must be durable facts about the user, their projects, preferences,
    or recurring patterns — NOT one-off task details or transient debugging notes.
  - Stale entries are flagged only; the user reviews and confirms removal later.
  - The summary should read like a journal entry: what was learned, what changed,
    what's worth remembering.
"""


def _gather_facts(store) -> list[dict]:
    try:
        return list(store.list_facts(limit=_MAX_FACTS_TO_INSPECT))
    except Exception as e:
        logger.warning("Could not list facts: %s", e)
        return []


def _gather_sessions(session_db, since: float | None) -> list[dict]:
    try:
        rows = session_db.list_sessions_rich(limit=_MAX_SESSIONS)
    except Exception as e:
        logger.warning("Could not list sessions: %s", e)
        return []
    if since is not None:
        rows = [s for s in rows if (s.get("started_at") or 0) >= since]
    return rows


def _format_transcripts(session_db, sessions: list[dict]) -> tuple[str, list[str]]:
    """Concatenate session messages into a single string. Returns (text, source_ids)."""
    chunks: list[str] = []
    sources: list[str] = []
    total = 0
    for s in sessions:
        sid = s.get("id")
        if not sid:
            continue
        try:
            msgs = session_db.get_messages_as_conversation(sid)
        except Exception:
            continue
        if not msgs:
            continue

        header = f"\n\n=== SESSION {sid} ({s.get('title') or s.get('preview') or 'untitled'}) ==="
        chunks.append(header)
        sources.append(sid)
        total += len(header)

        for m in msgs:
            role = m.get("role", "?")
            content = m.get("content") or ""
            if not isinstance(content, str):
                content = str(content)
            if not content.strip():
                continue
            line = f"\n[{role}] {content.strip()}"
            chunks.append(line)
            total += len(line)
            if total > _MAX_TRANSCRIPT_CHARS:
                chunks.append("\n... [transcript truncated]")
                return "".join(chunks), sources
    return "".join(chunks), sources


def _format_facts(facts: list[dict]) -> str:
    if not facts:
        return "(no existing facts)"
    out = []
    for f in facts:
        fid = f.get("fact_id")
        content = (f.get("content") or "").replace("\n", " ")
        trust = f.get("trust_score", 0.0)
        out.append(f"  [{fid}] (trust={trust:.2f}) {content}")
    return "\n".join(out)


def _call_synthesis_llm(facts_block: str, transcripts: str) -> dict:
    """Run the single-shot synthesis call and parse the JSON response."""
    from agent.auxiliary_client import call_llm

    user_msg = (
        "EXISTING FACTS:\n"
        f"{facts_block}\n\n"
        "RECENT SESSIONS:\n"
        f"{transcripts}\n\n"
        "Emit the JSON object now — no prose, no fences."
    )

    response = call_llm(
        task="dream",
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=8192,
        temperature=0.4,
        timeout=600.0,
    )

    raw = ""
    try:
        raw = response.choices[0].message.content or ""
    except Exception:
        pass

    return _parse_llm_json(raw)


# Strip optional ```json fences and leading/trailing prose around a JSON object.
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _parse_llm_json(raw: str) -> dict:
    """Best-effort JSON extraction from the LLM response."""
    text = _FENCE_RE.sub("", raw).strip()
    # If the model wrapped output in prose, snip from first { to last }
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            text = text[start:end + 1]
    try:
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("Expected JSON object at top level")
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("Could not parse dream LLM response as JSON: %s", e)
        return {"insights": [], "consolidations": [], "stale": [], "summary": raw}

    parsed.setdefault("insights", [])
    parsed.setdefault("consolidations", [])
    parsed.setdefault("stale", [])
    parsed.setdefault("summary", "")
    return parsed


# ---------------------------------------------------------------------------
# Application: write to holographic store + wiki
# ---------------------------------------------------------------------------

_MIN_CONSOLIDATION_CONFIDENCE = 0.7


def _apply_to_store(store, payload: dict) -> tuple[int, int]:
    """Apply insights + consolidations to the holographic store.

    Returns (insights_added, consolidations_applied).
    """
    added = 0
    for item in payload.get("insights") or []:
        content = (item.get("content") or "").strip() if isinstance(item, dict) else ""
        if not content:
            continue
        category = (item.get("category") or "dream").strip() if isinstance(item, dict) else "dream"
        tags_raw = item.get("tags", "") if isinstance(item, dict) else ""
        if isinstance(tags_raw, list):
            tags = ",".join(str(t) for t in tags_raw)
        else:
            tags = str(tags_raw or "")
        # Always stamp dream-originated facts so they're identifiable later.
        if "dream" not in tags.split(","):
            tags = ",".join(t for t in [tags, "dream"] if t)
        try:
            store.add_fact(content, category=category, tags=tags)
            added += 1
        except Exception as e:
            logger.warning("Failed to add dream insight: %s", e)

    consolidated = 0
    for item in payload.get("consolidations") or []:
        if not isinstance(item, dict):
            continue
        try:
            confidence = float(item.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < _MIN_CONSOLIDATION_CONFIDENCE:
            continue
        ids = item.get("merge_fact_ids") or []
        if not isinstance(ids, list) or len(ids) < 2:
            continue
        try:
            ids = [int(x) for x in ids]
        except (TypeError, ValueError):
            continue
        new_content = (item.get("new_content") or "").strip()
        if not new_content:
            continue
        # Keep the highest-trust fact, rewrite its content, remove the rest.
        keep_id = ids[0]
        try:
            existing = {f.get("fact_id"): f for f in store.list_facts(limit=10_000)}
            best = max(
                (existing[i] for i in ids if i in existing),
                key=lambda f: f.get("trust_score", 0.0),
                default=None,
            )
            if best is None:
                continue
            keep_id = int(best["fact_id"])
            store.update_fact(keep_id, content=new_content)
            for fid in ids:
                if fid != keep_id:
                    store.remove_fact(fid)
            consolidated += 1
        except Exception as e:
            logger.warning("Failed to consolidate facts %s: %s", ids, e)

    return added, consolidated


def _queue_stale(payload: dict) -> int:
    """Append stale-flagged facts to pending-removals.json. Never auto-deletes."""
    stale_in = payload.get("stale") or []
    if not isinstance(stale_in, list) or not stale_in:
        return 0

    path = _pending_removals_path()
    existing: list = []
    if path.exists():
        try:
            existing = json.loads(path.read_text())
            if not isinstance(existing, list):
                existing = []
        except (json.JSONDecodeError, OSError):
            existing = []

    queued = 0
    now_iso = datetime.now().isoformat(timespec="seconds")
    for item in stale_in:
        if not isinstance(item, dict):
            continue
        fid = item.get("fact_id")
        reason = (item.get("reason") or "").strip()
        if fid is None:
            continue
        try:
            fid_int = int(fid)
        except (TypeError, ValueError):
            continue
        existing.append({"fact_id": fid_int, "reason": reason, "queued_at": now_iso})
        queued += 1

    if queued:
        _write_json(path, existing)
    return queued


def _slugify(text: str, maxlen: int = 40) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:maxlen] or "dream"


def _write_wiki_entry(payload: dict, sources: list[str], counts: dict) -> Path:
    """Write the dream summary into the llm-wiki under dreams/.

    Creates the wiki dreams/ subdir, the entry file, dreams/index.md, and
    appends a one-liner to <wiki>/log.md (matching the wiki skill convention).
    """
    wiki_root = _resolve_wiki_path()
    dreams_dir = wiki_root / "dreams"
    dreams_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    stamp = now.strftime("%Y-%m-%d-%H%M")
    iso = now.isoformat(timespec="seconds")
    entry_path = dreams_dir / f"{stamp}.md"

    title = f"Dream — {now.strftime('%Y-%m-%d %H:%M')}"
    summary = (payload.get("summary") or "").strip() or "_(no summary produced)_"

    frontmatter = [
        "---",
        f"title: {title}",
        f"created: {iso}",
        "type: summary",
        "tags: [dream, synthesis, auto-generated]",
        f"sources: [{', '.join(f'session:{s}' for s in sources) if sources else ''}]",
        "---",
        "",
    ]

    body_parts = ["\n".join(frontmatter), f"# {title}\n", summary, ""]

    insights = payload.get("insights") or []
    if insights:
        body_parts.append("\n## New insights\n")
        for item in insights:
            if not isinstance(item, dict):
                continue
            content = (item.get("content") or "").strip()
            if not content:
                continue
            cat = (item.get("category") or "").strip()
            suffix = f" _({cat})_" if cat else ""
            body_parts.append(f"- {content}{suffix}")

    consolidations = payload.get("consolidations") or []
    if consolidations:
        body_parts.append("\n## Consolidations\n")
        for item in consolidations:
            if not isinstance(item, dict):
                continue
            merged = (item.get("new_content") or "").strip()
            ids = item.get("merge_fact_ids") or []
            if not merged:
                continue
            body_parts.append(f"- {merged}  _(merged facts: {', '.join(str(i) for i in ids)})_")

    stale = payload.get("stale") or []
    if stale:
        body_parts.append("\n## Flagged stale (queued for review)\n")
        for item in stale:
            if not isinstance(item, dict):
                continue
            fid = item.get("fact_id")
            reason = (item.get("reason") or "").strip()
            body_parts.append(f"- fact `{fid}` — {reason}")

    body_parts.append(
        f"\n---\n_Counts: {counts.get('insights_added', 0)} insights, "
        f"{counts.get('consolidations_applied', 0)} consolidations, "
        f"{counts.get('stale_queued', 0)} stale queued from "
        f"{counts.get('sessions_scanned', 0)} sessions._\n"
    )

    entry_path.write_text("\n".join(body_parts))

    # Update dreams/index.md
    index_path = dreams_dir / "index.md"
    line = (
        f"- [{now.strftime('%Y-%m-%d %H:%M')}]({entry_path.name}) — "
        f"{counts.get('insights_added', 0)} insights, "
        f"{counts.get('consolidations_applied', 0)} consolidations"
    )
    if index_path.exists():
        existing = index_path.read_text()
        if not existing.endswith("\n"):
            existing += "\n"
        index_path.write_text(existing + line + "\n")
    else:
        index_path.write_text(
            "# Dreams\n\n"
            "Reflective consolidation passes over past sessions, written by `/dream`.\n\n"
            + line + "\n"
        )

    # Append to the wiki root log if it exists (don't create — that's the
    # wiki skill's responsibility on first init).
    log_path = wiki_root / "log.md"
    if log_path.exists():
        try:
            with log_path.open("a") as f:
                f.write(f"\n- {iso} — dream pass written to dreams/{entry_path.name}\n")
        except OSError as e:
            logger.debug("Could not append to wiki log: %s", e)

    return entry_path


# ---------------------------------------------------------------------------
# Top-level runner
# ---------------------------------------------------------------------------

def _open_holographic_store():
    """Open the user's holographic memory store.

    Returns ``(store, None)`` on success or ``(None, error_str)`` on failure.
    Ensures ``src/`` is in sys.path before importing so the plugin packages
    (agent, tools, plugins.*) are always importable regardless of venv state.
    """
    import sqlite3 as _sqlite3
    import sys

    # dream.py lives at src/core/dream.py — src/ is two levels up.
    # Inserting it guarantees plugin imports work even when the editable
    # install's .pth file is stale (e.g. after spark update used the wrong venv).
    _src = str(Path(__file__).resolve().parent.parent)
    if _src not in sys.path:
        sys.path.insert(0, _src)

    try:
        from plugins.memory.holographic.store import MemoryStore as HoloStore
    except ImportError as e:
        logger.warning("Holographic store unavailable: %s", e)
        return None, str(e)
    except Exception as e:
        logger.warning("Failed to import holographic store: %s", e)
        return None, str(e)

    try:
        return HoloStore(), None
    except _sqlite3.DatabaseError as e:
        # DB file is corrupt — back it up and recreate automatically.
        logger.warning("Holographic store DB corrupt (%s) — attempting auto-repair.", e)
        try:
            _holo_path = get_spark_home() / "memory_store.db"
            if _holo_path.exists():
                _bak = _holo_path.with_suffix(".db.bak")
                _holo_path.rename(_bak)
                logger.info("Backed up corrupt memory_store.db to %s", _bak.name)
            return HoloStore(), None
        except Exception as _repair_err:
            logger.warning("Auto-repair failed: %s", _repair_err)
            return None, f"database corrupt and repair failed: {_repair_err}"
    except Exception as e:
        logger.warning("Failed to open holographic store: %s", e)
        return None, str(e)


def _open_session_db():
    """Open the session database. Returns the SessionDB or None on failure."""
    import sqlite3 as _sqlite3
    import sys

    _src = str(Path(__file__).resolve().parent.parent)
    if _src not in sys.path:
        sys.path.insert(0, _src)

    try:
        from core.spark_state import SessionDB
    except ImportError as e:
        logger.warning("SessionDB unavailable: %s", e)
        return None
    try:
        return SessionDB(db_path=get_spark_home() / "state.db")
    except _sqlite3.DatabaseError as e:
        logger.warning("Session DB error (%s). Run 'spark update' to repair.", e)
        return None
    except Exception as e:
        logger.warning("Failed to open session DB: %s", e)
        return None


def run_dream(*, since: float | None = None, dry_run: bool = False) -> DreamResult:
    """Run one dream pass.

    Args:
        since: Unix timestamp — only consider sessions started at or after this
               time. Defaults to the last dream's ``last_run_at``.
        dry_run: If True, run the LLM call but do not write to the store, wiki,
                 or state. Useful for previewing.

    Returns:
        DreamResult with counts and the wiki entry path (or None if dry_run /
        error).
    """
    result = DreamResult(dry_run=dry_run)

    state = get_state()
    if since is None:
        since = state.get("last_run_at")

    store, _holo_err = _open_holographic_store()
    if store is None:
        result.error = (
            f"holographic store unavailable: {_holo_err}"
            if _holo_err else "holographic store unavailable"
        )
        return result

    session_db = _open_session_db()
    if session_db is None:
        result.error = "session db unavailable"
        return result

    try:
        facts = _gather_facts(store)
        sessions = _gather_sessions(session_db, since)
        result.facts_scanned = len(facts)
        result.sessions_scanned = len(sessions)

        if not sessions and not facts:
            result.error = "nothing to dream on — no sessions or facts found"
            return result

        transcripts, sources = _format_transcripts(session_db, sessions)
        result.sources = sources
        facts_block = _format_facts(facts)

        payload = _call_synthesis_llm(facts_block, transcripts)
        result.raw_summary = (payload.get("summary") or "")[:5000]

        if dry_run:
            result.insights_added = len(payload.get("insights") or [])
            result.consolidations_applied = len(payload.get("consolidations") or [])
            result.stale_queued = len(payload.get("stale") or [])
            return result

        added, consolidated = _apply_to_store(store, payload)
        queued = _queue_stale(payload)
        result.insights_added = added
        result.consolidations_applied = consolidated
        result.stale_queued = queued

        counts = {
            "insights_added": added,
            "consolidations_applied": consolidated,
            "stale_queued": queued,
            "sessions_scanned": result.sessions_scanned,
        }
        result.wiki_entry = _write_wiki_entry(payload, sources, counts)

        state["last_run_at"] = time.time()
        state["first_run_completed"] = True
        state["total_runs"] = int(state.get("total_runs", 0)) + 1
        _save_state(state)

    except Exception as e:
        logger.exception("Dream pass failed: %s", e)
        result.error = str(e)
    finally:
        try:
            store.close()
        except Exception:
            pass

    return result


# ---------------------------------------------------------------------------
# Scheduler hook (called from cron.scheduler.tick once per minute)
# ---------------------------------------------------------------------------

_SCHEDULE_GRACE_SECONDS = 24 * 3600  # if missed (process down), run once when back up


def _is_due(schedule: dict, state: dict, now: float | None = None) -> bool:
    if not schedule.get("enabled"):
        return False
    if schedule.get("frequency", "daily") != "daily":
        return False
    now_ts = now if now is not None else time.time()
    last = state.get("last_run_at")
    if last is None:
        return True  # never run before — fire ASAP

    # Run at most once per 23h to allow drift, and only at/after the configured hour.
    if now_ts - float(last) < 23 * 3600:
        return False

    hour = int(schedule.get("hour", 3))
    local_hour = datetime.fromtimestamp(now_ts).hour
    # Allow firing any time after the configured hour, up to 24h later.
    return local_hour >= hour


def scheduler_tick(now: float | None = None) -> bool:
    """Called from the cron tick loop. Returns True if a dream was started.

    Heavy work happens inline — the cron tick already runs in a background
    thread, and dreams are infrequent (at most once a day).
    """
    try:
        schedule = get_schedule()
        state = get_state()
        if not _is_due(schedule, state, now=now):
            return False
        logger.info("Dream: scheduled daily pass is due — running now")
        result = run_dream()
        if result.error:
            logger.warning("Dream tick failed: %s", result.error)
            return False
        logger.info(
            "Dream tick complete: %d insights, %d consolidations, wiki=%s",
            result.insights_added,
            result.consolidations_applied,
            result.wiki_entry,
        )
        return True
    except Exception as e:
        logger.exception("Dream scheduler_tick crashed: %s", e)
        return False
