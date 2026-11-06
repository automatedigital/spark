"""SP08 browser fixture: production HTTP/UI/persistence; deterministic provider boundary.

Run with a synthetic SPARK_HOME and PYTHONPATH=src. No external model or user
profile is accessed. Only this fixture exposes /api/sp08-fixture evidence.
"""

import hashlib
import json
import os
import threading
import time
from collections import Counter

from core import run_agent
from core.spark_state import SessionDB
from spark_cli import web_server as web

reads = Counter()
created = Counter()
closed = []
requests = []
original_history = SessionDB.get_messages_as_conversation


def read_history(db, sid):
    reads[sid] += 1
    return original_history(db, sid)


class FixtureAgent:
    def __init__(self, **kw):
        self.session_id = kw["session_id"]
        self._session_db = kw["session_db"]
        self._session_messages = []
        self._active_children = []
        self._active_children_lock = threading.Lock()
        self.stream_delta_callback = kw.get("stream_delta_callback")
        created[self.session_id] += 1

    def close(self):
        assert self._session_db is None
        closed.append(self.session_id)

    def interrupt(self, *args):
        pass


def provider(agent, message, history, items):
    # This is the external provider/process replay boundary, not a fake HTTP/UI.
    history = agent._session_messages if history is None else history
    payload = [*history, {"role": "user", "content": message}]
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    requests.append({
        "session_id": agent.session_id, "sha256": hashlib.sha256(raw).hexdigest(),
        "history_count": len(history), "message": message,
        "history_reads": dict(reads),
    })
    text = "Fixture answer: " + message
    for token in ("Fixture ", "answer: ", message):
        if agent.stream_delta_callback:
            agent.stream_delta_callback(token)
        time.sleep(0.03)
    agent._session_messages = [*payload, {"role": "assistant", "content": text}]
    return {"final_response": text, "messages": agent._session_messages}


SessionDB.get_messages_as_conversation = read_history
run_agent.AIAgent = FixtureAgent
web._run_web_agent_turn = provider
web._resolve_web_turn_route = lambda *a, **kw: {"model": "fixture", "runtime": {}, "signature": "fixture"}
web._maybe_auto_title_web = lambda *a, **kw: None


def snapshot():
    from spark_cli.web_agent_cache import retained_context_bytes

    return {
        "agents": list(web._web_agents), "created": dict(created), "closed": closed,
        "history_reads": dict(reads), "requests": requests,
        "estimated_context_bytes": sum(retained_context_bytes(a) for a in web._web_agents.values()),
        "warm_inflight": sorted(web._web_warm_inflight),
    }


@web.app.get("/api/sp08-fixture")
async def evidence():
    return snapshot()


# This test-only route must precede the production SPA catch-all.
web.app.router.routes.insert(0, web.app.router.routes.pop())

if not os.environ.get("SPARK_HOME"):
    raise SystemExit("Set SPARK_HOME to a synthetic temporary profile for this fixture")

db = SessionDB()
try:
    for sid, title in (("sp08-a", "SP08 Alpha"), ("sp08-b", "SP08 Beta"), ("sp08-c", "SP08 Gamma")):
        if not db.get_session(sid):
            db.create_session(sid, "web", model="fixture")
            db.set_session_title(sid, title)
            db.append_message(sid, "user", f"{title} original Unicode é 中 👋")
            db.append_message(sid, "assistant", f"{title} durable answer")
finally:
    db.close()

web.start_server(host="127.0.0.1", port=int(os.environ.get("SP08_PORT", "5188")), open_browser=False)
