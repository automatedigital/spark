"""Test-only monotonic spans in the real HTTP/SessionDB paths; no external calls.

Launched with an isolated SPARK_HOME and the selected snapshot on PYTHONPATH.
The ASGI wrapper adds no task/thread boundary. Nested constructor/schema spans
are explicitly overlapping. Record output happens after response completion.
"""
import contextvars
import functools
import json
import sys
import time

from core.spark_state import SessionDB
from spark_cli.web_server import app, start_server

active = contextvars.ContextVar("attribution_request", default=None)


def timed_method(name):
    original = getattr(SessionDB, name)

    @functools.wraps(original)
    def wrapped(*args, **kwargs):
        record = active.get()
        if record is None:
            return original(*args, **kwargs)
        start, cpu = time.perf_counter_ns(), time.thread_time_ns()
        try:
            return original(*args, **kwargs)
        finally:
            record["spans"].append({
                "phase": name, "startNs": start,
                "endNs": time.perf_counter_ns(),
                "cpuNs": time.thread_time_ns() - cpu,
            })

    setattr(SessionDB, name, wrapped)


for method in ("__init__", "_init_schema", "search_messages", "close"):
    timed_method(method)


class RequestPhases:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"].startswith("/api/events"):
            return await self.app(scope, receive, send)
        record = {"path": scope["path"], "query": scope.get("query_string", b"").decode(),
                  "startNs": time.perf_counter_ns(), "spans": []}
        token = active.set(record)

        async def marked_send(message):
            if message["type"] == "http.response.start":
                record["headersNs"] = time.perf_counter_ns()
                record["status"] = message["status"]
            await send(message)

        try:
            return await self.app(scope, receive, marked_send)
        finally:
            record["endNs"] = time.perf_counter_ns()
            active.reset(token)
            print("ATTR_REQUEST " + json.dumps(record), file=sys.stderr, flush=True)


app.add_middleware(RequestPhases)
start_server("127.0.0.1", int(sys.argv[1]), False)
