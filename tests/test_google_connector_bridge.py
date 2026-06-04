"""Tests for the gws CLI bridge in spark_cli.google_connector.

The bridge turns a stored web-OAuth token into a gws "authorized_user"
credentials file so the agent can drive Google through the gws CLI.
"""

import json
import os

import spark_cli.google_connector as gc


def _configure(monkeypatch, *, cid="cid", csecret="csec"):
    monkeypatch.setattr(gc, "get_client_id", lambda: cid)
    monkeypatch.setattr(gc, "get_client_secret", lambda: csecret)


def test_default_scopes_are_read_write():
    joined = " ".join(gc.DEFAULT_GOOGLE_SCOPES)
    # read/write Gmail + full Drive by default (free for self-host test users)
    assert "gmail.modify" in joined
    assert "gmail.send" in joined
    assert "auth/calendar" in joined


def test_get_scopes_default(monkeypatch):
    monkeypatch.setattr(gc, "_get_google_config", lambda: {})
    assert gc.get_scopes() == gc.DEFAULT_GOOGLE_SCOPES


def test_get_scopes_config_override(monkeypatch):
    # A public/send-only build can dial scopes back via config.yaml.
    custom = ["openid", "email", "https://www.googleapis.com/auth/gmail.send"]
    monkeypatch.setattr(gc, "_get_google_config", lambda: {"scopes": custom})
    assert gc.get_scopes() == custom


def test_build_gws_credentials_shape(monkeypatch):
    _configure(monkeypatch)
    creds = gc.build_gws_credentials({"refresh_token": "rt-123"})
    assert creds == {
        "client_id": "cid",
        "client_secret": "csec",
        "refresh_token": "rt-123",
        "type": "authorized_user",
    }


def test_build_gws_credentials_none_without_refresh(monkeypatch):
    _configure(monkeypatch)
    assert gc.build_gws_credentials({"access_token": "x"}) is None


def test_build_gws_credentials_none_without_client(monkeypatch):
    monkeypatch.setattr(gc, "get_client_id", lambda: "")
    monkeypatch.setattr(gc, "get_client_secret", lambda: "")
    assert gc.build_gws_credentials({"refresh_token": "rt"}) is None


def test_write_gws_credentials_file_perms(monkeypatch):
    _configure(monkeypatch)
    path = gc.write_gws_credentials_file({"refresh_token": "rt-123"})
    assert path is not None and path.exists()
    assert (path.stat().st_mode & 0o777) == 0o600
    data = json.loads(path.read_text())
    assert data["type"] == "authorized_user"
    assert data["refresh_token"] == "rt-123"
    assert str(path).startswith(os.environ["SPARK_HOME"])


def test_gws_env_empty_when_disconnected(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(gc, "load_token", lambda: None)
    assert gc.gws_env() == {}


def test_gws_env_points_at_file_when_connected(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(gc, "load_token", lambda: {"refresh_token": "rt"})
    env = gc.gws_env()
    assert "GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE" in env
    assert env["GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE"].endswith("gws-credentials.json")


def test_save_token_writes_bridge(monkeypatch):
    _configure(monkeypatch)
    gc.save_token({"refresh_token": "rt-xyz", "email": "a@b.com"})
    assert gc._gws_credentials_path().exists()
    creds = json.loads(gc._gws_credentials_path().read_text())
    assert creds["refresh_token"] == "rt-xyz"


def test_clear_token_removes_bridge(monkeypatch):
    _configure(monkeypatch)
    gc.save_token({"refresh_token": "rt"})
    assert gc._gws_credentials_path().exists()
    gc.clear_token()
    assert not gc._gws_credentials_path().exists()
    assert not gc._token_path().exists()


def test_get_relay_url_and_is_configured(monkeypatch):
    monkeypatch.setattr(gc, "_get_google_config", lambda: {"relay_url": "https://relay.example/"})
    monkeypatch.delenv("GOOGLE_OAUTH_RELAY_URL", raising=False)
    assert gc.get_relay_url() == "https://relay.example"  # trailing slash stripped
    # relay alone makes the connector "configured" (no local client needed)
    monkeypatch.setattr(gc, "get_client_id", lambda: "")
    monkeypatch.setattr(gc, "get_client_secret", lambda: "")
    assert gc.is_configured() is True


def test_refresh_uses_relay_when_no_secret(monkeypatch):
    monkeypatch.setattr(gc, "get_relay_url", lambda: "https://relay.example")
    monkeypatch.setattr(gc, "get_client_secret", lambda: "")
    captured = {}

    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return {"access_token": "AT2", "expires_in": 3600}

    def fake_post(url, **kw):
        captured["url"] = url
        captured["json"] = kw.get("json")
        return FakeResp()

    monkeypatch.setattr(gc.httpx, "post", fake_post)
    out = gc.refresh_access_token({"refresh_token": "RT"})
    assert captured["url"] == "https://relay.example/refresh"
    assert captured["json"] == {"refresh_token": "RT"}
    assert out["access_token"] == "AT2"
    assert "expires_at" in out


def test_claim_relay_tokens(monkeypatch):
    monkeypatch.setattr(gc, "get_relay_url", lambda: "https://relay.example")

    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return {"access_token": "AT", "refresh_token": "RT", "expires_in": 3600}

    monkeypatch.setattr(gc.httpx, "post", lambda url, **kw: FakeResp())
    tok = gc.claim_relay_tokens("ticket-123")
    assert tok["refresh_token"] == "RT"
    assert "expires_at" in tok


def test_gws_bridge_inactive_in_relay_mode(monkeypatch):
    # No client_secret in relay mode → no authorized_user creds → bridge off.
    monkeypatch.setattr(gc, "get_client_id", lambda: "")
    monkeypatch.setattr(gc, "get_client_secret", lambda: "")
    assert gc.build_gws_credentials({"refresh_token": "RT"}) is None


def test_apply_process_env_sets_and_clears(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.delenv(gc.GWS_CREDENTIALS_ENV, raising=False)
    # Connected → var present and points at the bridge file.
    gc.save_token({"refresh_token": "rt"})  # save_token calls apply_process_env
    assert gc.GWS_CREDENTIALS_ENV in os.environ
    assert os.environ[gc.GWS_CREDENTIALS_ENV].endswith("gws-credentials.json")
    # Disconnected → var removed.
    gc.clear_token()
    assert gc.GWS_CREDENTIALS_ENV not in os.environ
