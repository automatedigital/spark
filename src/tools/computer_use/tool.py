"""computer_use tool handler — registered with the Spark tool registry."""

import json
import logging
from typing import Any, Dict

from tools.registry import registry, tool_error, tool_result
from tools.computer_use.schema import COMPUTER_USE_SCHEMA
from tools.computer_use.cua_backend import (
    CuaDriverBackend,
    CaptureResult,
    ActionResult,
    is_available,
)

logger = logging.getLogger(__name__)

# One backend instance per process — holds the sticky window context.
_backend = CuaDriverBackend()


def _check_cua_requirements() -> bool:
    return is_available()


def handle_computer_use(args: Dict[str, Any]) -> str:
    action = args.get("action")
    if not action:
        return tool_error("'action' is required")

    try:
        if action == "list_apps":
            apps = _backend.list_apps()
            return tool_result(apps=apps)

        if action == "focus_app":
            app = args.get("app")
            if not app:
                return tool_error("'app' is required for focus_app")
            result = _backend.focus_app(app)
            return _action_result(result)

        if action == "capture":
            mode = args.get("mode", "som")
            app = args.get("app")
            try:
                capture = _backend.capture(mode=mode, app=app)
            except RuntimeError as e:
                return tool_error(str(e))
            return _capture_result(capture)

        if action == "click":
            result = _backend.click(
                element=args.get("element"),
                x=args.get("x"),
                y=args.get("y"),
                button=args.get("button", "left"),
                click_count=args.get("click_count", 1),
            )
            return _action_result(result)

        if action == "type":
            text = args.get("text", "")
            if not text:
                return tool_error("'text' is required for type action")
            result = _backend.type_text(text)
            return _action_result(result)

        if action == "key":
            keys = args.get("keys", "")
            if not keys:
                return tool_error("'keys' is required for key action")
            result = _backend.key(keys)
            return _action_result(result)

        if action == "scroll":
            direction = args.get("direction")
            amount = args.get("amount", 3)
            if not direction:
                return tool_error("'direction' is required for scroll")
            result = _backend.scroll(
                direction=direction,
                amount=amount,
                element=args.get("element"),
                x=args.get("x"),
                y=args.get("y"),
            )
            return _action_result(result)

        if action == "drag":
            for field in ("start_x", "start_y", "end_x", "end_y"):
                if args.get(field) is None:
                    return tool_error(f"'{field}' is required for drag")
            result = _backend.drag(
                start_x=args["start_x"],
                start_y=args["start_y"],
                end_x=args["end_x"],
                end_y=args["end_y"],
            )
            return _action_result(result)

        if action == "set_value":
            value = args.get("value")
            element = args.get("element")
            if value is None or element is None:
                return tool_error("'value' and 'element' are required for set_value")
            result = _backend.set_value(value=value, element=element)
            return _action_result(result)

        return tool_error(f"Unknown action: {action!r}")

    except FileNotFoundError:
        from tools.computer_use.cua_backend import cua_driver_install_command

        return tool_error(
            "cua-driver not found. Install it to use computer_use: "
            f"{cua_driver_install_command()}"
        )
    except Exception as e:
        logger.exception("computer_use error (action=%s): %s", action, e)
        return tool_error(f"computer_use failed: {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Serialisers
# ---------------------------------------------------------------------------

def _capture_result(capture: CaptureResult) -> str:
    payload: Dict[str, Any] = {
        "success": True,
        "mode": capture.mode,
        "app": capture.app,
        "window_title": capture.window_title,
        "width": capture.width,
        "height": capture.height,
        "element_count": len(capture.elements),
        "elements": capture.elements,
    }
    if capture.png_b64:
        # Truncate for JSON transport; full image is accessible via vision_analyze
        payload["screenshot_b64"] = capture.png_b64
    return json.dumps(payload, ensure_ascii=False)


def _action_result(result: ActionResult) -> str:
    if result.success:
        payload: Dict[str, Any] = {"success": True, "message": result.message}
        if result.data:
            payload["data"] = result.data
        return json.dumps(payload, ensure_ascii=False)
    return tool_error(result.message)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

registry.register(
    name="computer_use",
    toolset="computer_use",
    schema=COMPUTER_USE_SCHEMA,
    handler=handle_computer_use,
    check_fn=_check_cua_requirements,
    description=(
        "macOS background desktop control via cua-driver. "
        "Screenshot, click, type, key, scroll, drag without stealing cursor focus."
    ),
    emoji="🖥️",
)
