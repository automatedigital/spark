import json

from agent.context_checkpoint import (
    CHECKPOINT_PREFIX,
    NARRATIVE_MISSING,
    ContextCheckpoint,
    assemble_checkpoint_context,
    build_context_checkpoint,
    narrative_delta,
)
from agent.context_compressor import ContextCompressor
from agent.model_metadata import estimate_messages_tokens_rough
from core.run_agent import AIAgent
from core.spark_state import SessionDB
from tools.todo_tool import TodoStore


def _history(round_number=0):
    path = f"/tmp/project-{round_number}/app.py"
    return [
        {"role": "user", "content": f"Fix the app. NEVER delete data. Only edit {path}."},
        {"role": "assistant", "content": "I decided to preserve compatibility.", "tool_calls": [{
            "id": f"call-{round_number}",
            "type": "function",
            "function": {"name": "terminal", "arguments": json.dumps({"command": "pytest -q"})},
        }]},
        {"role": "tool", "tool_call_id": f"call-{round_number}", "content": "FAILED tests/test_app.py::test_safe exit code 1"},
        {"role": "assistant", "content": "The test failed; the blocker is test_safe."},
        {"role": "user", "content": "Continue, but do not overwrite config."},
        {"role": "assistant", "content": "I will patch the implementation.", "tool_calls": [{
            "id": f"write-{round_number}",
            "type": "function",
            "function": {"name": "write_file", "arguments": json.dumps({"path": path, "content": "ok"})},
        }]},
        {"role": "tool", "tool_call_id": f"write-{round_number}", "content": '{"success":true,"artifact_id":"artifact:abc"}'},
        {"role": "assistant", "content": "The patch is complete."},
    ]


def test_loss_fields_survive_three_incremental_checkpoints():
    checkpoint = None
    for sequence in range(1, 4):
        checkpoint = build_context_checkpoint(
            _history(sequence),
            checkpoint_sequence=sequence,
            context_epoch=sequence,
            task_identity="task-stable",
            current_plan=[{"id": "verify", "content": "Run tests", "status": "pending"}],
            prior=checkpoint,
            narrative=f"narrative {sequence}",
        )
        checkpoint = ContextCheckpoint.from_dict(checkpoint.to_dict())
    assert checkpoint.task_identity == "task-stable"
    assert checkpoint.checkpoint_sequence == 3
    assert any("NEVER delete data" in item for item in checkpoint.constraints)
    assert any("do not overwrite config" in item for item in checkpoint.constraints)
    assert any("pytest -q" in item.arguments.get("command", "") for item in checkpoint.commands_and_tests)
    assert any(not item.success and "FAILED" in item.outcome for item in checkpoint.commands_and_tests)
    assert "/tmp/project-3/app.py" in checkpoint.touched_files
    assert "abc" in checkpoint.external_artifact_handles
    assert checkpoint.current_plan[0]["status"] == "pending"


def test_only_narrative_delta_is_sent_to_summarizer():
    delta = narrative_delta(_history())
    assert all(message["role"] != "tool" for message in delta)
    assert "pytest -q" not in " ".join(message["content"] for message in delta)


def test_typed_compressor_fails_safely_and_keeps_task_identity(monkeypatch):
    compressor = ContextCompressor(
        model="test", quiet_mode=True, config_context_length=100_000,
        protect_first_n=2, protect_last_n=2, checkpoint_mode="typed",
    )
    compressor.set_deterministic_state(
        current_plan=[{"id": "x", "content": "finish", "status": "pending"}],
        task_identity="same-session",
        context_epoch=0,
    )
    monkeypatch.setattr(compressor, "_generate_summary", lambda *a, **k: None)
    messages = _history() + _history(2) + _history(3)
    compressed = compressor.compress(messages, current_tokens=90_000)
    assert compressed[0]["content"].startswith(CHECKPOINT_PREFIX)
    payload = json.loads(compressed[0]["content"].split("\n", 2)[2])
    assert payload["task_identity"] == "same-session"
    assert payload["narrative"] == NARRATIVE_MISSING
    assert len(compressed) > 1
    assert compressed[-1] == messages[-1]


def test_checkpoint_plus_recent_tail_meets_twenty_percent_target():
    checkpoint = build_context_checkpoint(
        _history(), checkpoint_sequence=1, context_epoch=1,
        task_identity="task", narrative="brief",
    )
    recent = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": "x" * 4_000}
        for i in range(40)
    ]
    assembled = assemble_checkpoint_context(checkpoint, recent, context_window=100_000)
    assert estimate_messages_tokens_rough(assembled) <= 20_000


def test_database_persists_epoch_and_checkpoint_without_new_session(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    db.create_session("stable-task", "cli")
    checkpoint = build_context_checkpoint(
        _history(), checkpoint_sequence=1, context_epoch=1,
        task_identity="stable-task", narrative="done",
    )
    db.record_context_epoch(
        "stable-task", epoch=1, schema_fingerprint="abc",
        prompt_fingerprints={"reusable_fingerprint": "reuse"},
    )
    db.save_context_checkpoint(
        "stable-task", checkpoint_sequence=1, context_epoch=1,
        version=checkpoint.version, payload=checkpoint.to_dict(),
    )
    assert db.get_session("stable-task")["parent_session_id"] is None
    assert db.get_context_epoch("stable-task")["schema_fingerprint"] == "abc"
    restored = ContextCheckpoint.from_dict(db.get_latest_context_checkpoint("stable-task")["payload"])
    assert restored.task_identity == "stable-task"
    db.close()


def test_agent_compression_keeps_logical_session_and_persists_resume_marker(tmp_path, monkeypatch):
    db = SessionDB(tmp_path / "state.db")
    db.create_session("one-task", "cli")
    compressor = ContextCompressor(
        model="test", quiet_mode=True, config_context_length=100_000,
        protect_first_n=2, protect_last_n=2, checkpoint_mode="typed",
    )
    monkeypatch.setattr(compressor, "_generate_summary", lambda *a, **k: "narrative")
    agent = AIAgent.__new__(AIAgent)
    agent.session_id = "one-task"
    agent.model = "test"
    agent.platform = "cli"
    agent.context_compressor = compressor
    agent._todo_store = TodoStore()
    agent._session_db = db
    agent._memory_manager = None
    agent._context_epoch = 0
    agent._schema_fingerprint = "schema"
    agent.tools = []
    agent._last_flushed_db_idx = 99
    agent._context_pressure_warned_at = 0.0
    agent.flush_memories = lambda *a, **k: None
    agent._invalidate_system_prompt = lambda: None
    agent._build_system_prompt = lambda _message: "system"
    agent._cached_system_prompt = "system"
    agent._prompt_bundle = None
    agent._memory_store = None
    agent._vprint = lambda *a, **k: None
    agent.session_migrated_callback = lambda *a: (_ for _ in ()).throw(
        AssertionError("typed compression must not migrate sessions")
    )

    compressed, _ = agent._compress_context(
        _history() + _history(2) + _history(3), "system", approx_tokens=90_000,
    )
    assert agent.session_id == "one-task"
    assert agent._context_epoch == 1
    assert agent._last_flushed_db_idx == len(compressed)
    assert db.get_session("one-task")["ended_at"] is None
    assert db.get_latest_context_checkpoint("one-task") is not None
    # Typed state is not exposed as a synthetic assistant chat bubble.
    stored = db.get_messages("one-task")
    assert not any(str(message.get("content") or "").startswith(CHECKPOINT_PREFIX) for message in stored)
    continued = [
        *compressed,
        {"role": "user", "content": "new question"},
        {"role": "assistant", "content": "new answer"},
    ]
    agent._flush_messages_to_session_db(continued, conversation_history=_history() * 10)
    stored = db.get_messages("one-task")
    assert [message["content"] for message in stored] == ["new question", "new answer"]
    db.close()
