"""Export a conversation session to a shareable, redacted JSON file.

Reuses `SessionDB.export_session` for the raw dump and `redact_sensitive_text`
to strip secrets (API keys, tokens, passwords) from message text before the
file leaves the machine. Written under ``SPARK_HOME/exports/``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from spark_cli.config import get_spark_home


def _redact(text: str) -> str:
    from agent.redact import redact_sensitive_text

    return redact_sensitive_text(text)


def redact_session(session: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of an exported session with secrets stripped from messages."""
    out = dict(session)
    messages = []
    for msg in session.get("messages", []) or []:
        m = dict(msg)
        for key in ("content", "reasoning"):
            val = m.get(key)
            if isinstance(val, str) and val:
                m[key] = _redact(val)
        messages.append(m)
    out["messages"] = messages
    return out


def exports_dir() -> Path:
    d = get_spark_home() / "exports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def publish_export(path: str) -> dict[str, Any]:
    """Opt-in: publish a redacted export file to a public GitHub Gist via `gh`.

    Requires the `gh` CLI to be installed and authenticated. Returns {ok, url}
    or {error}. The caller must have already confirmed the user opted in.
    """
    import shutil
    import subprocess

    if not shutil.which("gh"):
        return {"error": "GitHub CLI (`gh`) is not installed/authenticated — cannot publish."}
    try:
        proc = subprocess.run(
            ["gh", "gist", "create", "--public", "--desc", "Spark session (redacted)", path],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Publish failed: {exc}"}
    if proc.returncode != 0:
        return {"error": (proc.stderr or proc.stdout or "gist create failed").strip()}
    url = (proc.stdout or "").strip().splitlines()[-1] if proc.stdout else ""
    return {"ok": True, "url": url}


def export_session_redacted(session_id: str, db: Any | None = None) -> dict[str, Any]:
    """Export a session to a redacted JSON file. Returns {ok, path, messages} or {error}."""
    own_db = False
    if db is None:
        from core.spark_state import SessionDB

        db = SessionDB()
        own_db = True
    try:
        raw = db.export_session(session_id)
    finally:
        if own_db:
            try:
                db.close()
            except Exception:
                pass
    if not raw:
        return {"error": f"Session not found: {session_id}"}

    redacted = redact_session(raw)
    path = exports_dir() / f"{session_id}.json"
    path.write_text(json.dumps(redacted, indent=2, default=str), encoding="utf-8")
    return {
        "ok": True,
        "path": str(path),
        "messages": len(redacted.get("messages", [])),
    }
