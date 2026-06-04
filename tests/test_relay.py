"""Tests for the Spark OAuth relay (crypto, TTL store, broker flow)."""


import pytest
from fastapi.testclient import TestClient

from spark_relay.app import RelayConfig, create_app
from spark_relay.crypto import sign_state, verify_state
from spark_relay.store import TTLStore

# --- crypto ----------------------------------------------------------------

def test_sign_verify_roundtrip():
    tok = sign_state({"cb": "https://x/cb", "n": "abc"}, "secret")
    payload = verify_state(tok, "secret")
    assert payload["cb"] == "https://x/cb"
    assert payload["n"] == "abc"
    assert "exp" in payload


def test_verify_rejects_wrong_secret():
    tok = sign_state({"a": 1}, "secret")
    assert verify_state(tok, "other") is None


def test_verify_rejects_tamper():
    tok = sign_state({"cb": "https://good"}, "secret")
    body, _, sig = tok.partition(".")
    forged = sign_state({"cb": "https://evil"}, "secret").partition(".")[0] + "." + sig
    assert verify_state(forged, "secret") is None


def test_verify_rejects_expired():
    tok = sign_state({"a": 1}, "secret", ttl=-1)
    assert verify_state(tok, "secret") is None


def test_sign_requires_secret():
    with pytest.raises(ValueError):
        sign_state({"a": 1}, "")


# --- TTL store -------------------------------------------------------------

def test_store_set_pop():
    s = TTLStore()
    s.set("k", {"v": 1}, ttl=10)
    assert s.pop("k") == {"v": 1}
    assert s.pop("k") is None  # one-time


def test_store_expiry():
    s = TTLStore()
    s.set("k", "v", ttl=-1)
    assert s.pop("k") is None


def test_store_sweep():
    s = TTLStore()
    s.set("a", 1, ttl=-1)
    s.set("b", 2, ttl=100)
    assert s.sweep() == 1
    assert len(s) == 1


# --- broker flow -----------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    cfg = RelayConfig(
        client_id="cid",
        client_secret="csec",
        signing_secret="sign-secret",
        redirect_uri="https://relay.example/callback",
    )
    app = create_app(cfg, TTLStore())

    async def fake_exchange(_cfg, _code, _verifier):
        return {"access_token": "AT", "refresh_token": "RT", "expires_in": 3600}

    monkeypatch.setattr("spark_relay.app._exchange_code", fake_exchange)
    return TestClient(app)


def test_healthz_ok(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_healthz_reports_missing_config():
    app = create_app(RelayConfig("", "", "", ""), TTLStore())
    r = TestClient(app).get("/healthz")
    assert r.json()["ok"] is False
    assert "RELAY_GOOGLE_CLIENT_ID" in r.json()["missing_config"]


def test_session_returns_auth_url(client):
    r = client.post("/session", json={"instance_callback": "https://inst.example/oauth/google/callback"})
    assert r.status_code == 200
    url = r.json()["auth_url"]
    assert "accounts.google.com" in url
    assert "code_challenge=" in url
    assert "client_id=cid" in url
    assert "redirect_uri=https%3A%2F%2Frelay.example%2Fcallback" in url


def test_session_rejects_bad_callback(client):
    r = client.post("/session", json={"instance_callback": "ftp://nope"})
    assert r.status_code == 400


def test_session_503_when_unconfigured():
    app = create_app(RelayConfig("", "", "", ""), TTLStore())
    r = TestClient(app).post("/session", json={"instance_callback": "https://x/cb"})
    assert r.status_code == 503


def test_full_flow_session_callback_claim(client):
    inst_cb = "https://inst.example/oauth/google/callback"
    # 1. session → auth_url with state
    r = client.post("/session", json={"instance_callback": inst_cb})
    auth_url = r.json()["auth_url"]
    import urllib.parse
    state = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(auth_url).query))["state"]

    # 2. Google → /callback (mocked exchange) → 302 back to instance with ticket
    r = client.get(
        "/callback", params={"code": "auth-code", "state": state},
        follow_redirects=False,
    )
    assert r.status_code in (302, 307)
    loc = r.headers["location"]
    assert loc.startswith(inst_cb)
    ticket = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(loc).query))["ticket"]

    # 3. instance claims the ticket → tokens (once)
    r = client.post("/claim", json={"ticket": ticket})
    assert r.status_code == 200
    assert r.json()["refresh_token"] == "RT"
    # ticket is single-use
    assert client.post("/claim", json={"ticket": ticket}).status_code == 400


def test_callback_rejects_unknown_state(client):
    r = client.get("/callback", params={"code": "x", "state": "bogus"}, follow_redirects=False)
    assert r.status_code == 400


def test_callback_propagates_google_error(client):
    inst_cb = "https://inst.example/cb"
    auth_url = client.post("/session", json={"instance_callback": inst_cb}).json()["auth_url"]
    import urllib.parse
    state = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(auth_url).query))["state"]
    r = client.get(
        "/callback", params={"state": state, "error": "access_denied"},
        follow_redirects=False,
    )
    assert r.status_code in (302, 307)
    assert "error=access_denied" in r.headers["location"]
