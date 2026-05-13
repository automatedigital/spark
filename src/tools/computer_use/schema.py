"""JSON schema for the computer_use tool."""

COMPUTER_USE_SCHEMA = {
    "name": "computer_use",
    "description": (
        "**Use this for native macOS desktop apps** (Notion app, Slack app, Finder, etc.) and "
        "when the user says computer-use, desktop app, or not the browser/website. "
        "Do NOT substitute browser_open or terminal GUI automation (osascript, screencapture, "
        "vision on screenshots). "
        "Control macOS desktop apps in the background via cua-driver. "
        "Does NOT steal cursor focus or switch Spaces. "
        "Start every task with action='capture' (app=<name>) to select the target window "
        "and get a screenshot with interactive element overlays. "
        "Then use click/type/key/scroll/drag to interact. "
        "list_apps returns running app names you can pass to capture."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "capture",
                    "click",
                    "type",
                    "key",
                    "scroll",
                    "drag",
                    "set_value",
                    "focus_app",
                    "list_apps",
                ],
                "description": (
                    "capture: screenshot + AX-tree element list (required first step). "
                    "click: click an element or coordinate. "
                    "type: type text into focused element. "
                    "key: send key combo e.g. 'cmd+s', 'return', 'shift+delete'. "
                    "scroll: scroll in a direction. "
                    "drag: drag from one point to another. "
                    "set_value: set dropdown/popup value by element index. "
                    "focus_app: update active window context (no focus theft). "
                    "list_apps: list running app names."
                ),
            },
            "app": {
                "type": "string",
                "description": (
                    "App name substring for capture/focus_app (case-insensitive). "
                    "E.g. 'Safari', 'Finder', 'Cursor'. "
                    "Required for capture when no window is already selected."
                ),
            },
            "mode": {
                "type": "string",
                "enum": ["som", "vision"],
                "description": (
                    "'som' (default): AX-tree element list + optional screenshot overlay. "
                    "'vision': screenshot only (no element list)."
                ),
            },
            "element": {
                "type": "integer",
                "description": "Element index from the last capture's element list.",
            },
            "x": {
                "type": "number",
                "description": "Screen x-coordinate (pixels from left).",
            },
            "y": {
                "type": "number",
                "description": "Screen y-coordinate (pixels from top).",
            },
            "text": {
                "type": "string",
                "description": "Text to type (for action='type').",
            },
            "keys": {
                "type": "string",
                "description": (
                    "Key combination to send (for action='key'). "
                    "E.g. 'cmd+s', 'return', 'escape', 'shift+delete', 'ctrl+a'."
                ),
            },
            "button": {
                "type": "string",
                "enum": ["left", "right", "middle"],
                "description": "Mouse button (default: 'left').",
            },
            "click_count": {
                "type": "integer",
                "description": "Number of clicks (1=click, 2=double-click). Default: 1.",
            },
            "direction": {
                "type": "string",
                "enum": ["up", "down", "left", "right"],
                "description": "Scroll direction.",
            },
            "amount": {
                "type": "number",
                "description": "Scroll amount in scroll units.",
            },
            "start_x": {
                "type": "number",
                "description": "Drag start x-coordinate.",
            },
            "start_y": {
                "type": "number",
                "description": "Drag start y-coordinate.",
            },
            "end_x": {
                "type": "number",
                "description": "Drag end x-coordinate.",
            },
            "end_y": {
                "type": "number",
                "description": "Drag end y-coordinate.",
            },
            "value": {
                "type": "string",
                "description": "Value to set for action='set_value' (popup/dropdown).",
            },
        },
        "required": ["action"],
    },
}
