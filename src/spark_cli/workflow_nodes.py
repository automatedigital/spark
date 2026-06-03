"""Built-in workflow node handlers + node-type catalog.

Importing this module registers every handler with the engine. Heavy imports
(tool registry, AIAgent) are deferred into the handlers that need them so the
engine and the node-type listing stay cheap.
"""

from __future__ import annotations

import csv
import json
import logging
import mimetypes
import re
import time
from html.parser import HTMLParser
from io import StringIO
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
        out.append(make_item({**(it.get("json") or {}), "__branch": "true" if ok else "false"}, it.get("binary")))
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
        branch = str(actual)
        if branch in allowed:
            out.append(make_item({**(it.get("json") or {}), "__branch": branch}, it.get("binary")))
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


# ── Files / data I/O ───────────────────────────────────────────────────────
@register_node_handler("io.file_source", category="io")
def _file_source_node(node: WorkflowNode, inputs: list[Item], ctx: ExecContext) -> list[Item]:
    params = resolve_params(node, ctx)
    path = str(params.get("path") or "").strip()
    if not path:
        raise ValueError("File Source node missing 'path'")
    file_path, file_ref = _workflow_file_path(params, ctx)
    if not file_path.exists() or file_path.is_dir():
        raise ValueError(f"File not found: {path}")
    mime, _ = mimetypes.guess_type(file_path.name)
    mode = str(params.get("mode") or "text")
    stat = file_path.stat()
    binary = {"file": {"fileRef": file_ref, "mimeType": mime or "application/octet-stream", "name": file_path.name}}
    payload: dict[str, Any] = {"path": path, "fileRef": file_ref, "mimeType": mime, "name": file_path.name, "size": stat.st_size}
    if mode != "binary":
        payload["content"] = file_path.read_text(encoding="utf-8", errors="replace")
    return [make_item(payload, binary)]


@register_node_handler("io.write_file", category="io")
def _write_file_node(node: WorkflowNode, inputs: list[Item], ctx: ExecContext) -> list[Item]:
    params = resolve_params(node, ctx)
    path = str(params.get("path") or "").strip()
    if not path:
        raise ValueError("Write File node missing 'path'")
    file_path, file_ref = _workflow_file_path(params, ctx, for_write=True)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    content = params.get("content")
    if content is None and inputs:
        first = inputs[0].get("json") or {}
        content = first.get("content", first)
    text = content if isinstance(content, str) else json.dumps(content, indent=2)
    file_path.write_text(text, encoding="utf-8")
    return [make_item({"path": path, "fileRef": file_ref, "bytes": len(text.encode("utf-8"))})]


@register_node_handler("io.read_table", category="io")
def _read_table_node(node: WorkflowNode, inputs: list[Item], ctx: ExecContext) -> list[Item]:
    params = resolve_params(node, ctx)
    file_path, file_ref = _workflow_file_path(params, ctx)
    suffix = file_path.suffix.lower()
    if suffix == ".json":
        data = json.loads(file_path.read_text(encoding="utf-8"))
        rows = data if isinstance(data, list) else [data]
    elif suffix == ".csv":
        rows = list(csv.DictReader(StringIO(file_path.read_text(encoding="utf-8", errors="replace"))))
    else:
        try:
            import pandas as pd  # type: ignore
        except ImportError as exc:
            raise ValueError("Spreadsheet reading requires pandas/openpyxl") from exc
        rows = pd.read_excel(file_path).to_dict(orient="records")
    return [make_item({"row": row, "index": i, "fileRef": file_ref}) for i, row in enumerate(rows)]


@register_node_handler("io.write_table", category="io")
def _write_table_node(node: WorkflowNode, inputs: list[Item], ctx: ExecContext) -> list[Item]:
    params = resolve_params(node, ctx)
    file_path, file_ref = _workflow_file_path(params, ctx, for_write=True)
    rows = params.get("rows")
    if rows is None:
        rows = [it.get("json") for it in inputs]
    if isinstance(rows, str):
        rows = json.loads(rows) if rows.strip() else []
    if not isinstance(rows, list):
        rows = [rows]
    file_path.parent.mkdir(parents=True, exist_ok=True)
    if file_path.suffix.lower() == ".csv":
        text = _rows_to_csv(rows)
        file_path.write_text(text, encoding="utf-8")
    elif file_path.suffix.lower() == ".xlsx":
        try:
            import pandas as pd  # type: ignore
        except ImportError as exc:
            raise ValueError("Spreadsheet writing requires pandas/openpyxl") from exc
        pd.DataFrame(rows).to_excel(file_path, index=False)
    else:
        file_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return [make_item({"path": str(params.get("path") or ""), "fileRef": file_ref, "rows": len(rows)})]


@register_node_handler("display.preview", category="display")
def _preview_node(node: WorkflowNode, inputs: list[Item], ctx: ExecContext) -> list[Item]:
    params = resolve_params(node, ctx)
    url = str(params.get("url") or "").strip()
    if not url:
        return list(inputs)
    return [make_item(_fetch_preview_metadata(url))]


@register_node_handler("display.render", category="display")
def _render_node(node: WorkflowNode, inputs: list[Item], ctx: ExecContext) -> list[Item]:
    params = resolve_params(node, ctx)
    content = params.get("content")
    if content is None and inputs:
        content = inputs[0].get("json")
    return [make_item({"content": content, "format": params.get("format") or "text"})]


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


def _workflow_file_path(params: dict[str, Any], ctx: ExecContext, *, for_write: bool = False):
    from spark_cli.workspace_routes import _project_dir, _safe_path, _workspace_root

    path = str(params.get("path") or "").strip()
    source = str(params.get("source") or ("project" if ctx.slug else "files"))
    slug = str(params.get("slug") or ctx.slug or "")
    if source == "project":
        if not slug:
            raise ValueError("Project file nodes require a project slug")
        root = _project_dir(slug)
        resolved = _safe_path(root, path)
        file_ref = f"project:{slug}:{path}"
    else:
        root = _workspace_root()
        rel = path if path.startswith("files/") else f"files/{path}"
        resolved = _safe_path(root, rel)
        file_ref = f"workspace:{rel}"
    if not for_write and not resolved.exists():
        raise ValueError(f"File not found: {path}")
    return resolved, file_ref


def _rows_to_csv(rows: list[Any]) -> str:
    dict_rows = [r if isinstance(r, dict) else {"value": r} for r in rows]
    fieldnames: list[str] = []
    for row in dict_rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    buf = StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames or ["value"])
    writer.writeheader()
    writer.writerows(dict_rows)
    return buf.getvalue()


class _PreviewParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.meta: dict[str, str] = {}
        self._in_title = False
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_d = {k.lower(): v or "" for k, v in attrs}
        lower = tag.lower()
        if lower == "title":
            self._in_title = True
        elif lower == "meta":
            key = (attrs_d.get("property") or attrs_d.get("name") or "").lower()
            if key and attrs_d.get("content"):
                self.meta[key] = attrs_d["content"]
        elif lower == "link" and "icon" in attrs_d.get("rel", "").lower():
            self.meta.setdefault("favicon", attrs_d.get("href", ""))

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title += text
        elif len(" ".join(self.text_parts)) < 5000:
            self.text_parts.append(text)


def _fetch_preview_metadata(url: str) -> dict[str, Any]:
    req = Request(url, headers={"User-Agent": "Spark-Workflow-Preview/1.0"})
    with urlopen(req, timeout=15) as resp:  # noqa: S310 - user-configured URL preview
        raw = resp.read(512_000)
        final_url = resp.url
        content_type = resp.headers.get("content-type", "")
    parser = _PreviewParser()
    parser.feed(raw.decode("utf-8", errors="replace"))
    image = parser.meta.get("og:image") or parser.meta.get("twitter:image") or ""
    favicon = parser.meta.get("favicon") or ""
    return {
        "url": final_url,
        "title": parser.meta.get("og:title") or parser.title or final_url,
        "description": parser.meta.get("og:description") or parser.meta.get("description") or "",
        "image": _absolute_url(final_url, image),
        "favicon": _absolute_url(final_url, favicon),
        "contentType": content_type,
        "text": re.sub(r"\s+", " ", " ".join(parser.text_parts)).strip()[:10000],
    }


def _absolute_url(base: str, maybe_url: str) -> str:
    if not maybe_url:
        return ""
    from urllib.parse import urljoin

    return urljoin(base, maybe_url)


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


# ── Agent / composition nodes ───────────────────────────────────────────────
@register_node_handler("agent", category="agent")
def _agent_node(node: WorkflowNode, inputs: list[Item], ctx: ExecContext) -> list[Item]:
    """Run an agentic turn with configurable toolsets and iteration budget."""
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
    toolsets = _coerce_list(params.get("toolsets"))
    max_iterations = _coerce_int(params.get("maxIterations"), default=10, minimum=1, maximum=ctx.max_iterations)
    skip_memory = _coerce_bool(params.get("skipMemory"), default=False)
    agent = AIAgent(
        session_id="wf_" + ctx.execution_id,
        model=runtime["model"],
        max_iterations=max_iterations,
        enabled_toolsets=toolsets or None,
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
        skip_memory=skip_memory,
        working_dir=working_dir,
    )
    ctx.emit("agent.started", {"nodeId": node.id, "model": runtime["model"], "maxIterations": max_iterations})
    reply = agent.chat(prompt)
    ctx.emit("agent.finished", {"nodeId": node.id})
    return [make_item({"reply": reply, "model": runtime["model"]})]


@register_node_handler("workflow.subworkflow", category="agent")
def _subworkflow_node(node: WorkflowNode, inputs: list[Item], ctx: ExecContext) -> list[Item]:
    """Execute another saved canvas workflow and return its terminal outputs."""
    from spark_cli.canvas_routes import _read_canvas
    from spark_cli.workflow_engine import WorkflowDoc, execute_workflow

    params = resolve_params(node, ctx)
    canvas_id = str(params.get("canvasId") or "").strip()
    if not canvas_id:
        raise ValueError("Sub-workflow node missing 'canvasId'")
    scope = str(params.get("scope") or ctx.doc.scope or "global")
    slug = params.get("slug") or ctx.doc.slug
    doc = WorkflowDoc(**_read_canvas(scope, slug, canvas_id))
    exec_id = f"{ctx.execution_id}_{node.id}"
    result = execute_workflow(
        doc,
        execution_id=exec_id,
        seed=inputs,
        cancelled=ctx.cancelled,
        max_iterations=ctx.max_iterations,
        emit=lambda event, data: ctx.emit(f"subworkflow.{event}", {"nodeId": node.id, **data}),
    )
    if result.status != "success":
        raise ValueError(result.error or "Sub-workflow failed")
    if not result.nodes:
        return []
    return result.nodes[-1].items


@register_node_handler("memory.context", category="agent")
def _context_memory_node(node: WorkflowNode, inputs: list[Item], ctx: ExecContext) -> list[Item]:
    """Read/write transient workflow-run state that downstream nodes can map."""
    params = resolve_params(node, ctx)
    key = str(params.get("key") or "default")
    mode = str(params.get("mode") or "write").lower()
    value = params.get("value")
    if mode in {"write", "set"}:
        ctx.state[key] = value if value is not None else [it.get("json") for it in inputs]
    elif mode == "append":
        ctx.state.setdefault(key, [])
        if not isinstance(ctx.state[key], list):
            ctx.state[key] = [ctx.state[key]]
        ctx.state[key].extend(value if isinstance(value, list) else [value if value is not None else inputs])
    return [make_item({"key": key, "value": ctx.state.get(key), "state": dict(ctx.state)})]


def _resolve_runtime(prompt: str, model: str | None) -> dict[str, Any]:
    """Resolve model/runtime for an agent node (reuses the web turn resolver)."""
    from spark_cli.web_server import _resolve_web_turn_route

    route = _resolve_web_turn_route(prompt)
    if model:
        route["model"] = model
    return route


def _coerce_bool(value: Any, *, default: bool = False) -> bool:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _coerce_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(v).strip() for v in parsed if str(v).strip()]
        except json.JSONDecodeError:
            pass
        return [v.strip() for v in value.split(",") if v.strip()]
    return [str(value)]


# ── Display nodes (non-executable; pass through) ────────────────────────────
for _display_type in ("display.note", "display.iframe", "display.media"):
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
        {"type": "io.file_source", "category": "io", "label": "File Source", "emoji": "📄"},
        {"type": "io.write_file", "category": "io", "label": "Write File", "emoji": "💾"},
        {"type": "io.read_table", "category": "io", "label": "Read Table", "emoji": "📊"},
        {"type": "io.write_table", "category": "io", "label": "Write Table", "emoji": "🧾"},
        {"type": "agent", "category": "agent", "label": "Agent", "emoji": "🤖"},
        {"type": "workflow.subworkflow", "category": "agent", "label": "Sub-workflow", "emoji": "🧩"},
        {"type": "memory.context", "category": "agent", "label": "Context Memory", "emoji": "🧠"},
        {"type": "display.note", "category": "display", "label": "Note", "emoji": "🗒"},
        {"type": "display.iframe", "category": "display", "label": "Embed (iframe)", "emoji": "🌐"},
        {"type": "display.preview", "category": "display", "label": "Web Preview", "emoji": "🔗"},
        {"type": "display.render", "category": "display", "label": "Render Output", "emoji": "🪟"},
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
