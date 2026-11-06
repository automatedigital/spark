"""Profile-local execution receipts, independent of jobs.json and saved documents.

Only the scheduler holding .tick.lock may reconcile unfinished attempts. SQLite
commits precede side effects/events; it cannot transact with jobs.json or delivery.
"""
from __future__ import annotations

import re
import sqlite3
import uuid
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path

from core.spark_constants import get_spark_home

MAX_HISTORY = 5000
_OUTPUT = re.compile(r"[0-9a-f]{12}/\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.md")


def _now() -> str:
    return datetime.now(UTC).isoformat()


class History:
    def __init__(self, home: Path | None = None):
        self.home = home if home is not None else get_spark_home()
        self.path = self.home / "cron" / "history.sqlite3"

    @contextmanager
    def _db(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.row_factory = sqlite3.Row
            db.executescript("""
                CREATE TABLE IF NOT EXISTS attempts (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    attempt_id TEXT NOT NULL UNIQUE,
                    job_id TEXT NOT NULL, occurrence TEXT NOT NULL,
                    cause TEXT NOT NULL, accepted_at TEXT NOT NULL,
                    started_at TEXT, finished_at TEXT,
                    execution TEXT NOT NULL DEFAULT 'accepted',
                    delivery TEXT NOT NULL DEFAULT 'unknown',
                    execution_error TEXT, delivery_error TEXT, output_ref TEXT,
                    settled INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(job_id, occurrence)
                );
                CREATE INDEX IF NOT EXISTS attempts_job ON attempts(job_id, seq);
                CREATE TABLE IF NOT EXISTS dispatch_guards (
                    job_id TEXT PRIMARY KEY, occurrence TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS manual_requests (
                    job_id TEXT PRIMARY KEY, occurrence TEXT NOT NULL
                );
            """)
            yield db

    def manual(self, job_id: str, occurrence: str) -> None:
        with self._db() as db:
            db.execute("INSERT OR REPLACE INTO manual_requests VALUES (?, ?)", (job_id, occurrence))

    def accept(self, job: dict) -> str | None:
        occurrence = str(job.get("next_run_at") or job.get("schedule", {}).get("run_at") or "legacy")
        attempt = uuid.uuid4().hex
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            guard = db.execute("SELECT occurrence FROM dispatch_guards WHERE job_id=?", (job["id"],)).fetchone()
            if guard and guard[0] == occurrence:
                return None
            manual = db.execute("SELECT occurrence FROM manual_requests WHERE job_id=?", (job["id"],)).fetchone()
            cause = "manual" if manual and manual[0] == occurrence else "schedule"
            inserted = db.execute("""INSERT OR IGNORE INTO attempts
                (attempt_id,job_id,occurrence,cause,accepted_at) VALUES (?,?,?,?,?)""",
                (attempt, job["id"], occurrence, cause, _now())).rowcount
            if inserted:
                db.execute("INSERT OR REPLACE INTO dispatch_guards VALUES (?,?)", (job["id"], occurrence))
                db.execute("DELETE FROM manual_requests WHERE job_id=? AND occurrence=?", (job["id"], occurrence))
            return attempt if inserted else None

    def start(self, attempt: str) -> bool:
        with self._db() as db:
            return bool(db.execute("UPDATE attempts SET execution='running',started_at=? WHERE attempt_id=? AND execution='accepted' AND settled=0", (_now(), attempt)).rowcount)

    def executed(self, attempt: str, outcome: str, error: str | None = None, output: Path | None = None) -> bool:
        if outcome not in {"success", "error", "cancelled"}:
            raise ValueError("Invalid execution outcome")
        reference = None
        if output is not None:
            try:
                reference = output.relative_to(self.home / "cron" / "output").as_posix()
            except ValueError as exc:
                raise ValueError("Output outside profile") from exc
            if not _OUTPUT.fullmatch(reference):
                raise ValueError("Invalid output reference")
        with self._db() as db:
            row = db.execute("SELECT job_id FROM attempts WHERE attempt_id=?", (attempt,)).fetchone()
            if reference and (not row or reference.split('/')[0] != row[0]):
                raise ValueError("Output belongs to another job")
            return bool(db.execute("""UPDATE attempts SET execution=?,execution_error=?,output_ref=?,finished_at=?
                WHERE attempt_id=? AND execution IN ('accepted','running') AND settled=0""",
                (outcome, str(error)[:2000] if error else None, reference, _now(), attempt)).rowcount)

    def attach_output(self, attempt: str, output: Path) -> None:
        try:
            reference = output.relative_to(self.home / "cron" / "output").as_posix()
        except ValueError:
            return
        if not _OUTPUT.fullmatch(reference):
            return
        with self._db() as db:
            db.execute("""UPDATE attempts SET output_ref=? WHERE attempt_id=? AND job_id=?
                AND output_ref IS NULL AND settled=0""", (reference, attempt, reference.split("/")[0]))

    def finish(self, attempt: str, delivery: str, error: str | None = None) -> bool:
        if delivery not in {"sent", "error", "silent", "suppressed", "no_target", "empty", "unknown"}:
            raise ValueError("Invalid delivery outcome")
        with self._db() as db:
            return bool(db.execute("""UPDATE attempts SET delivery=?,delivery_error=?,settled=1
                WHERE attempt_id=? AND settled=0 AND execution NOT IN ('accepted','running')""",
                (delivery, str(error)[:2000] if error else None, attempt)).rowcount)

    def reconcile(self) -> None:
        """Caller MUST own scheduler tick lock, proving no previous tick survives."""
        with self._db() as db:
            db.execute("""UPDATE attempts SET
                execution=CASE WHEN execution IN ('accepted','running') THEN 'interrupted' ELSE execution END,
                finished_at=COALESCE(finished_at,?), delivery='unknown',settled=1 WHERE settled=0""", (_now(),))

    def prune(self, live_job_ids: set[str] | None = None) -> None:
        with self._db() as db:
            # At most 5000 settled receipts plus active attempts. Compact guards
            # retain the latest occurrence for each live job, independently of
            # receipt retention, so pruning cannot replay an uncertain one-shot.
            db.execute("""DELETE FROM attempts WHERE settled=1 AND seq NOT IN
                (SELECT seq FROM attempts WHERE settled=1 ORDER BY seq DESC LIMIT ?)""", (MAX_HISTORY,))
            if live_job_ids is not None:
                for table in ("dispatch_guards", "manual_requests"):
                    for row in db.execute(f"SELECT job_id FROM {table}").fetchall():
                        if row[0] not in live_job_ids:
                            db.execute(f"DELETE FROM {table} WHERE job_id=?", (row[0],))

    def page(self, job_id: str | None = None, before: int | None = None, limit: int = 20) -> dict:
        if not 1 <= limit <= 50 or (before is not None and before < 1):
            raise ValueError("Invalid history page")
        with self._db() as db:
            rows = db.execute("""SELECT * FROM attempts WHERE (? IS NULL OR job_id=?)
                AND (? IS NULL OR seq<?) ORDER BY seq DESC LIMIT ?""",
                (job_id, job_id, before, before, limit + 1)).fetchall()
        entries = [dict(row) for row in rows[:limit]]
        for entry in entries:
            entry.pop("settled")
            entry.pop("occurrence")
        return {"attempts": entries, "next_before": entries[-1]["seq"] if len(rows) > limit else None}
