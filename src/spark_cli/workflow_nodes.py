"""Built-in workflow node handlers + node-type catalog.

Importing this module registers every handler with the engine. Heavy imports
(tool registry, AIAgent) are deferred into the handlers that need them so the
engine and the node-type listing stay cheap.
"""

from __future__ import annotations

import json
import logging
from typing import Any

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
        {"type": "control.merge", "category": "control", "label": "Merge", "emoji": "⛙"},
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
