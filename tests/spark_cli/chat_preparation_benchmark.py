"""Matched SP03 fixture; run with fresh PYTHONPATH and an isolated temporary home.

--baseline-source accepts the pinned web_server.py, leaving the checkout intact.
Control timings include scheduler wait plus GET /api/status via ASGI HTTP.
SSE probe heartbeats traverse the production generator (not the native 30s ping).
"""

import argparse
import asyncio
import hashlib
import json
import math
import os
import statistics
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

parser = argparse.ArgumentParser()
parser.add_argument("--baseline-source")
parser.add_argument("--output", required=True)
args = parser.parse_args()
home = tempfile.TemporaryDirectory(prefix="spark-sp03-bench-")
os.environ["SPARK_HOME"] = home.name
Path(home.name, "config.yaml").write_text(
    "model:\n  default: fixture\n  provider: ollama\ndashboard:\n  require_auth_nonlocal: false\n"
)

import httpx  # noqa: E402

from core.spark_state import SessionDB  # noqa: E402
from spark_cli import web_server as web  # noqa: E402

if args.baseline_source:
    exec(
        compile(Path(args.baseline_source).read_text(), args.baseline_source, "exec"), web.__dict__
    )

stages = []
original_history = SessionDB.get_messages_as_conversation
original_status_read = SessionDB.list_sessions_rich


def status_read(db, *args, **kwargs):
    started = time.monotonic()
    try:
        return original_status_read(db, *args, **kwargs)
    finally:
        stages.append({"stage": "status_sqlite", "ms": (time.monotonic() - started) * 1000})


SessionDB.list_sessions_rich = status_read


def history(db, sid):
    started = time.monotonic()
    time.sleep(0.12)
    try:
        return original_history(db, sid)
    finally:
        stages.append({"stage": "sqlite_history", "ms": (time.monotonic() - started) * 1000})


def route(*a, **k):
    started = time.monotonic()
    time.sleep(0.03)
    stages.append({"stage": "route_files", "ms": (time.monotonic() - started) * 1000})
    return {"model": "fixture", "runtime": {}, "signature": "fixture"}


def client(**kw):
    started = time.monotonic()
    time.sleep(0.04)
    stages.append({"stage": "provider_client", "ms": (time.monotonic() - started) * 1000})
    return SimpleNamespace(session_id=kw["session_id"])


SessionDB.get_messages_as_conversation = history
web._resolve_web_turn_route = route
web._new_web_agent = client
web._maybe_auto_title_web = lambda *a, **k: None
dispatches = []
release_provider = threading.Event()


def provider(*a, **k):
    dispatches.append(time.monotonic())
    if not release_provider.wait(60):
        raise TimeoutError("fixture provider boundary was not released")
    return {"final_response": "fixture response"}


web._run_web_agent_turn = provider
web._get_web_cached_agent = lambda *a: None


def summary(values):
    ordered = sorted(values)
    return {
        "n": len(values),
        "median_ms": statistics.median(values),
        "p95_ms": ordered[math.ceil(len(values) * 0.95) - 1],
    }


async def trial(index):
    db = SessionDB()
    ids = [f"trial-{index}-{i}" for i in range(4)]
    for sid in ids:
        db.create_session(sid, "web", model="fixture")
        db._conn.executemany(
            "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            [(sid, "user" if i % 2 == 0 else "assistant", f"history-{i}", i) for i in range(10000)],
        )
    db._conn.commit()
    db.close()
    web._web_event_loop = asyncio.get_running_loop()
    dispatches.clear()
    release_provider.clear()
    done = asyncio.Event()
    status, loop_delay, heartbeat = [], [], []

    async def disconnected():
        return False

    response = await web.sse_events_bus(
        SimpleNamespace(is_disconnected=disconnected), topics="chat.preparation_probe"
    )
    iterator = response.body_iterator
    assert await anext(iterator) == ": connected\n\n"

    async def read_heartbeats():
        async for data in iterator:
            if data.startswith("data: "):
                payload = json.loads(data[6:])["data"]
                heartbeat.append((time.monotonic() - payload["sent"]) * 1000)
            if done.is_set():
                break

    async def probe():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=web.app), base_url="http://127.0.0.1"
        ) as control:
            while not done.is_set():
                scheduled = time.monotonic() + 0.01
                await asyncio.sleep(0.01)
                result = await control.get("/api/status")
                assert result.status_code == 200
                status.append((time.monotonic() - scheduled) * 1000)
                web._publish_event("chat.preparation_probe", {"sent": scheduled}, "probe")

    async def probe_loop():
        while not done.is_set():
            scheduled = time.monotonic() + 0.01
            await asyncio.sleep(0.01)
            loop_delay.append(max(0, time.monotonic() - scheduled) * 1000)

    loop_probe = asyncio.create_task(probe_loop())
    reader = asyncio.create_task(read_heartbeats())
    controls = asyncio.create_task(probe())
    await asyncio.sleep(0.02)
    results = await asyncio.gather(
        *[
            web.send_conversation_message(
                sid, web.ConversationMessage(message="new prompt", submission_id=f"draft-{sid}")
            )
            for sid in ids
        ]
    )
    assert len({row["turn_id"] for row in results}) == 4
    deadline = time.monotonic() + 60
    while len(dispatches) < 4:
        if time.monotonic() > deadline:
            raise TimeoutError("four prepared turns did not reach the fixture provider")
        await asyncio.sleep(0.01)
    done.set()
    await controls
    await loop_probe
    web._publish_event("chat.preparation_probe", {"sent": time.monotonic()}, "probe")
    await asyncio.wait_for(reader, 5)
    await iterator.aclose()
    release_provider.set()
    await asyncio.gather(
        *[
            t
            for t in asyncio.all_tasks()
            if t is not asyncio.current_task() and "run_agent_task" in t.get_coro().__qualname__
        ]
    )
    return {"status_ms": status, "loop_delay_ms": loop_delay, "sse_probe_ms": heartbeat}


async def main():
    trials = [await trial(index) for index in range(5)]
    metrics = {key: summary([x for trial in trials for x in trial[key]]) for key in trials[0]}
    result = {
        "source_sha256": {
            "web_server": hashlib.sha256(Path(args.baseline_source or web.__file__).read_bytes()).hexdigest(),
            "chat_preparation": hashlib.sha256(Path(web.__file__).with_name("chat_preparation.py").read_bytes()).hexdigest(),
        },
        "base": "a12205a5737d7539875d6af16b3bb58c194e8edb",
        "baseline": bool(args.baseline_source),
        "trials": trials,
        "metrics": metrics,
        "stages": stages,
        "preparation_samples": getattr(getattr(web, "_chat_preparation", None), "samples", []),
        "load_average": os.getloadavg(),
        "pid": os.getpid(),
    }
    Path(args.output).write_text(json.dumps(result, indent=2))
    print(json.dumps(metrics, indent=2))


asyncio.run(main())
