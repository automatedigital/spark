# Plan: Improve the Canvas Tab

## Goal

Make the Canvas tab easier to evolve, safer to persist, and more reliable for everyday workflow authoring.

## Current Shape

- Frontend entrypoint: `src/spark_cli/web/src/pages/CanvasPage.tsx`
- Node renderers: `src/spark_cli/web/src/pages/canvas/render.tsx`
- Node data/defaults: `src/spark_cli/web/src/pages/canvas/types.ts`
- Inspector: `src/spark_cli/web/src/pages/canvas/Inspector.tsx`
- Frontend API types/client: `src/spark_cli/web/src/lib/api.ts`
- Backend storage routes: `src/spark_cli/canvas_routes.py`
- Agent-facing canvas tool: `src/tools/canvas_tool.py`
- Backend tests: `tests/spark_cli/test_canvas_routes.py`, `tests/tools/test_canvas_tool.py`

## Task List

### Phase 1: Extract State And Serialization

- [ ] Create `src/spark_cli/web/src/pages/canvas/model.ts`.
- [ ] Move `newNodeId` into `model.ts`.
- [ ] Move `makeCanvasNode` into `model.ts`.
- [ ] Move canvas id sanitization from `toEngineDoc` into a named `sanitizeCanvasId` helper.
- [ ] Add a `canvasIdentityKey(scope, slug, id)` helper.
- [ ] Move save serialization from `toEngineDoc` into `toCanvasDoc`.
- [ ] Move load deserialization from `loadCanvas` into `fromCanvasDoc`.
- [ ] Preserve legacy reads of node dimensions from `data.width` and `data.height` in `fromCanvasDoc`.
- [ ] Add unit tests for `sanitizeCanvasId`.
- [ ] Add unit tests for `toCanvasDoc`.
- [ ] Add unit tests for `fromCanvasDoc`.
- [ ] Replace inline serialization/deserialization in `CanvasPage.tsx` with `model.ts` helpers.
- [ ] Create `src/spark_cli/web/src/pages/canvas/useNodeCatalog.ts`.
- [ ] Move node-type fetching into `useNodeCatalog`.
- [ ] Move node search/grouping into `useNodeCatalog`.
- [ ] Replace inline node catalog state in `CanvasPage.tsx` with `useNodeCatalog`.
- [ ] Create `src/spark_cli/web/src/pages/canvas/useCanvasShortcuts.ts`.
- [ ] Move copy selection logic into `useCanvasShortcuts`.
- [ ] Move paste selection logic into `useCanvasShortcuts`.
- [ ] Move duplicate selection logic into `useCanvasShortcuts`.
- [ ] Move keyboard shortcut listener into `useCanvasShortcuts`.
- [ ] Replace inline shortcut handling in `CanvasPage.tsx` with `useCanvasShortcuts`.
- [ ] Confirm `CanvasPage.tsx` is meaningfully smaller after extraction.

### Phase 2: Fix Persistence Semantics

- [ ] Save the actual React Flow viewport with `rf.getViewport()`.
- [ ] Include viewport in `toCanvasDoc`.
- [ ] Restore viewport after `fromCanvasDoc` load.
- [ ] Store node `width` at top level in saved canvas nodes.
- [ ] Store node `height` at top level in saved canvas nodes.
- [ ] Stop writing node dimensions only inside `data`.
- [ ] Keep backward compatibility for existing canvas files with dimensions in `data`.
- [ ] Add backend support for a canvas `revision` field.
- [ ] Include `revision` in `CanvasDoc` responses.
- [ ] Include `revision` in canvas list summaries.
- [ ] Add optional `expectedRevision` handling for save requests.
- [ ] Return a conflict response when `expectedRevision` is stale.
- [ ] Track last loaded revision in the frontend.
- [ ] Send `expectedRevision` from frontend saves.
- [ ] Block autosave when a revision conflict is detected.
- [ ] Show a compact conflict state in the Canvas toolbar.
- [ ] Add a reload-remote action for conflicts.
- [ ] Add a save-over-remote action for conflicts.
- [ ] Add tests for viewport round-trip.
- [ ] Add tests for node dimension round-trip.
- [ ] Add tests for stale revision rejection.

### Phase 3: Make Undo, Dirty State, And Autosave Predictable

- [ ] Create `src/spark_cli/web/src/pages/canvas/useCanvasHistory.ts`.
- [ ] Move undo stack state into `useCanvasHistory`.
- [ ] Move redo stack state into `useCanvasHistory`.
- [ ] Add `canUndo` from `useCanvasHistory`.
- [ ] Add `canRedo` from `useCanvasHistory`.
- [ ] Record history before node creation.
- [ ] Record history before edge creation.
- [ ] Record history before node deletion.
- [ ] Record history before edge deletion.
- [ ] Record history before paste.
- [ ] Record history before duplicate.
- [ ] Record history before inspector param edits.
- [ ] Record node drag as one history entry per drag gesture.
- [ ] Cap history length.
- [ ] Clear redo history after new edits.
- [ ] Disable Undo button when `canUndo` is false.
- [ ] Disable Redo button when `canRedo` is false.
- [ ] Add a document dirty state separate from save state.
- [ ] Mark document dirty after graph edits.
- [ ] Mark document clean after successful save.
- [ ] Prevent autosave for unsaved new canvases.
- [ ] Prevent autosave while a workflow run is active.
- [ ] Prevent autosave during conflict state.
- [ ] Add dirty confirm before New.
- [ ] Add dirty confirm before Open.
- [ ] Add dirty confirm before Delete.
- [ ] Verify drag, delete, connect, param edit, paste, and duplicate can all be undone.

### Phase 4: Improve Node Configuration

- [ ] Create a field model helper for inspector params.
- [ ] Generate inspector fields from JSON schema when available.
- [ ] Keep explicit field overrides for Canvas-specific node types.
- [ ] Render string params with text inputs.
- [ ] Render number params with number inputs.
- [ ] Render integer params with number inputs.
- [ ] Render boolean params with checkboxes or switches.
- [ ] Render enum params with selects.
- [ ] Render object params with JSON textareas.
- [ ] Render array params with JSON textareas.
- [ ] Parse number inputs back to numbers.
- [ ] Parse boolean inputs back to booleans.
- [ ] Parse object JSON back to objects.
- [ ] Parse array JSON back to arrays.
- [ ] Show inline validation for invalid JSON.
- [ ] Prevent invalid JSON from silently overwriting the prior valid value.
- [ ] Improve mapped-value display in the inspector.
- [ ] Add a clear-mapping action.
- [ ] Handle upstream output with no sample keys.
- [ ] Add tests for typed param parsing.
- [ ] Add tests for invalid JSON handling.

### Phase 5: Separate Execution State From Document State

- [ ] Create `src/spark_cli/web/src/pages/canvas/useCanvasRun.ts`.
- [ ] Move `runningIds` into `useCanvasRun`.
- [ ] Move `runningAll` into `useCanvasRun`.
- [ ] Move `activeRunId` into `useCanvasRun`.
- [ ] Move `lastRunStatus` into `useCanvasRun`.
- [ ] Move single-node run logic into `useCanvasRun`.
- [ ] Move full workflow run logic into `useCanvasRun`.
- [ ] Move run cancellation logic into `useCanvasRun`.
- [ ] Guard stream event handling by current canvas identity.
- [ ] Close any active EventSource when loading a different canvas.
- [ ] Ensure run results do not mark the graph dirty.
- [ ] Ensure loading execution history does not mark the graph dirty.
- [ ] Clear stale running node ids after run completion.
- [ ] Clear stale running node ids after run cancellation.
- [ ] Improve execution history filtering by exact canvas identity.
- [ ] Show execution duration in the history panel.
- [ ] Show execution errors in the history panel.

### Phase 6: Refine Canvas UX

- [ ] Split toolbar markup into a `CanvasToolbar` component.
- [ ] Group document controls together in the toolbar.
- [ ] Group run controls together in the toolbar.
- [ ] Group edit controls together in the toolbar.
- [ ] Group panel controls together in the toolbar.
- [ ] Keep destructive delete visually separated.
- [ ] Disable Duplicate when nothing is selected.
- [ ] Disable Delete when there is no current saved canvas.
- [ ] Disable Run when the graph is empty.
- [ ] Add a first-time empty canvas state.
- [ ] Create an `OpenCanvasPanel` component.
- [ ] Add search to the open canvas panel.
- [ ] Sort saved canvases by updated time.
- [ ] Show global/project badges in the open canvas panel.
- [ ] Create a `NodeBrowserPanel` component.
- [ ] Add category filters to the node browser.
- [ ] Add recent node types to the node browser.
- [ ] Add loading state for node types.
- [ ] Add error state for node type loading failure.
- [ ] Add canvas-level error banner for failed load.
- [ ] Add canvas-level error banner for failed save.
- [ ] Add canvas-level error banner for failed run.

### Phase 7: Backend Hardening

- [ ] Validate node ids are unique in `canvas_routes.py`.
- [ ] Validate edges reference existing source nodes.
- [ ] Validate edges reference existing target nodes.
- [ ] Validate request body scope matches URL scope.
- [ ] Validate request body slug matches URL slug.
- [ ] Add a maximum node count guard.
- [ ] Add a maximum edge count guard.
- [ ] Add a maximum serialized canvas size guard.
- [ ] Return 400 with actionable messages for invalid docs.
- [ ] Include corrupt canvas entries in list responses with an `error` field.
- [ ] Add tests for duplicate node ids.
- [ ] Add tests for invalid edge references.
- [ ] Add tests for scope mismatch.
- [ ] Add tests for slug mismatch.
- [ ] Add tests for corrupt file listing.
- [ ] Confirm all canvas storage paths use `get_spark_home()`.

### Phase 8: Verify

- [ ] Run backend canvas route tests.
- [ ] Run canvas tool tests.
- [ ] Run frontend lint.
- [ ] Run frontend build.
- [ ] Manually create a global canvas.
- [ ] Manually create a project canvas.
- [ ] Manually drag a file into a global canvas.
- [ ] Manually drag a file into a project canvas.
- [ ] Manually resize a media node and verify it survives reload.
- [ ] Manually resize an iframe node and verify it survives reload.
- [ ] Manually pan/zoom and verify viewport survives reload.
- [ ] Manually trigger an agent `canvas` tool update while local board is dirty.
- [ ] Manually run a graph.
- [ ] Manually cancel a graph run.
- [ ] Manually load an execution result.

Verification commands:

```bash
source venv/bin/activate
python -m pytest tests/spark_cli/test_canvas_routes.py tests/tools/test_canvas_tool.py -q
cd src/spark_cli/web && npm run lint && npm run build
```

## Open Questions

- [ ] Decide whether Canvas results should ever persist in the canvas document.
- [ ] Decide whether agent `canvas` tool updates should support patch/append operations.
- [ ] Decide whether project canvas JSON files should remain directly editable in the Files tab.
- [ ] Decide whether unsaved canvases should be recoverable across reloads via local draft storage.
- [ ] Decide whether scheduled/webhook triggers need explicit registration outside normal save.
