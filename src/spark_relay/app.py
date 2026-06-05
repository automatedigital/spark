"""FastAPI app for the Spark OAuth relay.

Run with: ``uvicorn spark_relay.app:app --host 0.0.0.0 --port 8088``
Configure via environment variables (see ``config_from_env``).
"""

from __future__ import annotations

import logging
import os
import secrets
import urllib.parse
from dataclasses import dataclass, field

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

from spark_relay.crypto import sign_state, verify_state
from spark_relay.store import TTLStore

logger = logging.getLogger("spark_relay")

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

# Default scopes the shared client requests. Send-only / sensitive only (no CASA)
# until the shared OAuth app passes restricted-scope verification.
DEFAULT_RELAY_SCOPES = [
    "openid", "email", "profile",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/presentations",
]

STATE_TTL = 600   # /session → /callback
TICKET_TTL = 120  # /callback → /claim


@dataclass
class RelayConfig:
    client_id: str
    client_secret: str
    signing_secret: str
    redirect_uri: str                       # the relay's OWN registered callback
    scopes: list[str] = field(default_factory=lambda: list(DEFAULT_RELAY_SCOPES))
    token_url: str = GOOGLE_TOKEN_URL
    auth_url: str = GOOGLE_AUTH_URL

    def validate(self) -> list[str]:
        missing = [
            name for name, val in (
                ("RELAY_GOOGLE_CLIENT_ID", self.client_id),
                ("RELAY_GOOGLE_CLIENT_SECRET", self.client_secret),
                ("RELAY_SIGNING_SECRET", self.signing_secret),
                ("RELAY_REDIRECT_URI", self.redirect_uri),
            ) if not val
        ]
        return missing


def config_from_env(env: dict | None = None) -> RelayConfig:
    e = env if env is not None else os.environ
    scopes_raw = e.get("RELAY_SCOPES", "").strip()
    scopes = [s for s in scopes_raw.split(",") if s.strip()] if scopes_raw else list(DEFAULT_RELAY_SCOPES)
    return RelayConfig(
        client_id=e.get("RELAY_GOOGLE_CLIENT_ID", ""),
        client_secret=e.get("RELAY_GOOGLE_CLIENT_SECRET", ""),
        signing_secret=e.get("RELAY_SIGNING_SECRET", ""),
        redirect_uri=e.get("RELAY_REDIRECT_URI", ""),
        scopes=scopes,
    )


def _is_acceptable_callback(url: str) -> bool:
    """Only broker back to http(s) callbacks (basic anti-abuse)."""
    try:
        p = urllib.parse.urlparse(url)
    except ValueError:
        return False
    return p.scheme in ("http", "https") and bool(p.netloc)


def create_app(config: RelayConfig | None = None, store: TTLStore | None = None) -> FastAPI:
    cfg = config or config_from_env()
    st = store or TTLStore()
    app = FastAPI(title="Spark OAuth Relay")

    @app.get("/healthz")
    async def healthz():
        missing = cfg.validate()
        return JSONResponse({"ok": not missing, "missing_config": missing, "pending": len(st)})

    @app.post("/session")
    async def session(request: Request):
        """Start a flow. Body: {instance_callback, scopes?}. Returns {auth_url}."""
        if cfg.validate():
            return JSONResponse({"error": "relay_not_configured"}, status_code=503)
        body = await request.json()
        instance_callback = (body or {}).get("instance_callback", "")
        if not _is_acceptable_callback(instance_callback):
            return JSONResponse({"error": "invalid_instance_callback"}, status_code=400)

        # PKCE is generated and stored on the relay; the verifier never travels
        # with the browser, and tokens are exchanged here at /callback.
        import hashlib

        from spark_relay.crypto import _b64encode  # reuse encoder
        verifier = _b64encode(secrets.token_bytes(32))
        challenge = _b64encode(hashlib.sha256(verifier.encode()).digest())

        nonce = secrets.token_urlsafe(16)
        state = sign_state({"cb": instance_callback, "n": nonce}, cfg.signing_secret, ttl=STATE_TTL)
        st.set(f"state:{state}", {"verifier": verifier, "cb": instance_callback}, STATE_TTL)

        scopes = body.get("scopes") if isinstance(body.get("scopes"), list) else cfg.scopes
        params = {
            "client_id": cfg.client_id,
            "redirect_uri": cfg.redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent",
        }
        return JSONResponse({"auth_url": f"{cfg.auth_url}?{urllib.parse.urlencode(params)}"})

    @app.get("/callback")
    async def callback(code: str | None = None, state: str | None = None,
                       error: str | None = None):
        """Google redirects here. Exchange the code, then 302 back to the instance."""
        payload = verify_state(state or "", cfg.signing_secret)
        record = st.pop(f"state:{state}") if state else None
        if not payload or not record:
            return JSONResponse({"error": "invalid_or_expired_state"}, status_code=400)
        instance_cb = record["cb"]

        if error:
            return RedirectResponse(_with_query(instance_cb, {"error": error}))

        try:
            tokens = await _exchange_code(cfg, code or "", record["verifier"])
        except Exception as exc:
            logger.warning("relay token exchange failed: %s", exc)
            return RedirectResponse(_with_query(instance_cb, {"error": "exchange_failed"}))

        ticket = secrets.token_urlsafe(32)
        st.set(f"ticket:{ticket}", tokens, TICKET_TTL)
        return RedirectResponse(_with_query(instance_cb, {"ticket": ticket}))

    @app.post("/claim")
    async def claim(request: Request):
        """Instance redeems a one-time ticket for the tokens."""
        body = await request.json()
        ticket = (body or {}).get("ticket", "")
        tokens = st.pop(f"ticket:{ticket}") if ticket else None
        if not tokens:
            return JSONResponse({"error": "invalid_or_used_ticket"}, status_code=400)
        return JSONResponse(tokens)

    @app.post("/refresh")
    async def refresh(request: Request):
        """Refresh an access token on the instance's behalf.

        In relay mode the instance never holds the shared client_secret, so it
        cannot refresh directly with Google. It posts its refresh_token here and
        the relay (which holds the secret) returns a fresh access token.
        """
        if cfg.validate():
            return JSONResponse({"error": "relay_not_configured"}, status_code=503)
        body = await request.json()
        refresh_token = (body or {}).get("refresh_token", "")
        if not refresh_token:
            return JSONResponse({"error": "missing_refresh_token"}, status_code=400)
        try:
            tokens = await _refresh_token(cfg, refresh_token)
        except Exception as exc:
            logger.warning("relay /refresh failed: %s", exc)
            return JSONResponse({"error": "refresh_failed"}, status_code=502)
        return JSONResponse(tokens)

    return app


def _with_query(url: str, extra: dict) -> str:
    parts = list(urllib.parse.urlparse(url))
    q = dict(urllib.parse.parse_qsl(parts[4]))
    q.update(extra)
    parts[4] = urllib.parse.urlencode(q)
    return urllib.parse.urlunparse(parts)


async def _exchange_code(cfg: RelayConfig, code: str, verifier: str) -> dict:
    payload = {
        "client_id": cfg.client_id,
        "client_secret": cfg.client_secret,
        "code": code,
        "code_verifier": verifier,
        "grant_type": "authorization_code",
        "redirect_uri": cfg.redirect_uri,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(cfg.token_url, data=payload)
        resp.raise_for_status()
        return resp.json()


async def _refresh_token(cfg: RelayConfig, refresh_token: str) -> dict:
    payload = {
        "client_id": cfg.client_id,
        "client_secret": cfg.client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(cfg.token_url, data=payload)
        resp.raise_for_status()
        return resp.json()


# Module-level app for `uvicorn spark_relay.app:app`
app = create_app()
