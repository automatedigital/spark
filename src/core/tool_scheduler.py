"""Dependency-aware scheduler for one assistant tool-call batch."""

from __future__ import annotations

import concurrent.futures
import contextvars
import json
import logging
import threading
import time
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from core.async_runtime import get_async_runtime
from tools.effects import USER_INTERACTION, ToolEffects, resources_overlap
from tools.registry import ToolRegistry, registry

logger = logging.getLogger(__name__)

_execution_cancel: contextvars.ContextVar[threading.Event | None] = contextvars.ContextVar(
    "tool_execution_cancel", default=None
)
_execution_deadline: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "tool_execution_deadline", default=None
)


def execution_cancelled() -> bool:
    """Cooperative cancellation check for long-running tool handlers."""
    event = _execution_cancel.get()
    deadline = _execution_deadline.get()
    return bool(event and event.is_set()) or bool(deadline and time.monotonic() >= deadline)


def raise_if_execution_cancelled() -> None:
    """Raise ``InterruptedError`` when the current tool should stop."""
    if execution_cancelled():
        raise InterruptedError("tool execution cancelled or deadline exceeded")


@dataclass(frozen=True, slots=True)
class ScheduledTool:
    index: int
    tool_call_id: str
    name: str
    args: dict[str, Any]
    effects: ToolEffects
    resources: tuple[str, ...]
    dependencies: frozenset[int]


@dataclass(frozen=True, slots=True)
class ScheduledResult:
    index: int
    name: str
    args: dict[str, Any]
    content: str
    duration: float
    queue_wait: float = 0.0
    cancelled: bool = False
    timed_out: bool = False


def _parse_call(call: Any) -> tuple[str, str, dict[str, Any]]:
    function = call.function
    try:
        args = json.loads(function.arguments)
    except (json.JSONDecodeError, TypeError):
        args = {}
    if not isinstance(args, dict):
        args = {}
    # Facades are model-visible aliases for legacy handlers.  Classify the
    # normalized legacy action so file paths, reads/writes and web service caps
    # retain exactly the same conflict semantics.  The optional import keeps
    # this branch compatible while the facade rollout is disabled/rolled back.
    try:
        from tools.facades import normalize_facade_call

        normalized = normalize_facade_call(str(function.name), args)
        if isinstance(normalized, tuple) and len(normalized) == 2:
            normalized_name, normalized_args = normalized
            if isinstance(normalized_name, str) and isinstance(normalized_args, dict):
                return str(call.id), normalized_name, normalized_args
    except (ImportError, ValueError, TypeError):
        logger.debug("Ignoring error in _parse_call()", exc_info=True)
    return str(call.id), str(function.name), args


def effects_conflict(left: ScheduledTool, right: ScheduledTool) -> bool:
    """Return whether two calls require an order edge."""
    if USER_INTERACTION in left.effects.effects or USER_INTERACTION in right.effects.effects:
        return True
    overlap = any(
        resources_overlap(left_resource, right_resource)
        for left_resource in left.resources
        for right_resource in right.resources
    )
    if not overlap:
        return False
    if left.effects.ordered or right.effects.ordered:
        return True
    # Shared reads are safe.  Writes, processes and interaction conflict.
    return left.effects.writes or right.effects.writes


def build_tool_dag(
    tool_calls: Sequence[Any],
    *,
    tool_registry: ToolRegistry = registry,
) -> list[ScheduledTool]:
    """Build a deterministic dependency graph in assistant call order."""
    partial: list[tuple[int, str, str, dict[str, Any], ToolEffects, tuple[str, ...]]] = []
    for index, call in enumerate(tool_calls):
        call_id, name, args = _parse_call(call)
        effects = tool_registry.get_effects(name)
        partial.append((index, call_id, name, args, effects, effects.resources(args)))

    nodes: list[ScheduledTool] = []
    for index, call_id, name, args, effects, resources in partial:
        candidate = ScheduledTool(
            index=index,
            tool_call_id=call_id,
            name=name,
            args=args,
            effects=effects,
            resources=resources,
            dependencies=frozenset(),
        )
        deps = {
            prior.index
            for prior in nodes
            if effects_conflict(prior, candidate)
        }
        nodes.append(
            ScheduledTool(
                index=index,
                tool_call_id=call_id,
                name=name,
                args=args,
                effects=effects,
                resources=resources,
                dependencies=frozenset(deps),
            )
        )
    return nodes


def _cancelled_result(node: ScheduledTool, reason: str, *, timed_out: bool = False) -> ScheduledResult:
    return ScheduledResult(
        index=node.index,
        name=node.name,
        args=node.args,
        content=f"[Tool execution cancelled — {node.name} {reason}]",
        duration=0.0,
        cancelled=True,
        timed_out=timed_out,
    )


class ToolBatchScheduler:
    """Execute ready DAG nodes while respecting service concurrency caps."""

    def __init__(self, *, max_workers: int = 8, poll_interval: float = 0.01):
        self.max_workers = max(1, max_workers)
        self.poll_interval = max(0.001, poll_interval)

    def execute(
        self,
        nodes: Sequence[ScheduledTool],
        invoke: Callable[[ScheduledTool], str],
        *,
        interrupted: Callable[[], bool] | None = None,
        batch_deadline: float | None = None,
    ) -> list[ScheduledResult]:
        """Execute nodes and return results in original assistant order.

        ``batch_deadline`` is an absolute ``time.monotonic`` value.  Every
        queued/cancelled call receives a result, and the executor is joined so
        no callback or worker survives batch finalization.
        """
        if not nodes:
            return []
        cancel_event = threading.Event()
        pending = {node.index: node for node in nodes}
        completed: set[int] = set()
        running: dict[concurrent.futures.Future[ScheduledResult], ScheduledTool] = {}
        service_active: defaultdict[str, int] = defaultdict(int)
        results: list[ScheduledResult | None] = [None] * len(nodes)
        batch_queued_at = time.monotonic()

        def _run(node: ScheduledTool) -> ScheduledResult:
            started = time.monotonic()
            node_deadline = batch_deadline
            if node.effects.deadline_seconds is not None:
                own_deadline = started + node.effects.deadline_seconds
                node_deadline = min(node_deadline, own_deadline) if node_deadline else own_deadline
            cancel_token = _execution_cancel.set(cancel_event)
            deadline_token = _execution_deadline.set(node_deadline)
            try:
                if execution_cancelled():
                    return _cancelled_result(node, "was skipped before start")
                content = invoke(node)
                timed_out = bool(node_deadline and time.monotonic() >= node_deadline)
                if timed_out and not execution_cancelled():
                    timed_out = False
                if timed_out:
                    return _cancelled_result(node, "exceeded its deadline", timed_out=True)
                return ScheduledResult(
                    index=node.index,
                    name=node.name,
                    args=node.args,
                    content=content,
                    duration=time.monotonic() - started,
                    queue_wait=started - batch_queued_at,
                )
            except InterruptedError:
                return _cancelled_result(
                    node,
                    "stopped cooperatively",
                    timed_out=bool(node_deadline and time.monotonic() >= node_deadline),
                )
            except Exception as exc:
                return ScheduledResult(
                    index=node.index,
                    name=node.name,
                    args=node.args,
                    content=f"Error executing tool '{node.name}': {exc}",
                    duration=time.monotonic() - started,
                    queue_wait=started - batch_queued_at,
                )
            finally:
                _execution_deadline.reset(deadline_token)
                _execution_cancel.reset(cancel_token)

        runtime = get_async_runtime()
        try:
            while pending or running:
                deadline_expired = bool(batch_deadline and time.monotonic() >= batch_deadline)
                was_interrupted = bool(interrupted and interrupted())
                if deadline_expired or was_interrupted:
                    cancel_event.set()
                    reason = "exceeded the batch deadline" if deadline_expired else "was skipped due to user interrupt"
                    for index, node in list(pending.items()):
                        results[index] = _cancelled_result(
                            node, reason, timed_out=deadline_expired
                        )
                        completed.add(index)
                        pending.pop(index)

                made_progress = True
                while made_progress and pending and len(running) < self.max_workers and not cancel_event.is_set():
                    made_progress = False
                    for index in sorted(pending):
                        if len(running) >= self.max_workers:
                            break
                        node = pending[index]
                        if not node.dependencies.issubset(completed):
                            continue
                        service = node.effects.service or node.name
                        cap = node.effects.concurrency_cap
                        if cap is not None and service_active[service] >= cap:
                            continue
                        future = runtime.submit_tool(_run, node)
                        running[future] = node
                        service_active[service] += 1
                        pending.pop(index)
                        made_progress = True
                        break

                if not running:
                    if pending and not cancel_event.is_set():
                        # A malformed/cyclic graph must still produce complete
                        # transcripts rather than hanging the agent loop.
                        for index, node in list(pending.items()):
                            results[index] = _cancelled_result(node, "could not satisfy dependencies")
                            pending.pop(index)
                    continue

                done, _ = concurrent.futures.wait(
                    tuple(running),
                    timeout=self.poll_interval,
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )
                for future in done:
                    node = running.pop(future)
                    service = node.effects.service or node.name
                    service_active[service] = max(0, service_active[service] - 1)
                    result = future.result()
                    results[node.index] = result
                    completed.add(node.index)
        finally:
            cancel_event.set()
            # Futures are drained by the loop above.  The process runtime owns
            # and closes the shared executor at process shutdown.
            for future in running:
                future.cancel()
            if running:
                concurrent.futures.wait(tuple(running))

        return [
            result if result is not None else _cancelled_result(nodes[index], "did not return a result")
            for index, result in enumerate(results)
        ]


class OrderedCallbackDispatcher:
    """Single-worker, ordered, non-blocking display callback queue."""

    def __init__(self):
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="spark-tool-display"
        )
        self._lock = threading.Lock()
        self._tail: concurrent.futures.Future[Any] | None = None
        self._closed = False

    def emit(self, callback: Callable[..., Any] | None, *args: Any, **kwargs: Any) -> None:
        if callback is None:
            return
        with self._lock:
            if self._closed:
                return

            def _call() -> None:
                try:
                    callback(*args, **kwargs)
                except Exception:
                    # Display failures never alter model-visible tool results.
                    return

            self._tail = self._executor.submit(_call)

    def drain(self, timeout: float | None = 5.0) -> None:
        with self._lock:
            tail = self._tail
        if tail is not None:
            tail.result(timeout=timeout)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._executor.shutdown(wait=True, cancel_futures=False)
