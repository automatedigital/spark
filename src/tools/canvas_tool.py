"""Agent-facing Canvas tool — render a board of display widgets the user sees live.

The agent composes a canvas from simple widgets (markdown, text, notes, media,
embedded pages). Each widget maps to an existing ``display.*`` React Flow node
(see web/src/pages/canvas/CANVAS_MODEL.md), is auto-laid-out vertically, and the
whole board is written through the same storage the Canvas UI reads. A
``canvas.updated`` event is emitted so an open CanvasPage reloads immediately.
"""

from __future__ import annotations

import json
from typing import Any

from tools.registry import registry

# widget type → engine nodeType (the UI derives the render component via
# renderTypeFor(type) on load, so we store the engine type only).
_WIDGET_NODE_TYPE = {
    "markdown": "display.render",
    "text": "display.render",
    "note": "display.note",
    "media": "display.media",
    "iframe": "display.iframe",
    "preview": "display.preview",
    "actions": "display.actions",
}

_NODE_GAP_Y = 220


def _widget_to_node(index: int, widget: dict[str, Any]) -> dict[str, Any]:
    """Build a stored canvas node matching the UI's serialization shape:
    ``{id, type: <engineType>, position, params, data: {label, category}}``.
    """
    wtype = str(widget.get("type", "markdown")).lower()
    node_type = _WIDGET_NODE_TYPE.get(wtype, "display.render")

    if wtype == "actions":
        params = {
            "prompt": str(widget.get("prompt", widget.get("content", ""))),
            "options": [str(o) for o in (widget.get("options") or [])],
            "widget_id": str(widget.get("widget_id") or f"w{index}"),
        }
        label = widget.get("label") or "Actions"
    elif wtype in ("markdown", "text"):
        params = {"format": "markdown" if wtype == "markdown" else "text",
                  "content": str(widget.get("content", ""))}
        label = widget.get("label") or ("Markdown" if wtype == "markdown" else "Text")
    elif wtype == "note":
        params = {"text": str(widget.get("text", widget.get("content", "")))}
        label = widget.get("label") or "Note"
    else:  # media / iframe / preview
        params = {"url": str(widget.get("url", ""))}
        label = widget.get("label") or wtype.capitalize()

    return {
        "id": f"w{index}",
        "type": node_type,
        "position": {"x": 0, "y": index * _NODE_GAP_Y},
        "params": params,
        "data": {"label": label, "category": "display"},
    }


def canvas_render(
    canvas_id: str,
    widgets: list[dict[str, Any]],
    name: str | None = None,
    scope: str = "global",
    slug: str | None = None,
) -> str:
    """Render (replace) a canvas with the given display widgets."""
    if not canvas_id:
        return json.dumps({"error": "canvas_id is required"})
    if not isinstance(widgets, list) or not widgets:
        return json.dumps({"error": "widgets must be a non-empty list"})

    from spark_cli.canvas_routes import CanvasDoc, _write_canvas

    nodes = [_widget_to_node(i, w) for i, w in enumerate(widgets) if isinstance(w, dict)]
    doc = CanvasDoc(
        id=canvas_id,
        name=name or canvas_id,
        scope=scope,
        slug=slug,
        nodes=nodes,
        edges=[],
    )
    try:
        result = _write_canvas(scope, slug, canvas_id, doc)
    except Exception as exc:  # noqa: BLE001 — surface as tool error, not crash
        return json.dumps({"error": f"Failed to write canvas: {exc}"})

    # Notify any open CanvasPage to reload live (best-effort).
    try:
        from spark_cli.web_server import _publish_event

        _publish_event("canvas.updated", {"id": canvas_id, "scope": scope, "slug": slug})
    except Exception:
        pass

    return json.dumps({
        "ok": True,
        "canvas_id": canvas_id,
        "scope": scope,
        "node_count": len(nodes),
        "updatedAt": result.get("updatedAt"),
        "url": f"/canvas?id={canvas_id}",
    })


def canvas_await(
    canvas_id: str,
    widget_id: str,
    scope: str = "global",
    slug: str | None = None,
    timeout: float = 300.0,
) -> str:
    """Block until the user clicks an `actions` widget, returning the chosen value."""
    if not canvas_id or not widget_id:
        return json.dumps({"error": "canvas_id and widget_id are required"})
    from spark_cli.canvas_routes import wait_for_interaction

    value = wait_for_interaction(scope, slug, canvas_id, widget_id, min(max(timeout, 1.0), 1800.0))
    if value is None:
        return json.dumps({"timeout": True, "message": "No interaction within the time limit."})
    return json.dumps({"ok": True, "widget_id": widget_id, "value": value})


_CANVAS_SCHEMA = {
    "name": "canvas",
    "description": (
        "Render a visual board the user sees live in the Canvas UI. Compose it "
        "from display widgets: markdown (headings/lists/tables/code), text, "
        "sticky notes, media (image/audio/video URL), or embedded/live pages "
        "(iframe/preview). Use this to present structured results, dashboards, "
        "or visual summaries instead of (or alongside) a chat reply."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "canvas_id": {
                "type": "string",
                "description": "Stable id for the board (reused to update it). e.g. 'results'.",
            },
            "name": {"type": "string", "description": "Human-friendly board title."},
            "widgets": {
                "type": "array",
                "description": "Widgets rendered top-to-bottom.",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["markdown", "text", "note", "media", "iframe", "preview", "actions"],
                        },
                        "content": {"type": "string", "description": "For markdown/text/note."},
                        "text": {"type": "string", "description": "For note (alias of content)."},
                        "url": {"type": "string", "description": "For media/iframe/preview."},
                        "prompt": {"type": "string", "description": "For actions: the question shown above the buttons."},
                        "options": {"type": "array", "items": {"type": "string"}, "description": "For actions: button labels the user can click."},
                        "widget_id": {"type": "string", "description": "For actions: stable id to await with canvas_await."},
                        "label": {"type": "string", "description": "Optional node title."},
                    },
                    "required": ["type"],
                },
            },
            "scope": {"type": "string", "enum": ["global", "project"], "default": "global"},
            "slug": {"type": "string", "description": "Project slug when scope=project."},
        },
        "required": ["canvas_id", "widgets"],
    },
}


registry.register(
    name="canvas",
    toolset="canvas",
    schema=_CANVAS_SCHEMA,
    handler=lambda args, **kw: canvas_render(
        canvas_id=args.get("canvas_id", ""),
        widgets=args.get("widgets", []),
        name=args.get("name"),
        scope=args.get("scope", "global"),
        slug=args.get("slug"),
    ),
    emoji="🎨",
)


_CANVAS_AWAIT_SCHEMA = {
    "name": "canvas_await",
    "description": (
        "Wait for the user to click a button on an `actions` widget you rendered "
        "with the canvas tool, and return their choice. Use after rendering a "
        "board with an `actions` widget to get interactive input back."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "canvas_id": {"type": "string", "description": "The board id containing the actions widget."},
            "widget_id": {"type": "string", "description": "The actions widget's id."},
            "scope": {"type": "string", "enum": ["global", "project"], "default": "global"},
            "slug": {"type": "string", "description": "Project slug when scope=project."},
            "timeout": {"type": "number", "description": "Seconds to wait (default 300, max 1800)."},
        },
        "required": ["canvas_id", "widget_id"],
    },
}


registry.register(
    name="canvas_await",
    toolset="canvas",
    schema=_CANVAS_AWAIT_SCHEMA,
    handler=lambda args, **kw: canvas_await(
        canvas_id=args.get("canvas_id", ""),
        widget_id=args.get("widget_id", ""),
        scope=args.get("scope", "global"),
        slug=args.get("slug"),
        timeout=float(args.get("timeout", 300.0)),
    ),
    emoji="🎨",
)
