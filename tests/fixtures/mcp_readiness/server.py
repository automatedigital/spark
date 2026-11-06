"""Controlled wire-level MCP fixture (never calls external services)."""
import json
import os
import sys
import time

mode = sys.argv[1]
if len(sys.argv) > 2:
    open(sys.argv[2], 'w').write(str(os.getpid()))
for line in sys.stdin:
    request = json.loads(line)
    if 'id' not in request:
        continue
    method = request['method']
    if mode == 'stall':
        time.sleep(120)
    if method == 'initialize':
        result = {'protocolVersion': '2024-11-05', 'capabilities': {'tools': {}},
                  'serverInfo': {'name': 'fixture', 'version': '1'}}
    elif method == 'tools/list':
        if mode == 'malformed':
            result = {'tools': [{'name': 'secret', 'inputSchema': 'bad'}]}
        else:
            result = {'tools': [{'name': 'fixture', 'inputSchema': {'type': 'object'}}]}
            if mode == 'pages' and not request.get('params', {}).get('cursor'):
                result['nextCursor'] = 'page2'
    else:
        result = {}
    print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)
