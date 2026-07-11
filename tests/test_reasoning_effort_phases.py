from core.spark_constants import parse_reasoning_effort


def test_friendly_reasoning_phases_map_to_api_efforts():
    assert parse_reasoning_effort("light") == {"enabled": True, "effort": "low"}
    assert parse_reasoning_effort("medium") == {"enabled": True, "effort": "medium"}
    assert parse_reasoning_effort("hard") == {"enabled": True, "effort": "high"}

