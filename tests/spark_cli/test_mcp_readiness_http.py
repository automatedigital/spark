"""Local HTTP MCP wire fixtures, including paginated and invalid discovery."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

import pytest

from spark_cli.mcp_readiness import run_probe


@pytest.mark.parametrize('mode,count,error', [('pages', 2, None),
                                             ('malformed', None, 'connection_failed')])
def test_http_discovery(mode, count, error):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(405)
            self.end_headers()

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if 'id' not in request:
                self.send_response(202)
                self.end_headers()
                return
            if request['method'] == 'initialize':
                result = {'protocolVersion': '2024-11-05', 'capabilities': {'tools': {}},
                          'serverInfo': {'name': 'fixture', 'version': '1'}}
            else:
                result = {'tools': [{'name': 'fixture', 'inputSchema': {'type': 'object'}}]}
                if mode == 'pages' and not request.get('params', {}).get('cursor'):
                    result['nextCursor'] = 'next'
                if mode == 'malformed':
                    result['tools'] = 'SYNTHETIC_SECRET'
            body = json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = run_probe({'url': f'http://127.0.0.1:{server.server_port}/mcp'}, threading.Event())
        assert result['tool_count'] == count
        assert result['error'] == error
        assert 'SYNTHETIC_SECRET' not in json.dumps(result)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
