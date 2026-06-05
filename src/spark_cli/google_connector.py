"""
Google Workspace OAuth connector for Spark Agent.

Handles the full OAuth 2.0 Authorization Code + PKCE flow for Google APIs.
Tokens are stored in ~/.spark/connectors/google.json and auto-refreshed.

To enable: register a Google OAuth app at https://console.cloud.google.com/
    - Application type: "Web application"
    - Authorized redirect URIs: http://localhost:9119/oauth/google/callback
      (add additional ports if your dashboard runs on a different port)
Then set your client ID + secret in config.yaml:
    connectors:
      google:
        client_id: "your-client-id.apps.googleusercontent.com"
        client_secret: "your-client-secret"
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import time
from pathlib import Path

import httpx

from core.spark_constants import get_spark_home

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"

# Default scopes: PUBLIC + FREE set ("sensitive", not "restricted").
#
# Product decision: the app must be public (no 100-test-user cap), so it can only
# use scopes that pass FREE Google verification — i.e. *sensitive* scopes, never
# *restricted* ones. Restricted scopes (gmail.modify/readonly, full drive) would
# force the paid annual CASA assessment to publish. Consequently:
#   * Gmail is SEND-ONLY (gmail.send is sensitive; reading needs restricted scope).
#   * Drive is limited to drive.file (files the app creates or the user opens).
#   * Calendar / Docs / Sheets / Slides get full access (all sensitive).
#
# A deployment that DOES pursue CASA can opt into reading via config.yaml:
#   connectors:
#     google:
#       scopes: ["openid","email","profile",
#                "https://www.googleapis.com/auth/gmail.modify", ...]
DEFAULT_GOOGLE_SCOPES = [
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/gmail.send",        # send/compose (sensitive)
    "https://www.googleapis.com/auth/drive.file",         # app-created / user-picked files
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/presentations",
]


def get_scopes() -> list[str]:
    """Return the OAuth scopes to request, overridable via config.yaml.

    ``connectors.google.scopes`` (a list of scope URLs) replaces the defaults
    entirely, letting public/restricted-distribution builds dial scopes back.
    """
    override = _get_google_config().get("scopes")
    if isinstance(override, list) and override:
        return [str(s) for s in override]
    return list(DEFAULT_GOOGLE_SCOPES)


# Back-compat alias (some callers import GOOGLE_SCOPES directly).
GOOGLE_SCOPES = DEFAULT_GOOGLE_SCOPES

TOKEN_EXPIRY_SKEW_SECONDS = 120  # refresh 2 min before actual expiry


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _get_google_config() -> dict:
    """Load Google connector config from config.yaml."""
    try:
        from spark_cli.config import load_config
        config = load_config()
        return config.get("connectors", {}).get("google", {})
    except Exception:
        return {}


def _bundled_client() -> tuple[str, str]:
    """Bundled desktop client, but only on local/desktop installs (never a VPS).

    A bundled localhost client is useless on a server (the remote browser can't
    reach the instance's localhost), so on a server environment we ignore it and
    require BYO credentials.
    """
    try:
        from core.spark_constants import is_server_environment
        if is_server_environment():
            return "", ""
        from spark_cli.bundled_oauth import get_bundled_client
        return get_bundled_client()
    except Exception:
        return "", ""


def get_client_id() -> str:
    return (
        os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
        or _get_google_config().get("client_id", "")
        or _bundled_client()[0]
    )


def get_client_secret() -> str:
    return (
        os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
        or _get_google_config().get("client_secret", "")
        or _bundled_client()[1]
    )


def get_relay_url() -> str:
    """Base URL of the shared OAuth relay, if this instance uses one.

    When set (``connectors.google.relay_url`` or ``GOOGLE_OAUTH_RELAY_URL``), the
    connect flow is brokered through the relay (one-click, no per-instance OAuth
    client) instead of a locally-configured client.
    """
    url = (
        os.environ.get("GOOGLE_OAUTH_RELAY_URL")
        or _get_google_config().get("relay_url", "")
    )
    return url.rstrip("/")


def is_configured() -> bool:
    """True if we can start a connect flow — via a relay or a local client."""
    return bool(get_relay_url()) or bool(get_client_id() and get_client_secret())


def claim_relay_tokens(ticket: str) -> dict:
    """Redeem a one-time relay ticket for tokens. Raises on failure."""
    relay = get_relay_url()
    if not relay:
        raise ValueError("no relay_url configured")
    resp = httpx.post(f"{relay}/claim", json={"ticket": ticket}, timeout=15)
    resp.raise_for_status()
    token = resp.json()
    if "expires_in" in token and "expires_at" not in token:
        token["expires_at"] = int(time.time()) + int(token["expires_in"])
    return token


# ---------------------------------------------------------------------------
# Token storage
# ---------------------------------------------------------------------------

def _token_path() -> Path:
    path = get_spark_home() / "connectors" / "google.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_token() -> dict | None:
    """Load the stored Google token, or None if not connected."""
    p = _token_path()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def save_token(token: dict) -> None:
    _token_path().write_text(json.dumps(token, indent=2))
    # Keep the gws bridge credentials file in sync so the agent's gws CLI (and
    # gws-* skills) can authenticate and self-refresh from the same connection.
    try:
        write_gws_credentials_file(token)
        apply_process_env()
    except Exception as exc:  # never let the bridge break the core save
        logger.warning("Could not write gws bridge credentials: %s", exc)


def clear_token() -> None:
    for p in (_token_path(), _gws_credentials_path()):
        if p.exists():
            p.unlink()
    apply_process_env()


# ---------------------------------------------------------------------------
# Gmail IMAP App Password storage
# ---------------------------------------------------------------------------

def _imap_credentials_path() -> Path:
    path = get_spark_home() / "connectors" / "google" / "gmail-imap.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_imap_credentials() -> dict | None:
    """Load Gmail IMAP credentials, or None if inbox read is not configured."""
    p = _imap_credentials_path()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_imap_credentials(email_address: str, app_password: str) -> None:
    """Store Gmail IMAP App Password credentials (0600), profile-scoped."""
    email_address = email_address.strip()
    normalized_password = app_password.replace(" ", "").strip()
    if not email_address or "@" not in email_address:
        raise ValueError("A valid Gmail address is required")
    if len(normalized_password) < 12:
        raise ValueError("A Gmail App Password is required")

    data = {
        "email": email_address,
        "app_password": normalized_password,
        "imap_host": "imap.gmail.com",
        "imap_port": 993,
        "saved_at": int(time.time()),
    }
    path = _imap_credentials_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def clear_imap_credentials() -> None:
    p = _imap_credentials_path()
    if p.exists():
        p.unlink()


def has_imap_credentials() -> bool:
    return load_imap_credentials() is not None


def imap_status() -> dict:
    creds = load_imap_credentials()
    if not creds:
        return {"connected": False, "email": None}
    return {"connected": True, "email": creds.get("email")}


# ---------------------------------------------------------------------------
# gws CLI bridge — let the agent use the `gws` CLI from this same connection.
#
# The gws CLI reads an "authorized_user" credentials file pointed at by
# GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE and refreshes access tokens itself. We
# write that file from the refresh_token we already hold, so a single web-OAuth
# connect (which works on VPS, local web, and desktop) also powers gws.
# ---------------------------------------------------------------------------

def _gws_credentials_path() -> Path:
    path = get_spark_home() / "connectors" / "google" / "gws-credentials.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def build_gws_credentials(token: dict | None = None) -> dict | None:
    """Build the gws "authorized_user" credentials dict, or None if unavailable."""
    token = token if token is not None else load_token()
    if not token:
        return None
    refresh_token = token.get("refresh_token")
    client_id = get_client_id()
    client_secret = get_client_secret()
    if not (refresh_token and client_id and client_secret):
        return None
    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "type": "authorized_user",
    }


def write_gws_credentials_file(token: dict | None = None) -> Path | None:
    """Write the gws bridge credentials file (0600). Returns the path or None."""
    creds = build_gws_credentials(token)
    if creds is None:
        return None
    path = _gws_credentials_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(creds, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    return path


GWS_CREDENTIALS_ENV = "GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE"


def gws_env() -> dict[str, str]:
    """Environment that points the gws CLI at the bridge credentials, if present.

    Returns ``{}`` when not connected, so callers can unconditionally merge it.
    """
    path = _gws_credentials_path()
    if not path.exists():
        # Lazily materialize from a stored token if we have one.
        if write_gws_credentials_file() is None:
            return {}
    return {GWS_CREDENTIALS_ENV: str(path)}


def apply_process_env() -> None:
    """Mirror the gws bridge into ``os.environ`` for this Spark process.

    The agent runs ``gws`` (and ``gws-*`` skills) via the terminal tool, which
    inherits ``os.environ``. Setting the credentials-file var here makes those
    subprocesses authenticate from the active connection. Idempotent; clears the
    var when disconnected. Call at startup and after connect/disconnect.
    """
    env = gws_env()
    if env:
        os.environ.update(env)
    else:
        os.environ.pop(GWS_CREDENTIALS_ENV, None)


# ---------------------------------------------------------------------------
# PKCE helpers
# ---------------------------------------------------------------------------

def generate_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge)."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


# ---------------------------------------------------------------------------
# OAuth flow
# ---------------------------------------------------------------------------

def build_auth_url(state: str, code_challenge: str, redirect_uri: str) -> str:
    """Construct the Google OAuth authorization URL."""
    import urllib.parse

    params = {
        "client_id": get_client_id(),
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(get_scopes()),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",  # request refresh_token
        "prompt": "consent",       # always show consent to get refresh_token
    }
    return f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"


def exchange_code(code: str, code_verifier: str, redirect_uri: str) -> dict:
    """Exchange authorization code for access + refresh tokens."""
    payload: dict = {
        "client_id": get_client_id(),
        "code": code,
        "code_verifier": code_verifier,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }
    # Only include client_secret if one is configured (not needed for Desktop app + PKCE)
    secret = get_client_secret()
    if secret:
        payload["client_secret"] = secret

    resp = httpx.post(GOOGLE_TOKEN_URL, data=payload, timeout=15)
    if not resp.is_success:
        logger.error("Google token exchange failed %s: %s", resp.status_code, resp.text)
    resp.raise_for_status()
    token = resp.json()
    # Normalize: store absolute expiry timestamp
    if "expires_in" in token and "expires_at" not in token:
        token["expires_at"] = int(time.time()) + int(token["expires_in"])
    return token


def refresh_access_token(token: dict) -> dict:
    """Use the refresh_token to get a fresh access_token. Returns updated token dict."""
    refresh_token = token.get("refresh_token")
    if not refresh_token:
        raise ValueError("No refresh_token available — user must re-authorize")

    # Relay mode: we don't hold the shared client_secret, so the relay refreshes
    # on our behalf (it does hold the secret).
    relay = get_relay_url()
    if relay and not get_client_secret():
        resp = httpx.post(f"{relay}/refresh", json={"refresh_token": refresh_token}, timeout=15)
        resp.raise_for_status()
        new_data = resp.json()
        token.update(new_data)
        token["expires_at"] = int(time.time()) + int(new_data.get("expires_in", 3600))
        return token

    payload: dict = {
        "client_id": get_client_id(),
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    secret = get_client_secret()
    if secret:
        payload["client_secret"] = secret

    resp = httpx.post(GOOGLE_TOKEN_URL, data=payload, timeout=15)
    resp.raise_for_status()
    new_data = resp.json()
    # Merge: keep existing fields (especially refresh_token — Google may not re-issue it)
    token.update(new_data)
    token["expires_at"] = int(time.time()) + int(new_data.get("expires_in", 3600))
    return token


def get_valid_access_token() -> str | None:
    """Return a valid access token, refreshing if needed. None if not connected."""
    token = load_token()
    if not token:
        return None

    expires_at = token.get("expires_at", 0)
    if time.time() + TOKEN_EXPIRY_SKEW_SECONDS >= expires_at:
        try:
            token = refresh_access_token(token)
            save_token(token)
        except Exception as exc:
            logger.warning("Google token refresh failed: %s", exc)
            return None

    return token.get("access_token")


def get_user_info(access_token: str) -> dict:
    """Fetch the authenticated user's profile from Google."""
    resp = httpx.get(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def get_connection_status_async() -> dict:
    """Return a status dict for the frontend (async-safe)."""
    import asyncio
    token = load_token()
    imap = imap_status()
    if not token:
        return {
            "connected": False,
            "configured": is_configured(),
            "email": None,
            "name": None,
            "picture": None,
            "gmail_read": imap,
        }

    # Run the potentially-blocking token refresh in a thread
    access_token = await asyncio.get_event_loop().run_in_executor(None, get_valid_access_token)
    if not access_token:
        return {
            "connected": False,
            "configured": is_configured(),
            "email": token.get("email"),
            "name": token.get("name"),
            "picture": token.get("picture"),
            "error": "token_expired",
            "gmail_read": imap,
        }

    # If we have cached profile info, return it without a network call
    if token.get("email"):
        return {
            "connected": True,
            "configured": is_configured(),
            "email": token.get("email"),
            "name": token.get("name"),
            "picture": token.get("picture"),
            "gmail_read": imap,
        }

    # Fetch and cache profile (run in thread to avoid blocking event loop)
    try:
        import asyncio
        info = await asyncio.get_event_loop().run_in_executor(None, get_user_info, access_token)
        token["email"] = info.get("email")
        token["name"] = info.get("name")
        token["picture"] = info.get("picture")
        save_token(token)
        return {
            "connected": True,
            "configured": is_configured(),
            "email": token["email"],
            "name": token["name"],
            "picture": token["picture"],
            "gmail_read": imap,
        }
    except Exception as exc:
        logger.warning("Could not fetch Google user info: %s", exc)
        return {
            "connected": True,
            "configured": is_configured(),
            "email": None,
            "name": None,
            "picture": None,
            "gmail_read": imap,
        }
