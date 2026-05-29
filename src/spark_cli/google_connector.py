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
from typing import Optional

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

GOOGLE_SCOPES = [
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]

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


# Spark's registered Google OAuth client (Desktop app type — public, no secret needed).
# See: https://console.cloud.google.com/apis/credentials
SPARK_GOOGLE_CLIENT_ID = "688733154744-3o0lgqp488dk3li23qpldld4r0qc3t3k.apps.googleusercontent.com"


def get_client_id() -> str:
    # Allow override via env or config, fall back to the baked-in app client ID
    return (
        os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
        or _get_google_config().get("client_id", "")
        or SPARK_GOOGLE_CLIENT_ID
    )


def get_client_secret() -> str:
    # Desktop app + PKCE requires no client_secret — this is intentionally empty
    return (
        os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
        or _get_google_config().get("client_secret", "")
        or ""
    )


def is_configured() -> bool:
    """Always True — client_id is baked in."""
    return True


# ---------------------------------------------------------------------------
# Token storage
# ---------------------------------------------------------------------------

def _token_path() -> Path:
    path = get_spark_home() / "connectors" / "google.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_token() -> Optional[dict]:
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


def clear_token() -> None:
    p = _token_path()
    if p.exists():
        p.unlink()


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
        "scope": " ".join(GOOGLE_SCOPES),
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


def get_valid_access_token() -> Optional[str]:
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


def get_connection_status() -> dict:
    """Return a status dict for the frontend."""
    token = load_token()
    if not token:
        return {
            "connected": False,
            "configured": is_configured(),
            "email": None,
            "name": None,
            "picture": None,
        }

    access_token = get_valid_access_token()
    if not access_token:
        return {
            "connected": False,
            "configured": is_configured(),
            "email": token.get("email"),
            "name": token.get("name"),
            "picture": token.get("picture"),
            "error": "token_expired",
        }

    # If we have cached profile info, return it without a network call
    if token.get("email"):
        return {
            "connected": True,
            "configured": is_configured(),
            "email": token.get("email"),
            "name": token.get("name"),
            "picture": token.get("picture"),
        }

    # Fetch and cache profile
    try:
        info = get_user_info(access_token)
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
        }
    except Exception as exc:
        logger.warning("Could not fetch Google user info: %s", exc)
        return {
            "connected": True,
            "configured": is_configured(),
            "email": None,
            "name": None,
            "picture": None,
        }
