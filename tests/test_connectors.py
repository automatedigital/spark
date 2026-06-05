"""Tests for the connectors foundation (registry, base, Google adapter).

The Google connector is now a thin adapter over spark_cli.google_connector (the
web-OAuth engine) plus the gws CLI bridge. We exercise it by monkeypatching the
google_connector module functions.
"""

import os

from tools.connectors import (
    CONNECTOR_REGISTRY,
    Connector,
    ConnectorState,
    Transport,
    get_connector,
    list_connectors,
)
from tools.connectors.google import GoogleWorkspaceConnector

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
    # free tier must NOT advertise restricted read scopes
    assert "gmail.readonly" not in " ".join(desc["scopes"])
    assert "gws-drive" in desc["skills"]


# --- state dir isolation ---------------------------------------------------

def test_state_dir_under_spark_home():
    c = get_connector("google")
    d = c.state_dir()
    assert d.exists()
    assert d.name == "google"
    assert "connectors" in str(d)
    assert str(d).startswith(os.environ["SPARK_HOME"])


def test_meta_roundtrip():
    c = get_connector("google")
    assert c.read_meta() == {}
    c.write_meta({"hello": "world"})
    assert c.read_meta()["hello"] == "world"
    mode = (c.state_dir() / "meta.json").stat().st_mode & 0o777
    assert mode == 0o600


# --- status (adapter over google_connector) --------------------------------

def _patch_gc(monkeypatch, *, token=None, configured=True, gws_env=None):
    import spark_cli.google_connector as gc
    monkeypatch.setattr(gc, "load_token", lambda: token)
    monkeypatch.setattr(gc, "is_configured", lambda: configured)
    monkeypatch.setattr(gc, "gws_env", lambda: gws_env or {})
    monkeypatch.setattr(gc, "imap_status", lambda: {"connected": False, "email": None})
    return gc


def test_status_disconnected_when_no_token(monkeypatch):
    _patch_gc(monkeypatch, token=None, configured=True)
    st = get_connector("google").status()
    assert st.state is ConnectorState.DISCONNECTED
    assert "Connectors tab" in st.detail


def test_status_not_configured_message(monkeypatch):
    _patch_gc(monkeypatch, token=None, configured=False)
    st = get_connector("google").status()
    assert st.state is ConnectorState.DISCONNECTED
    assert "config" in st.detail.lower()


def test_status_connected_with_account(monkeypatch):
    _patch_gc(
        monkeypatch,
        token={"email": "alice@example.com", "refresh_token": "r"},
        gws_env={"GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE": "/x"},
    )
    st = get_connector("google").status()
    assert st.state is ConnectorState.CONNECTED
    assert st.account == "alice@example.com"
    assert st.extra["bridge"] is True
    assert "gmail.send" in " ".join(st.scopes)


def test_status_connected_with_imap_only(monkeypatch):
    gc = _patch_gc(monkeypatch, token=None, configured=True)
    monkeypatch.setattr(gc, "imap_status", lambda: {"connected": True, "email": "a@gmail.com"})
    st = get_connector("google").status()
    assert st.state is ConnectorState.CONNECTED
    assert st.account == "a@gmail.com"
    assert st.extra["gmail_read"]["connected"] is True


def test_status_never_raises(monkeypatch):
    import spark_cli.google_connector as gc

    def boom():
        raise RuntimeError("kaboom")

    monkeypatch.setattr(gc, "load_token", boom)
    st = get_connector("google").status()
    assert st.state is ConnectorState.ERROR
    assert "kaboom" in st.detail


# --- connect / disconnect --------------------------------------------------

def test_connect_already_connected_returns_status(monkeypatch):
    _patch_gc(monkeypatch, token={"email": "bob@example.com", "refresh_token": "r"})
    st = get_connector("google").connect()
    assert st.connected
    assert st.account == "bob@example.com"


def test_connect_when_disconnected_gives_guidance(monkeypatch):
    _patch_gc(monkeypatch, token=None, configured=True)
    st = get_connector("google").connect()
    assert st.state is ConnectorState.DISCONNECTED
    assert "how_to_connect" in st.extra


def test_disconnect_clears_token(monkeypatch):
    import spark_cli.google_connector as gc
    cleared = {"v": False}
    monkeypatch.setattr(gc, "load_token", lambda: None)
    monkeypatch.setattr(gc, "clear_token", lambda: cleared.update(v=True))
    st = get_connector("google").disconnect()
    assert st.state is ConnectorState.DISCONNECTED
    assert cleared["v"] is True


def test_gws_env_delegates(monkeypatch):
    _patch_gc(monkeypatch, token={"refresh_token": "r"},
              gws_env={"GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE": "/tmp/creds.json"})
    env = get_connector("google").gws_env()
    assert env["GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE"] == "/tmp/creds.json"


def test_github_oauth_save_syncs_gh_cli(monkeypatch, tmp_path):
    import spark_cli.oauth_connectors as oc

    monkeypatch.setenv("SPARK_HOME", str(tmp_path / ".spark"))
    monkeypatch.setattr(oc.shutil, "which", lambda name: "/usr/bin/gh" if name == "gh" else None)
    calls = {}

    def fake_run(cmd, *, input, text, capture_output, check, timeout):
        calls["cmd"] = cmd
        calls["input"] = input
        calls["text"] = text
        calls["capture_output"] = capture_output
        calls["check"] = check
        calls["timeout"] = timeout

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr(oc.subprocess, "run", fake_run)
    oc.save_token("github", {"access_token": "gho_test", "account": "alice"})

    saved = oc.load_token("github")
    assert saved["github_cli_sync"]["synced"] is True
    assert calls["cmd"] == ["/usr/bin/gh", "auth", "login", "--hostname", "github.com", "--with-token"]
    assert calls["input"] == "gho_test\n"
