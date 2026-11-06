"""Probe the unresolved cached-agent physical-worker DB ownership requirement.

This exits 1 when construction/use/disposal occur on different threads. It is a
standalone acceptance probe, not an expected-failure pytest test. No live model
or user profile is used.
"""

import argparse
import asyncio
import json
import os
import tempfile
import threading
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--output", required=True)
args = parser.parse_args()
profile = tempfile.TemporaryDirectory(prefix="spark-sp03-db-owner-")
os.environ["SPARK_HOME"] = profile.name

from core import run_agent  # noqa: E402
from core.spark_state import SessionDB  # noqa: E402
from spark_cli import web_server as web  # noqa: E402

opened = {}
trace = []
original_init = SessionDB.__init__
original_close = SessionDB.close
agent_database = None


def thread():
    return {"id": threading.get_ident(), "name": threading.current_thread().name}


def db_init(db, *args, **kwargs):
    original_init(db, *args, **kwargs)
    opened[db] = thread()


def db_close(db):
    if db is agent_database:
        trace.append({"stage": "close", **thread()})
    return original_close(db)


class FixtureAgent:
    def __init__(self, **kwargs):
        global agent_database
        self.session_id = kwargs["session_id"]
        self._session_db = kwargs["session_db"]
        agent_database = self._session_db
        trace.append({"stage": "create", **opened[agent_database]})


def provider(agent, message, history, items):
    assert agent._session_db.get_session(agent.session_id) is not None
    trace.append({"stage": "use", **thread()})
    return {"final_response": "fixture answer"}


SessionDB.__init__ = db_init
SessionDB.close = db_close
run_agent.AIAgent = FixtureAgent
web._resolve_web_turn_route = lambda *a, **k: {
    "model": "fixture",
    "runtime": {},
    "signature": "fixture",
}
web._run_web_agent_turn = provider
web._maybe_auto_title_web = lambda *a, **k: None


async def main():
    accepted = await web.create_conversation(
        web.ConversationCreate(
            message="physical DB ownership probe",
            submission_id="ownership-probe",
        )
    )
    await asyncio.gather(
        *[
            task
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task()
            and "run_agent_task" in task.get_coro().__qualname__
        ]
    )
    web._close_web_agent(accepted["session_id"])
    result = {
        "single_worker": len({event["id"] for event in trace}) == 1,
        "trace": trace,
        "stages": [event["stage"] for event in trace],
    }
    assert result["stages"] == ["create", "use", "close"]
    Path(args.output).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["single_worker"] else 1


raise SystemExit(asyncio.run(main()))
