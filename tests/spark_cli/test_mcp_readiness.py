"""Real isolated process and owner safety checks for SP23."""
import json
from pathlib import Path
import sys
import threading

import os
import pytest

from spark_cli import mcp_readiness as readiness

FIXTURE = Path(__file__).parents[1] / 'fixtures/mcp_readiness/server.py'


def config(mode='pages', *args):
    return {'command': sys.executable, 'args': [str(FIXTURE), mode, *map(str, args)]}


@pytest.mark.parametrize('mode,count,error', [('pages', 2, None), ('success', 1, None),
                                             ('malformed', None, 'connection_failed')])
def test_real_stdio(mode, count, error):
    result = readiness.run_probe(config(mode), threading.Event())
    assert result['tool_count'] == count
    assert result['error'] == error
    assert result['duration_ms'] > 0


def test_timeout_cleans_owned_server(tmp_path):
    pidfile = tmp_path / 'pid'
    result = readiness.run_probe(config('stall', pidfile), threading.Event(), timeout=3)
    assert result['error'] == 'timeout'
    pid = int(pidfile.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_cancel():
    event = threading.Event()
    event.set()
    assert readiness.run_probe(config(), event)['error'] == 'cancelled'


def test_owner_bounds_dedupe_revision_and_profile(monkeypatch, tmp_path):
    entered = threading.Event()
    release = threading.Event()
    def probe(cfg, cancel, **kwargs):
        entered.set()
        release.wait(5)
        return {'error': None, 'tool_count': 3, 'duration_ms': 1}
    monkeypatch.setattr(readiness, 'run_probe', probe)
    monkeypatch.setenv('SPARK_HOME', str(tmp_path / 'one'))
    owner = readiness.ReadinessOwner(workers=1, capacity=1)
    try:
        first = owner.start('one', config())
        assert entered.wait(2)
        assert owner.start('one', config()) == first
        with pytest.raises(OverflowError):
            owner.start('two', config())
        assert owner.summaries({'one': config('success')})['one']['state'] == 'unknown'
        monkeypatch.setenv('SPARK_HOME', str(tmp_path / 'two'))
        assert owner.summaries({'one': config()})['one']['state'] == 'unknown'
        release.set()
    finally:
        release.set()
        owner.pool.shutdown(wait=True)
    monkeypatch.setenv('SPARK_HOME', str(tmp_path / 'one'))
    assert owner.summaries({'one': config('success')})['one']['state'] == 'unknown'


def test_get_and_save_never_disclose_config_or_probe(monkeypatch):
    import asyncio
    from spark_cli import mcp_config, mcp_routes
    secret = 'SYNTHETIC_SECRET_DO_NOT_RETURN'
    monkeypatch.setattr(mcp_config, '_get_mcp_servers', lambda: {
        'fixture': {'url': f'https://user:{secret}@invalid/?token={secret}',
                    'env': {'KEY': secret}, 'headers': {'Authorization': secret}}})
    result = asyncio.run(mcp_routes.mcp_servers_list())
    assert secret not in json.dumps(result)
    assert result['readiness']['fixture']['state'] == 'unknown'
    assert result['servers']['fixture'] == {'configured': True}


def test_real_http_auth_failure_is_safe():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'SYNTHETIC_SECRET')
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = readiness.run_probe({'url': f'http://127.0.0.1:{server.server_port}/mcp',
                                      'headers': {'Authorization': 'SYNTHETIC_SECRET'}}, threading.Event())
        assert result['error'] == 'connection_failed'
        assert 'SYNTHETIC_SECRET' not in json.dumps(result)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
