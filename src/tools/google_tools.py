"""
Google Workspace tools for Spark Agent.

Tools activate automatically when a Google OAuth token is present.
Connect via the Connectors tab in the web dashboard.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC
from typing import Any

from tools.registry import registry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_gmail_read_connected() -> bool:
    """check_fn: expose Gmail search when OAuth or Gmail IMAP can read mail."""
    try:
        from spark_cli.google_connector import has_imap_credentials, load_token
        return bool(load_token()) or has_imap_credentials()
    except Exception:
        return False


def _check_google_oauth_connected() -> bool:
    """check_fn: expose Workspace API tools only when OAuth is connected."""
    try:
        from spark_cli.google_connector import load_token
        return bool(load_token())
    except Exception:
        return False


async def _get_token_async() -> str | None:
    import asyncio
    try:
        from spark_cli.google_connector import get_valid_access_token
        # Run the synchronous token fetch in a thread to avoid blocking the event loop
        return await asyncio.get_event_loop().run_in_executor(None, get_valid_access_token)
    except Exception:
        return None


def _not_connected() -> str:
    return json.dumps({
        "error": "not_connected",
        "message": "Google Workspace is not connected. Open Settings → Connectors and click 'Connect Google'.",
    })


def _insufficient_scope() -> str:
    return json.dumps({
        "error": "insufficient_scope",
        "message": (
            "Reading Gmail requires the restricted 'gmail.readonly' scope, which "
            "is not part of Spark's free-tier Google connection (Gmail is "
            "send-only on the free tier). To read mail for free, connect Gmail "
            "read access with a Google App Password in Settings → Connectors, "
            "or use a bring-your-own OAuth client that requests gmail.readonly."
        ),
    })


def _is_scope_error(exc: Exception) -> bool:
    """True if an httpx error looks like a 403 insufficient-permission/scope."""
    resp = getattr(exc, "response", None)
    if resp is None:
        return False
    if resp.status_code not in (401, 403):
        return False
    body = (getattr(resp, "text", "") or "").lower()
    return (
        "insufficient" in body
        or "scope" in body
        or "permission" in body
        or resp.status_code == 403
    )


def _gmail_headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


def _decode_header(value: str | None) -> str:
    import email.header

    if not value:
        return ""
    parts = email.header.decode_header(value)
    out: list[str] = []
    for chunk, enc in parts:
        if isinstance(chunk, bytes):
            out.append(chunk.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(chunk)
    return "".join(out)


def _gmail_search_imap_sync(query: str, max_results: int) -> dict:
    import email
    import imaplib

    from spark_cli.google_connector import load_imap_credentials

    creds = load_imap_credentials()
    if not creds:
        raise ValueError("Gmail IMAP is not connected")

    host = creds.get("imap_host", "imap.gmail.com")
    port = int(creds.get("imap_port", 993))
    username = creds["email"]
    password = creds["app_password"]
    raw_query = (query or "in:anywhere").replace("\\", "\\\\").replace('"', '\\"')

    with imaplib.IMAP4_SSL(host, port) as imap:
        imap.login(username, password)
        imap.select("INBOX", readonly=True)
        typ, data = imap.uid("search", None, "X-GM-RAW", f'"{raw_query}"')
        if typ != "OK":
            raise RuntimeError("Gmail IMAP search failed")

        ids = data[0].split() if data and data[0] else []
        selected = list(reversed(ids))[:max_results]
        results = []
        for uid in selected:
            typ, msg_data = imap.uid(
                "fetch",
                uid,
                "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)] BODY.PEEK[TEXT]<0.500>)",
            )
            if typ != "OK":
                continue

            raw_parts = [
                part[1]
                for part in msg_data
                if isinstance(part, tuple) and isinstance(part[1], bytes)
            ]
            if not raw_parts:
                continue
            raw_message = b"\r\n".join(raw_parts)
            msg = email.message_from_bytes(raw_message)
            snippet = ""
            if len(raw_parts) > 1:
                snippet = raw_parts[-1].decode("utf-8", errors="replace")
            results.append({
                "id": uid.decode("ascii", errors="replace"),
                "subject": _decode_header(msg.get("Subject")) or "(no subject)",
                "from": _decode_header(msg.get("From")),
                "date": msg.get("Date", ""),
                "snippet": " ".join(snippet.split())[:500],
                "thread_id": "",
                "source": "imap",
            })

        imap.close()
        return {"results": results, "total": len(ids), "query": query, "source": "imap"}


# ---------------------------------------------------------------------------
# Gmail search
# ---------------------------------------------------------------------------

async def _gmail_search(args: dict[str, Any]) -> str:
    import asyncio

    import httpx

    query = args.get("query", "")
    max_results = min(int(args.get("max_results", 10)), 50)

    try:
        from spark_cli.google_connector import has_imap_credentials
        if has_imap_credentials():
            data = await asyncio.get_event_loop().run_in_executor(
                None,
                _gmail_search_imap_sync,
                query,
                max_results,
            )
            return json.dumps(data)
    except Exception as exc:
        logger.warning("gmail_search IMAP error: %s", exc)
        return json.dumps({"error": "imap_failed", "message": str(exc)})

    access_token = await _get_token_async()
    if not access_token:
        return _not_connected()

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                params={"q": query, "maxResults": max_results},
                headers=_gmail_headers(access_token),
            )
            resp.raise_for_status()
            data = resp.json()
            messages = data.get("messages", [])

            if not messages:
                return json.dumps({"results": [], "total": 0, "query": query})

            async def fetch_detail(msg_id: str) -> dict | None:
                try:
                    r = await client.get(
                        f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_id}",
                        params={"format": "metadata", "metadataHeaders": ["Subject", "From", "Date"]},
                        headers=_gmail_headers(access_token),
                    )
                    r.raise_for_status()
                    d = r.json()
                    hdrs = {h["name"]: h["value"] for h in d.get("payload", {}).get("headers", [])}
                    return {
                        "id": msg_id,
                        "subject": hdrs.get("Subject", "(no subject)"),
                        "from": hdrs.get("From", ""),
                        "date": hdrs.get("Date", ""),
                        "snippet": d.get("snippet", ""),
                        "thread_id": d.get("threadId", ""),
                    }
                except Exception as exc:
                    logger.debug("Failed to fetch message %s: %s", msg_id, exc)
                    return None

            details = await asyncio.gather(*[fetch_detail(m["id"]) for m in messages[:max_results]])
            results = [d for d in details if d is not None]

        return json.dumps({
            "results": results,
            "total": data.get("resultSizeEstimate", len(results)),
            "query": query,
        })

    except Exception as exc:
        if _is_scope_error(exc):
            return _insufficient_scope()
        logger.warning("gmail_search error: %s", exc)
        return json.dumps({"error": str(exc)})


registry.register(
    name="gmail_search",
    toolset="google_workspace",
    is_async=True,
    check_fn=_check_gmail_read_connected,
    schema={
        "name": "gmail_search",
        "description": (
            "Search Gmail messages (subject, sender, date, snippet). Uses Gmail "
            "IMAP App Password read access when configured; otherwise requires "
            "OAuth read access (gmail.modify/readonly)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Gmail search query (same syntax as Gmail search bar, e.g. 'from:alice subject:invoice is:unread')",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of messages to return (default 10, max 50)",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    },
    handler=_gmail_search,
    description="Search Gmail messages",
    emoji="📧",
)


# ---------------------------------------------------------------------------
# Calendar list events
# ---------------------------------------------------------------------------

async def _calendar_list_events(args: dict[str, Any]) -> str:
    from datetime import datetime

    import httpx

    access_token = await _get_token_async()
    if not access_token:
        return _not_connected()

    max_results = min(int(args.get("max_results", 10)), 50)
    calendar_id = args.get("calendar_id", "primary")
    time_min = args.get("time_min") or datetime.now(UTC).isoformat()

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events",
                params={
                    "maxResults": max_results,
                    "orderBy": "startTime",
                    "singleEvents": "true",
                    "timeMin": time_min,
                },
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            data = resp.json()

        events = []
        for item in data.get("items", []):
            start = item.get("start", {})
            end = item.get("end", {})
            events.append({
                "id": item.get("id"),
                "summary": item.get("summary", "(no title)"),
                "description": item.get("description", ""),
                "start": start.get("dateTime") or start.get("date"),
                "end": end.get("dateTime") or end.get("date"),
                "location": item.get("location", ""),
                "attendees": [a.get("email") for a in item.get("attendees", [])],
                "html_link": item.get("htmlLink", ""),
                "status": item.get("status", ""),
            })

        return json.dumps({
            "events": events,
            "calendar_id": calendar_id,
            "total": len(events),
        })

    except Exception as exc:
        logger.warning("calendar_list_events error: %s", exc)
        return json.dumps({"error": str(exc)})


registry.register(
    name="calendar_list_events",
    toolset="google_workspace",
    is_async=True,
    check_fn=_check_google_oauth_connected,
    schema={
        "name": "calendar_list_events",
        "description": "List upcoming Google Calendar events. Returns title, start/end time, location, and attendees.",
        "parameters": {
            "type": "object",
            "properties": {
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of events to return (default 10, max 50)",
                    "default": 10,
                },
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar ID to query (default: 'primary')",
                    "default": "primary",
                },
                "time_min": {
                    "type": "string",
                    "description": "ISO 8601 datetime for earliest event start (default: now)",
                },
            },
            "required": [],
        },
    },
    handler=_calendar_list_events,
    description="List upcoming Google Calendar events",
    emoji="📅",
)
