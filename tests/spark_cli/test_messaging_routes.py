"""Tests for the Messaging REST API (src/spark_cli/messaging_routes.py)."""

from __future__ import annotations

import os

import pytest

from spark_cli.config import get_spark_home


@pytest.fixture(autouse=True)
def _clean_environ():
    """Restore os.environ after each test.

    ``save_env_value`` mirrors writes into ``os.environ``, which would
    otherwise leak credentials between tests in the same process.
    """
    snapshot = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(snapshot)


@pytest.fixture
def client():
    fastapi = pytest.importorskip("fastapi")
    from starlette.testclient import TestClient

    from spark_cli.messaging_routes import register_messaging_routes

    app = fastapi.FastAPI()
    register_messaging_routes(app)
    return TestClient(app)


def _env_file_text() -> str:
    env_path = get_spark_home() / ".env"
    return env_path.read_text(encoding="utf-8") if env_path.exists() else ""


# ---------------------------------------------------------------------------
# List + detail
# ---------------------------------------------------------------------------


def test_list_returns_all_platforms(client):
    body = client.get("/api/messaging/platforms").json()

    ids = {p["id"] for p in body["platforms"]}
    expected = {
        "telegram", "discord", "slack", "mattermost", "matrix", "whatsapp",
        "signal", "bluebubbles", "homeassistant", "email", "sms", "dingtalk",
        "feishu", "wecom", "wecom_callback", "weixin", "qqbot", "webhook",
        "api_server",
    }
    assert expected <= ids
    assert isinstance(body["gateway_running"], bool)

    for platform in body["platforms"]:
        assert platform["name"]
        assert "description" in platform
        assert "help_text" in platform
        assert "setup_guide_url" in platform
        assert isinstance(platform["enabled"], bool)
        assert isinstance(platform["configured"], bool)
        assert set(platform["fields"]) == {"required", "recommended", "advanced"}


def test_detail_shape_telegram(client):
    resp = client.get("/api/messaging/platforms/telegram")
    assert resp.status_code == 200
    body = resp.json()

    assert body["id"] == "telegram"
    assert body["name"] == "Telegram"
    assert body["setup_guide_url"].startswith("https://")
    assert isinstance(body["gateway_running"], bool)

    required = body["fields"]["required"]
    assert [f["key"] for f in required] == ["TELEGRAM_BOT_TOKEN"]
    token = required[0]
    assert token["type"] == "secret"
    assert token["set"] is False
    assert token["value"] == ""
    assert token["label"]
    assert token["description"]

    recommended_keys = [f["key"] for f in body["fields"]["recommended"]]
    assert "TELEGRAM_ALLOWED_USERS" in recommended_keys

    # Unconfigured platform: disabled + not configured
    assert body["enabled"] is False
    assert body["configured"] is False


def test_unknown_platform_is_404(client):
    assert client.get("/api/messaging/platforms/nope").status_code == 404
    assert client.put("/api/messaging/platforms/nope", json={"enabled": True}).status_code == 404
    assert client.post("/api/messaging/platforms/nope/restart").status_code == 404


# ---------------------------------------------------------------------------
# Save round-trip
# ---------------------------------------------------------------------------


def test_save_round_trip_persists_and_masks_secrets(client):
    token = "123456789:AAFakeTelegramTokenXYZ9876"
    resp = client.put(
        "/api/messaging/platforms/telegram",
        json={
            "enabled": True,
            "values": {
                "TELEGRAM_BOT_TOKEN": token,
                "TELEGRAM_ALLOWED_USERS": "42,77",
            },
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["enabled"] is True
    assert body["configured"] is True
    assert sorted(body["saved"]) == ["TELEGRAM_ALLOWED_USERS", "TELEGRAM_BOT_TOKEN"]
    assert "restart" in body

    # Persisted to the isolated SPARK_HOME .env
    env_text = _env_file_text()
    assert f"TELEGRAM_BOT_TOKEN={token}" in env_text
    assert "TELEGRAM_ALLOWED_USERS=42,77" in env_text
    assert "TELEGRAM_ENABLED=true" in env_text

    # Read-back masks the secret but keeps the last 4 chars + set flag
    got = client.get("/api/messaging/platforms/telegram").json()
    token_field = got["fields"]["required"][0]
    assert token_field["set"] is True
    assert token_field["value"].endswith(token[-4:])
    assert token not in token_field["value"]
    assert token_field["value"].startswith("•")

    # Non-secret values come back verbatim
    allowed = next(
        f for f in got["fields"]["recommended"] if f["key"] == "TELEGRAM_ALLOWED_USERS"
    )
    assert allowed["value"] == "42,77"


def test_masked_value_not_overwritten_on_save(client):
    token = "123456789:AAFakeTelegramTokenXYZ9876"
    client.put(
        "/api/messaging/platforms/telegram",
        json={"values": {"TELEGRAM_BOT_TOKEN": token}},
    )
    masked = client.get("/api/messaging/platforms/telegram").json()["fields"]["required"][0]["value"]
    assert masked != token

    # Submitting the masked placeholder back (as the UI does) must be a no-op
    resp = client.put(
        "/api/messaging/platforms/telegram",
        json={"values": {"TELEGRAM_BOT_TOKEN": masked, "TELEGRAM_ALLOWED_USERS": "42"}},
    )
    assert resp.status_code == 200
    assert resp.json()["saved"] == ["TELEGRAM_ALLOWED_USERS"]

    env_text = _env_file_text()
    assert f"TELEGRAM_BOT_TOKEN={token}" in env_text
    assert masked not in env_text


def test_secret_can_be_cleared_with_empty_value(client):
    client.put(
        "/api/messaging/platforms/telegram",
        json={"values": {"TELEGRAM_BOT_TOKEN": "123456789:AAFakeTelegramTokenXYZ9876"}},
    )
    resp = client.put(
        "/api/messaging/platforms/telegram",
        json={"values": {"TELEGRAM_BOT_TOKEN": ""}},
    )
    assert resp.status_code == 200
    assert resp.json()["configured"] is False
    assert "TELEGRAM_BOT_TOKEN=\n" in _env_file_text()


def test_unknown_field_rejected(client):
    resp = client.put(
        "/api/messaging/platforms/telegram",
        json={"values": {"NOT_A_REAL_FIELD": "x"}},
    )
    assert resp.status_code == 400
    assert "NOT_A_REAL_FIELD" in resp.json()["detail"]


def test_enable_toggle_writes_native_flag(client):
    resp = client.put("/api/messaging/platforms/whatsapp", json={"enabled": True})
    assert resp.status_code == 200
    assert resp.json()["enabled"] is True
    assert "WHATSAPP_ENABLED=true" in _env_file_text()

    resp = client.put("/api/messaging/platforms/whatsapp", json={"enabled": False})
    assert resp.json()["enabled"] is False
    assert "WHATSAPP_ENABLED=false" in _env_file_text()


def test_bool_values_coerced_to_env_strings(client):
    resp = client.put(
        "/api/messaging/platforms/telegram",
        json={"values": {"TELEGRAM_REQUIRE_MENTION": True}},
    )
    assert resp.status_code == 200
    assert "TELEGRAM_REQUIRE_MENTION=true" in _env_file_text()


# ---------------------------------------------------------------------------
# Auto-enable on credential save
# ---------------------------------------------------------------------------


def _slack_tokens() -> dict:
    return {
        "SLACK_BOT_TOKEN": "xoxb-fake-bot-token-1234",
        "SLACK_APP_TOKEN": "xapp-fake-app-token-5678",
    }


def test_token_save_auto_enables_platform(client):
    """Saving credentials without the toggle persists SLACK_ENABLED=true."""
    resp = client.put(
        "/api/messaging/platforms/slack",
        json={"values": _slack_tokens()},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["configured"] is True
    assert body["enabled"] is True
    assert "SLACK_ENABLED=true" in _env_file_text()


def test_partial_credential_save_does_not_enable(client):
    resp = client.put(
        "/api/messaging/platforms/slack",
        json={"values": {"SLACK_BOT_TOKEN": "xoxb-fake-bot-token-1234"}},
    )
    assert resp.status_code == 200
    assert resp.json()["configured"] is False
    assert "SLACK_ENABLED" not in _env_file_text()


def test_token_save_does_not_override_explicit_toggle_off(client):
    # User explicitly disabled the platform earlier
    client.put("/api/messaging/platforms/slack", json={"enabled": False})
    assert "SLACK_ENABLED=false" in _env_file_text()

    resp = client.put(
        "/api/messaging/platforms/slack",
        json={"values": _slack_tokens()},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is True
    assert body["enabled"] is False
    assert "SLACK_ENABLED=false" in _env_file_text()
    assert "SLACK_ENABLED=true" not in _env_file_text()


def test_explicit_toggle_in_same_request_wins(client):
    resp = client.put(
        "/api/messaging/platforms/slack",
        json={"enabled": False, "values": _slack_tokens()},
    )
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False
    assert "SLACK_ENABLED=false" in _env_file_text()


def test_native_flag_platform_not_auto_enabled_by_value_save(client):
    # webhook is flag-native: saving a value must not flip WEBHOOK_ENABLED
    resp = client.put(
        "/api/messaging/platforms/webhook",
        json={"values": {"WEBHOOK_PORT": "8644"}},
    )
    assert resp.status_code == 200
    assert "WEBHOOK_ENABLED" not in _env_file_text()


def test_enabled_flags_registered_in_optional_env_vars():
    from gateway.platform_fields import all_platform_specs
    from spark_cli.config import OPTIONAL_ENV_VARS

    for spec in all_platform_specs():
        assert spec.enabled_env in OPTIONAL_ENV_VARS or spec.enabled_env in {
            "WHATSAPP_ENABLED"  # tracked via _EXTRA_ENV_KEYS
        }, f"{spec.enabled_env} missing from OPTIONAL_ENV_VARS"


# ---------------------------------------------------------------------------
# Restart
# ---------------------------------------------------------------------------


def test_restart_endpoint_best_effort_when_gateway_down(client):
    # Isolated SPARK_HOME has no gateway.pid → not running, but still 200
    resp = client.post("/api/messaging/platforms/telegram/restart")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["running"] is False
    assert body["platform"] == "telegram"


def test_restart_endpoint_restarts_embedded_desktop_gateway(client, monkeypatch):
    import spark_cli.desktop_gateway as desktop_gateway

    monkeypatch.setenv("SPARK_DESKTOP", "1")
    monkeypatch.setattr(desktop_gateway, "restart_desktop_gateway", lambda: True)

    resp = client.post("/api/messaging/platforms/slack/restart")

    assert resp.status_code == 200
    assert resp.json() == {
        "ok": True,
        "running": True,
        "detail": "Desktop gateway restarted.",
        "platform": "slack",
    }


def test_save_succeeds_even_when_restart_fails(client, monkeypatch):
    import spark_cli.messaging_routes as mr

    def _boom():
        raise RuntimeError("gateway exploded")

    monkeypatch.setattr(mr, "_trigger_gateway_restart", _boom)

    resp = client.put(
        "/api/messaging/platforms/telegram",
        json={"values": {"TELEGRAM_ALLOWED_USERS": "42"}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["restart"]["ok"] is False
    assert "exploded" in body["restart"]["detail"]
    assert "TELEGRAM_ALLOWED_USERS=42" in _env_file_text()
