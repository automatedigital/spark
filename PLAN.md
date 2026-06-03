# Plan: "Canvas" Tab — Infinite Canvas with Draggable Tools

Add a new top-level tab **Canvas**: an infinite, pannable/zoomable canvas (React Flow)
where the user drags tools/nodes onto the page, wires them into an agentic node graph,
**chats inside the canvas** via chat nodes, and **saves canvases either globally or into a
project folder**.

## Locked decisions
- **Engine:** `@xyflow/react` (React Flow).
- **Chat:** a first-class **Chat node**, bound to the agent backend but **canvas-local** —
  it does **not** create a session visible in the Chat tab.
- **Persistence:** backend-saved canvases (JSON), with **two scopes**:
  - **Global** → `get_spark_home()/canvases/<name>.canvas.json`
  - **Project** → `get_spark_home()/workspace/<slug>/<name>.canvas.json` — stored as a
    **visible file in the project tree** (not hidden), so it appears in the **Files tab**.
  - **Many named canvases per project.**
  A canvas is a JSON doc: `{ id, name, scope, nodes, edges, viewport, version, updatedAt }`.
- **Open-from-Files:** clicking a `*.canvas.json` file in the Files tab switches to the
  **Canvas tab** and opens that canvas (no inline editor), via the existing
  `globalNavigation` bus.

## Context (how the web UI + backend are wired)

**Frontend** — Vite + React + Tailwind at `src/spark_cli/web/`. Tabs are a hand-rolled
page switch in [App.tsx](src/spark_cli/web/src/App.tsx), not a router:
- `NAV_ITEMS` (line ~28) `{ id, labelKey, icon }`; `PageId` derived from it.
- `PAGE_COMPONENTS` map → page component; `FULL_WIDTH_PAGES` set for edge-to-edge pages.
- Active page persisted to `localStorage["spark-active-page"]`; icons from `lucide-react`.
- Labels in [en.ts](src/spark_cli/web/src/i18n/en.ts) (nav block + per-page section).
- API client: [api.ts](src/spark_cli/web/src/lib/api.ts). Model page to copy:
  [KanbanPage.tsx](src/spark_cli/web/src/pages/KanbanPage.tsx).

**Backend** — FastAPI. Workspace/project routes in
[workspace_routes.py](src/spark_cli/workspace_routes.py) (`router`, mounted by
[web_server.py](src/spark_cli/web_server.py)):
- Projects are real folders: `_workspace_root() = get_spark_home()/"workspace"`,
  `_project_dir(slug)`, with `_safe_path()` for traversal safety — **reuse these**.
- Per-project conversations API already exists (`/projects/{slug}/conversations`) — the
  Chat node builds on the same agent backend.

## Tasks

### 1. Dependency + tab scaffold
- [x] Add `@xyflow/react` to `src/spark_cli/web/package.json`; install.
- [x] Create `src/spark_cli/web/src/pages/CanvasPage.tsx` (placeholder, full-screen).
- [x] Register in [App.tsx](src/spark_cli/web/src/App.tsx): import; add to `NAV_ITEMS`
      (icon e.g. `Workflow`); add to `PAGE_COMPONENTS`; add `"canvas"` to `FULL_WIDTH_PAGES`.
- [x] Add `canvas` nav label + `canvas: { ... }` page section in
      [en.ts](src/spark_cli/web/src/i18n/en.ts) (mirror other locales).
- [x] Verify tab appears, switches, persists.

### 2. Backend: canvas persistence API
- [x] New routes (extend [workspace_routes.py](src/spark_cli/workspace_routes.py) or a new
      `canvas_routes.py` mounted in [web_server.py](src/spark_cli/web_server.py)):
  - `GET  /api/canvases` — list global + per-project canvases (id, name, scope, slug, updatedAt).
  - `GET  /api/canvases/{scope}/{id}` — load one (`scope` = `global` | `project:<slug>`).
  - `PUT  /api/canvases/{scope}/{id}` — create/update (write JSON doc).
  - `DELETE /api/canvases/{scope}/{id}` — delete.
- [x] Global dir helper `get_spark_home()/"canvases"`; project canvases write directly into
      `_project_dir(slug)` as `<name>.canvas.json` (visible in the file tree). Use
      `_safe_path`-style guards. Create dirs lazily (do **not** mkdir SPARK_HOME root —
      follow profile-safety rules in CLAUDE.md).
- [x] Pydantic models for the canvas doc; validate `scope`/`slug`.
- [x] Tests in `tests/` using the `_isolate_spark_home` fixture (no writes to real `~/.spark`).

### 3. Frontend API client + save/load UX + Files-tab integration
- [x] Add canvas methods to [api.ts](src/spark_cli/web/src/lib/api.ts) (list/load/save/delete).
- [x] Canvas toolbar: name field, **Save** with scope picker (Global vs a project from
      `api.listProjects()`), **Open** (canvas browser), **New**, **Delete**.
- [x] Debounced autosave once a canvas has a name+scope; restore last-open canvas via
      `localStorage["spark-canvas-last"]`.
- [x] Extend `GlobalNavTarget` in
      [globalNavigation.ts](src/spark_cli/web/src/lib/globalNavigation.ts) with a
      `{ type: "canvas"; scope; id }` variant.
- [x] In [FilesPage.tsx](src/spark_cli/web/src/pages/FilesPage.tsx): detect `*.canvas.json`
      on file select → instead of the inline editor, call `setGlobalNavTarget({type:"canvas",
      scope:"project:<slug>", id})`. (Optional: distinct canvas icon for these files.)
- [x] In [App.tsx](src/spark_cli/web/src/App.tsx): listen for the canvas nav target, switch
      `page` to `"canvas"`, and pass the target into `CanvasPage` to auto-open it (mirror how
      other `globalNavigation` targets are consumed via `takeGlobalNavTarget`).

### 4. Infinite canvas surface
- [x] Render React Flow filling the page: pan, zoom, minimap, grid background, fit-view, controls.
- [x] Typed `nodes`/`edges` state ↔ the persisted canvas doc.

### 5. Tool palette + drag-to-place
- [x] Left/floating palette of draggable node types; HTML5 dnd `onDrop` → create node at cursor.
- [x] Node catalog (v1):
  - **Note** (sticky/text, Excalidraw-style)
  - **Chat node** — message thread bound to the agent API (model selector; streams replies)
  - **Agent node** — prompt + model, input/output ports
  - **Tool node** — wraps a Spark tool from the registry
  - **Input / Output** nodes
- [x] Drag-reposition, multi-select, delete, duplicate.

### 6. Node graph + chat + run
- [x] Custom node components with typed handles; edge connect + validation.
- [x] **Chat node**: talk to the agent backend but keep the thread **canvas-local** — persist
      messages inside the canvas JSON doc; do **not** create a session that appears in the
      Chat tab. For a **project-scoped** canvas, default the chat node's working context to
      that project's folder (pass the project slug); global canvases use the default context.
- [x] Right-drawer config panel per node (prompt, model, tool args).
- [x] **Run** (v1-minimal): execute an Agent/Tool node via `api.ts`, surface output back into
      the node; topological order for connected graphs. (Full graph orchestration can follow.)

### 7. Polish + theming
- [x] Match Spark skin/theme tokens (dark/light); reuse `components/ui/*`.
- [x] Delete-key removes nodes/edges; fit-view + zoom via React Flow Controls; empty-state palette hint.
      (Duplicate shortcut and a numeric zoom-% readout deferred — Controls cover zoom for now.)

### 8. Verify + ship
- [x] Build the web app in `src/spark_cli/web/`; verify in browser preview: tab loads,
      drag-place works, edges connect, chat node responds, save→global & save→project both
      round-trip after reload.
- [x] Web lint/typecheck; backend `pytest` for the new canvas routes.
- [x] Rebuild bundled `web_dist` if required by the build pipeline.
- [x] Feature branch `canvas-tab`; commit + PR (per repo workflow).

## Resolved
- Storage: `~/.spark/canvases/` (global) and visible `*.canvas.json` files in each
  `~/.spark/workspace/<slug>/` (project). Many named canvases per project.
- Opening a `*.canvas.json` from the Files tab switches to the Canvas tab and opens it.
- Chat nodes are canvas-local; they never appear in the Chat tab.

- Project-scoped Chat nodes default their working context to the project's folder (slug);
  global-canvas chat nodes use the default context.
