# Canvas model — what the agent can draw/control

The Canvas is a React Flow node-graph stored as a JSON document
(`canvas_routes.py`, `CanvasDoc`): `{id, name, scope, slug, nodes[], edges[],
viewport, version}`. Each node is a React Flow node `{id, type, position{x,y},
data}` where `data` is `CanvasNodeData` (`{nodeType, label, params, ...}`).

## Render node types (`render.tsx` → `renderNodeTypes`)

| React Flow `type` | engine `nodeType` | renders | params |
|-------------------|-------------------|---------|--------|
| `workflow` | tool/agent/control/trigger/io | a workflow step card | per node schema |
| `iframe` | `display.iframe` | sandboxed iframe | `{url, allowDomains, blockDomains}` |
| `preview` | `display.preview` | live preview frame | `{url}` |
| `media` | `display.media` | image/audio/video | `{url}` |
| `note` | `display.note` | freeform sticky note | `{text}` |
| `render` | `display.render` | **markdown or text** | `{format: "markdown"\|"text", content}` |

`renderTypeFor(nodeType)` maps engine type → render key.

## Agent-drawable surface

The **`display.*` nodes are the A2UI surface**: the agent composes a board of
display widgets. `display.render` (markdown) is the most expressive — markdown
gives headings, lists, **tables**, code, and links without new components.
`display.note`, `display.media`, `display.iframe`, `display.preview` cover
sticky notes, media, and embedded/live pages.

The agent pushes these via the **`canvas` tool** (`src/tools/canvas_tool.py`),
which writes a canvas doc through the same storage the UI reads and emits a
`canvas.updated` event so an open `CanvasPage` reloads live.

## Schema the agent emits (widgets)

The tool accepts a `widgets` list; each is auto-laid-out vertically and mapped
to a display node:

- `{type: "markdown", content}` → `display.render` (markdown) — use markdown
  tables for tabular data, fenced blocks for code/charts-as-text.
- `{type: "text", content}` → `display.render` (text/pre).
- `{type: "note", text}` → `display.note`.
- `{type: "media", url}` → `display.media`.
- `{type: "iframe", url}` / `{type: "preview", url}` → embedded/live page.
</content>
