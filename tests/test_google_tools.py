import json

import pytest

from tools import google_tools


@pytest.mark.asyncio
async def test_gmail_search_uses_imap_app_password(monkeypatch):
    import imaplib

    from spark_cli import google_connector as gc

    gc.save_imap_credentials("alice@gmail.com", "abcd efgh ijkl mnop")
    calls = {}

    class FakeImap:
        def __init__(self, host, port):
            calls["host"] = host
            calls["port"] = port

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def login(self, username, password):
            calls["login"] = (username, password)

        def select(self, mailbox, readonly=False):
            calls["select"] = (mailbox, readonly)
            return ("OK", [])

        def uid(self, command, *args):
            calls.setdefault("uid", []).append((command, args))
            if command == "search":
                return ("OK", [b"1 2"])
            return (
                "OK",
                [
                    (
                        b"2",
                        b"Subject: Test subject\r\nFrom: Alice <alice@example.com>\r\n"
                        b"Date: Fri, 05 Jun 2026 10:00:00 +0000\r\n\r\n"
                        b"Hello from Gmail",
                    )
                ],
            )

        def close(self):
            calls["closed"] = True

    monkeypatch.setattr(imaplib, "IMAP4_SSL", FakeImap)

    out = json.loads(await google_tools._gmail_search({"query": "is:unread", "max_results": 1}))
    assert out["source"] == "imap"
    assert out["total"] == 2
    assert out["results"][0]["subject"] == "Test subject"
    assert calls["login"] == ("alice@gmail.com", "abcdefghijklmnop")
    assert calls["uid"][0] == ("search", (None, "X-GM-RAW", '"is:unread"'))


def test_google_check_connected_accepts_imap_only(monkeypatch):
    from spark_cli import google_connector as gc

    monkeypatch.setattr(gc, "load_token", lambda: None)
    monkeypatch.setattr(gc, "has_imap_credentials", lambda: True)
    assert google_tools._check_gmail_read_connected() is True
    assert google_tools._check_google_oauth_connected() is False
