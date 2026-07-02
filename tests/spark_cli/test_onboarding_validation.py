import pytest

from spark_cli.onboarding_validation import (
    normalize_http_base_url,
    normalize_model_name,
    normalize_port,
    normalize_secret,
)


@pytest.mark.parametrize("raw", ["0", "65536", "abc", "22x", ""])
def test_normalize_port_rejects_invalid_values(raw):
    with pytest.raises(ValueError):
        normalize_port(raw)


@pytest.mark.parametrize("raw,expected", [("22", 22), ("  8644  ", 8644), ("65535", 65535)])
def test_normalize_port_accepts_valid_values(raw, expected):
    assert normalize_port(raw) == expected


@pytest.mark.parametrize("raw", ["localhost:11434", "ftp://host", "", "http://host:0", "http://host:65536", "http://host/path?q=1"])
def test_normalize_http_base_url_rejects_invalid_values(raw):
    with pytest.raises(ValueError):
        normalize_http_base_url(raw)


def test_normalize_http_base_url_accepts_and_strips_trailing_slash():
    assert normalize_http_base_url(" http://localhost:11434/ ") == "http://localhost:11434"
    assert normalize_http_base_url("https://example.com/v1///") == "https://example.com/v1"


@pytest.mark.parametrize("raw", ["", "placeholder", "your-api-key", "abc"])
def test_normalize_secret_rejects_empty_placeholder_or_too_short(raw):
    with pytest.raises(ValueError):
        normalize_secret(raw, field_name="API key", min_length=4)


def test_normalize_secret_accepts_trimmed_value():
    assert normalize_secret("  sk-test-value\n", field_name="API key") == "sk-test-value"


@pytest.mark.parametrize("raw", ["", "bad model", "model\nname"])
def test_normalize_model_name_rejects_invalid_values(raw):
    with pytest.raises(ValueError):
        normalize_model_name(raw)


def test_normalize_model_name_accepts_provider_style_ids():
    assert normalize_model_name("anthropic/claude-sonnet-4-6") == "anthropic/claude-sonnet-4-6"
    assert normalize_model_name("qwen2.5-coder:32b") == "qwen2.5-coder:32b"
