import json
from pathlib import Path

from agent.efficiency_metrics import measure_request

FIXTURES = Path(__file__).parent / "fixtures"


def test_fixture_set_is_versioned_redacted_and_complete():
    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    assert manifest["fixture_version"] == "1.0.0"
    rows = [json.loads(line) for line in (FIXTURES / manifest["cases_file"]).read_text().splitlines()]
    assert {row["workload"] for row in rows} == {
        "direct_answer", "code_edit", "multi_tool_research", "large_file_read",
        "long_session", "reconnect", "concurrent_chats",
    }
    fixture_text = json.dumps({"manifest": manifest, "rows": rows}).lower()
    for forbidden in ("api_key", "access_token", "refresh_token", "private message", "sk-"):
        assert forbidden not in fixture_text


def test_every_static_fixture_can_be_request_accounted():
    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    rows = [json.loads(line) for line in (FIXTURES / manifest["cases_file"]).read_text().splitlines()]
    for row in rows:
        if not isinstance(row["messages"], list):
            continue
        result = measure_request(row["messages"], row.get("tools"))
        assert result.estimated_prompt_tokens > 0
        assert sum((result.system_prompt_tokens, result.conversation_tokens,
                    result.injected_context_tokens, result.tool_result_tokens,
                    result.schema_tokens)) == result.estimated_prompt_tokens
