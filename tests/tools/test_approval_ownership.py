"""Deterministic registration/queue races; no command execution or external I/O."""
import contextvars
import gc
import json
import threading
import weakref
from concurrent.futures import ThreadPoolExecutor

import pytest

from tools import approval

KEY = "synthetic-approval-owner"
COMMAND = "rm -rf /synthetic-never-executed"


@pytest.fixture(autouse=True)
def isolated_approvals(monkeypatch):
    monkeypatch.setenv("SPARK_GATEWAY_SESSION", "1")
    monkeypatch.delenv("SPARK_YOLO_MODE", raising=False)
    monkeypatch.setenv("TIRITH_ENABLED", "false")
    monkeypatch.setattr(approval, "_permanent_approved", set())
    monkeypatch.setattr(approval, "_get_approval_config", lambda: {"mode": "manual", "gateway_timeout": 3})
    approval.clear_session(KEY)
    yield
    approval.unregister_gateway_notify(KEY)
    approval.clear_session(KEY)


def bound_context(owner):
    context = contextvars.copy_context()
    context.run(approval.set_current_session_key, KEY, owner=owner)
    return context


def guard():
    return approval.check_all_command_guards(COMMAND, "local")


def test_superseding_registration_cancels_old_waiters_and_stale_cleanup_cannot_touch_new():
    old_notified, new_notified = threading.Event(), threading.Event()
    old = approval.register_gateway_notify(KEY, lambda data: old_notified.set())
    old_context = bound_context(old)
    with ThreadPoolExecutor(max_workers=2) as pool:
        old_result = pool.submit(old_context.run, guard)
        assert old_notified.wait(2)
        new = approval.register_gateway_notify(KEY, lambda data: new_notified.set())
        new_result = pool.submit(bound_context(new).run, guard)
        try:
            assert new_notified.wait(2)
            cancelled = old_result.result(2)
            assert cancelled["approved"] is False and "cancelled" in cancelled["message"]
            approval.unregister_gateway_notify(KEY, old)
            assert approval.has_blocking_approval(KEY)
            assert len(approval._gateway_queues[KEY]) == 1
            assert old_context.run(guard)["approved"] is False
            assert len(approval._gateway_queues[KEY]) == 1
            assert approval.resolve_gateway_approval(KEY, "once") == 1
            assert new_result.result(2)["user_approved"] is True
            assert approval.resolve_gateway_approval(KEY, "once") == 0
        finally:
            approval.unregister_gateway_notify(KEY)
    assert KEY not in approval._gateway_queues


@pytest.mark.parametrize("notify_raises", [False, True])
def test_callback_already_captured_when_replaced_cannot_enqueue_or_remove_new_waiter(notify_raises):
    entered, release, notified = threading.Event(), threading.Event(), threading.Event()

    def old_notify(data):
        entered.set()
        assert release.wait(3)
        if notify_raises:
            raise RuntimeError("synthetic old transport failure")

    old = approval.register_gateway_notify(KEY, old_notify)
    with ThreadPoolExecutor(max_workers=2) as pool:
        old_result = pool.submit(bound_context(old).run, guard)
        try:
            assert entered.wait(2)
            # The old entry must already be queued while its callback runs;
            # replacement cancels it atomically, without holding a lock over I/O.
            assert len(approval._gateway_queues[KEY]) == 1
            new = approval.register_gateway_notify(KEY, lambda data: notified.set())
            new_result = pool.submit(bound_context(new).run, guard)
            assert notified.wait(2)
            release.set()
            assert old_result.result(2)["approved"] is False
            approval.unregister_gateway_notify(KEY, old)
            assert len(approval._gateway_queues[KEY]) == 1
            assert approval._gateway_owners[KEY] is new
            assert approval.resolve_gateway_approval(KEY, "once") == 1
            assert new_result.result(2)["approved"] is True
        finally:
            release.set()
            approval.unregister_gateway_notify(KEY)


def test_three_competing_owners_only_latest_can_request_approval():
    owners, contexts = [], []
    notified = []
    for _ in range(3):
        owners.append(approval.register_gateway_notify(KEY, lambda data: notified.append(data)))
        contexts.append(bound_context(owners[-1]))
    for owner, context in zip(owners[:-1], contexts[:-1]):
        approval.unregister_gateway_notify(KEY, owner)
        for check in (approval.check_all_command_guards, approval.check_dangerous_command):
            result = context.run(check, COMMAND, "local")
            assert result["approved"] is False and "cancelled" in result["message"]
    assert notified == [] and KEY not in approval._pending
    assert approval._gateway_owners[KEY] is owners[-1]


def test_stop_wins_before_late_registration_without_clobbering_replacement():
    cancelled = threading.Event()
    cancelled.set()
    new = approval.register_gateway_notify(KEY, lambda data: None)
    retired = approval.register_gateway_notify(KEY, lambda data: pytest.fail("retired callback"), cancelled=cancelled)
    assert approval._gateway_owners[KEY] is new
    assert bound_context(retired).run(guard)["approved"] is False
    approval.unregister_gateway_notify(KEY, retired)
    assert approval._gateway_owners[KEY] is new


@pytest.mark.parametrize("preapproved", [False, True])
def test_unregister_and_reregister_during_guard_collection_cannot_borrow_callback(monkeypatch, preapproved):
    entered, release = threading.Event(), threading.Event()
    notified = []

    def security_scan(command):
        entered.set()
        assert release.wait(3)
        return {"action": "allow", "findings": []}

    monkeypatch.setattr("tools.tirith_security.check_command_security", security_scan)
    owner = approval.register_gateway_notify(KEY, lambda data: notified.append("old"))
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(bound_context(owner).run, guard)
        try:
            assert entered.wait(2)
            approval.unregister_gateway_notify(KEY, owner)
            replacement = approval.register_gateway_notify(KEY, lambda data: notified.append("new"))
            if preapproved:
                approval.approve_session(KEY, "delete in root path")
            release.set()
            result = future.result(2)
            assert result["approved"] is False and "cancelled" in result["message"]
            assert notified == [] and not approval.has_blocking_approval(KEY)
            assert KEY not in approval._pending
            assert approval._gateway_owners[KEY] is replacement
        finally:
            release.set()
            approval.unregister_gateway_notify(KEY)


@pytest.mark.parametrize("cancel", [approval.unregister_gateway_notify, approval.clear_session])
def test_whole_session_cancellation_wakes_every_parallel_waiter(cancel):
    barrier = threading.Barrier(4)
    owner = approval.register_gateway_notify(KEY, lambda data: barrier.wait(3))
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(bound_context(owner).run, guard) for _ in range(3)]
        try:
            barrier.wait(3)
            assert len(approval._gateway_queues[KEY]) == 3
            cancel(KEY)
            assert not approval.has_blocking_approval(KEY)
            for future in futures:
                result = future.result(2)
                assert result["approved"] is False and "cancelled" in result["message"]
        finally:
            approval.unregister_gateway_notify(KEY)


def test_no_callback_legacy_batch_fallback_is_preserved():
    token = approval.set_current_session_key(KEY)
    try:
        result = guard()
        assert result["status"] == "approval_required"
        assert approval._pending[KEY]["command"] == COMMAND
    finally:
        approval.reset_current_session_key(token)


def test_legacy_session_binding_does_not_acquire_execution_ownership():
    approval.register_gateway_notify(KEY, lambda data: None)
    token = approval.set_current_session_key(KEY)
    try:
        approval.unregister_gateway_notify(KEY)
        assert approval.check_all_command_guards("pwd", "local")["approved"] is True
        assert guard()["status"] == "approval_required"
    finally:
        approval.reset_current_session_key(token)


def test_legacy_pending_guard_belongs_to_registration():
    old = approval.register_gateway_notify(KEY, lambda data: None)
    result = bound_context(old).run(approval.check_dangerous_command, COMMAND, "local")
    assert result["status"] == "approval_required" and KEY in approval._pending
    new = approval.register_gateway_notify(KEY, lambda data: None)
    assert KEY not in approval._pending and KEY not in approval._pending_owners
    approval.unregister_gateway_notify(KEY, old)
    assert approval._gateway_owners[KEY] is new


@pytest.mark.parametrize("retire", ["stop", "replace"])
def test_normal_callback_cleanup_preserves_execution_until_stop_or_supersession(retire):
    owner = approval.register_gateway_notify(KEY, lambda data: None)
    context = bound_context(owner)
    approval.unregister_gateway_notify(KEY, owner)
    assert context.run(approval.check_all_command_guards, "pwd", "local")["approved"] is True
    result = context.run(guard)
    assert result["approved"] is False and "No active approval callback" in result["message"]
    assert KEY not in approval._pending and not approval.has_blocking_approval(KEY)
    if retire == "stop":
        approval.unregister_gateway_notify(KEY)
    else:
        approval.register_gateway_notify(KEY, lambda data: pytest.fail("borrowed replacement callback"))
    for command in ("pwd", COMMAND):
        result = context.run(approval.check_all_command_guards, command, "local")
        assert result["approved"] is False and "cancelled" in result["message"]


def test_normal_callback_cleanup_does_not_retain_finished_execution_contexts():
    owner = approval.register_gateway_notify(KEY, lambda data: None)
    context = bound_context(owner)
    reference = weakref.ref(owner)
    approval.unregister_gateway_notify(KEY, owner)
    assert approval._gateway_lifetimes[KEY] is owner
    del context, owner
    gc.collect()
    assert reference() is None and KEY not in approval._gateway_lifetimes


@pytest.mark.parametrize("backend", ["local", "ssh"])
def test_sandbox_rpc_thread_inherits_registration_and_cancels_without_borrowing_replacement(monkeypatch, backend):
    """Real RPC loops; synthetic dispatch calls the guard, never a shell tool.

    Local sandbox runs a harmless Python read_file stub over UDS. Remote process
    and filesystem I/O are synthetic; the polling loop and thread remain real.
    """
    from tools import code_execution_tool as sandbox

    notified, dispatched = threading.Event(), threading.Event()
    observed = []

    def dispatch(*args, **kwargs):
        observed.append(approval.get_current_session_key())
        result = guard()
        dispatched.set()
        return json.dumps(result)

    class SyntheticRemote:
        def get_temp_dir(self):
            return "/synthetic"

        def execute(self, command, **kwargs):
            if "command -v python3" in command:
                return {"output": "OK"}
            if command.startswith("ls -1 ") and not dispatched.is_set():
                return {"output": "/synthetic/rpc/req_000001"}
            if command.startswith("cat "):
                return {"output": json.dumps({"tool": "read_file", "args": {"path": "synthetic"}, "seq": 1})}
            if "python3 script.py" in command:
                assert dispatched.wait(4)
            return {"output": "", "returncode": 0}

    monkeypatch.setattr("core.model_tools.handle_function_call", dispatch)
    monkeypatch.setattr("tools.terminal_tool._get_env_config", lambda: {"env_type": backend})
    monkeypatch.setattr(sandbox, "_load_config", lambda: {"timeout": 5, "max_tool_calls": 1})
    if backend == "ssh":
        monkeypatch.setattr(sandbox, "_get_or_create_env", lambda task: (SyntheticRemote(), "ssh"))
        monkeypatch.setattr(sandbox, "_ship_file_to_remote", lambda *args: None)
    owner = approval.register_gateway_notify(KEY, lambda data: notified.set())
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(bound_context(owner).run, sandbox.execute_code,
                             "from spark_tools import read_file\nread_file('synthetic')",
                             "synthetic-rpc", ["read_file"])
        try:
            assert notified.wait(3), "RPC must use parent's registered callback"
            new = approval.register_gateway_notify(KEY, lambda data: pytest.fail("replacement callback borrowed"))
            result = json.loads(future.result(6))
            assert result["status"] == "success" and result["tool_calls_made"] == 1
            assert observed == [KEY]
            assert not approval.has_blocking_approval(KEY)
            approval.unregister_gateway_notify(KEY, owner)
            assert approval._gateway_owners[KEY] is new
        finally:
            approval.unregister_gateway_notify(KEY)
