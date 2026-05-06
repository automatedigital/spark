"""Dashboard authentication for LAN-safe Spark Web UI."""

from __future__ import annotations

import ipaddress
import os
import secrets
from pathlib import Path
from typing import Optional

from core.spark_constants import get_spark_home

_TOKEN_FILENAME = "dashboard.token"
_ENV_KEYS = ("SPARK_DASHBOARD_TOKEN", "SPARK_DASHBOARD_SECRET")


def dashboard_token_path() -> Path:
    return get_spark_home() / _TOKEN_FILENAME


def ensure_dashboard_token_file() -> str:
    """Ensure ``~/.spark/dashboard.token`` exists; return the secret string."""
    path = dashboard_token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raw = path.read_text(encoding="utf-8").strip()
        if raw:
            return raw
    token = secrets.token_urlsafe(32)
    path.write_text(token + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return token


def get_configured_dashboard_secret() -> str:
    """Resolve dashboard shared secret: env override, then token file."""
    for key in _ENV_KEYS:
        v = os.environ.get(key, "").strip()
        if v:
            return v
    p = dashboard_token_path()
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    return ""


def client_host_is_trusted_local(host: Optional[str]) -> bool:
    """True if TCP peer is loopback (safe to skip bearer token)."""
    if not host:
        return False
    # Starlette/FastAPI TestClient uses this synthetic host.
    if host == "testclient":
        return True
    try:
        ip = ipaddress.ip_address(host)
        return bool(getattr(ip, "is_loopback", False))
    except ValueError:
        return host in ("localhost", "::1")


def extract_bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


def validate_dashboard_request(
    client_host: Optional[str],
    authorization: Optional[str],
    *,
    require_for_remote: bool,
    secret: str,
    query_token: Optional[str] = None,
) -> bool:
    """Return True if the request may access protected API routes."""
    if not require_for_remote:
        return True
    if not secret:
        # Misconfiguration: treat as locked (deny remote) unless local
        if client_host_is_trusted_local(client_host):
            return True
        return False
    if client_host_is_trusted_local(client_host):
        return True
    bearer = extract_bearer_token(authorization)
    qtok = (query_token or "").strip()
    token = bearer or qtok or None
    return bool(token and secrets.compare_digest(token, secret))
