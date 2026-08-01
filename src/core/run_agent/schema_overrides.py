"""Lightweight dynamic schema tailoring that never imports tool handlers."""

from __future__ import annotations

import os
import platform
from collections.abc import Set

SANDBOX_ALLOWED_TOOLS = frozenset(
    {"web_search", "web_extract", "read_file", "write_file", "search_files", "patch", "terminal"}
)

_TOOL_DOC_LINES = (
    ("web_search", "  web_search(query, limit=5) -> search results"),
    ("web_extract", "  web_extract(urls, use_llm_processing=True) -> extracted markdown"),
    ("read_file", "  read_file(path, offset=1, limit=500) -> bounded file content"),
    ("write_file", "  write_file(path, content) -> overwrite the complete file"),
    ("search_files", "  search_files(pattern, target='content', path='.') -> matches"),
    ("patch", "  patch(path, old_string, new_string, replace_all=False) -> replace file text"),
    ("terminal", "  terminal(command, timeout=None, workdir=None) -> output and exit_code"),
)


def terminal_description(default: str) -> str:
    if platform.system() != "Windows" or os.getenv("TERMINAL_ENV", "local").lower() != "local":
        return default
    unix = "Use POSIX shell syntax for Unix local hosts and container/SSH/cloud backends."
    windows = (
        "Native Windows local execution uses PowerShell (pwsh, with Windows PowerShell 5.1 fallback). "
        "Emit PowerShell syntax; do not use POSIX source/eval/export/pwd or Git Bash/WSL launchers."
    )
    return default.replace(unix, windows)


def build_execute_code_schema(enabled_sandbox_tools: Set[str]) -> dict:
    tool_lines = "\n".join(line for name, line in _TOOL_DOC_LINES if name in enabled_sandbox_tools)
    examples = [name for name in ("web_search", "terminal") if name in enabled_sandbox_tools]
    if not examples:
        examples = sorted(enabled_sandbox_tools)[:2]
    import_str = ", ".join(examples) + (", ..." if examples else "...")
    return {
        "name": "execute_code",
        "description": (
            "Run Python with Spark tools. Use for 3+ calls with filtering, branching, loops, retries, "
            "or intermediate processing. Use normal calls for one operation or results needing direct reasoning.\n\n"
            f"Available via `from spark_tools import ...`:\n\n{tool_lines}\n\n"
            "Limits: 5-minute timeout, 50KB stdout, 50 tool calls; terminal is foreground-only. "
            "Print the final result. Python stdlib is available."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": f"Python code. Import tools with `from spark_tools import {import_str}`.",
                }
            },
            "required": ["code"],
        },
    }
