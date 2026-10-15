"""Synthetic P09 process boundary: die after REAL provider/tool acceptance.

This is not a live provider capture. Reuses transport-v1.json and the test HTTP
script, runs real AIAgent + child workers, then os._exit(73) without cleanup.
Invoked only by test_orchestration_replay.py with temporary SPARK_HOME/database.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parents[4]))

from core.spark_state import SessionDB
from tests.run_agent.test_orchestration_replay import HTTPReplay, RuntimeReplay

script = json.loads(Path(__file__).with_name("transport-v1.json").read_text())
wire = HTTPReplay(script, Path(sys.argv[2]))
httpx.HTTPTransport.handle_request = lambda self, request: wire.handle(request)
db = SessionDB(Path(sys.argv[1]))
runtime = RuntimeReplay(script, wire, db, asyncio.new_event_loop(), None)
parent = runtime.parent("lost-process", web=False)
runtime.start_root(parent)
root_request = next(c for c in wire.calls if c["messages"][-1]["role"] == "tool"
                    and c["messages"][-1]["tool_call_id"] == "dispatch-1")
print("REPLAY_ACCEPTED=" + root_request["messages"][-1]["content"], flush=True)
os._exit(73)
