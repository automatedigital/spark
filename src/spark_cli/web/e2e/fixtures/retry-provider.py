"""SP16 manual browser replay: real agent, SQLite and transport; no live provider.

Run with an isolated SPARK_HOME and own-src PYTHONPATH. The companion Vite
server must proxy to this port. Submit once, observe retry, refresh, then Stop.
The read-only observation endpoint verifies no accepted prompt/provider replay.
"""

import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
from openai import OpenAI

import core.run_agent as runtime
from spark_cli import web_server as web

assert os.environ.get("SPARK_HOME", "").startswith(("/tmp/", "/private/tmp/"))
observations: dict[str, list[Any]] = {"requests": [], "retry_events": [], "interrupts": []}


def provider(request):
    observations["requests"].append({"at": time.time(), "payload": json.loads(request.content)})
    return httpx.Response(429, headers={"Retry-After": "120"}, json={
        "error": {"message": "SP16 provider replay rate limit", "type": "rate_limit_error", "code": "rate_limit"},
    })


def client(**kwargs):
    return OpenAI(
        api_key="replay-only", base_url="http://provider.replay/v1", max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(provider)),
    )


class ReplayAgent(runtime.AIAgent):
    def __init__(self, **kwargs):
        kwargs.update(skip_context_files=True, skip_memory=True)
        super().__init__(**kwargs)

    def _emit_status(self, message):
        from core.run_agent.retry_policy import RetryStatus
        if isinstance(message, RetryStatus):
            observations["retry_events"].append(message.data)
        return super()._emit_status(message)

    def interrupt(self, message=None):
        observations["interrupts"].append(time.monotonic())
        return super().interrupt(message)


runtime.OpenAI = client
agent_patch = patch("core.run_agent.AIAgent", ReplayAgent)
agent_patch.start()
runtime.get_tool_definitions = lambda **kwargs: []
runtime.check_toolset_requirements = lambda: {}
web._resolve_web_turn_route = lambda *a, **kw: {
    "model": "replay", "runtime": {"api_key": "replay-only", "base_url": "http://provider.replay/v1",
    "provider": "custom", "api_mode": "chat_completions"}, "signature": ("sp16-replay",),
}
web._maybe_auto_title_web = lambda *a, **kw: None


@web.app.get("/api/dev/retry-replay-observations")
def read_observations():
    return observations


# The app imports a final SPA catch-all before fixture-only routes are added.
web.app.router.routes.insert(0, web.app.router.routes.pop())


Path(os.environ["SPARK_HOME"]).mkdir(parents=True, exist_ok=True)
Path(os.environ["SPARK_HOME"], "config.yaml").write_text(
    "model:\n  default: replay\n  provider: custom\n  context_length: 128000\n"
)
web.start_server(host="127.0.0.1", port=int(sys.argv[1]), open_browser=False)
