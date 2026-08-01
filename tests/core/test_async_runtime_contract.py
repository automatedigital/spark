import json
import threading
from pathlib import Path

from tools.effects import NETWORK, READ, ToolEffects
from tools.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[2]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_hot_tool_bridges_create_no_per_call_loops_or_one_worker_executors():
    for relative in (
        "src/core/model_tools.py",
        "src/tools/homeassistant_tool.py",
        "src/tools/mcp_tool.py",
    ):
        source = _source(relative)
        assert "asyncio.new_event_loop(" not in source
        assert "ThreadPoolExecutor(max_workers=1)" not in source
    assert "asyncio.run(" not in _source("src/core/model_tools.py")
    assert "asyncio.run(" not in _source("src/tools/homeassistant_tool.py")


def test_gateway_and_web_handlers_use_bounded_runtime_offload():
    for relative in ("src/gateway/run.py", "src/spark_cli/web_server.py"):
        source = _source(relative)
        assert "run_in_executor(" not in source
        assert "asyncio.to_thread(" not in source
        assert "await _run_blocking(" in source


def test_inventory_covers_every_forbidden_pattern_family():
    inventory = _source("docs/performance/async-runtime-inventory.md")
    for pattern in (
        "asyncio.run",
        "new_event_loop",
        "ThreadPoolExecutor",
        "requests",
        "httpx",
        "time.sleep",
    ):
        assert pattern in inventory


def test_recorded_benchmarks_meet_scheduler_and_runtime_contracts():
    report = json.loads(
        _source("docs/performance/scheduler-runtime-benchmark.json")
    )
    assert report["scheduler"]["median_seconds"] < 1.2
    assert report["scheduler"]["p95_seconds"] < 1.2
    assert report["runtime"]["loops_created"] == 1
    assert report["runtime"]["open_client_pools"] == 1
    assert report["runtime"]["failures"] == 0
    assert report["runtime"]["retries"] == 0
    assert report["stress"]["randomized_batches"] == 1000
    assert report["stress"]["complete_result_sets"] == 1000
    assert report["stress"]["shutdown_leaks"] == 0


def test_sync_network_registry_handler_uses_runtime_tool_pool():
    test_registry = ToolRegistry()
    test_registry.register(
        name="network_fixture",
        toolset="fixture",
        schema={"name": "network_fixture", "parameters": {"type": "object"}},
        handler=lambda _args, **_kwargs: threading.current_thread().name,
        effects=ToolEffects(
            frozenset({READ, NETWORK}),
            ("const:remote:fixture",),
            service="fixture",
        ),
    )
    assert test_registry.dispatch("network_fixture", {}).startswith("spark-tool-worker")
