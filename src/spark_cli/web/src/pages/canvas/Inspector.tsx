import { useState } from "react";
import type { Node, Edge } from "@xyflow/react";
import { X, Link2, Pencil } from "lucide-react";
import type { CanvasNodeData } from "./types";
import { fieldsFor, type InspectorField } from "./inspectorFields";

interface InspectorProps {
  node: Node;
  nodes: Node[];
  edges: Edge[];
  onClose: () => void;
  onParam: (key: string, value: unknown) => void;
  onRun: () => void;
  running: boolean;
}

/** Upstream nodes (direct sources) available for field-mapping. */
function upstreamSources(nodeId: string, nodes: Node[], edges: Edge[]) {
  const ids = edges.filter((e) => e.target === nodeId).map((e) => e.source);
  return nodes.filter((n) => ids.includes(n.id));
}

export default function Inspector({ node, nodes, edges, onClose, onParam, onRun, running }: InspectorProps) {
  const data = node.data as CanvasNodeData;
  const [tab, setTab] = useState<"params" | "input" | "output">("params");
  const [jsonDrafts, setJsonDrafts] = useState<Record<string, string>>({});
  const [jsonErrors, setJsonErrors] = useState<Record<string, string>>({});
  const sources = upstreamSources(node.id, nodes, edges);
  const fields = fieldsFor(data);
  const executable = data.category !== "display";

  const outputItems = data.result?.items ?? [];
  const inputItems = sources.flatMap((s) => (s.data as CanvasNodeData).result?.items ?? []);

  const isMapped = (v: unknown) => typeof v === "object" && v !== null && "__map" in (v as object);

  const setMapping = (key: string, ref: string) => {
    if (!ref) {
      onParam(key, "");
      return;
    }
    const [nodeId, ...rest] = ref.split("::");
    onParam(key, { __map: { node: nodeId, field: rest.join("::") } });
  };

  const clearMapping = (key: string) => onParam(key, "");

  const jsonValue = (key: string, val: unknown) => {
    const draft = jsonDrafts[`${node.id}:${key}`];
    if (draft !== undefined) return draft;
    return typeof val === "string" ? val : val == null ? "" : JSON.stringify(val, null, 2);
  };

  const setJsonValue = (key: string, raw: string) => {
    const draftKey = `${node.id}:${key}`;
    setJsonDrafts((prev) => ({ ...prev, [draftKey]: raw }));
    if (!raw.trim()) {
      setJsonErrors((prev) => ({ ...prev, [draftKey]: "" }));
      onParam(key, null);
      return;
    }
    try {
      const parsed = JSON.parse(raw);
      setJsonErrors((prev) => ({ ...prev, [draftKey]: "" }));
      onParam(key, parsed);
    } catch {
      setJsonErrors((prev) => ({ ...prev, [draftKey]: "Invalid JSON; last valid value is still saved." }));
    }
  };

  const renderEditor = (field: InspectorField, val: unknown) => {
    if (field.kind === "textarea") {
      return (
        <textarea
          value={typeof val === "string" ? val : val == null ? "" : JSON.stringify(val, null, 2)}
          onChange={(e) => onParam(field.key, e.target.value)}
          rows={3}
          className="rounded-sm border border-border bg-background/60 p-2 font-mono text-[11px] outline-none focus:border-primary"
        />
      );
    }
    if (field.kind === "json") {
      const draftKey = `${node.id}:${field.key}`;
      return (
        <>
          <textarea
            value={jsonValue(field.key, val)}
            onChange={(e) => setJsonValue(field.key, e.target.value)}
            rows={4}
            className="rounded-sm border border-border bg-background/60 p-2 font-mono text-[11px] outline-none focus:border-primary"
          />
          {jsonErrors[draftKey] && <p className="text-[10px] text-destructive">{jsonErrors[draftKey]}</p>}
        </>
      );
    }
    if (field.kind === "number") {
      return (
        <input
          type="number"
          value={typeof val === "number" ? val : val == null ? "" : Number(val)}
          onChange={(e) => onParam(field.key, e.target.value === "" ? null : Number(e.target.value))}
          className="h-7 rounded-sm border border-border bg-background/60 px-2 text-[11px] outline-none focus:border-primary"
        />
      );
    }
    if (field.kind === "boolean") {
      return (
        <label className="flex h-7 items-center gap-2 text-[11px] text-foreground">
          <input
            type="checkbox"
            checked={Boolean(val)}
            onChange={(e) => onParam(field.key, e.target.checked)}
          />
          {val ? "true" : "false"}
        </label>
      );
    }
    if (field.kind === "select") {
      return (
        <select
          value={typeof val === "string" ? val : val == null ? "" : String(val)}
          onChange={(e) => onParam(field.key, e.target.value)}
          className="h-7 rounded-sm border border-border bg-background/60 px-2 text-[11px] outline-none focus:border-primary"
        >
          {(field.options ?? []).map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      );
    }
    return (
      <input
        value={typeof val === "string" ? val : val == null ? "" : String(val)}
        onChange={(e) => onParam(field.key, e.target.value)}
        className="h-7 rounded-sm border border-border bg-background/60 px-2 text-[11px] outline-none focus:border-primary"
      />
    );
  };

  return (
    <aside className="flex w-80 shrink-0 flex-col border-l border-border bg-card/70 backdrop-blur-xl">
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        <span className="text-sm">{data.emoji ?? "⚙️"}</span>
        <span className="flex-1 truncate text-sm font-semibold text-foreground">{data.label}</span>
        <button type="button" onClick={onClose} className="text-muted-foreground hover:text-foreground">
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-border text-xs">
        {(["params", "input", "output"] as const).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={`flex-1 px-2 py-1.5 capitalize transition ${
              tab === t ? "border-b-2 border-primary text-foreground" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {tab === "params" && (
          <div className="flex flex-col gap-3">
            {data.description && <p className="text-[11px] text-muted-foreground">{data.description}</p>}
            {fields.length === 0 && <p className="text-xs text-muted-foreground">No parameters.</p>}
            {fields.map((field) => {
              const { key } = field;
              const val = data.params?.[key];
              const mapped = isMapped(val);
              return (
                <div key={key} className="flex flex-col gap-1">
                  <div className="flex items-center justify-between">
                    <label className="text-[11px] font-medium text-muted-foreground">{key}</label>
                    {sources.length > 0 && (
                      <span className="flex items-center gap-1 text-[10px] text-muted-foreground/60">
                        {mapped ? <Link2 className="h-3 w-3" /> : <Pencil className="h-3 w-3" />}
                        {mapped ? "mapped" : "literal"}
                        {mapped && (
                          <button type="button" onClick={() => clearMapping(key)} className="ml-1 underline hover:text-foreground">
                            clear
                          </button>
                        )}
                      </span>
                    )}
                  </div>
                  {/* Mapping picker */}
                  {sources.length > 0 && (
                    <select
                      value={mapped ? `${(val as { __map: { node: string; field: string } }).__map.node}::${(val as { __map: { node: string; field: string } }).__map.field}` : ""}
                      onChange={(e) => setMapping(key, e.target.value)}
                      className="h-7 rounded-sm border border-border bg-background/60 px-1.5 text-[11px] outline-none focus:border-primary"
                    >
                      <option value="">— literal value —</option>
                      {sources.map((s) => {
                        const sd = s.data as CanvasNodeData;
                        const sample = sd.result?.items?.[0]?.json ?? {};
                        const keys = Object.keys(sample);
                        return (keys.length ? keys : ["reply", "value", "result"]).map((fk) => (
                          <option key={`${s.id}-${fk}`} value={`${s.id}::${fk}`}>
                            {sd.label} → {fk}
                          </option>
                        ));
                      })}
                    </select>
                  )}
                  {/* Literal editor (hidden when mapped) */}
                  {!mapped && renderEditor(field, val)}
                </div>
              );
            })}
            {executable && (
              <button
                type="button"
                onClick={onRun}
                disabled={running}
                className="mt-1 rounded-sm bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition hover:bg-primary/90 disabled:opacity-50"
              >
                {running ? "Running…" : "Run this node"}
              </button>
            )}
          </div>
        )}

        {tab === "input" && <JsonView items={inputItems} empty="No upstream output yet — run upstream nodes." />}
        {tab === "output" && (
          <>
            {data.result?.error && <p className="mb-2 text-xs text-destructive">{data.result.error}</p>}
            <JsonView items={outputItems} empty="No output yet — run this node." />
          </>
        )}
      </div>
    </aside>
  );
}

function JsonView({ items, empty }: { items: Array<{ json: unknown }>; empty: string }) {
  if (!items.length) return <p className="text-xs text-muted-foreground">{empty}</p>;
  return (
    <pre className="overflow-x-auto whitespace-pre-wrap rounded-sm border border-border bg-background/50 p-2 font-mono text-[10px] text-foreground">
      {JSON.stringify(items.map((i) => i.json), null, 2)}
    </pre>
  );
}
