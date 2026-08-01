import asyncio
import threading
import time

from core.async_runtime import AsyncRuntime, TransportKey


async def _loop_identity():
    return id(asyncio.get_running_loop())


def test_all_threads_share_exactly_one_runtime_loop():
    runtime = AsyncRuntime(max_workers=4)
    try:
        identities = []

        def worker():
            identities.append(runtime.run(_loop_identity()))

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert len(set(identities)) == 1
        assert runtime.telemetry()["loops_created"] == 1
    finally:
        runtime.shutdown()


def test_transport_pool_reuses_only_complete_isolation_key():
    runtime = AsyncRuntime()
    key_a = TransportKey.scoped(
        "provider", profile="one", base_url="https://example.test",
        credential="secret-a", proxy="", tls_policy="default",
    )
    key_b = TransportKey.scoped(
        "provider", profile="one", base_url="https://example.test",
        credential="secret-b", proxy="", tls_policy="default",
    )
    key_c = TransportKey.scoped(
        "provider", profile="two", base_url="https://example.test",
        credential="secret-a", proxy="", tls_policy="default",
    )
    key_d = TransportKey.scoped(
        "provider", profile="one", base_url="https://other.test",
        credential="secret-a", proxy="", tls_policy="default",
    )
    key_e = TransportKey.scoped(
        "provider", profile="one", base_url="https://example.test",
        credential="secret-a", proxy="http://proxy.test:8080", tls_policy="default",
    )
    key_f = TransportKey.scoped(
        "provider", profile="one", base_url="https://example.test",
        credential="secret-a", proxy="", tls_policy="insecure",
    )

    async def acquire():
        first = await runtime.get_http_client(key_a)
        same = await runtime.get_http_client(key_a)
        other_credential = await runtime.get_http_client(key_b)
        other_profile = await runtime.get_http_client(key_c)
        other_base = await runtime.get_http_client(key_d)
        other_proxy = await runtime.get_http_client(key_e)
        other_tls = await runtime.get_http_client(key_f)
        return first, same, other_credential, other_profile, other_base, other_proxy, other_tls

    try:
        first, same, other_credential, other_profile, other_base, other_proxy, other_tls = runtime.run(acquire())
        assert first is same
        assert first is not other_credential
        assert first is not other_profile
        assert len({id(first), id(other_credential), id(other_profile), id(other_base), id(other_proxy), id(other_tls)}) == 6
        assert "secret" not in repr(key_a)
        runtime.run(runtime.close_transport(key_a))
        assert first.is_closed
        assert not other_credential.is_closed
        telemetry = runtime.telemetry()
        assert telemetry["clients_created"] == 6
        assert telemetry["client_reuses"] == 1
        assert telemetry["clients_closed"] == 1
        assert telemetry["active_clients"] == 5
    finally:
        runtime.shutdown()
    assert runtime.telemetry()["shutdown_leaks"] == 0


def test_bounded_worker_pool_reports_queue_and_shutdown_state():
    runtime = AsyncRuntime(max_workers=2)

    async def load():
        return await asyncio.gather(
            *(runtime.run_blocking(time.sleep, 0.02) for _ in range(20))
        )

    try:
        runtime.run(load())
        telemetry = runtime.telemetry()
        assert telemetry["worker_submissions"] == 20
        assert telemetry["worker_peak_active"] <= 2
        assert telemetry["worker_peak_queue_depth"] >= 2
        assert telemetry["worker_pool_waits"] > 0
        assert telemetry["open_file_descriptors"] >= 0
        assert "active_connections" in telemetry
        assert "idle_connections" in telemetry
    finally:
        runtime.shutdown()
    assert runtime.telemetry()["active_tasks"] == 0
    assert runtime.telemetry()["shutdown_leaks"] == 0


def test_cancel_restart_and_close_do_not_leak_loop_bound_state():
    first = AsyncRuntime()
    cancelled = threading.Event()

    async def wait_forever():
        await asyncio.sleep(60)

    timer = threading.Timer(0.02, cancelled.set)
    timer.start()
    try:
        try:
            first.run(wait_forever(), cancelled=cancelled.is_set)
        except InterruptedError:
            pass
        assert first.telemetry()["cancelled_tasks"] == 1
    finally:
        timer.join()
        first.shutdown()

    second = AsyncRuntime()
    try:
        assert second.run(_loop_identity()) != 0
        assert second.telemetry()["loops_created"] == 1
    finally:
        second.shutdown()
    assert first.telemetry()["shutdown_leaks"] == 0
    assert second.telemetry()["shutdown_leaks"] == 0


def test_sequential_and_twenty_concurrent_requests_use_one_pool():
    runtime = AsyncRuntime(connection_limit=20)
    key = TransportKey.scoped(
        "load-test", base_url="https://load.invalid", credential="fixture"
    )

    async def fake_request():
        # Acquire the real pooled client while keeping the load test hermetic.
        client = await runtime.get_http_client(key)
        await asyncio.sleep(0.005)
        return id(client)

    try:
        sequential_start = time.monotonic()
        sequential = [runtime.run(fake_request()) for _ in range(100)]
        sequential_elapsed = time.monotonic() - sequential_start

        async def concurrent_batch():
            return await asyncio.gather(*(fake_request() for _ in range(20)))

        concurrent_start = time.monotonic()
        concurrent = runtime.run(concurrent_batch())
        concurrent_elapsed = time.monotonic() - concurrent_start
        assert len(set(sequential + concurrent)) == 1
        assert concurrent_elapsed < sequential_elapsed / 3
        telemetry = runtime.telemetry()
        assert telemetry["loops_created"] == 1
        assert telemetry["clients_created"] == 1
        assert telemetry["client_reuses"] == 119
    finally:
        runtime.shutdown()
