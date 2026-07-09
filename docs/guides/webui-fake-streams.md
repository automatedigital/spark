# WebUI Fake Streams

The web dashboard has a local-only fake streaming harness for reproducing chat
state bugs without provider keys, model latency, or token cost.

## Start

```bash
source .venv/bin/activate
SPARK_WEB_FAKE_STREAMS=1 python -m spark_cli.main dashboard --port 9119
```

The endpoint is disabled unless `SPARK_WEB_FAKE_STREAMS=1` is set.

## Create A Stream

```bash
curl -s http://127.0.0.1:9119/api/dev/fake-streams \
  -H 'content-type: application/json' \
  -d '{
    "session_id": "fake_alpha",
    "message": "Preview stress test",
    "events": [
      {"type": "status", "kind": "initializing_agent", "text": "Preparing fake agent"},
      {"type": "reasoning", "text": "Synthetic reasoning event"},
      {"type": "tool_start", "tool_call_id": "tool_1", "name": "fake_lookup", "args": {"q": "spark"}},
      {"type": "tool_end", "tool_call_id": "tool_1", "name": "fake_lookup", "result": {"ok": true}},
      {"type": "token", "text": "Hello "},
      {"type": "stall", "text": "Holding the stream open", "phase": "api"},
      {"type": "token", "text": "world", "delay_ms": 1000}
    ]
  }'
```

Supported event types are `status`, `recover`, `reasoning`, `token`, `tool_start`,
`tool_end`, `stall`, `migrate`, `complete`, and `fail`.

## Cleanup

Stop the dashboard process and unset the flag:

```bash
unset SPARK_WEB_FAKE_STREAMS
```

Fake sessions are normal web sessions in the active `SPARK_HOME`. Remove them
from the UI like any other test chat, or use a temporary `SPARK_HOME` while
stress testing.
