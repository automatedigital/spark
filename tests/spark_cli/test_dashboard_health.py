from unittest.mock import patch

from spark_cli.dashboard_health import (
    check_dashboard_health,
    dashboard_frontend_assets_ready,
    dashboard_health_url,
    dashboard_probe_host,
    format_dashboard_health_failure,
)


def test_dashboard_probe_host_uses_loopback_for_wildcard():
    assert dashboard_probe_host("0.0.0.0") == "127.0.0.1"
    assert dashboard_probe_host("::") == "127.0.0.1"
    assert dashboard_probe_host("localhost") == "localhost"


def test_dashboard_health_url_uses_public_auth_endpoint():
    enabled, url, host, port = dashboard_health_url(
        {"dashboard": {"enabled_with_gateway": True, "host": "0.0.0.0", "port": 9123}}
    )

    assert enabled is True
    assert host == "0.0.0.0"
    assert port == 9123
    assert url == "http://127.0.0.1:9123/api/dashboard/auth/info"


def test_disabled_dashboard_is_successful_skip():
    result = check_dashboard_health({"dashboard": {"enabled_with_gateway": False}})

    assert result.enabled is False
    assert result.ok is True


def test_healthy_dashboard_passes():
    class Response:
        def getcode(self):
            return 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    with (
        patch("spark_cli.dashboard_health.dashboard_frontend_assets_ready", return_value=(True, "")),
        patch("spark_cli.dashboard_health.request.urlopen", return_value=Response()),
    ):
        result = check_dashboard_health({"dashboard": {"host": "0.0.0.0", "port": 9119}})

    assert result.enabled is True
    assert result.ok is True
    assert result.status_code == 200


def test_failed_dashboard_health_formats_recovery_commands():
    with (
        patch("spark_cli.dashboard_health.dashboard_frontend_assets_ready", return_value=(True, "")),
        patch("spark_cli.dashboard_health.request.urlopen", side_effect=ConnectionRefusedError("nope")),
    ):
        result = check_dashboard_health({"dashboard": {"host": "0.0.0.0", "port": 9119}})

    assert result.ok is False
    assert "nope" in result.error

    message = format_dashboard_health_failure(result)
    assert "http://127.0.0.1:9119/api/dashboard/auth/info" in message
    assert "spark config migrate" in message
    assert "spark gateway restart" in message


def test_dashboard_health_fails_when_frontend_assets_are_missing():
    with patch(
        "spark_cli.dashboard_health.dashboard_frontend_assets_ready",
        return_value=(False, "Dashboard frontend assets directory is missing"),
    ):
        result = check_dashboard_health({"dashboard": {"host": "0.0.0.0", "port": 9119}})

    assert result.ok is False
    assert "frontend assets" in result.error


def test_dashboard_frontend_assets_ready_requires_js_and_css(tmp_path):
    web_dist = tmp_path / "web_dist"
    assets = web_dist / "assets"
    assets.mkdir(parents=True)
    (web_dist / "index.html").write_text("<html></html>", encoding="utf-8")

    ok, error = dashboard_frontend_assets_ready(web_dist)
    assert ok is False
    assert "JavaScript assets" in error

    (assets / "app.js").write_text("console.log('ok')", encoding="utf-8")
    ok, error = dashboard_frontend_assets_ready(web_dist)
    assert ok is False
    assert "CSS assets" in error

    (assets / "app.css").write_text("body {}", encoding="utf-8")
    ok, error = dashboard_frontend_assets_ready(web_dist)
    assert ok is True
    assert error == ""
