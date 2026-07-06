from unittest.mock import patch

from spark_cli.dashboard_health import (
    check_dashboard_health,
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

    with patch("spark_cli.dashboard_health.request.urlopen", return_value=Response()):
        result = check_dashboard_health({"dashboard": {"host": "0.0.0.0", "port": 9119}})

    assert result.enabled is True
    assert result.ok is True
    assert result.status_code == 200


def test_failed_dashboard_health_formats_recovery_commands():
    with patch("spark_cli.dashboard_health.request.urlopen", side_effect=ConnectionRefusedError("nope")):
        result = check_dashboard_health({"dashboard": {"host": "0.0.0.0", "port": 9119}})

    assert result.ok is False
    assert "nope" in result.error

    message = format_dashboard_health_failure(result)
    assert "http://127.0.0.1:9119/api/dashboard/auth/info" in message
    assert "spark config migrate" in message
    assert "spark gateway restart" in message
