"""Process-wide asynchronous runtime and pooled transports.

Spark exposes synchronous tool handlers for compatibility with the model tool
registry, while a growing number of implementations are asynchronous.  This
module provides the one supported sync-to-async bridge: a single daemon event
loop, a bounded blocking-I/O executor, and credential-scoped HTTP client pools.

The runtime is deliberately process-scoped.  Callers may close a transport
scope, but must not close the process runtime or another caller's client.
"""

from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import hashlib
import os
import threading
import time
from collections.abc import Awaitable, Callable, Mapping
from contextvars import copy_context
from dataclasses import dataclass
from typing import Any, TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class TransportKey:
    """Non-secret identity for a safely shareable transport pool.

    Credentials are represented only by a one-way fingerprint.  Profiles,
    base URLs, proxies, and TLS policies are part of the key so clients can
    never cross an isolation boundary merely because they use the same host.
    """

    family: str
    profile: str = "default"
    base_url: str = ""
    credential_fingerprint: str = "anonymous"
    proxy: str = ""
    tls_policy: str = "default"

    @classmethod
    def scoped(
        cls,
        family: str,
        *,
        profile: str = "default",
        base_url: str = "",
        credential: str = "",
        proxy: str = "",
        tls_policy: str = "default",
    ) -> TransportKey:
        digest = (
            hashlib.sha256(credential.encode("utf-8", errors="surrogatepass")).hexdigest()[:16]
            if credential
            else "anonymous"
        )
        return cls(
            family=family,
            profile=profile or "default",
            base_url=base_url.rstrip("/"),
            credential_fingerprint=digest,
            proxy=proxy,
            tls_policy=tls_policy,
        )


class AsyncRuntime:
    """Own one event loop, bounded worker pool, and reusable async clients."""

    def __init__(
        self, *, max_workers: int = 16, tool_workers: int = 8,
        connection_limit: int = 32,
    ):
        self._max_workers = max(1, max_workers)
        self._tool_workers = max(1, tool_workers)
        self._connection_limit = max(1, connection_limit)
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()
        self._state_lock = threading.RLock()
        self._closed = False
        self._executor: concurrent.futures.ThreadPoolExecutor | None = None
        self._tool_executor: concurrent.futures.ThreadPoolExecutor | None = None
        self._named_executors: dict[str, concurrent.futures.ThreadPoolExecutor] = {}
        self._clients: dict[TransportKey, Any] = {}
        self._created_at = time.monotonic()
        self._telemetry: dict[str, int | float] = {
            "loops_created": 0,
            "submitted_tasks": 0,
            "completed_tasks": 0,
            "cancelled_tasks": 0,
            "timed_out_tasks": 0,
            "active_tasks": 0,
            "peak_active_tasks": 0,
            "worker_submissions": 0,
            "worker_active": 0,
            "worker_peak_active": 0,
            "worker_queue_depth": 0,
            "worker_peak_queue_depth": 0,
            "worker_pool_waits": 0,
            "clients_created": 0,
            "client_reuses": 0,
            "clients_closed": 0,
            "shutdown_leaks": 0,
        }

    def _ensure_started(self) -> asyncio.AbstractEventLoop:
        with self._state_lock:
            if self._closed:
                raise RuntimeError("async runtime is closed")
            if self._loop is not None and self._loop.is_running():
                return self._loop
            # A concurrent caller may arrive after the owner thread was
            # started but before it published ``_loop``.  Only the first
            # caller creates the thread; all others wait on the same barrier.
            if self._thread is None or not self._thread.is_alive():
                self._ready.clear()
                self._thread = threading.Thread(
                    target=self._run_loop,
                    name="spark-async-runtime",
                    daemon=True,
                )
                self._thread.start()
        if not self._ready.wait(timeout=10):
            raise RuntimeError("async runtime failed to start")
        assert self._loop is not None
        return self._loop

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=self._max_workers,
            thread_name_prefix="spark-runtime-worker",
        )
        tool_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=self._tool_workers,
            thread_name_prefix="spark-tool-worker",
        )
        loop.set_default_executor(executor)
        with self._state_lock:
            self._loop = loop
            self._executor = executor
            self._tool_executor = tool_executor
            self._telemetry["loops_created"] = int(self._telemetry["loops_created"]) + 1
            self._ready.set()
        try:
            loop.run_forever()
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
            executor.shutdown(wait=True, cancel_futures=True)
            tool_executor.shutdown(wait=True, cancel_futures=True)
            for named_executor in self._named_executors.values():
                named_executor.shutdown(wait=True, cancel_futures=True)
            self._named_executors.clear()
            loop.close()

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        """Return the owned loop, starting it lazily."""
        return self._ensure_started()

    def submit(self, awaitable: Awaitable[T]) -> concurrent.futures.Future[T]:
        """Schedule an awaitable on the process loop from any thread."""
        loop = self._ensure_started()

        async def _tracked() -> T:
            with self._state_lock:
                self._telemetry["active_tasks"] = int(self._telemetry["active_tasks"]) + 1
                self._telemetry["peak_active_tasks"] = max(
                    int(self._telemetry["peak_active_tasks"]),
                    int(self._telemetry["active_tasks"]),
                )
            try:
                return await awaitable
            finally:
                with self._state_lock:
                    self._telemetry["active_tasks"] = max(
                        0, int(self._telemetry["active_tasks"]) - 1
                    )
                    self._telemetry["completed_tasks"] = int(
                        self._telemetry["completed_tasks"]
                    ) + 1

        with self._state_lock:
            self._telemetry["submitted_tasks"] = int(self._telemetry["submitted_tasks"]) + 1
        return asyncio.run_coroutine_threadsafe(_tracked(), loop)

    def run(
        self,
        awaitable: Awaitable[T],
        *,
        timeout: float | None = 300,
        cancelled: Callable[[], bool] | None = None,
    ) -> T:
        """Run an awaitable from synchronous code with cancellation polling."""
        if threading.current_thread() is self._thread:
            if hasattr(awaitable, "close"):
                awaitable.close()  # type: ignore[attr-defined]
            raise RuntimeError("cannot synchronously wait from the async runtime thread")
        future = self.submit(awaitable)
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            if cancelled is not None and cancelled():
                future.cancel()
                with self._state_lock:
                    self._telemetry["cancelled_tasks"] = int(
                        self._telemetry["cancelled_tasks"]
                    ) + 1
                raise InterruptedError("asynchronous operation cancelled")
            wait_for = 0.05
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    future.cancel()
                    with self._state_lock:
                        self._telemetry["timed_out_tasks"] = int(
                            self._telemetry["timed_out_tasks"]
                        ) + 1
                    raise TimeoutError("asynchronous operation timed out")
                wait_for = min(wait_for, remaining)
            try:
                return future.result(timeout=wait_for)
            except concurrent.futures.TimeoutError:
                continue

    async def run_blocking(self, fn: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
        """Run unavoidable blocking work in the bounded runtime executor."""
        future = self.submit_blocking(fn, *args, **kwargs)
        return await asyncio.wrap_future(future)

    def submit_blocking(
        self, fn: Callable[..., T], /, *args: Any, **kwargs: Any
    ) -> concurrent.futures.Future[T]:
        """Submit blocking work to the process pool with context propagation."""
        self._ensure_started()
        return self._submit_worker(self._executor, fn, *args, **kwargs)

    def submit_tool(
        self, fn: Callable[..., T], /, *args: Any, **kwargs: Any
    ) -> concurrent.futures.Future[T]:
        """Submit tool work to the runtime-owned pool reserved against nesting deadlocks."""
        self._ensure_started()
        return self._submit_worker(self._tool_executor, fn, *args, **kwargs)

    async def run_named_blocking(
        self,
        pool: str,
        max_workers: int,
        fn: Callable[..., T],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """Run work in a bounded named pool owned by this runtime service."""
        future = self.submit_named(pool, max_workers, fn, *args, **kwargs)
        return await asyncio.wrap_future(future)

    def submit_named(
        self,
        pool: str,
        max_workers: int,
        fn: Callable[..., T],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> concurrent.futures.Future[T]:
        self._ensure_started()
        with self._state_lock:
            executor = self._named_executors.get(pool)
            if executor is None:
                executor = concurrent.futures.ThreadPoolExecutor(
                    max_workers=max(1, max_workers),
                    thread_name_prefix=f"spark-{pool}",
                )
                self._named_executors[pool] = executor
        return self._submit_worker(executor, fn, *args, **kwargs)

    def _submit_worker(
        self,
        executor: concurrent.futures.ThreadPoolExecutor | None,
        fn: Callable[..., T],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> concurrent.futures.Future[T]:
        self._ensure_started()
        queued_at = time.monotonic()
        with self._state_lock:
            self._telemetry["worker_submissions"] = int(
                self._telemetry["worker_submissions"]
            ) + 1
            self._telemetry["worker_queue_depth"] = int(
                self._telemetry["worker_queue_depth"]
            ) + 1
            if (
                int(self._telemetry["worker_active"]) >= self._max_workers
                or int(self._telemetry["worker_queue_depth"]) > self._max_workers
            ):
                self._telemetry["worker_pool_waits"] = int(
                    self._telemetry["worker_pool_waits"]
                ) + 1
            self._telemetry["worker_peak_queue_depth"] = max(
                int(self._telemetry["worker_peak_queue_depth"]),
                int(self._telemetry["worker_queue_depth"]),
            )

        context = copy_context()

        def _call() -> T:
            with self._state_lock:
                self._telemetry["worker_queue_depth"] = max(
                    0, int(self._telemetry["worker_queue_depth"]) - 1
                )
                self._telemetry["worker_active"] = int(self._telemetry["worker_active"]) + 1
                self._telemetry["worker_peak_active"] = max(
                    int(self._telemetry["worker_peak_active"]),
                    int(self._telemetry["worker_active"]),
                )
                self._telemetry["last_worker_queue_wait_ms"] = round(
                    (time.monotonic() - queued_at) * 1000, 3
                )
            try:
                return context.run(fn, *args, **kwargs)
            finally:
                with self._state_lock:
                    self._telemetry["worker_active"] = max(
                        0, int(self._telemetry["worker_active"]) - 1
                    )

        # The pools are published before the runtime readiness barrier opens.
        selected = executor
        if selected is None:
            selected = self._executor
        assert selected is not None
        return selected.submit(_call)

    async def get_http_client(
        self,
        key: TransportKey,
        *,
        headers: Mapping[str, str] | None = None,
        timeout: float = 30.0,
    ) -> Any:
        """Return a pooled ``httpx.AsyncClient`` for an isolation key."""
        if asyncio.get_running_loop() is not self.loop:
            raise RuntimeError("pooled clients may only be used on the Spark async runtime")
        with self._state_lock:
            client = self._clients.get(key)
        if client is not None and not client.is_closed:
            with self._state_lock:
                self._telemetry["client_reuses"] = int(self._telemetry["client_reuses"]) + 1
            return client
        import httpx

        kwargs: dict[str, Any] = {
            "base_url": key.base_url or "",
            "headers": dict(headers or {}),
            "timeout": timeout,
            "limits": httpx.Limits(
                max_connections=self._connection_limit,
                max_keepalive_connections=max(1, self._connection_limit // 2),
            ),
            "http2": False,
        }
        if key.proxy:
            kwargs["proxy"] = key.proxy
        if key.tls_policy == "insecure":
            kwargs["verify"] = False
        elif key.tls_policy.startswith("ca:"):
            kwargs["verify"] = key.tls_policy[3:]
        client = httpx.AsyncClient(**kwargs)
        with self._state_lock:
            self._clients[key] = client
            self._telemetry["clients_created"] = int(self._telemetry["clients_created"]) + 1
        return client

    async def close_transport(self, key: TransportKey) -> None:
        """Close one credential/profile transport scope without affecting peers."""
        with self._state_lock:
            client = self._clients.pop(key, None)
        if client is not None:
            await client.aclose()
            with self._state_lock:
                self._telemetry["clients_closed"] = int(self._telemetry["clients_closed"]) + 1

    def telemetry(self) -> dict[str, int | float]:
        """Return lifecycle counters without exposing transport secrets."""
        with self._state_lock:
            snapshot = dict(self._telemetry)
            snapshot["active_clients"] = sum(
                1 for client in self._clients.values() if not client.is_closed
            )
            # httpx owns per-origin socket details internally; clients with no
            # in-flight request tracked by this boundary are reusable/idle.
            snapshot["active_connections"] = int(snapshot["active_tasks"])
            snapshot["idle_connections"] = snapshot["active_clients"]
            snapshot["runtime_uptime_seconds"] = round(time.monotonic() - self._created_at, 3)
            snapshot["named_worker_pools"] = len(self._named_executors)
            snapshot["open_file_descriptors"] = _open_fd_count()
            snapshot["closed"] = int(self._closed)
            return snapshot

    def shutdown(self, *, timeout: float = 15.0) -> None:
        """Close clients, cancel tasks, and stop the loop in dependency order."""
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
            loop = self._loop
            thread = self._thread
        if loop is not None and loop.is_running():
            async def _close() -> None:
                with self._state_lock:
                    clients = list(self._clients.values())
                    self._clients.clear()
                if clients:
                    results = await asyncio.gather(
                        *(client.aclose() for client in clients),
                        return_exceptions=True,
                    )
                    leaks = sum(isinstance(result, Exception) for result in results)
                    with self._state_lock:
                        self._telemetry["clients_closed"] = int(
                            self._telemetry["clients_closed"]
                        ) + len(clients) - leaks
                        self._telemetry["shutdown_leaks"] = int(
                            self._telemetry["shutdown_leaks"]
                        ) + leaks

            try:
                asyncio.run_coroutine_threadsafe(_close(), loop).result(timeout=timeout)
            finally:
                loop.call_soon_threadsafe(loop.stop)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)
            if thread.is_alive():
                with self._state_lock:
                    self._telemetry["shutdown_leaks"] = int(
                        self._telemetry["shutdown_leaks"]
                    ) + 1


def _open_fd_count() -> int:
    for directory in ("/proc/self/fd", "/dev/fd"):
        try:
            return len(os.listdir(directory))
        except OSError:
            continue
    try:
        import psutil

        process = psutil.Process()
        return int(process.num_fds()) if hasattr(process, "num_fds") else -1
    except Exception:
        return -1


_runtime: AsyncRuntime | None = None
_runtime_lock = threading.Lock()


def get_async_runtime() -> AsyncRuntime:
    """Return the lazily-created process runtime singleton."""
    global _runtime
    with _runtime_lock:
        if _runtime is None or _runtime.telemetry()["closed"]:
            _runtime = AsyncRuntime()
        return _runtime


def shutdown_async_runtime() -> None:
    """Idempotent process-shutdown hook."""
    global _runtime
    with _runtime_lock:
        runtime = _runtime
        _runtime = None
    if runtime is not None:
        runtime.shutdown()


atexit.register(shutdown_async_runtime)
