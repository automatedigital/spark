# Plan: Canvas → Workflows + Infinite Embed Canvas

The **Canvas** tab (name kept) becomes **one infinite surface with two coexisting kinds of
nodes**:

1. **Workflow nodes** — n8n-style: typed nodes pass data along connections, a **server-side
   execution engine** runs the graph (manual / scheduled / webhook / file-watch triggered),
   with an **agentic/iterative** layer for tool-calling agent loops.
2. **Embed / media nodes** — free-form: live **iframe** embeds, **URL/web previews**, images,
   video, PDFs, and rich notes — a moodboard/whiteboard that can sit next to (and feed) the
   workflow graph on the same canvas.

The two are not separate apps: an embed node can be a *data source* for a workflow (e.g. a
URL-preview node feeds its page text into an agent), and a workflow's output can render into
an embed/preview node. Connections are optional — drop a lone iframe to just pin a live site.

The current canvas (React Flow surface, palette, drag-drop, save/load global+project,
canvas-local chat) is the foundation — see [PR #21](https://github.com/automatedigital/spark/pull/21).
This plan reshapes node semantics around **data flow + execution + live embeds**, not just layout.

---

## What "works like n8n" means here

1. **Nodes pass data.** Every node receives an input array of JSON *items* and emits an
   output array. Connections carry data, not just visual lines.
2. **Triggers start runs.** Manual ▶, Schedule (cron), Webhook, File-watch.
3. **Actions do work.** Each registered Spark **tool becomes a node**, its JSON schema
   auto-rendered as a parameter form. Plus Agent, HTTP, Code, File, Set/Edit nodes.
4. **Control flow.** IF / Switch (branch), Loop / SplitInBatches (iterate), Merge, Wait.
5. **Agentic engines.** Agent node runs a tool-calling loop until done; can feed its output
   back into the graph or into another agent (iterative refinement).
6. **Execution is observable.** Run the whole flow or a single node; per-node input/output
   JSON, status, timing, and errors in an inspector; execution history.
7. **Files are first-class.** Pull in existing workspace/project files or upload new ones as
   inputs; pass binary/text data between nodes; write results back to files.
8. **Live embeds are first-class too.** Iframe / URL-preview / image / video / PDF nodes
   render live content directly on the canvas, resizable, and can connect into the graph.

---

## Architecture (grounded in the codebase)

**Backend**
- Tool registry already exposes what a node catalog needs
  ([src/tools/registry.py](src/tools/registry.py)):
  `get_all_tool_names()`, `get_definitions(names)` (OpenAI/JSON-schema for form rendering),
  `get_tool_to_toolset_map()`, `get_emoji()`, and `dispatch(name, args, **kwargs)` to run one.
- Agent runtime: `AIAgent` ([src/core/run_agent/__init__.py](src/core/run_agent/__init__.py))
  for agent nodes (reuse the stateless pattern from `POST /api/canvas/chat`).
- Scheduling: [src/cron/](src/cron/) (`parse_schedule`, `compute_next_run`, `trigger_job`)
  for Schedule triggers.
- Webhooks: existing gateway webhook adapter (`tests/gateway/test_webhook_adapter.py`) for
  Webhook triggers.
- Files: [src/spark_cli/workspace_routes.py](src/spark_cli/workspace_routes.py)
  (`_project_dir`, `_safe_path`, upload + read endpoints) for the File node + uploads.
- Canvas persistence: [src/spark_cli/canvas_routes.py](src/spark_cli/canvas_routes.py) —
  extend the saved doc with `nodes[].params`, typed edges, and `triggers`.

**Frontend**
- [CanvasPage.tsx](src/spark_cli/web/src/pages/CanvasPage.tsx) +
  [canvas/](src/spark_cli/web/src/pages/canvas/) (React Flow). Reshape `nodes.tsx`/`types.ts`
  into a node-type *registry* with a generic param-form renderer.
- API client [api.ts](src/spark_cli/web/src/lib/api.ts).

---

## Progress (branch `canvas-workflows`)

**Shipped & verified** (engine round-trips end-to-end in the browser):
- Phase 0 complete: `workflow_engine.py` (WorkflowDoc, item envelope, node-handler
  registry, field-mapping resolver, topological executor) + frontend node model.
- Phase 1: `/api/workflows/run`, `/run-node`, SQLite execution history. *Still TODO: SSE
  streaming, per-run timeout + cancel.*
- Phase 2 complete: `/node-types` exposes every Spark tool; schema-driven param form;
  literal⇄field-mapping picker; tool dispatch; searchable node browser.
- Phase 3 (partial): Set / IF / Merge nodes + the four trigger *node types* exist. *TODO:
  actually register schedule/webhook/file-watch triggers; Switch/Loop/Code/HTTP/Wait.*
- Phase 4 (partial): Agent node runs a stateless turn. *TODO: configurable tool-loop with
  toolset + iteration budget, sub-workflow, refinement loop.*
- Phase 5b (partial): sandboxed resizable iframe ✓, media node ✓, free placement ✓, basic
  web-preview card + note. *TODO: backend OG/text fetch for previews, PDF, upload-to-node,
  Markdown render, domain allowlist.*
- Phase 6 (partial): inspector (params + Input/Output JSON), run bar, node search/add,
  notes. *TODO: SSE-driven live badges, Stop, history drawer, edge preview, undo/redo.*

Tests: `test_workflow_engine.py` (8) + `test_workflow_routes.py` (5) + `test_canvas_routes.py`
(5) all green.

---

## Phase 0 — Data model & node SDK (foundation)
- [x] Define a **WorkflowDoc** schema (supersedes the loose CanvasDoc): `nodes[]` with
      `{ id, type, params, position, credentials? }`, `edges[]` with `{ source, sourceOutput,
      target, targetInput }`, `triggers[]`, `settings`. Version + migrate existing canvases.
- [x] Define the **item/data envelope** passed along edges:
      `{ json: object, binary?: { [key]: { fileRef, mimeType, name } } }[]`.
- [x] Backend `workflow_engine.py`: a node-handler interface
      `run(node, inputItems, ctx) -> outputItems` and a node-type registry.
- [x] Frontend node-type registry (`canvas/nodeRegistry.ts`): each type declares
      inputs/outputs, an icon, a param schema, and a React body renderer.
- [x] Node **category** in the type definition: `trigger | action | control | agent | io |
      display`. **`display` nodes** (iframe, preview, media, note) are non-executable by
      default — they render on the canvas and may optionally expose output items — so the
      embed/moodboard half and the workflow half share one model and one save file.

## Phase 1 — Execution engine (server-side)
- [x] `POST /api/workflows/{scope}/{id}/run` — execute a saved workflow; returns an
      `executionId`. Topological scheduling from trigger node(s); pass items along edges.
- [x] `POST /api/workflows/run-node` — run a single node with provided input items (for the
      "execute node" button) without persisting.
- [ ] Per-node execution state streamed over SSE (reuse the SSE pattern in
      [web_server.py](src/spark_cli/web_server.py)): `node.started/succeeded/failed`,
      output items, duration, error.
- [x] **Execution history**: persist runs under `~/.spark/workflows/executions/` (or SQLite);
      `GET /api/workflows/.../executions` + a single execution view.
- [ ] Guardrails: max nodes, max iterations, per-run timeout, cancel endpoint.

## Phase 2 — Tool nodes auto-generated from the registry
- [x] `GET /api/workflows/node-types` — enumerate every registered tool as a node type
      (name, toolset, emoji, JSON-schema params) via `registry.get_definitions()` +
      `get_tool_to_toolset_map()`.
- [x] Generic **param-form renderer**: turn a tool's JSON schema into form fields
      (string/number/bool/enum/object/array). Each field can be set to a **literal** or
      **mapped** to an upstream node's output field via a dropdown (`{node → field}`).
- [x] **Mapping resolver** (backend): resolve each mapped param from the executing items
      before dispatch. Design it as the single place expressions can later plug into.
- [x] **Tool node** executes via `registry.dispatch(name, resolvedArgs)`; map the JSON-string
      result back into output items.
- [x] Palette becomes a **searchable node browser** grouped by toolset (40+ tools), not a
      fixed list.

## Phase 3 — Core control-flow & data nodes
- [ ] **Trigger nodes (all four ship in v1)**: Manual ▶, Schedule (cron via
      [src/cron/](src/cron/)), Webhook (registers a gateway webhook route + per-workflow
      secret), File-watch (watch a project path/glob).
- [ ] **IF / Switch** (conditional branching with multiple outputs).
- [ ] **Loop / SplitInBatches** (iterate items, with a loop-back edge) + **Merge**.
- [x] **Set / Edit Fields** (build or transform the JSON item).
- [ ] **Code node** — run JS/Python over items in the existing sandbox (reuse `execute_code`).
- [ ] **HTTP Request** node.
- [ ] **Wait / Delay** node.

## Phase 4 — Agentic / iterative engine
- [x] **Agent node**: a tool-calling loop (`AIAgent`) with a selectable toolset, max-iteration
      budget, and structured output; streams reasoning/tool-calls into the inspector.
- [ ] **Sub-workflow node**: call another saved workflow as a step (composition).
- [ ] **Agent-to-agent / refinement loop**: wire an agent's output back through IF/Loop for
      iterative improvement until a condition is met.
- [ ] Memory/context node so agent nodes can share state across iterations.

## Phase 5 — Files & data I/O
- [ ] **File source node**: pick an existing file from a workspace **project** or the chat
      **files** area (reuse `/api/workspace/...` listing); load as a binary/text item.
- [ ] **Upload**: drag a file onto the canvas (or a node) → upload via
      [workspace_routes.py](src/spark_cli/workspace_routes.py) and create a File node.
- [ ] **Write File node**: persist an item's content back to a project/file path.
- [ ] Binary passthrough in the item envelope (reference by `fileRef`, not inlined bytes).
- [ ] Read/Write **Spreadsheet/CSV/JSON** helper nodes (lean on existing `xlsx`/file tools).

## Phase 5b — Live embeds & rich media (the "infinite canvas" half)
- [x] **Iframe / Embed node**: render an arbitrary URL in a sandboxed `<iframe>`
      (`sandbox`, `referrerpolicy`, allowlist) directly on the canvas; resizable; refresh +
      open-in-new-tab controls. Stored as `{ url, width, height, sandbox }` in the node.
- [ ] **URL / Web-preview node**: fetch a page's title/description/OG image/favicon (reuse
      existing fetch/scrape tools) for a link-card preview; "expand to live iframe" toggle.
      Exposes page text/metadata as **output items** so it can feed the workflow graph.
- [ ] **Image / Video / PDF nodes**: render media from a URL or an uploaded/workspace file
      (reuse `mediaFileUrl` + the upload routes); pannable/zoomable, resizable.
- [ ] **Rich note / Markdown node** (upgrade the current Note): live-rendered Markdown.
- [ ] **Embed ↔ graph bridge**: embed/preview nodes can connect into workflow inputs, and a
      workflow can target a **Preview/Render node** to display its output (HTML/image/text).
- [x] **Free-placement mode**: embeds work with **no connections** (pure moodboard); the
      canvas mixes connected workflow subgraphs and loose pinned embeds on one surface.
- [ ] **Security**: iframe sandboxing defaults, a domain allow/block setting, and respect for
      desktop (Tauri) webview embed constraints; never auto-execute remote content beyond the
      sandboxed iframe.

## Phase 6 — Builder UX & inspector
- [x] **Node inspector panel** (right drawer): params form, plus **Input** / **Output** JSON
      tabs showing the items from the last run; per-node run/error badges on the canvas.
- [ ] **Run bar**: ▶ Run, Run-from-node, Stop, last-execution status, execution-history drawer.
- [ ] Edge data preview (hover an edge → see items count/sample).
- [x] Node search/add (drag from browser **or** click an output `+` to add the next node).
- [ ] Copy/paste, duplicate, multi-select, undo/redo, alignment helpers.
- [x] Sticky notes / comments retained from the current Note node.

## Phase 7 — Hardening, security, ship
- [ ] Sandbox/timeout/iteration limits enforced for Code, HTTP, Agent, and Loop nodes.
- [ ] Webhook auth + per-workflow secret; respect dashboard auth on all new routes.
- [ ] Profile-safe paths (`get_spark_home()`), no writes to `~/.spark/` in tests.
- [ ] Tests: engine (topo order, branching, loops, error propagation), tool-node dispatch,
      file I/O, trigger registration; web build/typecheck/lint.
- [ ] Docs + rebuild `web_dist`; feature branch + PR.

---

## Decisions (locked)

- **Execution: server-side.** The engine runs in the Spark backend so schedules/webhooks
  fire without the browser open, and nodes reuse the real tool registry + `AIAgent`.
- **Data mapping: field-mapping dropdowns for v1.** Nodes reference upstream output fields
  via dropdowns (pick `{node → field}`), not free-text expressions. n8n-style
  `{{ $json.x }}` expressions are a **post-v1** enhancement layered on the same resolver.
- **Triggers: all four in v1.** Manual ▶, Schedule (cron), Webhook, and File-watch all ship
  in Phase 3.
- **Execution history: SQLite.** Persist runs in a new table (better for history queries)
  rather than flat JSON.

- **Tab name: stays "Canvas".** It hosts both executable workflows and a free-form infinite
  surface of live embeds/media — one canvas, two modes that mix freely.

## Out of scope (for now)
- Multi-user collaboration / real-time co-editing.
- A marketplace of community workflow templates.
- Visual debugging time-travel beyond per-node last-run I/O.
