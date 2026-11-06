"""Idle context operations using the existing compressor and session lineage.

Connections are created, used and closed by the calling worker. No live agent,
loaded memory, system prefix or original transcript is mutated by this module.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any

from agent.context_compressor import ContextCompressor

LIVE_STATES = {'created', 'pending', 'queued', 'starting', 'running', 'working',
               'streaming', 'waiting', 'waiting_for_input', 'waiting_for_approval',
               'cancel_requested', 'stopping'}


def revision(messages: list[dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(messages, sort_keys=True, default=str).encode()).hexdigest()


def require_idle(db, session_id: str) -> None:
    family = db.resolve_compression_chain(session_id)
    for sid in family:
        if db.list_web_pending_actions(sid):
            raise ValueError('Resolve pending decisions before compacting.')
        if any(run.get('status') in LIVE_STATES for run in db.list_subagent_runs(sid)):
            raise ValueError('Wait for delegated work before compacting.')
        for row in db._conn.execute('SELECT projection_json FROM web_turn_projections WHERE session_id = ?', (sid,)):
            projection = json.loads(row['projection_json'])
            if projection.get('turn_active') or (projection.get('state') or projection.get('status')) in LIVE_STATES:
                raise ValueError('Wait for the active turn before compacting.')


def compressor_for_session(row: dict, cached=None) -> ContextCompressor:
    import copy

    if isinstance(cached, ContextCompressor):
        return copy.copy(cached)
    from spark_cli.config import load_config
    from spark_cli.model_config import read_global_model_config
    from spark_cli.runtime_provider import resolve_runtime_provider

    config = load_config()
    model_config = read_global_model_config(config)
    from spark_cli.auth import AuthError
    try:
        runtime = resolve_runtime_provider(requested=None)
    except AuthError:
        # Offline preflight and deterministic reduction need no inference key.
        runtime = {"provider": model_config.provider, "base_url": model_config.base_url,
                   "api_mode": model_config.api_mode}
    selected = row.get('model')
    model = selected if selected and selected != 'auto' else model_config.model
    return ContextCompressor(
        model=model, provider=runtime.get('provider') or '',
        base_url=runtime.get('base_url') or '', api_key=runtime.get('api_key') or '',
        api_mode=runtime.get('api_mode') or '', quiet_mode=True,
        config_context_length=(config.get("model") or {}).get("context_length") if isinstance(config.get("model"), dict) else None,
    )


def persist_compaction(db, session_id, messages, compressed, compressor, expected_revision, reserve_child=None):
    """Commit continuation, checkpoint and lineage together or retain all old state."""
    child = 'compact_' + uuid.uuid4().hex[:16]
    if reserve_child is not None:
        reserve_child(child)
    now = time.time()
    checkpoint = compressor._last_shadow_checkpoint
    stats = dict(compressor.last_compaction)

    def commit(conn):
        require_idle(db, session_id)
        if db.resolve_latest_descendant(session_id) != session_id or revision(db.get_messages_as_conversation(session_id)) != expected_revision:
            raise ValueError('Context changed; review a fresh preflight before compacting.')
        row = db.get_session(session_id)
        title = db.get_next_title_in_lineage(row['title']) if row.get('title') else None
        conn.execute(
            'INSERT INTO sessions (id, source, user_id, model, model_config, system_prompt, parent_session_id, started_at, title, kanban_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (child, row['source'], row.get('user_id'), row.get('model'), row.get('model_config'), row.get('system_prompt'), session_id, now, title, row.get('kanban_status')),
        )
        for index, message in enumerate(compressed):
            conn.execute(
                'INSERT INTO messages (session_id, role, content, tool_call_id, tool_calls, tool_name, timestamp, reasoning, reasoning_details, codex_reasoning_items) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (child, message['role'], message.get('content'), message.get('tool_call_id'),
                 json.dumps(message['tool_calls']) if message.get('tool_calls') else None,
                 message.get('tool_name'), now + index * 0.000001, message.get('reasoning'),
                 json.dumps(message['reasoning_details']) if message.get('reasoning_details') else None,
                 json.dumps(message['codex_reasoning_items']) if message.get('codex_reasoning_items') else None),
            )
        conn.execute('UPDATE sessions SET message_count = ?, tool_call_count = ? WHERE id = ?',
                     (len(compressed), sum(len(m.get('tool_calls') or []) for m in compressed), child))
        conn.execute('INSERT INTO context_checkpoints (session_id, checkpoint_sequence, context_epoch, version, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?)',
                     (session_id, checkpoint.checkpoint_sequence, checkpoint.context_epoch, checkpoint.version, json.dumps(checkpoint.to_dict()), now))
        # The checkpoint belongs to the source transcript. The continuation is
        # already a complete compact transcript: giving it a typed checkpoint
        # would make the normal resume path replace protected rows with a tail.
        conn.execute('INSERT INTO session_context_epochs SELECT ?, epoch, schema_fingerprint, prompt_fingerprints_json, prompt_sources_json, created_at FROM session_context_epochs WHERE session_id = ?', (child, session_id))
        conn.execute('INSERT INTO session_briefs SELECT ?, text, updated_at FROM session_briefs WHERE session_id = ?', (child, session_id))
        conn.execute('INSERT INTO context_items SELECT ? || id, ?, type, source_path, inclusion_mode, scope, content, content_ref, size_bytes, excerpt_range, search_query, label, created_at FROM context_items WHERE session_id = ?', (child + ':', child, session_id))
        conn.execute("UPDATE sessions SET ended_at = ?, end_reason = 'compression' WHERE id = ?", (now, session_id))
        event, _ = db._append_session_event_row(conn, session_id, 'context.compacted',
                      {'session_id': child, 'parent_session_id': session_id, 'checkpoint_owner_session_id': session_id, **stats}, 'context.compacted:' + child, now)
        return event

    event = db._execute_write(commit)
    db._publish_committed_events([event])
    return {'session_id': child, 'parent_session_id': session_id, 'checkpoint_owner_session_id': session_id, **stats}
