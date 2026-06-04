"""Incremental tool-stdout streaming: _wait_for_process fires the output
callback for each line as it's read, not only on completion."""

from __future__ import annotations

import time

from tools.environments import base
from tools.environments.base import (
    BaseEnvironment,
    set_output_callback,
)


class _FakeStdout:
    """Yields lines slowly so we can observe incremental delivery."""

    def __init__(self, lines, delay=0.05):
        self._lines = list(lines)
        self._delay = delay

    def __iter__(self):
        for ln in self._lines:
            time.sleep(self._delay)
            yield ln


class _FakeProc:
    def __init__(self, lines):
        self.stdout = _FakeStdout(lines)
        self._polls = 0
        self.returncode = 0

    def poll(self):
        # Stay "running" briefly so the drain thread can deliver lines.
        self._polls += 1
        return None if self._polls < 8 else 0


class _Env(BaseEnvironment):
    def _run_bash(self, *a, **k):  # pragma: no cover - not used here
        raise NotImplementedError

    def cleanup(self):  # pragma: no cover
        pass

    def _kill_process(self, proc):  # pragma: no cover
        pass


def _make_env() -> _Env:
    env = _Env.__new__(_Env)
    return env


def test_output_callback_fires_per_line():
    received: list[str] = []
    set_output_callback(received.append)
    try:
        env = _make_env()
        proc = _FakeProc(["line 1\n", "line 2\n", "line 3\n"])
        result = env._wait_for_process(proc, timeout=10)
    finally:
        set_output_callback(None)

    # All lines streamed via the callback...
    assert received == ["line 1\n", "line 2\n", "line 3\n"]
    # ...and still aggregated into the final buffer.
    assert "line 1" in result["output"] and "line 3" in result["output"]
    assert result["returncode"] == 0


def test_no_callback_is_safe():
    set_output_callback(None)
    env = _make_env()
    proc = _FakeProc(["a\n", "b\n"])
    result = env._wait_for_process(proc, timeout=10)
    assert "a" in result["output"]


def test_output_callback_is_thread_local_accessor():
    set_output_callback(None)
    assert base._get_output_callback() is None
    cb = lambda s: None  # noqa: E731
    set_output_callback(cb)
    assert base._get_output_callback() is cb
    set_output_callback(None)
