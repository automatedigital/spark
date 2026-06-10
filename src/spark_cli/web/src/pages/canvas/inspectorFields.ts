import type { JsonSchemaProp } from "@/lib/api";
import type { CanvasNodeData } from "./types";

export type InspectorFieldKind = "text" | "textarea" | "json" | "number" | "boolean" | "select";

export interface InspectorField {
  key: string;
  kind: InspectorFieldKind;
  options?: string[];
}

const explicitFields: Record<string, InspectorField[]> = {
  agent: [
    { key: "model", kind: "text" },
    { key: "maxIterations", kind: "number" },
    { key: "toolsets", kind: "text" },
    { key: "skipMemory", kind: "boolean" },
    { key: "prompt", kind: "textarea" },
  ],
  "workflow.subworkflow": [
    { key: "scope", kind: "text" },
    { key: "slug", kind: "text" },
    { key: "canvasId", kind: "text" },
  ],
  "memory.context": [
    { key: "mode", kind: "text" },
    { key: "key", kind: "text" },
    { key: "value", kind: "textarea" },
  ],
  "trigger.manual": [{ key: "payload", kind: "json" }],
  "trigger.webhook": [{ key: "secret", kind: "text" }],
  "trigger.schedule": [{ key: "schedule", kind: "text" }],
  "trigger.filewatch": [{ key: "path", kind: "text" }],
  "data.set": [{ key: "fields", kind: "json" }],
  "control.if": [
    { key: "field", kind: "text" },
    { key: "equals", kind: "text" },
  ],
  "control.switch": [
    { key: "field", kind: "text" },
    { key: "case", kind: "text" },
    { key: "cases", kind: "json" },
  ],
  "control.loop": [
    { key: "count", kind: "number" },
    { key: "batchSize", kind: "number" },
  ],
  "action.code": [{ key: "code", kind: "textarea" }],
  "action.http": [
    { key: "method", kind: "text" },
    { key: "url", kind: "text" },
    { key: "headers", kind: "json" },
    { key: "body", kind: "textarea" },
    { key: "timeout", kind: "number" },
  ],
  "action.wait": [{ key: "seconds", kind: "number" }],
  "display.render": [
    { key: "format", kind: "select", options: ["text", "markdown"] },
    { key: "content", kind: "textarea" },
  ],
  "display.iframe": [
    { key: "url", kind: "text" },
    { key: "allowDomains", kind: "text" },
    { key: "blockDomains", kind: "text" },
  ],
  "io.file_source": [
    { key: "source", kind: "text" },
    { key: "slug", kind: "text" },
    { key: "path", kind: "text" },
    { key: "mode", kind: "text" },
  ],
  "io.write_file": [
    { key: "source", kind: "text" },
    { key: "slug", kind: "text" },
    { key: "path", kind: "text" },
    { key: "content", kind: "textarea" },
  ],
  "io.read_table": [
    { key: "source", kind: "text" },
    { key: "slug", kind: "text" },
    { key: "path", kind: "text" },
  ],
  "io.write_table": [
    { key: "source", kind: "text" },
    { key: "slug", kind: "text" },
    { key: "path", kind: "text" },
    { key: "rows", kind: "json" },
  ],
};

function fieldFromSchema(key: string, prop: JsonSchemaProp): InspectorField {
  if (prop.enum?.length) return { key, kind: "select", options: prop.enum.map(String) };
  if (prop.type === "number" || prop.type === "integer") return { key, kind: "number" };
  if (prop.type === "boolean") return { key, kind: "boolean" };
  if (prop.type === "object" || prop.type === "array") return { key, kind: "json" };
  return { key, kind: "text" };
}

export function fieldsFor(data: CanvasNodeData): InspectorField[] {
  const explicit = explicitFields[data.nodeType];
  if (explicit) return explicit;
  const props = data.schema?.properties ?? {};
  if (Object.keys(props).length) {
    return Object.entries(props).map(([key, prop]) => fieldFromSchema(key, prop));
  }
  return Object.keys(data.params ?? {}).map((key) => ({
    key,
    kind: key === "text" ? "textarea" : "text",
  }));
}
