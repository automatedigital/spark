"""Export a conversation session to a shareable, redacted JSON or Markdown file.

Reuses `SessionDB.export_session` for the raw dump and `redact_sensitive_text`
to strip secrets (API keys, tokens, passwords) from message text before the
file leaves the machine. Written under ``SPARK_HOME/exports/``.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from spark_cli.config import get_spark_home

logger = logging.getLogger(__name__)
_SECRET_FIELD = re.compile(
    r"api_?key|token|secret|password|passwd|access_token|refresh_token|auth_token|"
    r"bearer|authorization|credential|secret_value|raw_secret|secret_input|key_material",
    re.IGNORECASE,
)


def _redact(text: str) -> str:
    from agent.redact import redact_sensitive_text

    return redact_sensitive_text(text, force=True)


def redact_session(session: dict[str, Any]) -> dict[str, Any]:
    """Recursively copy and sanitize all export fields, independent of log policy.

    Credential fields cover unprefixed values in decoded tool arguments too.
    Raw SessionDB backup/export data is never modified.
    """
    def clean(value: Any, key: str = "") -> Any:
        if isinstance(value, str):
            if _SECRET_FIELD.fullmatch(key):
                return "[REDACTED]"
            # Parse JSON argument strings before cleaning so escaped credentials
            # and arbitrary nesting receive the same treatment as decoded data.
            try:
                decoded = json.loads(value)
            except (ValueError, TypeError):
                decoded = None
            if isinstance(decoded, (dict, list)):
                sanitized = clean(decoded)
                return value if sanitized == decoded else json.dumps(sanitized, ensure_ascii=False)
            return _redact(value)
        if isinstance(value, dict):
            return {k: clean(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [clean(v, key) for v in value]
        return value

    return {key: clean(value, key) for key, value in session.items()}


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


def export_session_redacted(
    session_id: str, db: Any | None = None, *, format: str = "json"
) -> dict[str, Any]:
    """Write a local redacted export. Returns {ok, path, messages} or {error}."""
    if format not in {"json", "markdown"}:
        return {"error": "Unsupported export format. Choose json or markdown."}
    if not session_id or Path(session_id).name != session_id or session_id in {".", ".."}:
        return {"error": "Invalid session ID for export."}
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
                logger.debug("Ignoring error in export_session_redacted()", exc_info=True)
    if not raw:
        return {"error": f"Session not found: {session_id}"}

    redacted = redact_session(raw)
    if format == "markdown":
        from spark_cli.session_export_markdown import render_session_markdown

        content = render_session_markdown(redacted)
        suffix = "md"
    else:
        content = json.dumps(redacted, indent=2, default=str, ensure_ascii=False)
        suffix = "json"
    try:
        path = exports_dir() / f"{session_id}.{suffix}"
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        return {"error": f"Could not write session export: {exc}"}
    return {
        "ok": True,
        "path": str(path),
        "messages": len(redacted.get("messages", [])),
    }
