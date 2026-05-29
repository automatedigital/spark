"""
Google Workspace tools for Spark Agent.

Tools activate automatically when a Google OAuth token is present.
Connect via the Connectors tab in the web dashboard.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from tools.registry import registry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_token() -> str | None:
    try:
        from spark_cli.google_connector import get_valid_access_token
        return get_valid_access_token()
    except Exception:
        return None


def _not_connected() -> str:
    return json.dumps({
        "error": "not_connected",
        "message": "Google Workspace is not connected. Open the Connectors tab in the dashboard and click 'Connect Google'.",
    })


def _gmail_headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


# ---------------------------------------------------------------------------
# Gmail search
# ---------------------------------------------------------------------------

def _gmail_search(args: dict[str, Any]) -> str:
    import httpx

    access_token = _get_token()
    if not access_token:
        return _not_connected()

    query = args.get("query", "")
    max_results = min(int(args.get("max_results", 10)), 50)

    try:
        resp = httpx.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            params={"q": query, "maxResults": max_results},
            headers=_gmail_headers(access_token),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        messages = data.get("messages", [])

        if not messages:
            return json.dumps({"results": [], "total": 0, "query": query})

        # Fetch snippets for each message
        results = []
        for msg in messages[:max_results]:
            try:
                detail = httpx.get(
                    f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg['id']}",
                    params={"format": "metadata", "metadataHeaders": ["Subject", "From", "Date"]},
                    headers=_gmail_headers(access_token),
                    timeout=10,
                )
                detail.raise_for_status()
                d = detail.json()
                headers = {
                    h["name"]: h["value"]
                    for h in d.get("payload", {}).get("headers", [])
                }
                results.append({
                    "id": msg["id"],
                    "subject": headers.get("Subject", "(no subject)"),
                    "from": headers.get("From", ""),
                    "date": headers.get("Date", ""),
                    "snippet": d.get("snippet", ""),
                    "thread_id": d.get("threadId", ""),
                })
            except Exception as exc:
                logger.debug("Failed to fetch message %s: %s", msg["id"], exc)

        return json.dumps({
            "results": results,
            "total": data.get("resultSizeEstimate", len(results)),
            "query": query,
        })

    except Exception as exc:
        logger.warning("gmail_search error: %s", exc)
        return json.dumps({"error": str(exc)})


registry.register(
    name="gmail_search",
    toolset="google_workspace",
    schema={
        "name": "gmail_search",
        "description": "Search Gmail messages. Returns subject, sender, date, and snippet for each result.",
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

def _calendar_list_events(args: dict[str, Any]) -> str:
    import httpx
    from datetime import datetime, timezone

    access_token = _get_token()
    if not access_token:
        return _not_connected()

    max_results = min(int(args.get("max_results", 10)), 50)
    calendar_id = args.get("calendar_id", "primary")
    time_min = args.get("time_min") or datetime.now(timezone.utc).isoformat()

    try:
        resp = httpx.get(
            f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events",
            params={
                "maxResults": max_results,
                "orderBy": "startTime",
                "singleEvents": "true",
                "timeMin": time_min,
            },
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
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
                "attendees": [
                    a.get("email") for a in item.get("attendees", [])
                ],
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
