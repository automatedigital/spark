import os
import json
from datetime import datetime, timedelta, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[2] / "src" / "tools" / "managed_tool_gateway.py"
MODULE_SPEC = spec_from_file_location("managed_tool_gateway_test_module", MODULE_PATH)
assert MODULE_SPEC and MODULE_SPEC.loader
managed_tool_gateway = module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = managed_tool_gateway
MODULE_SPEC.loader.exec_module(managed_tool_gateway)
resolve_managed_tool_gateway = managed_tool_gateway.resolve_managed_tool_gateway


def test_resolve_managed_tool_gateway_is_inactive_without_access_token():
    with patch.dict(
        os.environ,
        {
            "SPARK_ENABLE_NOUS_MANAGED_TOOLS": "1",
            "TOOL_GATEWAY_DOMAIN": "automatedigital.ai",
        },
        clear=False,
    ):
        result = resolve_managed_tool_gateway(
            "firecrawl",
            token_reader=lambda: None,
        )

    assert result is None


def test_resolve_managed_tool_gateway_is_disabled_without_feature_flag():
    with patch.dict(
        os.environ, {"TOOL_GATEWAY_DOMAIN": "automatedigital.ai"}, clear=False
    ):
        result = resolve_managed_tool_gateway(
            "firecrawl",
            token_reader=lambda: "gateway-token",
        )

    assert result is None

