import { useEffect, useMemo, useState } from "react";
import { api, type WorkflowNodeType } from "@/lib/api";

export function useNodeCatalog(search: string) {
  const [nodeTypes, setNodeTypes] = useState<WorkflowNodeType[]>([]);

  useEffect(() => {
    api.getWorkflowNodeTypes().then((r) => setNodeTypes(r.nodeTypes)).catch(() => {});
  }, []);

  const grouped = useMemo(() => {
    const q = search.toLowerCase();
    const filtered = nodeTypes.filter(
      (t) => !q || t.label.toLowerCase().includes(q) || (t.toolset ?? "").toLowerCase().includes(q),
    );
    const groups: Record<string, WorkflowNodeType[]> = {};
    for (const t of filtered) {
      const g = t.category === "action" ? `tools · ${t.toolset ?? "core"}` : t.category;
      (groups[g] ??= []).push(t);
    }
    return Object.entries(groups).sort((a, b) => a[0].localeCompare(b[0]));
  }, [nodeTypes, search]);

  return { nodeTypes, grouped };
}
