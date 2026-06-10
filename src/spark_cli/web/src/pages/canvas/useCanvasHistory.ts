import { useCallback, useRef, useState } from "react";
import { useReactFlow, type Edge, type Node } from "@xyflow/react";

interface GraphSnapshot {
  nodes: Node[];
  edges: Edge[];
}

export function useCanvasHistory(
  setNodes: (nodes: Node[]) => void,
  setEdges: (edges: Edge[]) => void,
  limit = 50,
) {
  const rf = useReactFlow();
  const undoRef = useRef<GraphSnapshot[]>([]);
  const redoRef = useRef<GraphSnapshot[]>([]);
  const [version, setVersion] = useState(0);

  const bump = useCallback(() => setVersion((v) => v + 1), []);

  const remember = useCallback(() => {
    undoRef.current.push({ nodes: rf.getNodes(), edges: rf.getEdges() });
    if (undoRef.current.length > limit) undoRef.current.shift();
    redoRef.current = [];
    bump();
  }, [bump, limit, rf]);

  const undo = useCallback(() => {
    const prev = undoRef.current.pop();
    if (!prev) return;
    redoRef.current.push({ nodes: rf.getNodes(), edges: rf.getEdges() });
    setNodes(prev.nodes);
    setEdges(prev.edges);
    bump();
  }, [bump, rf, setEdges, setNodes]);

  const redo = useCallback(() => {
    const next = redoRef.current.pop();
    if (!next) return;
    undoRef.current.push({ nodes: rf.getNodes(), edges: rf.getEdges() });
    setNodes(next.nodes);
    setEdges(next.edges);
    bump();
  }, [bump, rf, setEdges, setNodes]);

  return {
    remember,
    undo,
    redo,
    canUndo: undoRef.current.length > 0,
    canRedo: redoRef.current.length > 0,
    version,
  };
}
