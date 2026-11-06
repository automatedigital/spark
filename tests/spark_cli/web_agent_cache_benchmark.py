"""Matched SP08 provider-boundary replay plus 100-session memory pressure.

Baseline accepts pinned source files, never modifies a checkout. First-token is
request entry to the deterministic provider's first callback, not live model or
network latency. RSS is measured independently from the logical context estimate.
"""

import argparse
import asyncio
import gc
import hashlib
import json
import math
import os
import statistics
import subprocess
import tempfile
import threading
import time
import tracemalloc
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--baseline-web")
parser.add_argument("--baseline-preparation")
parser.add_argument("--output", required=True)
parser.add_argument("--trials", type=int, default=100)
parser.add_argument("--pressure-only", action="store_true")
args = parser.parse_args()
profile = tempfile.TemporaryDirectory(prefix="spark-sp08-benchmark-")
os.environ["SPARK_HOME"] = profile.name
Path(profile.name, "config.yaml").write_text("model:\n  default: fixture\n  provider: ollama\n")

from core import run_agent  # noqa: E402
from core.spark_state import SessionDB  # noqa: E402
from spark_cli import chat_preparation as prep  # noqa: E402
from spark_cli import web_server as web  # noqa: E402
from spark_cli.web_agent_cache import retained_context_bytes  # noqa: E402

if args.baseline_preparation:
    exec(compile(Path(args.baseline_preparation).read_text(), args.baseline_preparation, "exec"), prep.__dict__)
if args.baseline_web:
    exec(compile(Path(args.baseline_web).read_text(), args.baseline_web, "exec"), web.__dict__)

reads = 0
original_history = SessionDB.get_messages_as_conversation


def history(db, sid):
    global reads
    reads += 1
    return original_history(db, sid)


SessionDB.get_messages_as_conversation = history


class FixtureAgent:
    def __init__(self, **kw):
        self.session_id = kw["session_id"]
        self._session_db = kw["session_db"]
        self._session_messages = []
        self._active_children = []
        self._active_children_lock = threading.Lock()
        self.stream_delta_callback = kw.get("stream_delta_callback")

    def close(self):
        assert self._session_db is None


run_agent.AIAgent = FixtureAgent
web._resolve_web_turn_route = lambda *a, **kw: {"model": "fixture", "runtime": {}, "signature": "fixture"}
web._maybe_auto_title_web = lambda *a, **kw: None
first_tokens = {}
request_hashes = {}


def provider(agent, message, conversation_history, items):
    past = agent._session_messages if conversation_history is None else conversation_history
    payload = [*past, {"role": "user", "content": message}]
    request_hashes[agent.session_id] = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    # Identical external provider delay in baseline/candidate and cold/warm.
    time.sleep(0.005)
    first_tokens[agent.session_id] = time.perf_counter()
    if agent.stream_delta_callback:
        agent.stream_delta_callback("fixture answer")
    agent._session_messages = [*payload, {"role": "assistant", "content": "fixture answer"}]
    return {"final_response": "fixture answer"}


web._run_web_agent_turn = provider


def summary(values):
    return {"n": len(values), "median_ms": statistics.median(values),
            "p95_ms": sorted(values)[math.ceil(len(values) * 0.95) - 1]}


async def settle():
    await asyncio.gather(*[t for t in asyncio.all_tasks() if t is not asyncio.current_task()
                          and "run_agent_task" in t.get_coro().__qualname__])
    for _ in range(10000):
        if web._chat_preparation.pending == 0 and not web._chat_preparation.claims:
            return
        await asyncio.sleep(0.001)
    raise TimeoutError("preparation did not quiesce")


async def timings():
    results = {"cold": [], "warm": [], "cold_preparation": [], "warm_preparation": []}
    read_counts = {"cold": [], "warm": []}
    # Initialize optional cache schema outside measured steady-state calls.
    db = SessionDB()
    db.create_session("initialization", "web", model="fixture")
    db.close()
    prep.load_chat_preparation("initialization")
    for index in range(args.trials):
        for mode in (("cold", "warm") if index % 2 == 0 else ("warm", "cold")):
            sid = f"{mode}-{index}"
            db = SessionDB()
            db.create_session(sid, "web", model="fixture")
            db._conn.executemany(
                "INSERT INTO messages(session_id,role,content,timestamp) VALUES (?,?,?,?)",
                [(sid, "user" if i % 2 == 0 else "assistant", f"row-{i} é 中 👋 " + "x" * 2000, i)
                 for i in range(1000)],
            )
            db._conn.commit()
            expected = db.get_messages_as_conversation(sid)
            db.close()
            if mode == "warm":
                await web.warm_session_agent(sid)
                await settle()
            before_reads = reads
            web._chat_preparation.samples.clear()
            before_samples = 0
            start = time.perf_counter()
            await web.send_conversation_message(sid, web.ConversationMessage(message="matched prompt", submission_id=sid))
            await settle()
            elapsed = (first_tokens[sid] - start) * 1000
            expected_bytes = json.dumps([*expected, {"role": "user", "content": "matched prompt"}], ensure_ascii=False, sort_keys=True).encode()
            assert request_hashes[sid] == hashlib.sha256(expected_bytes).hexdigest()
            results[mode].append(elapsed)
            read_counts[mode].append(reads - before_reads)
            # Real preparation worker samples; exclude durable completion work.
            samples = web._chat_preparation.samples[before_samples:]
            preparation = [s["work_ms"] + s["queue_ms"] for s in samples if s["stage"] == "prepare_agent"]
            assert len(preparation) == 1
            results[f"{mode}_preparation"].append(preparation[0])
            web._close_web_agent(sid)
    return {"latency": {k: summary(v) for k, v in results.items()}, "raw_ms": results,
            "history_reads_per_send": read_counts, "request_hashes": request_hashes}


def rss_bytes():
    return int(subprocess.check_output(["ps", "-o", "rss=", "-p", str(os.getpid())], text=True).strip()) * 1024


def memory_pressure():
    for sid in list(web._web_agents):
        web._close_web_agent(sid)
    gc.collect()
    tracemalloc.start()
    before = {"rss_bytes": rss_bytes(), "traced_bytes": tracemalloc.get_traced_memory()[0]}
    peak_entries, peak_estimate = 0, 0
    web._web_agent_cache_limit = lambda: 8
    if not args.baseline_web:
        web._web_agent_cache_policy = lambda: (1800, 12 * 1024 * 1024)
    for index in range(100):
        sid = f"pressure-{index}"
        db = SessionDB()
        db.create_session(sid, "web", model="fixture")
        db.append_message(sid, "user", f"session-{index}:" + "é中x" * 350_000)
        db.close()
        web._web_warm_inflight.add(sid)
        try:
            if args.baseline_web:
                agent = web._new_web_agent(
                    session_id=sid, model="fixture", runtime={}, signature="fixture",
                    token_callback=None, tool_start_callback=None, tool_complete_callback=None,
                    reasoning_callback=None, status_callback=None,
                )
                db = SessionDB()
                try:
                    web._hydrate_web_agent_from_history(agent, db.get_messages_as_conversation(sid))
                finally:
                    db.close()
            else:
                web._warm_web_agent(prep.load_chat_preparation(sid), {
                    "model": "fixture", "runtime": {}, "signature": "fixture",
                })
        finally:
            web._web_warm_inflight.discard(sid)
            web._evict_web_agent_cache_if_needed()
        peak_entries = max(peak_entries, len(web._web_agents))
        peak_estimate = max(peak_estimate, sum(retained_context_bytes(a) for a in web._web_agents.values()))
    if args.baseline_web:
        del agent
    gc.collect()
    retained = {"rss_bytes": rss_bytes(), "traced_bytes": tracemalloc.get_traced_memory()[0],
                "entries": len(web._web_agents),
                "estimated_context_bytes": sum(retained_context_bytes(a) for a in web._web_agents.values())}
    for sid in list(web._web_agents):
        web._close_web_agent(sid)
    gc.collect()
    quiescent = {"rss_bytes": rss_bytes(), "traced_bytes": tracemalloc.get_traced_memory()[0],
                 "entries": len(web._web_agents)}
    tracemalloc.stop()
    return {"before": before, "after_100_retained": retained, "after_release_gc": quiescent,
            "peak_entries": peak_entries, "peak_estimated_context_bytes": peak_estimate}


result = {} if args.pressure_only else asyncio.run(timings())
result["memory_pressure"] = memory_pressure()
result["baseline"] = bool(args.baseline_web)
result["load_average"] = os.getloadavg()
Path(args.output).write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps({"latency": result.get("latency"), "memory_pressure": result["memory_pressure"]}, indent=2))
