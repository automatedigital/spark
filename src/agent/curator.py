"""Curator — background skill maintenance orchestrator.

The curator is an auxiliary-model task that periodically reviews agent-created
skills and maintains the collection. It runs inactivity-triggered (no cron
daemon): when the agent has been idle for at least ``min_idle_hours`` and the
last curator run was older than ``interval_hours`` ago, ``maybe_run_curator()``
spawns a forked AIAgent to do the review in a daemon thread.

Responsibilities:
  - Spawn a background review agent that can pin / archive / consolidate /
    patch agent-created skills via skill_manage
  - Persist curator state (last_run_at, paused, etc.) in .curator_state
  - Show the result summary on the next session start

Strict invariants:
  - Only touches skills under ~/.spark/skills/ that were created by the agent
    (bundled and hub-installed skills are excluded)
  - Never auto-deletes — only archives. Archive is recoverable.
  - Uses an auxiliary AIAgent fork; never touches the main session's cache.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_HOURS = 24 * 7   # 7 days
DEFAULT_MIN_IDLE_HOURS = 2
DEFAULT_STALE_AFTER_DAYS = 30
DEFAULT_ARCHIVE_AFTER_DAYS = 90


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _spark_home() -> Path:
    from core.spark_constants import get_spark_home
    return get_spark_home()


def _state_file() -> Path:
    return _spark_home() / "skills" / ".curator_state"


def _skills_dir() -> Path:
    return _spark_home() / "skills"


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

def _default_state() -> dict[str, Any]:
    return {
        "last_run_at": None,
        "last_run_duration_seconds": None,
        "last_run_summary": None,
        "last_run_summary_shown_at": None,
        "paused": False,
        "run_count": 0,
    }


def load_state() -> dict[str, Any]:
    path = _state_file()
    if not path.exists():
        return _default_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            base = _default_state()
            base.update({k: v for k, v in data.items() if k in base})
            return base
    except (OSError, json.JSONDecodeError) as e:
        logger.debug("Failed to read curator state: %s", e)
    return _default_state()


def save_state(data: dict[str, Any]) -> None:
    path = _state_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".curator_state_", suffix=".tmp")
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
        logger.debug("Failed to save curator state: %s", e, exc_info=True)


def set_paused(paused: bool) -> None:
    state = load_state()
    state["paused"] = bool(paused)
    save_state(state)


def is_paused() -> bool:
    return bool(load_state().get("paused"))


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _load_config() -> dict[str, Any]:
    try:
        from spark_cli.config import load_config
        cfg = load_config()
    except Exception as e:
        logger.debug("Failed to load config for curator: %s", e)
        return {}
    if not isinstance(cfg, dict):
        return {}
    cur = cfg.get("curator") or {}
    return cur if isinstance(cur, dict) else {}


def is_enabled() -> bool:
    """Default ON when no config says otherwise."""
    return bool(_load_config().get("enabled", True))


def get_interval_hours() -> int:
    try:
        return int(_load_config().get("interval_hours", DEFAULT_INTERVAL_HOURS))
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL_HOURS


def get_min_idle_hours() -> float:
    try:
        return float(_load_config().get("min_idle_hours", DEFAULT_MIN_IDLE_HOURS))
    except (TypeError, ValueError):
        return DEFAULT_MIN_IDLE_HOURS


def get_stale_after_days() -> int:
    try:
        return int(_load_config().get("stale_after_days", DEFAULT_STALE_AFTER_DAYS))
    except (TypeError, ValueError):
        return DEFAULT_STALE_AFTER_DAYS


def get_archive_after_days() -> int:
    try:
        return int(_load_config().get("archive_after_days", DEFAULT_ARCHIVE_AFTER_DAYS))
    except (TypeError, ValueError):
        return DEFAULT_ARCHIVE_AFTER_DAYS


# ---------------------------------------------------------------------------
# Skill enumeration (agent-created only)
# ---------------------------------------------------------------------------

_EXCLUDED_DIRS = frozenset({".git", ".github", ".hub", ".archive", "__pycache__"})


def _list_agent_created_skills() -> list[dict[str, Any]]:
    """Return a list of dicts for every skill under ~/.spark/skills/ that is
    not bundled with the install and not hub-installed.

    Agent-created skills live directly under ``~/.spark/skills/<name>/`` (or
    a category sub-directory) and have a ``SKILL.md`` file. We exclude:
      - ``.archive/`` — already archived
      - bundled skills (skills from the install's ``src/`` tree)
      - hub-installed skills (``~/.spark/skills/.hub/``)
    """
    skills_dir = _skills_dir()
    if not skills_dir.exists():
        return []

    # Determine bundled skill names so we can exclude them.
    try:
        bundled_root = Path(__file__).parent.parent / "skills"
        bundled_names = {p.name for p in bundled_root.iterdir() if p.is_dir()} if bundled_root.exists() else set()
    except Exception:
        bundled_names = set()

    results: list[dict[str, Any]] = []
    for entry in skills_dir.iterdir():
        if not entry.is_dir():
            continue
        if entry.name in _EXCLUDED_DIRS or entry.name.startswith("."):
            continue
        if entry.name in bundled_names:
            continue
        skill_md = entry / "SKILL.md"
        if skill_md.exists():
            results.append({
                "name": entry.name,
                "path": str(entry),
                "skill_md_path": str(skill_md),
            })
        else:
            # Check category sub-directories
            for sub in entry.iterdir():
                if sub.is_dir() and sub.name not in _EXCLUDED_DIRS:
                    sub_md = sub / "SKILL.md"
                    if sub_md.exists():
                        results.append({
                            "name": sub.name,
                            "path": str(sub),
                            "skill_md_path": str(sub_md),
                            "category": entry.name,
                        })

    return sorted(results, key=lambda r: r["name"])


def _render_candidate_list() -> str:
    """Human/agent-readable list of agent-created skills, enriched with usage data."""
    rows = _list_agent_created_skills()
    if not rows:
        return "No agent-created skills to review."

    # Enrich with usage data from sidecar when available
    usage_by_name: dict = {}
    try:
        from tools.skill_usage import agent_created_report
        for rec in agent_created_report():
            usage_by_name[rec["name"]] = rec
    except Exception:
        pass

    lines = [f"Agent-created skills ({len(rows)}):\n"]
    for r in rows:
        cat = f"  category={r['category']}" if r.get("category") else ""
        usage = usage_by_name.get(r["name"])
        if usage:
            activity = usage.get("activity_count", 0)
            state = usage.get("state", "active")
            last = usage.get("last_activity_at") or "never"
            lines.append(f"- {r['name']}{cat}  [state={state}, activity={activity}, last_active={last}]")
        else:
            lines.append(f"- {r['name']}{cat}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Idle / interval check
# ---------------------------------------------------------------------------

def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None


def should_run_now(now: datetime | None = None) -> bool:
    """Return True if all conditions are met to run the curator.

    On first observation (no prior run), seeds ``last_run_at`` and defers
    the first real pass by one full interval so the curator doesn't fire
    immediately after install.
    """
    if not is_enabled():
        return False
    if is_paused():
        return False

    state = load_state()
    last = _parse_iso(state.get("last_run_at"))

    if now is None:
        now = datetime.now(UTC)

    if last is None:
        try:
            state["last_run_at"] = now.isoformat()
            state["last_run_summary"] = (
                "deferred first run — curator seeded; will run after one interval"
            )
            save_state(state)
        except Exception as e:
            logger.debug("Failed to seed curator last_run_at: %s", e)
        return False

    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    interval = timedelta(hours=get_interval_hours())
    return (now - last) >= interval


# ---------------------------------------------------------------------------
# Review prompt
# ---------------------------------------------------------------------------

CURATOR_REVIEW_PROMPT = (
    "You are running as Spark's background skill CURATOR. Your job is to "
    "review the agent-created skills and consolidate, improve, or archive "
    "them to keep the skill library clean and discoverable.\n\n"
    "Hard rules:\n"
    "1. DO NOT touch bundled or hub-installed skills — the candidate list "
    "below contains only agent-created skills.\n"
    "2. DO NOT delete any skill. Archiving (moving its directory into "
    "~/.spark/skills/.archive/) is the maximum destructive action. "
    "Archives are recoverable.\n"
    "3. DO NOT touch skills you have already merged into an umbrella.\n\n"
    "How to work:\n"
    "1. Review each skill. Identify clusters of overlapping or related skills.\n"
    "2. For each cluster: merge narrow siblings into one broader umbrella "
    "skill via skill_manage (action=patch or action=create), then archive "
    "the absorbed siblings.\n"
    "3. Skills that are high-quality and standalone: keep.\n"
    "4. Skills that are low-quality, outdated, or irrelevant with no "
    "consolidation target: archive.\n\n"
    "When done, write a short human-readable summary of what you did:\n"
    "- How many skills reviewed\n"
    "- How many archived\n"
    "- How many merged / patched\n"
    "- Key decisions\n"
)


# ---------------------------------------------------------------------------
# LLM review pass
# ---------------------------------------------------------------------------

def _run_llm_review(prompt: str) -> dict[str, Any]:
    """Spawn an AIAgent fork to run the curator review prompt.

    Returns a dict with keys: final, summary, error.
    Never raises — callers get a structured failure instead.
    """
    result: dict[str, Any] = {"final": "", "summary": "", "error": None}
    try:
        from core.run_agent import AIAgent
    except Exception as e:
        result["error"] = f"AIAgent import failed: {e}"
        result["summary"] = result["error"]
        return result

    review_agent: Any = None
    try:
        review_agent = AIAgent(
            max_iterations=200,
            quiet_mode=True,
            platform="curator",
            skip_context_files=True,
            skip_memory=True,
        )
        review_agent._memory_nudge_interval = 0
        review_agent._skill_nudge_interval = 0

        with open(os.devnull, "w", encoding="utf-8") as _devnull, \
             contextlib.redirect_stdout(_devnull), \
             contextlib.redirect_stderr(_devnull):
            conv_result = review_agent.run_conversation(user_message=prompt)

        final = ""
        if isinstance(conv_result, dict):
            final = str(conv_result.get("final_response") or "").strip()
        result["final"] = final
        result["summary"] = (final[:240] + "…") if len(final) > 240 else (final or "no change")
    except Exception as e:
        result["error"] = f"error: {e}"
        result["summary"] = result["error"]
    finally:
        if review_agent is not None:
            try:
                review_agent.close()
            except Exception:
                pass
    return result


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def run_curator_review(
    on_summary: Callable[[str], None] | None = None,
    synchronous: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Execute a single curator review pass.

    Steps:
      1. Enumerate agent-created skills.
      2. If candidates exist, spawn a forked AIAgent with the review prompt.
      3. Update .curator_state with last_run_at and a one-line summary.
      4. Invoke *on_summary* with a user-visible description.

    *synchronous=True* runs the LLM in the calling thread (default: daemon thread).
    *dry_run=True* instructs the LLM not to mutate skills (report only).
    """
    start = datetime.now(UTC)

    state = load_state()
    if not dry_run:
        state["last_run_at"] = start.isoformat()
        state["run_count"] = int(state.get("run_count", 0)) + 1
    state["last_run_summary"] = "running…"
    save_state(state)

    def _llm_pass():
        candidate_list = _render_candidate_list()
        llm_meta: dict[str, Any] = {}

        if "No agent-created skills" in candidate_list:
            final_summary = "no candidates"
            llm_meta = {"final": "", "summary": "skipped (no candidates)", "error": None}
        else:
            dry_banner = (
                "\n\n⚠ DRY-RUN: produce a report only — do NOT call skill_manage or "
                "move any files.\n\n"
                if dry_run
                else ""
            )
            prompt = f"{CURATOR_REVIEW_PROMPT}{dry_banner}\n{candidate_list}"
            llm_meta = _run_llm_review(prompt)
            final_summary = llm_meta.get("summary", "no change")

        elapsed = (datetime.now(UTC) - start).total_seconds()
        state2 = load_state()
        state2["last_run_duration_seconds"] = round(elapsed, 1)
        state2["last_run_summary"] = final_summary
        save_state(state2)

        if on_summary:
            try:
                on_summary(f"curator: {final_summary}")
            except Exception:
                pass

    if synchronous:
        _llm_pass()
    else:
        t = threading.Thread(target=_llm_pass, daemon=True, name="curator-review")
        t.start()

    return {"started_at": start.isoformat(), "dry_run": dry_run}


# ---------------------------------------------------------------------------
# Public entry point for the agent loop
# ---------------------------------------------------------------------------

def maybe_run_curator(
    *,
    idle_for_seconds: float | None = None,
    on_summary: Callable[[str], None] | None = None,
) -> dict[str, Any] | None:
    """Best-effort: run a curator pass if all gates pass. Never raises."""
    try:
        if not should_run_now():
            return None
        if idle_for_seconds is not None:
            min_idle_s = get_min_idle_hours() * 3600.0
            if idle_for_seconds < min_idle_s:
                return None
        return run_curator_review(on_summary=on_summary)
    except Exception as e:
        logger.debug("maybe_run_curator failed: %s", e, exc_info=True)
        return None
