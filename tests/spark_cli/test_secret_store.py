"""Tests for the keychain-backed secret store (src/spark_cli/secret_store.py)."""

from __future__ import annotations

import sys
import types

import pytest

from spark_cli import secret_store as ss


class FakeKeyring:
    def __init__(self):
        self.store: dict[tuple[str, str], str] = {}

    def set_password(self, service, key, value):
        self.store[(service, key)] = value

    def get_password(self, service, key):
        return self.store.get((service, key))

    def delete_password(self, service, key):
        if (service, key) not in self.store:
            raise KeyError("no such password")
        del self.store[(service, key)]


@pytest.fixture
def fake_keyring(monkeypatch):
    fake = FakeKeyring()
    module = types.SimpleNamespace(
        set_password=fake.set_password,
        get_password=fake.get_password,
        delete_password=fake.delete_password,
    )
    monkeypatch.setattr(ss, "_keyring", lambda: module)
    return fake


def test_set_get_roundtrip(fake_keyring):
    ss.set_secret("proj", "token", "s3cret")
    assert ss.get_secret("proj", "token") == "s3cret"


def test_secrets_scoped_per_workspace(fake_keyring):
    ss.set_secret("a", "token", "AA")
    ss.set_secret("b", "token", "BB")
    assert ss.get_secret("a", "token") == "AA"
    assert ss.get_secret("b", "token") == "BB"


def test_delete(fake_keyring):
    ss.set_secret("proj", "token", "x")
    assert ss.delete_secret("proj", "token") is True
    assert ss.get_secret("proj", "token") is None
    assert ss.delete_secret("proj", "missing") is False


def test_missing_backend_degrades(monkeypatch):
    # Simulate keyring not installed.
    monkeypatch.setitem(sys.modules, "keyring", None)
    assert ss.get_secret("proj", "token") is None
    assert ss.delete_secret("proj", "token") is False
    with pytest.raises(ss.KeychainUnavailable):
        ss.set_secret("proj", "token", "x")
