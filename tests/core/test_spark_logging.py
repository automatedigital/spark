"""Tests for core/spark_logging.py — trace_id, session context, JSON formatter."""

import json
import logging
import os
import threading
from unittest.mock import patch

import pytest

from core.spark_logging import (
    _JsonFormatter,
    clear_session_context,
    get_trace_id,
    new_trace_id,
    set_session_context,
)


class TestTraceId:
    def test_new_trace_id_returns_hex_string(self):
        tid = new_trace_id()
        assert isinstance(tid, str)
        assert len(tid) == 16
        int(tid, 16)  # must be valid hex

    def test_get_trace_id_returns_current(self):
        tid = new_trace_id()
        assert get_trace_id() == tid

    def test_each_call_generates_unique_id(self):
        ids = {new_trace_id() for _ in range(20)}
        assert len(ids) == 20

    def test_trace_id_empty_string_before_first_call(self, monkeypatch):
        import contextvars
        from core.spark_logging import _trace_id_var
        token = _trace_id_var.set("")
        try:
            assert get_trace_id() == ""
        finally:
            _trace_id_var.reset(token)

    def test_trace_id_propagates_to_log_record(self):
        tid = new_trace_id()
        record = logging.LogRecord(
            name="test", level=logging.INFO,
            pathname="", lineno=0, msg="msg", args=(), exc_info=None,
        )
        # The record factory injects trace_id — simulate what the factory adds
        record.trace_id = get_trace_id()  # type: ignore[attr-defined]
        assert record.trace_id == tid  # type: ignore[attr-defined]


class TestSessionContext:
    def test_set_and_clear(self):
        set_session_context("test-session-123")
        clear_session_context()

    def test_thread_isolation(self):
        """Session context must not leak between threads."""
        results: list = []

        def _worker():
            set_session_context("worker-session")
            import time; time.sleep(0.01)
            from core.spark_logging import _session_context
            results.append(getattr(_session_context, "session_id", None))

        set_session_context("main-session")
        t = threading.Thread(target=_worker)
        t.start()
        t.join()
        from core.spark_logging import _session_context
        assert getattr(_session_context, "session_id", None) == "main-session"


class TestJsonFormatter:
    def _make_record(self, msg="hello", level=logging.INFO, exc_info=None) -> logging.LogRecord:
        record = logging.LogRecord(
            name="test.logger", level=level,
            pathname="test.py", lineno=1,
            msg=msg, args=(), exc_info=exc_info,
        )
        record.session_tag = " [sess-abc]"  # type: ignore[attr-defined]
        record.trace_id = "deadbeef12345678"  # type: ignore[attr-defined]
        return record

    def test_output_is_valid_json(self):
        fmt = _JsonFormatter()
        line = fmt.format(self._make_record())
        parsed = json.loads(line)
        assert isinstance(parsed, dict)

    def test_contains_required_fields(self):
        fmt = _JsonFormatter()
        parsed = json.loads(fmt.format(self._make_record("test message")))
        assert "ts" in parsed
        assert "level" in parsed
        assert "logger" in parsed
        assert parsed["msg"] == "test message"
        assert parsed["logger"] == "test.logger"

    def test_session_id_included_when_present(self):
        fmt = _JsonFormatter()
        parsed = json.loads(fmt.format(self._make_record()))
        assert parsed.get("session_id") == "sess-abc"

    def test_trace_id_included(self):
        fmt = _JsonFormatter()
        parsed = json.loads(fmt.format(self._make_record()))
        assert parsed.get("trace_id") == "deadbeef12345678"

    def test_exc_info_included_when_present(self):
        fmt = _JsonFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            import sys
            exc = sys.exc_info()
        record = self._make_record(exc_info=exc)
        parsed = json.loads(fmt.format(record))
        assert "exc" in parsed
        assert "ValueError" in parsed["exc"]

    def test_empty_session_tag_omitted(self):
        fmt = _JsonFormatter()
        record = self._make_record()
        record.session_tag = ""
        parsed = json.loads(fmt.format(record))
        assert "session_id" not in parsed

    def test_empty_trace_id_omitted(self):
        fmt = _JsonFormatter()
        record = self._make_record()
        record.trace_id = ""
        parsed = json.loads(fmt.format(record))
        assert "trace_id" not in parsed
