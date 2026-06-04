"""HMAC-signed state tokens for the OAuth relay.

The relay embeds the originating instance's callback URL in the OAuth ``state``
parameter and signs it so Google's redirect can only be brokered back to a
callback the relay itself issued. Tokens are URL-safe and carry an expiry.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def sign_state(payload: dict[str, Any], secret: str, *, ttl: int = 600) -> str:
    """Return ``<body>.<sig>`` where body is base64(JSON) including an expiry."""
    if not secret:
        raise ValueError("signing secret must not be empty")
    data = dict(payload)
    data["exp"] = int(time.time()) + int(ttl)
    body = _b64encode(json.dumps(data, separators=(",", ":"), sort_keys=True).encode())
    sig = _b64encode(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_state(token: str, secret: str) -> dict[str, Any] | None:
    """Return the payload if signature + expiry are valid, else ``None``."""
    if not token or not secret or "." not in token:
        return None
    body, _, sig = token.partition(".")
    expected = _b64encode(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(_b64decode(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    return payload
