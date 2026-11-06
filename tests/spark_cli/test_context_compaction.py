"""SP14 real-persistence and provider-boundary regressions."""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from agent.context_compressor import ContextCompressor
from agent.context_policy import reduce_tool_output, validate_tool_pairs
from core.spark_state import SessionDB
from spark_cli.context_compaction import persist_compaction, revision


def history():
    messages = [{'role': 'system', 'content': 'Never disclose secrets.'},
                {'role': 'user', 'content': 'Preserve /tmp/required.txt and attachment:abc. Should we deploy?'}]
    for i in range(35):
        messages.extend([
            {'role': 'assistant', 'content': f'Inspecting batch {i}', 'tool_calls': [
                {'id': f'c{i}', 'type': 'function', 'function': {'name': 'terminal', 'arguments': '{"command":"pytest"}'}}]},
            {'role': 'tool', 'tool_call_id': f'c{i}', 'content': json.dumps({'output': 'identical diagnostic\n' * 1800 + f'FACT-{i}: exit code 1; artifact_id:keep-{i}', 'exit_code': 1})},
            {'role': 'assistant', 'content': f'Pending approval for batch {i}. Decision: preserve all data.'},
        ])
    messages.append({'role': 'user', 'content': 'Keep the attachment and unresolved deployment decision.'})
    return messages


def compressor():
    return ContextCompressor('test', quiet_mode=True, config_context_length=100_000)


def seed(sid='context-test'):
    db = SessionDB()
    db.create_session(sid, 'web', model='test', system_prompt='NEVER change the prefix')
    for message in history():
        db.append_message(sid, message['role'], content=message.get('content'),
                          tool_calls=message.get('tool_calls'), tool_call_id=message.get('tool_call_id'))
    db.set_brief(sid, 'Required deployment decision remains pending')
    db._conn.execute("INSERT INTO context_items (id, session_id, type, scope, content, content_ref, created_at) VALUES ('attachment:abc', ?, 'note', 'pinned', 'REQUIRED ATTACHMENT FACT', 'artifact:abc', 1)", (sid,))
    return db, sid


def test_deterministic_reduction_retains_facts_pairs_and_prefix():
    engine = compressor()
    messages = history()
    before = json.dumps(messages)
    started = time.perf_counter()
    with patch.object(engine, '_generate_summary', side_effect=AssertionError('deterministic reduction must precede LLM')):
        output = engine.compress(messages, safe_boundary=True)
    assert validate_tool_pairs(output)
    assert output[:2] == messages[:2]
    assert output[-1] == messages[-1]
    for i in range(35):
        text = json.dumps(output)
        assert f'FACT-{i}' in text and f'keep-{i}' in text
        assert f'Pending approval for batch {i}' in text
    assert json.dumps(messages) == before
    assert engine.last_compaction['after_estimated_tokens'] < engine.last_compaction['before_estimated_tokens'] * .8
    print('SP14 fixture metrics', engine.last_compaction, 'wall_seconds', time.perf_counter() - started)


@pytest.mark.parametrize('failure', ['failure', 'timeout'])
def test_summary_failure_retains_original_and_last_checkpoint(monkeypatch, failure):
    import agent.context_policy as policy
    engine = compressor()
    messages = [{'role': 'user' if i % 2 == 0 else 'assistant', 'content': ('ordinary prose ' * 100) + str(i)} for i in range(40)]
    checkpoint = object()
    engine._typed_checkpoint = checkpoint
    def summary(*args, **kwargs):
        if failure == 'timeout':
            time.sleep(.05)
        return None
    monkeypatch.setattr(policy, 'SUMMARY_TIMEOUT_SECONDS', .01)
    monkeypatch.setattr(engine, '_generate_summary', summary)
    result = engine.compress(messages, safe_boundary=True)
    assert result is messages
    assert engine._typed_checkpoint is checkpoint
    assert engine.compression_count == 0
    assert engine.last_compaction['status'] == 'unchanged'


def test_incomplete_tool_group_cannot_be_compacted():
    messages = history()[:-3]
    engine = compressor()
    assert engine.compress(messages, safe_boundary=True) is messages
    assert 'incomplete' in engine.last_compaction['reason']


def test_tool_json_retains_status_and_unique_lines():
    raw = json.dumps({'stdout': 'same\n' * 100 + 'required fact\n', 'exit_code': 7, 'artifact_id': 'a'})
    reduced = json.loads(reduce_tool_output(raw))
    assert reduced['exit_code'] == 7 and reduced['artifact_id'] == 'a'
    assert 'required fact' in reduced['stdout'] and '100 times total' in reduced['stdout']


def test_persistence_lineage_checkpoint_and_stale_revision():
    db, sid = seed()
    try:
        messages = db.get_messages_as_conversation(sid)
        engine = compressor()
        engine.set_deterministic_state(task_identity=sid)
        output = engine.compress(messages, safe_boundary=True)
        with pytest.raises(ValueError, match='changed'):
            persist_compaction(db, sid, messages, output, engine, 'stale')
        assert db.resolve_latest_descendant(sid) == sid
        assert db.get_latest_context_checkpoint(sid) is None
        result = persist_compaction(db, sid, messages, output, engine, revision(messages))
        child = result['session_id']
        assert db.resolve_latest_descendant(sid) == child
        assert db.get_messages_as_conversation(sid) == messages
        assert db.get_messages_as_conversation(child) == output
        assert db.get_session(child)['system_prompt'] == 'NEVER change the prefix'
        assert db.get_brief(child) == 'Required deployment decision remains pending'
        assert db.get_latest_context_checkpoint(sid)['payload']['task_identity'] == sid
        assert db.get_latest_context_checkpoint(child) is None
        attached = db._conn.execute('SELECT content, content_ref FROM context_items WHERE session_id = ?', (child,)).fetchone()
        assert attached['content'] == 'REQUIRED ATTACHMENT FACT'
        assert attached['content_ref'] == 'artifact:abc'
    finally:
        db.close()


def test_api_idle_compact_active_race_and_estimate(monkeypatch):
    from spark_cli import web_server as web
    db, sid = seed()
    db.close()
    entered = threading.Event()
    release = threading.Event()
    committed = threading.Event()
    finish = threading.Event()
    from spark_cli import context_compaction as domain
    original_persist = domain.persist_compaction
    def hold_committed(*args, **kwargs):
        result = original_persist(*args, **kwargs)
        committed.set()
        assert finish.wait(5)
        return result
    monkeypatch.setattr(domain, 'persist_compaction', hold_committed)
    original = ContextCompressor.compress
    def hold(engine, *args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(engine, *args, **kwargs)
    monkeypatch.setattr(ContextCompressor, 'compress', hold)
    client = TestClient(web.app)
    preflight = client.get(f'/api/conversations/{sid}/context/preflight')
    assert preflight.status_code == 200, preflight.text
    assert preflight.json()['can_compact']
    estimate = client.post('/api/estimate-tokens', json={'session_id': sid}).json()
    assert estimate['total_tokens'] > 0
    assert {b['label'] for b in estimate['breakdown']} >= {'History', 'Tools', 'Instructions', 'Memory', 'Attachments'}
    assert estimate['provider_actual_tokens'] is None
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.post, f'/api/conversations/{sid}/context/compact', json={'expected_revision': preflight.json()['revision']})
        try:
            assert entered.wait(5)
            active = client.get(f'/api/conversations/{sid}/context/preflight').json()
            assert not active['can_compact']
            assert client.post(f'/api/conversations/{sid}/context/compact', json={'expected_revision': active['revision']}).status_code == 409
            assert client.post(f'/api/conversations/{sid}/messages', json={'message': 'race'}).status_code == 409
        finally:
            release.set()
        try:
            assert committed.wait(5)
            check = SessionDB()
            try:
                child = check.resolve_latest_descendant(sid)
            finally:
                check.close()
            assert child != sid
            assert client.post(f'/api/conversations/{child}/messages', json={'message': 'rollover race'}).status_code == 409
        finally:
            finish.set()
        response = future.result(10)
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'compacted'
    assert not web._is_web_turn_active(sid)


def test_pending_approval_blocks_preflight():
    from spark_cli import web_server as web
    db, sid = seed()
    try:
        db.create_web_pending_action(action_id='approval-one', session_id=sid, turn_id='turn-one', kind='approval', payload={'command': 'deploy'})
        response = TestClient(web.app).get(f'/api/conversations/{sid}/context/preflight')
        assert response.status_code == 200, response.text
        assert not response.json()['can_compact']
        assert 'pending' in response.json()['blocked_reason']
    finally:
        db.close()


def test_summary_bounds_and_protected_facts(monkeypatch):
    from types import SimpleNamespace
    engine = compressor()
    messages = [{'role': 'user' if i % 2 == 0 else 'assistant', 'content': ('ordinary prose ' * 100) + str(i)} for i in range(40)]
    messages[7]['content'] = 'Decision: keep /tmp/required.txt. Pending approval remains unresolved.'
    messages[8]['content'] = 'NEVER remove attachment:abc or change the protected instructions.'
    calls = []
    def provider(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='Brief background.'))])
    monkeypatch.setattr('agent.context_compressor.call_llm', provider)
    output = engine.compress(messages, safe_boundary=True)
    assert output is not messages
    assert messages[7] in output and messages[8] in output
    assert calls[0]['max_tokens'] <= 4000
    assert calls[0]['timeout'] == 20
    # A cheaper answer that loses protected facts never replaces these rows.
    assert 'attachment:abc' in json.dumps(output)


@pytest.mark.asyncio
async def test_cancelled_http_wait_keeps_reservation_until_worker_finishes(monkeypatch):
    import asyncio

    from spark_cli import web_server as web
    db, sid = seed('cancelled-context')
    db.close()
    preflight = web._context_preflight(sid)
    entered, release = threading.Event(), threading.Event()
    original = ContextCompressor.compress
    def hold(engine, *args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(engine, *args, **kwargs)
    monkeypatch.setattr(ContextCompressor, 'compress', hold)
    task = asyncio.create_task(web.compact_conversation_context(sid, web.ContextCompactRequest(expected_revision=preflight['revision'])))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert web._is_web_turn_active(sid)
    finally:
        release.set()
    for _ in range(200):
        if not web._is_web_turn_active(sid):
            break
        await asyncio.sleep(.01)
    assert not web._is_web_turn_active(sid)
