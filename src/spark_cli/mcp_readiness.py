"""Bounded, profile/revision-scoped MCP test owner; never touches live discovery."""
from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from typing import Any

from core.spark_constants import get_spark_home
from spark_cli.admin_runs import _admin_run_queues, _admin_runs, _new_admin_run, _queue_admin_event

ERRORS = {"connection_failed", "sdk_unavailable", "auth_unsupported", "timeout",
          "invalid_result", "unsupported_platform", "cancelled"}


def run_probe(config: dict, cancel: threading.Event, timeout: float = 15, *, profile: str | None = None) -> dict:
    if os.name != "posix":
        return {"error": "unsupported_platform", "tool_count": None, "duration_ms": 0}

    subprocess.run(["ps", "-axo", "pid=,ppid="], stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, timeout=1, check=True)
    start = time.monotonic()
    result = {"error": "invalid_result", "tool_count": None, "duration_ms": 0}
    with tempfile.TemporaryFile() as output:
        proc = subprocess.Popen(
            [sys.executable, "-m", "spark_cli.mcp_probe"], stdin=subprocess.PIPE,
            stdout=output, stderr=subprocess.DEVNULL, start_new_session=True,
            env={**os.environ, **({"SPARK_HOME": profile} if profile else {})},
        )
        descendants: set[int] = set()
        try:
            payload = json.dumps(config).encode()
            if len(payload) > 65536:
                return result
            first = True
            while True:
                table = subprocess.run(["ps", "-axo", "pid=,ppid="], capture_output=True,
                                       timeout=1, check=True, text=True).stdout
                parents = {int(row.split()[0]): int(row.split()[1])
                           for row in table.splitlines() if len(row.split()) == 2}
                owned = {proc.pid}
                for _ in range(32):
                    found = {pid for pid, parent in parents.items() if parent in owned}
                    if found <= owned:
                        break
                    owned.update(found)
                descendants.update(owned - {proc.pid})
                if cancel.is_set():
                    result["error"] = "cancelled"
                    break
                if time.monotonic() - start >= timeout:
                    result["error"] = "timeout"
                    break
                try:
                    proc.communicate(input=payload if first else None, timeout=0.1)
                except subprocess.TimeoutExpired:
                    first = False
                    continue
                output.seek(0)
                raw = output.read(4097)
                if proc.returncode == 0 and len(raw) <= 4096:
                    value = json.loads(raw)
                    count = value.get("tool_count")
                    error = value.get("error")
                    if (error is None and type(count) is int and 0 <= count <= 10000) or (
                        error in ERRORS and count is None
                    ):
                        result.update(error=error, tool_count=count)
                break
        except Exception:
            pass
        finally:
            # SDK stdio children can have their own process groups. Kill owned
            # descendants as well as the probe group before reaping the probe.
            for child in descendants:
                try:
                    os.kill(child, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=2)
    result["duration_ms"] = round((time.monotonic() - start) * 1000)
    return result


class ReadinessOwner:
    def __init__(self, workers: int = 2, capacity: int = 8):
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="mcp-test")
        self.capacity = capacity
        self.lock = threading.RLock()
        self.records: dict[tuple[str, str], dict[str, Any]] = {}
        self.pending = 0

    def _record(self, name: str, config: dict) -> dict:
        key = (str(get_spark_home().resolve()), name)
        revision = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
        old = self.records.get(key)
        if old is None or old["revision"] != revision:
            if old:
                old["cancel"].set()
            old = {"profile": key[0], "revision": revision, "state": "unknown", "last_test_at": None,
                   "duration_ms": None, "tool_count": None, "error": None,
                   "run_id": None, "cancel": threading.Event()}
            self.records[key] = old
        return old

    def summaries(self, servers: dict) -> dict:
        with self.lock:
            profile = str(get_spark_home().resolve())
            for key in list(self.records):
                if key[0] == profile and key[1] not in servers:
                    self.records.pop(key)["cancel"].set()
            return {name: self._summary(self._record(name, config))
                    for name, config in servers.items()}

    @staticmethod
    def _summary(record: dict) -> dict:
        return {key: value for key, value in record.items() if key not in {"revision", "cancel", "profile"}}

    def start(self, name: str, config: dict) -> dict:
        with self.lock:
            record = self._record(name, config)
            if record["state"] == "testing":
                return {"run_id": record["run_id"], "status": "queued"}
            if self.pending >= self.capacity:
                raise OverflowError
            previous = record.get("run_id")
            if previous:
                _admin_runs.pop(previous, None)
                _admin_run_queues.pop(previous, None)
            run_id, _ = _new_admin_run("mcp.test", {})
            record.update(state="testing", run_id=run_id)
            self.pending += 1
            self.pool.submit(self._execute, record, deepcopy(config), run_id)
            return {"run_id": run_id, "status": "queued"}

    def _execute(self, record: dict, config: dict, run_id: str) -> None:
        run = _admin_runs[run_id]
        run.update(status="running", started_at=time.time())
        _queue_admin_event(run_id, {"type": "state", "status": "running"})
        try:
            result = run_probe(config, record["cancel"], profile=record["profile"])
        except Exception:
            result = {"error": "connection_failed", "tool_count": None, "duration_ms": 0}
        with self.lock:
            if record["cancel"].is_set():
                result.update(error="cancelled", tool_count=None)
            self.pending -= 1
            record.update(result, state="failed" if result["error"] else "ready",
                          last_test_at=time.time())
            run.update(status="failed" if result["error"] else "done",
                       finished_at=time.time(), exit_code=1 if result["error"] else 0,
                       error=result["error"], readiness=self._summary(record))
            _queue_admin_event(run_id, {"type": "done", "run": run})


owner = ReadinessOwner()
