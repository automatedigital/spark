"""Built-in workflow node handlers + node-type catalog.

Importing this module registers every handler with the engine. Heavy imports
(tool registry, AIAgent) are deferred into the handlers that need them so the
engine and the node-type listing stay cheap.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from spark_cli.workflow_engine import (
    ExecContext,
    Item,
    WorkflowNode,
    make_item,
    register_node_handler,
    resolve_params,
)

_log = logging.getLogger(__name__)


# ── Triggers ────────────────────────────────────────────────────────────────
@register_node_handler("trigger.manual", category="trigger")
def _manual_trigger(node: WorkflowNode, inputs: list[Item], ctx: ExecContext) -> list[Item]:
    """Emit a single seed item so downstream nodes have something to run on."""
    params = resolve_params(node, ctx)
    payload = params.get("payload")
    if isinstance(payload, str) and payload.strip():
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = {"value": payload}
    return [make_item(payload if payload is not None else {})]


@register_node_handler("trigger.schedule", category="trigger")
def _schedule_trigger(node: WorkflowNode, inputs: list[Item], ctx: ExecContext) -> list[Item]:
    """When executed (manually or by the scheduler) emit a tick item.

    Registration of the actual cron schedule is handled out-of-band by the run
    endpoint; here we just seed the graph.
    """
    return [make_item({"triggeredAt": ctx.execution_id})]


@register_node_handler("trigger.webhook", category="trigger")
def _webhook_trigger(node: WorkflowNode, inputs: list[Item], ctx: ExecContext) -> list[Item]:
    """Seed with the webhook payload passed in via ``params.payload`` (set by the
    webhook route when a call arrives)."""
    params = resolve_params(node, ctx)
    return [make_item(params.get("payload") or {})]


@register_node_handler("trigger.filewatch", category="trigger")
def _filewatch_trigger(node: WorkflowNode, inputs: list[Item], ctx: ExecContext) -> list[Item]:
    params = resolve_params(node, ctx)
    return [make_item({"path": params.get("path"), "event": params.get("event", "change")})]


# ── Data / control nodes ────────────────────────────────────────────────────
@register_node_handler("data.set", category="control")
def _set_fields(node: WorkflowNode, inputs: list[Item], ctx: ExecContext) -> list[Item]:
    """Merge a dict of fields into each incoming item's json (or create one)."""
    params = resolve_params(node, ctx)
    fields = params.get("fields") or {}
    if isinstance(fields, str):
        try:
            fields = json.loads(fields)
        except json.JSONDecodeError:
            fields = {}
    if not inputs:
        return [make_item(dict(fields))]
    out: list[Item] = []
    for it in inputs:
        merged = {**(it.get("json") or {}), **fields}
        out.append(make_item(merged, it.get("binary")))
    return out


@register_node_handler("control.if", category="control")
def _if_node(node: WorkflowNode, inputs: list[Item], ctx: ExecContext) -> list[Item]:
    """Pass items whose mapped field is truthy. (Branch outputs land in a follow-up;
    v1 filters the stream.)"""
    params = resolve_params(node, ctx)
    field = params.get("field", "value")
    expected = params.get("equals")
    out: list[Item] = []
    for it in inputs:
        actual = (it.get("json") or {}).get(field)
        ok = (actual == expected) if expected is not None else bool(actual)
        if ok:
            out.append(it)
    return out


@register_node_handler("control.merge", category="control")
def _merge_node(node: WorkflowNode, inputs: list[Item], ctx: ExecContext) -> list[Item]:
    return list(inputs)


@register_node_handler("control.switch", category="control")
def _switch_node(node: WorkflowNode, inputs: list[Item], ctx: ExecContext) -> list[Item]:
    """Filter items by matching a field against one of the configured cases.

    The current topological engine has one output stream per node, so v1 treats
    Switch as a selectable filter. Multi-output edge routing can layer on this
    handler once edge handles carry branch names through the executor.
    """
    params = resolve_params(node, ctx)
    field = params.get("field", "value")
    selected = params.get("case")
    cases = params.get("cases") or []
    if isinstance(cases, str):
        try:
            cases = json.loads(cases) if cases.strip() else []
        except json.JSONDecodeError:
            cases = []

    allowed = {str(c.get("value")) for c in cases if isinstance(c, dict) and c.get("enabled", True)}
    if selected not in (None, ""):
        allowed = {str(selected)}
    if not allowed:
        return list(inputs)

    out: list[Item] = []
    for it in inputs:
        actual = (it.get("json") or {}).get(field)
        if str(actual) in allowed:
            out.append(it)
    return out


@register_node_handler("control.loop", category="control")
def _loop_node(node: WorkflowNode, inputs: list[Item], ctx: ExecContext) -> list[Item]:
    """Expand each item into repeated iteration items.

    This is the first, acyclic Loop/SplitInBatches primitive: downstream nodes
    receive one item per iteration with ``iteration`` and ``source`` metadata.
    """
    params = resolve_params(node, ctx)
    count = _coerce_int(params.get("count"), default=1, minimum=0, maximum=ctx.max_iterations)
    batch_size = _coerce_int(params.get("batchSize"), default=1, minimum=1, maximum=ctx.max_iterations)
    source_items = inputs or [make_item({})]
    out: list[Item] = []
    iteration = 0
    for it in source_items:
        for _ in range(count):
            if ctx.cancelled():
                break
            iteration += 1
            out.append(
                make_item(
                    {
                        **(it.get("json") or {}),
                        "iteration": iteration,
                        "batchIndex": (iteration - 1) // batch_size,
                        "source": it.get("json") or {},
                    },
                    it.get("binary"),
                )
            )
            if len(out) >= ctx.max_iterations:
                return out
    return out


@register_node_handler("action.wait", category="action")
def _wait_node(node: WorkflowNode, inputs: list[Item], ctx: ExecContext) -> list[Item]:
    params = resolve_params(node, ctx)
    seconds = _coerce_float(params.get("seconds"), default=1.0, minimum=0.0, maximum=60.0)
    if seconds:
        time.sleep(seconds)
    return list(inputs)


@register_node_handler("action.http", category="action")
def _http_node(node: WorkflowNode, inputs: list[Item], ctx: ExecContext) -> list[Item]:
    params = resolve_params(node, ctx)
    url = str(params.get("url") or "").strip()
    if not url:
        raise ValueError("HTTP node missing 'url'")
    method = str(params.get("method") or "GET").upper()
    headers = params.get("headers") or {}
    body = params.get("body")
    timeout = _coerce_float(params.get("timeout"), default=20.0, minimum=0.1, maximum=120.0)
    if isinstance(headers, str):
        headers = _parse_json_object(headers, "headers")
    data = None
    if body not in (None, ""):
        data = body.encode("utf-8") if isinstance(body, str) else json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json", **headers}

    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310 - explicit user-configured workflow URL
            raw = resp.read()
            text = raw.decode(resp.headers.get_content_charset() or "utf-8", errors="replace")
            parsed: Any
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = text
            return [
                make_item(
                    {
                        "status": resp.status,
                        "url": resp.url,
                        "headers": dict(resp.headers.items()),
                        "body": parsed,
                    }
                )
            ]
    except HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        return [make_item({"status": exc.code, "url": url, "error": text})]
    except URLError as exc:
        raise ValueError(f"HTTP request failed: {exc.reason}") from exc


@register_node_handler("action.code", category="action")
def _code_node(node: WorkflowNode, inputs: list[Item], ctx: ExecContext) -> list[Item]:
    """Run Python over workflow items using the existing execute_code sandbox.

    User code receives ``items`` and should assign ``output`` to either an item
    list or plain JSON values. Printed output is preserved when no structured
    output marker is emitted.
    """
    from tools.code_execution_tool import execute_code

    params = resolve_params(node, ctx)
    code = str(params.get("code") or "").strip()
    if not code:
        raise ValueError("Code node has no code")
    script = _wrap_code_script(code, inputs)
    raw = execute_code(script, task_id=ctx.execution_id)
    result = json.loads(raw) if isinstance(raw, str) else raw
    if result.get("status") != "success":
        raise ValueError(result.get("error") or result.get("output") or "Code execution failed")
    marker = "__SPARK_WORKFLOW_OUTPUT__="
    output_text = str(result.get("output") or "")
    for line in reversed(output_text.splitlines()):
        if line.startswith(marker):
            payload = json.loads(line[len(marker) :])
            if isinstance(payload, list):
                return [_ensure_item(v) for v in payload]
            return [_ensure_item(payload)]
    return [make_item({"output": output_text, "durationSeconds": result.get("duration_seconds")})]


def _wrap_code_script(code: str, inputs: list[Item]) -> str:
    encoded_items = json.dumps(inputs, ensure_ascii=False)
    return f"""import json
items = json.loads({encoded_items!r})
output = None

{code}

def _spark_item(value):
    if isinstance(value, dict) and "json" in value:
        return value
    return {{"json": value if value is not None else {{}}, "binary": {{}}}}

if output is not None:
    payload = [_spark_item(v) for v in output] if isinstance(output, list) else [_spark_item(output)]
    print("__SPARK_WORKFLOW_OUTPUT__=" + json.dumps(payload, ensure_ascii=False))
"""


def _ensure_item(value: Any) -> Item:
    if isinstance(value, dict) and "json" in value:
        return {"json": value.get("json") or {}, "binary": value.get("binary") or {}}
    return make_item(value)


def _parse_json_object(value: str, label: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value) if value.strip() else {}
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} must be a JSON object")
    return parsed


def _coerce_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, minimum), maximum)


def _coerce_float(value: Any, *, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, minimum), maximum)


# ── Tool node (auto-backed by the registry) ─────────────────────────────────
@register_node_handler("tool", category="action")
def _tool_node(node: WorkflowNode, inputs: list[Item], ctx: ExecContext) -> list[Item]:
    """Dispatch a registered Spark tool. ``params.tool`` is the tool name; the rest
    of ``params.args`` are the (resolved) arguments."""
    from tools.registry import registry

    params = resolve_params(node, ctx)
    tool_name = params.get("tool") or node.data.get("tool")
    if not tool_name:
        raise ValueError("Tool node missing 'tool' name")
    args = params.get("args") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args) if args.strip() else {}
        except json.JSONDecodeError as exc:
            raise ValueError(f"Tool args are not valid JSON: {exc}")
    raw = registry.dispatch(tool_name, args)
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        parsed = {"result": raw}
    return [make_item(parsed)]


# ── Agent node (stateless tool-calling turn) ────────────────────────────────
@register_node_handler("agent", category="agent")
def _agent_node(node: WorkflowNode, inputs: list[Item], ctx: ExecContext) -> list[Item]:
    """Run a single stateless agent turn. Mirrors POST /api/canvas/chat so canvas
    agents never create Chat-tab sessions."""
    from core.run_agent import AIAgent

    params = resolve_params(node, ctx)
    prompt = params.get("prompt") or ""
    if not prompt and inputs:
        prompt = str((inputs[0].get("json") or {}).get("prompt", "")) or json.dumps(inputs[0].get("json", {}))
    if not prompt:
        raise ValueError("Agent node has no prompt")

    working_dir = None
    if ctx.slug:
        from spark_cli.workspace_routes import _project_dir

        working_dir = str(_project_dir(ctx.slug))

    model = params.get("model") or None
    runtime = _resolve_runtime(prompt, model)
    agent = AIAgent(
        session_id="wf_" + ctx.execution_id,
        model=runtime["model"],
        api_key=runtime["runtime"].get("api_key"),
        base_url=runtime["runtime"].get("base_url"),
        provider=runtime["runtime"].get("provider"),
        api_mode=runtime["runtime"].get("api_mode"),
        command=runtime["runtime"].get("command"),
        args=list(runtime["runtime"].get("args") or []),
        credential_pool=runtime["runtime"].get("credential_pool"),
        request_overrides=runtime.get("request_overrides"),
        quiet_mode=True,
        platform="web",
        session_db=None,
        working_dir=working_dir,
    )
    reply = agent.chat(prompt)
    return [make_item({"reply": reply, "model": runtime["model"]})]


def _resolve_runtime(prompt: str, model: str | None) -> dict[str, Any]:
    """Resolve model/runtime for an agent node (reuses the web turn resolver)."""
    from spark_cli.web_server import _resolve_web_turn_route

    route = _resolve_web_turn_route(prompt)
    if model:
        route["model"] = model
    return route


# ── Display nodes (non-executable; pass through) ────────────────────────────
for _display_type in ("display.note", "display.iframe", "display.preview", "display.media"):
    register_node_handler(_display_type, category="display")(
        lambda node, inputs, ctx: list(inputs)
    )


# ── Node-type catalog (for the frontend node browser) ───────────────────────
def node_type_catalog() -> list[dict[str, Any]]:
    """Static built-in node types + every registered tool as a node type.

    Tool node types carry their JSON schema so the UI can render a param form.
    """
    builtins: list[dict[str, Any]] = [
        {"type": "trigger.manual", "category": "trigger", "label": "Manual Trigger", "emoji": "▶"},
        {"type": "trigger.schedule", "category": "trigger", "label": "Schedule", "emoji": "⏰"},
        {"type": "trigger.webhook", "category": "trigger", "label": "Webhook", "emoji": "🪝"},
        {"type": "trigger.filewatch", "category": "trigger", "label": "File Watch", "emoji": "👁"},
        {"type": "data.set", "category": "control", "label": "Set Fields", "emoji": "✏️"},
        {"type": "control.if", "category": "control", "label": "IF", "emoji": "🔀"},
        {"type": "control.switch", "category": "control", "label": "Switch", "emoji": "🔁"},
        {"type": "control.loop", "category": "control", "label": "Loop", "emoji": "🔂"},
        {"type": "control.merge", "category": "control", "label": "Merge", "emoji": "⛙"},
        {"type": "action.code", "category": "action", "label": "Code", "emoji": "⌨️"},
        {"type": "action.http", "category": "action", "label": "HTTP Request", "emoji": "🌍"},
        {"type": "action.wait", "category": "action", "label": "Wait", "emoji": "⏳"},
        {"type": "agent", "category": "agent", "label": "Agent", "emoji": "🤖"},
        {"type": "display.note", "category": "display", "label": "Note", "emoji": "🗒"},
        {"type": "display.iframe", "category": "display", "label": "Embed (iframe)", "emoji": "🌐"},
        {"type": "display.preview", "category": "display", "label": "Web Preview", "emoji": "🔗"},
        {"type": "display.media", "category": "display", "label": "Media", "emoji": "🖼"},
    ]

    tools: list[dict[str, Any]] = []
    try:
        from core import model_tools  # noqa: F401 — triggers tool discovery
        from tools.registry import registry

        names = registry.get_all_tool_names()
        defs = {d["function"]["name"]: d for d in registry.get_definitions(set(names), quiet=True)}
        ts_map = registry.get_tool_to_toolset_map()
        for name in sorted(names):
            d = defs.get(name)
            if not d:
                continue
            fn = d.get("function", {})
            tools.append(
                {
                    "type": "tool",
                    "category": "action",
                    "label": name,
                    "tool": name,
                    "toolset": ts_map.get(name, "core"),
                    "emoji": registry.get_emoji(name, "⚡"),
                    "description": fn.get("description", ""),
                    "schema": fn.get("parameters", {}),
                }
            )
    except Exception as exc:  # noqa: BLE001 — tool listing is best-effort
        _log.warning("Tool node catalog unavailable: %s", exc)

    return builtins + tools
