"""Probe every physical DB lifetime of a cached web agent.

This exits 1 when any connection is used or closed outside its opening worker. It is a
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
original_get_session = SessionDB.get_session
agent_databases = set()
agent_database = None


def thread():
    return {"id": threading.get_ident(), "name": threading.current_thread().name}


def db_init(db, *args, **kwargs):
    original_init(db, *args, **kwargs)
    opened[db] = thread()


def db_close(db):
    if db in agent_databases:
        trace.append({"stage": "close", "db": id(db), **thread()})
    return original_close(db)


def db_get_session(db, *args, **kwargs):
    # Track the exact real connection supplied to the provider, including a
    # fresh lease on a reused cached agent. No object-wide affinity assumption.
    if db not in agent_databases:
        agent_databases.add(db)
        trace.append({"stage": "create", "db": id(db), **opened[db]})
    trace.append({"stage": "use", "db": id(db), **thread()})
    return original_get_session(db, *args, **kwargs)


class FixtureAgent:
    def __init__(self, **kwargs):
        global agent_database
        self.session_id = kwargs["session_id"]
        self._session_db = kwargs["session_db"]
        agent_database = self._session_db
        agent_databases.add(agent_database)
        trace.append({"stage": "create", "db": id(agent_database), **opened[agent_database]})


def provider(agent, message, history, items):
    assert agent._session_db.get_session(agent.session_id) is not None
    return {"final_response": "fixture answer"}


SessionDB.__init__ = db_init
SessionDB.close = db_close
SessionDB.get_session = db_get_session
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
        "single_worker": all(
            len({event["id"] for event in trace if event["db"] == id(db)}) == 1
            for db in agent_databases
        ),
        "trace": trace,
        "stages": [event["stage"] for event in trace],
    }
    assert any(event["stage"] == "use" for event in trace)
    for db in agent_databases:
        stages = [event["stage"] for event in trace if event["db"] == id(db)]
        assert stages[0] == "create" and stages[-1] == "close"
        assert stages.count("create") == stages.count("close") == 1
    Path(args.output).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["single_worker"] else 1


raise SystemExit(asyncio.run(main()))
