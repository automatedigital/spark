# WebUI Fake Streams

The web dashboard has a local-only fake streaming harness for reproducing chat
state bugs without provider keys, model latency, or token cost.

## Start

For preview-pane testing, use the disposable runner:

```bash
source .venv/bin/activate
python scripts/preview_webui_stress.py
```

Open the printed Preview URL, select **Disposable WebUI stress stream**, switch
between chats, scroll, and press **Stop** while the response is growing. The
runner binds both services to loopback, uses a temporary `SPARK_HOME`, and
removes its processes, session database, logs, and other profile artifacts on
exit, failure, SIGINT, or SIGTERM. Pass `--keep-home` only when those artifacts
are intentionally needed for debugging.

For a manually scripted stream, start the server directly:

```bash
source .venv/bin/activate
SPARK_WEB_FAKE_STREAMS=1 python -m spark_cli.main dashboard --port 9119
```

The endpoint is disabled unless `SPARK_WEB_FAKE_STREAMS=1` is set and rejects
non-loopback clients even when the dashboard itself is exposed on the network.

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

Fake sessions are normal web sessions in the active `SPARK_HOME`. Prefer the
disposable runner above. If the dashboard was started manually, remove fake
sessions from the UI or delete only the temporary `SPARK_HOME` you created for
the test; never point destructive cleanup at a real profile.
