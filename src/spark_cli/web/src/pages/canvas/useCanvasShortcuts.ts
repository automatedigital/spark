import { useCallback, useEffect, useRef, type Dispatch, type SetStateAction } from "react";
import { useReactFlow, type Node } from "@xyflow/react";
import { newNodeId } from "./model";

interface UseCanvasShortcutsArgs {
  selectedIds: string[];
  setNodes: Dispatch<SetStateAction<Node[]>>;
  setSelectedIds: Dispatch<SetStateAction<string[]>>;
  remember: () => void;
  undo: () => void;
  redo: () => void;
}

export function useCanvasShortcuts({ selectedIds, setNodes, setSelectedIds, remember, undo, redo }: UseCanvasShortcutsArgs) {
  const rf = useReactFlow();
  const clipboardRef = useRef<Node[]>([]);

  const copySelection = useCallback(() => {
    const ids = new Set(selectedIds);
    clipboardRef.current = rf.getNodes().filter((n) => ids.has(n.id));
  }, [rf, selectedIds]);

  const pasteSelection = useCallback(() => {
    if (!clipboardRef.current.length) return;
    remember();
    const pasted = clipboardRef.current.map((n) => {
      const id = newNodeId();
      return {
        ...n,
        id,
        selected: true,
        position: { x: n.position.x + 32, y: n.position.y + 32 },
        data: { ...n.data, result: null },
      };
    });
    setNodes((nds) => nds.map((n) => ({ ...n, selected: false })).concat(pasted));
    setSelectedIds(pasted.map((n) => n.id));
  }, [remember, setNodes, setSelectedIds]);

  const duplicateSelection = useCallback(() => {
    copySelection();
    pasteSelection();
  }, [copySelection, pasteSelection]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;
      if (!mod) return;
      if (e.key === "c") {
        copySelection();
      } else if (e.key === "v") {
        e.preventDefault();
        pasteSelection();
      } else if (e.key === "d") {
        e.preventDefault();
        duplicateSelection();
      } else if (e.key === "z" && e.shiftKey) {
        e.preventDefault();
        redo();
      } else if (e.key === "z") {
        e.preventDefault();
        undo();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [copySelection, pasteSelection, duplicateSelection, undo, redo]);

  return { copySelection, pasteSelection, duplicateSelection };
}
