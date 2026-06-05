"""Generic OAuth support for connector catalog entries.

This intentionally supports two modes:

* local/desktop with bundled or configured provider clients
* VPS/BYO with per-instance provider client credentials

A hosted relay can replace the local exchange later without changing the UI
contract: POST /api/connectors/{id}/connect still returns an auth_url.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

import httpx

from core.spark_constants import get_spark_home


@dataclass(frozen=True)
class OAuthProvider:
    id: str
    name: str
    auth_url: str
    token_url: str
    scopes: tuple[str, ...]
    userinfo_url: str = ""
    user_field: str = "login"
    requires_secret: bool = True
    device_code_url: str = ""


OAUTH_PROVIDERS: dict[str, OAuthProvider] = {
    "github": OAuthProvider(
        id="github",
        name="GitHub",
        auth_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        scopes=("repo", "read:user", "user:email"),
        userinfo_url="https://api.github.com/user",
        user_field="login",
        requires_secret=False,
        device_code_url="https://github.com/login/device/code",
    ),
    "notion": OAuthProvider(
        id="notion",
        name="Notion",
        auth_url="https://api.notion.com/v1/oauth/authorize",
        token_url="https://api.notion.com/v1/oauth/token",
        scopes=(),
        user_field="workspace_name",
    ),
    "hubspot": OAuthProvider(
        id="hubspot",
        name="HubSpot",
        auth_url="https://app.hubspot.com/oauth/authorize",
        token_url="https://api.hubapi.com/oauth/v1/token",
        scopes=("crm.objects.contacts.read", "crm.objects.contacts.write"),
        userinfo_url="https://api.hubapi.com/oauth/v1/access-tokens/{access_token}",
        user_field="hub_domain",
    ),
    "asana": OAuthProvider(
        id="asana",
        name="Asana",
        auth_url="https://app.asana.com/-/oauth_authorize",
        token_url="https://app.asana.com/-/oauth_token",
        scopes=("default",),
        userinfo_url="https://app.asana.com/api/1.0/users/me",
        user_field="email",
    ),
    "airtable": OAuthProvider(
        id="airtable",
        name="Airtable",
        auth_url="https://airtable.com/oauth2/v1/authorize",
        token_url="https://airtable.com/oauth2/v1/token",
        scopes=("data.records:read", "data.records:write", "schema.bases:read"),
        userinfo_url="https://api.airtable.com/v0/meta/whoami",
        user_field="email",
    ),
}


def token_path(provider_id: str) -> Path:
    path = get_spark_home() / "connectors" / provider_id / "oauth.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_token(provider_id: str) -> dict | None:
    path = token_path(provider_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_token(provider_id: str, token: dict) -> None:
    if provider_id == "github":
        token["github_cli_sync"] = sync_github_cli(token)
    token_path(provider_id).write_text(json.dumps(token, indent=2), encoding="utf-8")
    try:
        os.chmod(token_path(provider_id), 0o600)
    except OSError:
        pass


def clear_token(provider_id: str) -> None:
    path = token_path(provider_id)
    if path.exists():
        path.unlink()


def token_status(provider_id: str) -> tuple[bool, str | None]:
    token = load_token(provider_id)
    if not token:
        return False, None
    account = token.get("account") or token.get("email") or token.get("workspace_name")
    return True, str(account) if account else None


def sync_status(provider_id: str) -> dict:
    token = load_token(provider_id) or {}
    if provider_id != "github":
        return {}
    return token.get("github_cli_sync") or {}


def sync_github_cli(token: dict) -> dict:
    """Import the GitHub OAuth token into gh's auth store when gh is present."""
    access_token = str(token.get("access_token") or "").strip()
    if not access_token:
        return {"synced": False, "reason": "missing_token"}
    gh_bin = _resolve_bin("gh") or _install_github_cli()
    if not gh_bin:
        return {"synced": False, "reason": "gh_not_installed"}
    try:
        proc = subprocess.run(
            [gh_bin, "auth", "login", "--hostname", "github.com", "--with-token"],
            input=f"{access_token}\n",
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"synced": False, "reason": "gh_login_failed", "detail": str(exc)}
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        return {
            "synced": False,
            "reason": "gh_login_failed",
            "detail": detail[:240],
        }
    return {"synced": True, "host": "github.com"}


def _provider_config(provider_id: str) -> dict:
    try:
        from spark_cli.config import load_config

        cfg = load_config()
        return ((cfg.get("connectors") or {}).get(provider_id) or {}).get("oauth", {}) or {}
    except Exception:
        return {}


def client_credentials(provider_id: str) -> tuple[str, str]:
    env_prefix = provider_id.upper().replace("-", "_")
    cfg = _provider_config(provider_id)
    client_id = (
        os.environ.get(f"{env_prefix}_OAUTH_CLIENT_ID")
        or os.environ.get(f"SPARK_{env_prefix}_OAUTH_CLIENT_ID")
        or _bundled_public_client_id(provider_id)
        or cfg.get("client_id", "")
    )
    client_secret = (
        os.environ.get(f"{env_prefix}_OAUTH_CLIENT_SECRET")
        or os.environ.get(f"SPARK_{env_prefix}_OAUTH_CLIENT_SECRET")
        or cfg.get("client_secret", "")
    )
    return str(client_id or ""), str(client_secret or "")


def _bundled_public_client_id(provider_id: str) -> str:
    if provider_id == "github":
        return os.environ.get("SPARK_DESKTOP_GITHUB_CLIENT_ID") or "Ov23li006d76L74vToM4"
    return ""


def is_configured(provider_id: str) -> bool:
    provider = OAUTH_PROVIDERS.get(provider_id)
    if not provider:
        return False
    client_id, client_secret = client_credentials(provider_id)
    return bool(client_id and (client_secret or not provider.requires_secret))


def generate_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def build_auth_url(provider_id: str, *, state: str, code_challenge: str, redirect_uri: str) -> str:
    provider = OAUTH_PROVIDERS[provider_id]
    client_id, _ = client_credentials(provider_id)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "state": state,
    }
    if provider.scopes:
        params["scope"] = " ".join(provider.scopes)
    # Providers that don't use PKCE generally ignore these extra parameters.
    params["code_challenge"] = code_challenge
    params["code_challenge_method"] = "S256"
    if provider_id == "notion":
        params["owner"] = "user"
    return f"{provider.auth_url}?{urlencode(params)}"


def exchange_code(
    provider_id: str,
    *,
    code: str,
    code_verifier: str,
    redirect_uri: str,
) -> dict:
    provider = OAUTH_PROVIDERS[provider_id]
    client_id, client_secret = client_credentials(provider_id)
    data = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code": code,
        "code_verifier": code_verifier,
    }
    if client_secret:
        data["client_secret"] = client_secret
    headers = {"Accept": "application/json"}
    if provider_id == "notion" and client_secret:
        auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        headers["Authorization"] = f"Basic {auth}"
        data.pop("client_id", None)
        data.pop("client_secret", None)
    resp = httpx.post(provider.token_url, data=data, headers=headers, timeout=20)
    resp.raise_for_status()
    token = resp.json()
    if "expires_in" in token and "expires_at" not in token:
        token["expires_at"] = int(time.time()) + int(token["expires_in"])
    return token


def request_device_code(provider_id: str) -> dict:
    provider = OAUTH_PROVIDERS[provider_id]
    if not provider.device_code_url:
        raise ValueError(f"{provider.name} does not support device flow")
    client_id, _ = client_credentials(provider_id)
    if not client_id:
        raise ValueError(f"{provider.name} OAuth client_id is not configured")
    resp = httpx.post(
        provider.device_code_url,
        data={
            "client_id": client_id,
            "scope": " ".join(provider.scopes),
        },
        headers={"Accept": "application/json"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def poll_device_code(provider_id: str, device_code: str) -> dict:
    provider = OAUTH_PROVIDERS[provider_id]
    client_id, _ = client_credentials(provider_id)
    resp = httpx.post(
        provider.token_url,
        data={
            "client_id": client_id,
            "device_code": device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        },
        headers={"Accept": "application/json"},
        timeout=15,
    )
    resp.raise_for_status()
    token = resp.json()
    if "expires_in" in token and "expires_at" not in token:
        token["expires_at"] = int(time.time()) + int(token["expires_in"])
    return token


def enrich_token(provider_id: str, token: dict) -> dict:
    provider = OAUTH_PROVIDERS[provider_id]
    access_token = token.get("access_token")
    if not access_token:
        return token
    if provider_id == "notion":
        token["account"] = token.get("workspace_name") or token.get("bot_id")
        return token
    if not provider.userinfo_url:
        return token
    url = provider.userinfo_url.format(access_token=access_token)
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    try:
        resp = httpx.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if provider_id == "asana":
            data = data.get("data") or data
        account = data.get(provider.user_field) or data.get("email") or data.get("login")
        if account:
            token["account"] = account
    except Exception:
        pass
    return token


def _resolve_bin(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for path in (
        Path("/opt/homebrew/bin") / name,
        Path("/usr/local/bin") / name,
        Path.home() / ".local" / "bin" / name,
    ):
        try:
            if path.is_file() and os.access(path, os.X_OK):
                return str(path)
        except OSError:
            continue
    return None


def _install_github_cli() -> str | None:
    """Best-effort desktop/local install for gh, currently macOS Homebrew."""
    import platform

    if platform.system() != "Darwin":
        return None
    brew = _resolve_bin("brew")
    if not brew:
        return None
    try:
        proc = subprocess.run(
            [brew, "install", "gh"],
            text=True,
            capture_output=True,
            check=False,
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return _resolve_bin("gh")
