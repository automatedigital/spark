#!/usr/bin/env python3
"""Deterministic, isolated CI runner; reads one case JSON from stdin."""

import json
import os
import sys

payload = json.load(sys.stdin)
condition = payload["condition"]
case = payload["case"]
response = case[f"{condition}_response"]
print(
    json.dumps(
        {
            "response": response,
            "output_tokens": max(1, (len(response) + 3) // 4),
            "latency_ms": 1.0,
            "cost_usd": 0.0,
            "tool_success": True,
            "fallback_count": 0,
            "follow_up_turns": 0,
            "routing_reason": "pinned_fixture_model",
            "model_label": "deterministic-replay-v1",
            "isolated_user_config": "spark-response-eval-" in os.environ.get("HOME", "")
            and os.environ.get("SPARK_HOME", "").startswith(os.environ.get("HOME", "")),
        }
    )
)
