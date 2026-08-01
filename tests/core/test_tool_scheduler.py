import json
import random
import sqlite3
import sys
import threading
import time
from types import ModuleType, SimpleNamespace

from core.async_runtime import get_async_runtime
from core.tool_scheduler import (
    OrderedCallbackDispatcher,
    ToolBatchScheduler,
    build_tool_dag,
    execution_cancelled,
)
from tools.effects import NETWORK, READ, ToolEffects
from tools.registry import ToolRegistry, registry


def _call(call_id: str, name: str, **args):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(args)),
    )


def test_every_registered_tool_has_complete_effect_metadata():
    for name in registry.get_all_tool_names():
        effects = registry.get_effects(name)
        assert effects.effects
        assert effects.resource_templates
        assert effects.service


def test_conflict_table_covers_state_process_browser_and_interaction():
    calls = [
        _call("r1", "read_file", path="/tmp/a"),
        _call("r2", "read_file", path="/tmp/a"),
        _call("w1", "write_file", path="/tmp/a", content="x"),
        _call("w2", "write_file", path="/tmp/b", content="y"),
        _call("t1", "terminal", command="pwd", workdir="/tmp/a"),
        _call("t2", "terminal", command="pwd", workdir="/tmp/b"),
        _call("b1", "browser_snapshot"),
        _call("b2", "browser_click", element="1"),
        _call("m1", "memory", action="add", content="a"),
        _call("m2", "memory", action="add", content="b"),
        _call("d1", "todo", todos=[]),
        _call("c1", "clarify", question="continue?"),
        _call("web", "web_search", query="spark"),
    ]
    nodes = build_tool_dag(calls)
    assert nodes[1].dependencies == frozenset()  # overlapping reads are safe
    assert {0, 1}.issubset(nodes[2].dependencies)  # write follows both reads
    assert 2 not in nodes[3].dependencies  # independent path write
    assert 4 in nodes[5].dependencies  # terminal process state is serialized
    assert 6 in nodes[7].dependencies  # browser session mutation is serialized
    assert 8 in nodes[9].dependencies  # memory writes are serialized
    assert 9 not in nodes[10].dependencies  # todo uses independent state
    assert nodes[11].dependencies == frozenset(range(11))  # user interaction is a barrier
    assert 11 in nodes[12].dependencies  # nothing passes an interaction barrier


def test_facade_calls_are_normalized_before_effect_classification(monkeypatch):
    facades = ModuleType("tools.facades")

    def normalize(name, args):
        if name != "files":
            return name, args
        action = args["action"]
        legacy = "read_file" if action == "read" else "write_file"
        return legacy, {key: value for key, value in args.items() if key != "action"}

    facades.normalize_facade_call = normalize
    monkeypatch.setitem(sys.modules, "tools.facades", facades)
    nodes = build_tool_dag(
        [
            _call("one", "files", action="read", path="/tmp/facade"),
            _call("two", "files", action="write", path="/tmp/facade", content="x"),
        ]
    )
    assert [node.name for node in nodes] == ["read_file", "write_file"]
    assert nodes[1].dependencies == frozenset({0})


def test_four_independent_half_second_tools_finish_under_target():
    nodes = build_tool_dag(
        [_call(str(index), "read_file", path=f"/tmp/file-{index}") for index in range(4)]
    )
    started = time.monotonic()
    results = ToolBatchScheduler(max_workers=4).execute(
        nodes, lambda _node: (time.sleep(0.5) or "ok")
    )
    elapsed = time.monotonic() - started
    assert elapsed < 1.2
    assert [result.content for result in results] == ["ok"] * 4


def test_conflicting_tools_remain_ordered_without_artificial_delay():
    nodes = build_tool_dag(
        [_call(str(index), "write_file", path="/tmp/shared", content=str(index)) for index in range(4)]
    )
    observed = []
    started = time.monotonic()
    results = ToolBatchScheduler(max_workers=4).execute(
        nodes, lambda node: (observed.append(node.index) or str(node.index))
    )
    assert time.monotonic() - started < 0.5
    assert observed == [0, 1, 2, 3]
    assert [result.content for result in results] == ["0", "1", "2", "3"]


def test_remote_service_concurrency_cap_is_enforced():
    test_registry = ToolRegistry()
    test_registry.register(
        name="rate_limited_read",
        toolset="fixture",
        schema={"name": "rate_limited_read", "parameters": {"type": "object"}},
        handler=lambda _args: "ok",
        effects=ToolEffects(
            frozenset({READ, NETWORK}),
            ("const:remote:fixture",),
            concurrency_cap=2,
            service="fixture-api",
        ),
    )
    nodes = build_tool_dag(
        [_call(str(index), "rate_limited_read") for index in range(8)],
        tool_registry=test_registry,
    )
    active = 0
    peak = 0
    lock = threading.Lock()

    def invoke(_node):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.01)
        with lock:
            active -= 1
        return "ok"

    ToolBatchScheduler(max_workers=8).execute(nodes, invoke)
    assert peak == 2


def test_batch_deadline_cancels_running_and_queued_calls():
    nodes = build_tool_dag(
        [_call(str(index), "read_file", path=f"/tmp/deadline-{index}") for index in range(8)]
    )

    def invoke(_node):
        while not execution_cancelled():
            time.sleep(0.001)
        raise InterruptedError

    results = ToolBatchScheduler(max_workers=2).execute(
        nodes,
        invoke,
        batch_deadline=time.monotonic() + 0.02,
    )
    assert len(results) == 8
    assert all(result.cancelled and result.timed_out for result in results)


def test_state_write_effects_prevent_locked_db_transactions(tmp_path):
    database = tmp_path / "scheduler.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE counter (value INTEGER NOT NULL)")
        connection.execute("INSERT INTO counter VALUES (0)")
    nodes = build_tool_dag(
        [_call(str(index), "memory", action="add", content=str(index)) for index in range(20)]
    )

    def invoke(_node):
        with sqlite3.connect(database, timeout=0) as connection:
            connection.execute("BEGIN IMMEDIATE")
            value = connection.execute("SELECT value FROM counter").fetchone()[0]
            time.sleep(0.001)
            connection.execute("UPDATE counter SET value = ?", (value + 1,))
        return "ok"

    results = ToolBatchScheduler(max_workers=8).execute(nodes, invoke)
    assert not any("locked" in result.content.lower() for result in results)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT value FROM counter").fetchone()[0] == 20


def test_cancellation_emits_one_result_per_call_and_joins_workers():
    cancelled = threading.Event()
    worker_threads = []
    nodes = build_tool_dag(
        [_call(str(index), "read_file", path=f"/tmp/{index}") for index in range(12)]
    )

    def invoke(_node):
        worker_threads.append(threading.current_thread())
        while not execution_cancelled():
            time.sleep(0.001)
        raise InterruptedError

    timer = threading.Timer(0.02, cancelled.set)
    timer.start()
    results = ToolBatchScheduler(max_workers=4).execute(
        nodes, invoke, interrupted=cancelled.is_set
    )
    timer.join()
    assert len(results) == len(nodes)
    assert all(result.cancelled for result in results)
    assert worker_threads
    assert get_async_runtime().telemetry()["worker_active"] == 0


def test_one_thousand_randomized_batches_have_complete_deterministic_transcripts():
    rng = random.Random(4815)
    scheduler = ToolBatchScheduler(max_workers=4)
    cancelled_batches = 0
    for batch in range(1000):
        count = rng.randint(1, 5)
        cancel_batch = rng.random() < 0.2
        calls = [
            _call(f"{batch}-{index}", "read_file", path=f"/tmp/{rng.randint(0, 3)}")
            for index in range(count)
        ]
        nodes = build_tool_dag(calls)
        results = scheduler.execute(
            nodes,
            lambda node: (time.sleep(rng.random() / 100000) or node.tool_call_id),
            interrupted=lambda: cancel_batch,
        )
        assert len(results) == len(calls)
        if cancel_batch:
            cancelled_batches += 1
            assert all(result.cancelled for result in results)
        else:
            assert [result.content for result in results] == [call.id for call in calls]
    assert cancelled_batches >= 100


def test_display_callbacks_are_nonblocking_ordered_and_closed_cleanly():
    events = []
    dispatcher = OrderedCallbackDispatcher()

    def slow(value):
        time.sleep(0.05)
        events.append(value)

    started = time.monotonic()
    dispatcher.emit(slow, "start")
    dispatcher.emit(slow, "complete")
    assert time.monotonic() - started < 0.02
    dispatcher.close()
    assert events == ["start", "complete"]
    dispatcher.emit(slow, "after-close")
    assert events == ["start", "complete"]
