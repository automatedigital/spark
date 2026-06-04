"""Tests for the connectors foundation (registry, base, Google connector).

These exercise the connector layer without requiring the real `gws` binary by
injecting a fake runner into GoogleWorkspaceConnector.
"""

import json
import os

from tools.connectors import (
    CONNECTOR_REGISTRY,
    Connector,
    ConnectorState,
    Transport,
    get_connector,
    list_connectors,
)
from tools.connectors.google import GoogleWorkspaceConnector, RunResult

# Realistic `gws auth status` payloads (gws exits 0 in BOTH cases).
_STATUS_LOGGED_OUT = json.dumps({"auth_method": "none", "storage": "none",
                                 "credential_source": "none"})


def _status_authed(email="user@example.com"):
    return json.dumps({"auth_method": "oauth", "storage": "file",
                       "credential_source": "encrypted", "email": email})

# --- registry --------------------------------------------------------------

def test_registry_lists_google():
    assert "google" in CONNECTOR_REGISTRY


def test_get_connector_returns_fresh_instances():
    a = get_connector("google")
    b = get_connector("google")
    assert isinstance(a, GoogleWorkspaceConnector)
    assert a is not b  # factory, not singleton


def test_get_connector_unknown_returns_none():
    assert get_connector("does-not-exist") is None


def test_list_connectors_instances():
    cons = list_connectors()
    assert all(isinstance(c, Connector) for c in cons)
    assert any(c.id == "google" for c in cons)


def test_describe_is_json_safe():
    desc = get_connector("google").describe()
    assert desc["id"] == "google"
    assert desc["transport"] == Transport.CLI.value
    assert "gmail.send" in " ".join(desc["scopes"])
    assert "gws-gmail" in desc["skills"]


# --- state dir isolation ---------------------------------------------------

def test_state_dir_under_spark_home(tmp_path, monkeypatch):
    # _isolate_spark_home already points SPARK_HOME at a temp dir.
    c = get_connector("google")
    d = c.state_dir()
    assert d.exists()
    assert d.name == "google"
    assert "connectors" in str(d)
    # must live under SPARK_HOME, never real ~/.spark
    assert str(d).startswith(os.environ["SPARK_HOME"])


def test_meta_roundtrip():
    c = get_connector("google")
    assert c.read_meta() == {}
    c.write_meta({"hello": "world"})
    assert c.read_meta()["hello"] == "world"
    # meta file must be 0600
    mode = (c.state_dir() / "meta.json").stat().st_mode & 0o777
    assert mode == 0o600


# --- client secret ---------------------------------------------------------

def test_install_client_secret_dict_and_perms():
    c = get_connector("google")
    assert not c.has_client_secret()
    c.install_client_secret({"installed": {"client_id": "abc"}})
    assert c.has_client_secret()
    p = c.state_dir() / "client_secret.json"
    assert "abc" in p.read_text()
    assert (p.stat().st_mode & 0o777) == 0o600


# --- status state machine (fake runner) ------------------------------------

def _connector_with(runner, *, installed=True, monkeypatch=None):
    c = GoogleWorkspaceConnector(runner=runner)
    if monkeypatch is not None:
        monkeypatch.setattr(c, "is_installed", lambda: installed)
    return c


def test_status_not_installed(monkeypatch):
    c = _connector_with(lambda *a, **k: RunResult(0), installed=False, monkeypatch=monkeypatch)
    st = c.status()
    assert st.state is ConnectorState.NOT_INSTALLED
    assert not st.connected


def test_status_connected_parses_email(monkeypatch):
    def runner(args, **kw):
        return RunResult(0, stdout=_status_authed("alice@example.com"))
    c = _connector_with(runner, monkeypatch=monkeypatch)
    st = c.status()
    assert st.state is ConnectorState.CONNECTED
    assert st.connected
    assert st.account == "alice@example.com"
    assert "gmail.send" in " ".join(st.scopes)


def test_status_disconnected_when_logged_out_json(monkeypatch):
    # The critical case: gws exits 0 but reports "none" — must NOT be connected.
    c = _connector_with(lambda *a, **k: RunResult(0, stdout=_STATUS_LOGGED_OUT),
                        monkeypatch=monkeypatch)
    st = c.status()
    assert st.state is ConnectorState.DISCONNECTED


def test_status_never_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("kaboom")
    c = _connector_with(boom, monkeypatch=monkeypatch)
    st = c.status()  # must swallow
    assert st.state is ConnectorState.ERROR
    assert "kaboom" in st.detail


# --- connect / disconnect --------------------------------------------------

def test_connect_not_installed(monkeypatch):
    c = _connector_with(lambda *a, **k: RunResult(0), installed=False, monkeypatch=monkeypatch)
    st = c.connect(interactive=False)
    assert st.state is ConnectorState.NOT_INSTALLED


def test_connect_success_then_status(monkeypatch):
    calls = []

    def runner(args, **kw):
        calls.append(tuple(args[:2]))
        if args[:2] == ["auth", "login"]:
            return RunResult(0)
        if args[:2] == ["auth", "status"]:
            return RunResult(0, stdout=_status_authed("bob@example.com"))
        return RunResult(1)

    c = _connector_with(runner, monkeypatch=monkeypatch)
    st = c.connect(interactive=False)
    assert st.connected
    assert st.account == "bob@example.com"
    assert ("auth", "login") in calls


def test_connect_installs_inline_secret(monkeypatch):
    c = _connector_with(lambda *a, **k: RunResult(0), monkeypatch=monkeypatch)
    c.connect(interactive=False, client_secret={"installed": {"client_id": "z"}})
    assert c.has_client_secret()


def test_connect_login_failure(monkeypatch):
    c = _connector_with(lambda *a, **k: RunResult(2, stderr="denied"),
                        monkeypatch=monkeypatch)
    st = c.connect(interactive=False)
    assert st.state is ConnectorState.DISCONNECTED
    assert "denied" in st.detail


def test_disconnect_removes_secret(monkeypatch):
    c = _connector_with(lambda *a, **k: RunResult(0), monkeypatch=monkeypatch)
    c.install_client_secret({"installed": {}})
    assert c.has_client_secret()
    st = c.disconnect()
    assert st.state is ConnectorState.DISCONNECTED
    assert not c.has_client_secret()


def test_auth_env_isolates_config_dir(monkeypatch):
    from tools.connectors.google import GWS_CONFIG_DIR_ENV, GWS_KEYRING_BACKEND_ENV
    c = _connector_with(lambda *a, **k: RunResult(0), monkeypatch=monkeypatch)
    # Even with no client secret, gws is pinned to a per-profile config dir.
    env = c._auth_env()
    assert env[GWS_CONFIG_DIR_ENV].endswith("gws-config")
    assert env[GWS_KEYRING_BACKEND_ENV] == "file"
    assert env[GWS_CONFIG_DIR_ENV].startswith(os.environ["SPARK_HOME"])


def test_auth_env_exposes_client_id_secret(monkeypatch):
    from tools.connectors.google import GWS_CLIENT_ID_ENV, GWS_CLIENT_SECRET_ENV
    c = _connector_with(lambda *a, **k: RunResult(0), monkeypatch=monkeypatch)
    c.install_client_secret({"installed": {"client_id": "cid-123", "client_secret": "sec-xyz"}})
    env = c._auth_env()
    assert env[GWS_CLIENT_ID_ENV] == "cid-123"
    assert env[GWS_CLIENT_SECRET_ENV] == "sec-xyz"


def test_read_client_id_secret_shapes(monkeypatch):
    c = _connector_with(lambda *a, **k: RunResult(0), monkeypatch=monkeypatch)
    # web shape
    c.install_client_secret({"web": {"client_id": "w", "client_secret": "ws"}})
    assert c._read_client_id_secret() == ("w", "ws")
    # flat shape
    c.install_client_secret({"client_id": "f", "client_secret": "fs"})
    assert c._read_client_id_secret() == ("f", "fs")


def test_connect_passes_free_tier_scopes(monkeypatch):
    seen = {}

    def runner(args, **kw):
        if args[:2] == ["auth", "login"]:
            seen["login"] = args
            return RunResult(0)
        return RunResult(0, stdout="x@y.com")

    c = _connector_with(runner, monkeypatch=monkeypatch)
    c.connect(interactive=False)
    assert "--scopes" in seen["login"]
    scope_arg = seen["login"][seen["login"].index("--scopes") + 1]
    assert "gmail.send" in scope_arg
    # never request restricted scopes
    assert "gmail.readonly" not in scope_arg
    assert "auth/drive\"" not in scope_arg  # not the full-drive scope
