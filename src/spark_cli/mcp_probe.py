"""Isolated SDK readiness probe. Configuration arrives only on stdin."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from contextlib import AsyncExitStack


async def probe(config: dict) -> int:
    from jsonschema.validators import validator_for
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    from tools.mcp_tool import _interpolate_env_vars

    config = _interpolate_env_vars(config)

    async with AsyncExitStack() as stack:
        if str(config.get("auth") or "").lower().strip() == "oauth":
            # A readiness test must never start an interactive authorization flow.
            raise NotImplementedError
        if config.get("url"):
            import httpx
            from mcp.client.streamable_http import streamable_http_client
            client = await stack.enter_async_context(httpx.AsyncClient(
                headers=config.get("headers") or {}, timeout=10, follow_redirects=False,
            ))
            read, write, _ = await stack.enter_async_context(
                streamable_http_client(config["url"], http_client=client)
            )
        else:
            from tools.mcp_tool import _build_safe_env, _resolve_stdio_command
            from tools.osv_check import check_package_for_malware
            env = _build_safe_env(config.get("env"))
            command, env = _resolve_stdio_command(config["command"], env)
            args = config.get("args", [])
            if check_package_for_malware(command, args):
                raise PermissionError
            read, write = await stack.enter_async_context(stdio_client(
                StdioServerParameters(command=command, args=args, env=env)
            ))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        count = 0
        cursor = None
        seen = set()
        for _ in range(100):
            page = await session.list_tools(cursor=cursor)
            for tool in page.tools:
                validator_for(tool.inputSchema).check_schema(tool.inputSchema)
            count += len(page.tools)
            if count > 10000:
                raise ValueError
            cursor = page.nextCursor
            if not cursor:
                return count
            if cursor in seen:
                raise ValueError
            seen.add(cursor)
        raise ValueError


def main() -> None:
    # SDK/server output is untrusted. Only our final structured record uses stdout.
    result_fd = os.dup(sys.stdout.fileno())
    with open(os.devnull, "w") as sink:
        os.dup2(sink.fileno(), sys.stdout.fileno())
        os.dup2(sink.fileno(), sys.stderr.fileno())
        start = time.monotonic()
        result: dict = {"error": "connection_failed", "tool_count": None}
        try:
            raw = sys.stdin.buffer.read(65537)
            if len(raw) > 65536:
                raise ValueError
            config = json.loads(raw)
            result = {"error": None, "tool_count": asyncio.run(
                asyncio.wait_for(probe(config), timeout=12)
            )}
        except ImportError:
            result["error"] = "sdk_unavailable"
        except NotImplementedError:
            result["error"] = "auth_unsupported"
        except TimeoutError:
            result["error"] = "timeout"
        except Exception:
            pass
        result["duration_ms"] = round((time.monotonic() - start) * 1000)
        with os.fdopen(result_fd, "w") as output:
            json.dump(result, output)


if __name__ == "__main__":
    main()
