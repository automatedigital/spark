"""Matched web execution/callback replay; pass a baseline web_server.py path.

Run with the active test venv and this checkout's src on PYTHONPATH. Imports and
provider waits are outside/inside the measured interval respectively. This is a
synthetic local overhead measurement, not a live provider or browser benchmark.
"""
import asyncio
import importlib.util
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path


def sample(source):
    spec = importlib.util.spec_from_file_location("spark_cli.web_server", source)
    server = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = server
    spec.loader.exec_module(server)
    current = [None]
    server._get_web_turn = lambda *_: ("replay", current[0])
    server._publish_event = lambda *args, **kwargs: None
    server._touch_web_turn = lambda *args, **kwargs: None
    server._record_web_turn_timing = lambda *args, **kwargs: None
    server._append_web_turn_token = lambda *args, **kwargs: None
    server._refresh_web_agent_for_computer_use = lambda *args: None
    server._inject_brief_if_present = lambda sid, text: text
    server._maybe_capture_codex_usage_limit = lambda *args: None

    class Agent:
        session_id = "replay"

        def _interruptible_streaming_api_call(self, payload):
            assert payload == {"model": "replay", "messages": [{"role": "user", "content": "fixed"}]}
            time.sleep(0.004)
            for _ in range(100):
                callbacks[0]("text ")
            callbacks[1]("one", "read", {})
            time.sleep(0.002)
            callbacks[2]("one", "read", {}, "ok")
            return {"final_response": "fixed"}

        def run_conversation(self, message):
            callbacks[4]("lifecycle", "Preparing")
            return self._interruptible_streaming_api_call({"model": "replay", "messages": [{"role": "user", "content": message}]})

    agent = Agent()
    elapsed = []
    for _ in range(45):
        started = time.perf_counter()
        turn = server.WebActiveTurn(0, 0, "", False, "replay", "starting")
        current[0] = turn
        timing = getattr(turn, "timing_summary", None)
        if timing:
            timing.mark("accepted")
        callbacks = server._make_web_chat_callbacks("replay", asyncio.Queue(), None)
        time.sleep(0.001)
        if timing:
            timing.mark("preparation_ready")
            timing.mark("execution_queued")
        time.sleep(0.002)
        server._run_web_agent_turn(agent, "fixed")
        if timing:
            timing.mark("finish")
        server._web_turn_projection_payload("replay", turn, status="completed")
        elapsed.append(time.perf_counter() - started)
    print(json.dumps({"median_seconds": statistics.median(elapsed[5:]), "turns": 40, "tokens_per_turn": 100}))


if __name__ == "__main__":
    if sys.argv[1] == "--sample":
        sample(sys.argv[2])
    else:
        baseline = sys.argv[1]
        candidate = str(Path(__file__).resolve().parents[2] / "src/spark_cli/web_server.py")
        results = {"baseline": [], "candidate": []}
        for label in ("baseline", "candidate", "candidate", "baseline", "candidate", "baseline", "baseline", "candidate"):
            output = subprocess.check_output([sys.executable, __file__, "--sample", baseline if label == "baseline" else candidate], text=True)
            results[label].append(json.loads(output.strip().splitlines()[-1])["median_seconds"])
        b, c = (statistics.median(results[key]) for key in ("baseline", "candidate"))
        print(json.dumps({"samples": results, "baseline_median_seconds": b, "candidate_median_seconds": c,
                          "overhead_percent": (c / b - 1) * 100, "fixture": "1ms preparation, 2ms queue, 4ms provider, 2ms tool, 100 text callbacks"}, indent=2))
