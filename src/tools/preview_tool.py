"""Workspace preview/browser tools for agentic webapp verification."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from core.spark_constants import get_spark_home
from tools.registry import registry


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, default=str)


def _call(name: str, fn, *args, **kwargs) -> str:
    try:
        result = fn(*args, **kwargs)
        return _json({"success": True, "tool": name, "result": result})
    except Exception as exc:
        return _json({"success": False, "tool": name, "error": str(exc)})


def preview_open(slug: str, url: str | None = None) -> str:
    from spark_cli.workspace_routes import PreviewNavigate, navigate_preview, start_preview

    if url:
        return _call("preview_open", navigate_preview, slug, PreviewNavigate(url=url))
    return _call("preview_open", start_preview, slug, None)


def preview_snapshot(slug: str) -> str:
    from spark_cli.workspace_routes import get_preview_snapshot

    return _call("preview_snapshot", get_preview_snapshot, slug)


def preview_console(slug: str) -> str:
    from spark_cli.workspace_routes import get_preview_console

    return _call("preview_console", get_preview_console, slug)


def preview_click(slug: str, selector: str) -> str:
    from spark_cli.workspace_routes import PreviewBrowserAction, preview_click as _preview_click

    return _call("preview_click", _preview_click, slug, PreviewBrowserAction(selector=selector))


def preview_type(slug: str, selector: str, text: str) -> str:
    from spark_cli.workspace_routes import PreviewBrowserAction, preview_type as _preview_type

    return _call(
        "preview_type",
        _preview_type,
        slug,
        PreviewBrowserAction(selector=selector, text=text),
    )


def preview_evaluate(slug: str, expression: str) -> str:
    from spark_cli.workspace_routes import PreviewBrowserAction, preview_evaluate as _preview_evaluate

    return _call(
        "preview_evaluate",
        _preview_evaluate,
        slug,
        PreviewBrowserAction(expression=expression),
    )


def preview_screenshot(slug: str) -> str:
    from spark_cli.workspace_routes import _get_preview_session_or_404, _run_agent_browser

    try:
        session = _get_preview_session_or_404(slug)
        out_dir = get_spark_home() / "cache" / "screenshots"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"preview_{slug}_{uuid.uuid4().hex[:10]}.png"
        agent_result = _run_agent_browser(slug, ["screenshot", str(out_path)], timeout=20)
        if agent_result and agent_result.get("success") and out_path.exists():
            return _json(
                {
                    "success": True,
                    "tool": "preview_screenshot",
                    "result": {
                        "screenshot_path": str(out_path),
                        "url": session.get("url"),
                        "source": "agent-browser",
                        "ts": time.time(),
                    },
                }
            )

        from playwright.sync_api import sync_playwright  # type: ignore

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.goto(str(session["url"]), wait_until="networkidle", timeout=8000)
            page.screenshot(path=str(out_path), full_page=True)
            browser.close()
        return _json(
            {
                "success": True,
                "tool": "preview_screenshot",
                "result": {
                    "screenshot_path": str(out_path),
                    "url": session.get("url"),
                    "source": "playwright",
                    "ts": time.time(),
                },
            }
        )
    except Exception as exc:
        return _json({"success": False, "tool": "preview_screenshot", "error": str(exc)})


_OPEN_PARAM = {
    "type": "object",
    "properties": {
        "slug": {"type": "string", "description": "Workspace project slug."},
        "url": {
            "type": "string",
            "description": "Optional http/https URL to open in the shared browser. Omit to start the detected app preview.",
        },
    },
    "required": ["slug"],
}


_SLUG_PARAM = {
    "type": "object",
    "properties": {"slug": {"type": "string", "description": "Workspace project slug."}},
    "required": ["slug"],
}


registry.register(
    name="preview_open",
    toolset="preview",
    schema={
        "name": "preview_open",
        "description": "Start or reuse a workspace app preview, or open an http/https URL in the shared agent browser for the project.",
        "parameters": _OPEN_PARAM,
    },
    handler=lambda args, **kw: preview_open(args.get("slug", ""), args.get("url")),
)

registry.register(
    name="preview_snapshot",
    toolset="preview",
    schema={
        "name": "preview_snapshot",
        "description": "Fetch a bounded text/accessibility snapshot of the active workspace browser page.",
        "parameters": _SLUG_PARAM,
    },
    handler=lambda args, **kw: preview_snapshot(args.get("slug", "")),
)

registry.register(
    name="preview_console",
    toolset="preview",
    schema={
        "name": "preview_console",
        "description": "Return bounded server/browser diagnostic messages for the active workspace browser.",
        "parameters": _SLUG_PARAM,
    },
    handler=lambda args, **kw: preview_console(args.get("slug", "")),
)

registry.register(
    name="preview_click",
    toolset="preview",
    schema={
        "name": "preview_click",
        "description": "Click a CSS selector in the active shared browser session.",
        "parameters": {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "selector": {"type": "string", "description": "CSS selector to click."},
            },
            "required": ["slug", "selector"],
        },
    },
    handler=lambda args, **kw: preview_click(args.get("slug", ""), args.get("selector", "")),
)

registry.register(
    name="preview_type",
    toolset="preview",
    schema={
        "name": "preview_type",
        "description": "Fill a CSS selector in the active shared browser session.",
        "parameters": {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "selector": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["slug", "selector", "text"],
        },
    },
    handler=lambda args, **kw: preview_type(
        args.get("slug", ""), args.get("selector", ""), args.get("text", "")
    ),
)

registry.register(
    name="preview_evaluate",
    toolset="preview",
    schema={
        "name": "preview_evaluate",
        "description": "Evaluate JavaScript in the active shared browser session.",
        "parameters": {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "expression": {"type": "string"},
            },
            "required": ["slug", "expression"],
        },
    },
    handler=lambda args, **kw: preview_evaluate(args.get("slug", ""), args.get("expression", "")),
)

registry.register(
    name="preview_screenshot",
    toolset="preview",
    schema={
        "name": "preview_screenshot",
        "description": "Capture a screenshot of the active shared browser and return a local image path.",
        "parameters": _SLUG_PARAM,
    },
    handler=lambda args, **kw: preview_screenshot(args.get("slug", "")),
)
