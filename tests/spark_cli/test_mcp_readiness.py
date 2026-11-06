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


def test_sdk_missing_is_safe_and_does_not_import_live_discovery(monkeypatch, tmp_path):
    stub = tmp_path / 'mcp.py'
    stub.write_text('raise ImportError("SYNTHETIC_SECRET")\n')
    monkeypatch.setenv('PYTHONPATH', str(tmp_path) + os.pathsep + str(FIXTURE.parents[3] / 'src'))
    result = readiness.run_probe(config(), threading.Event())
    assert result['error'] == 'sdk_unavailable'
    assert 'SYNTHETIC_SECRET' not in json.dumps(result)


def test_two_real_probes_slow_does_not_block_fast(monkeypatch, tmp_path):
    import time
    monkeypatch.setenv('SPARK_HOME', str(tmp_path))
    owner = readiness.ReadinessOwner(workers=2, capacity=2)
    pidfile = tmp_path / 'slow-pid'
    slow = config('stall', pidfile)
    fast = config('success')
    try:
        owner.start('slow', slow)
        owner.start('fast', fast)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            result = owner.summaries({'slow': slow, 'fast': fast})
            if result['fast']['state'] == 'ready':
                break
            time.sleep(0.05)
        assert result['fast']['state'] == 'ready'
        assert result['slow']['state'] == 'testing'
        owner.summaries({'fast': fast})  # Removing configuration cancels owned work.
    finally:
        owner.summaries({})
        owner.pool.shutdown(wait=True)
    with pytest.raises(ProcessLookupError):
        os.kill(int(pidfile.read_text()), 0)


def test_create_keeps_credentials_out_of_response(monkeypatch):
    import asyncio
    from spark_cli import mcp_config, mcp_routes
    secret = 'SYNTHETIC_SECRET'
    saved = {}
    monkeypatch.setattr(mcp_config, '_save_mcp_server', lambda name, cfg: saved.update({name: cfg}))
    monkeypatch.setattr(mcp_config, '_get_mcp_servers', lambda: saved)
    result = asyncio.run(mcp_routes.mcp_servers_create(mcp_routes.McpServerCreate(
        name='fixture', url='https://invalid/?token=' + secret,
        headers={'Authorization': secret}, env={'KEY': secret})))
    assert saved['fixture']['headers']['Authorization'] == secret
    assert secret not in json.dumps(result)


def test_invalid_credentials_never_echo_in_validation_errors():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from spark_cli.mcp_routes import register_mcp_routes
    app = FastAPI()
    register_mcp_routes(app)
    with TestClient(app) as client:
        response = client.post('/api/mcp/servers', json={
            'name': 'fixture', 'url': 'http://invalid',
            'env': {'KEY': {'secret': 'SYNTHETIC_SECRET'}}})
    assert response.status_code == 400
    assert 'SYNTHETIC_SECRET' not in response.text
