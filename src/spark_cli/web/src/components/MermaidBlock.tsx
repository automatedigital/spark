import { useEffect, useRef, useState } from "react";
import { mermaidSourceError } from "./mermaidSafety";

let renderQueue: Promise<unknown> = Promise.resolve();
let diagramId = 0;

// Mermaid's configuration is global. Serialize initialize/render together so
// concurrent chat blocks and theme changes cannot borrow each other's config.
function renderDiagram(source: string, dark: boolean, cancelled: () => boolean) {
  const job = renderQueue.catch(() => {}).then(async () => {
    if (cancelled()) return "";
    const [{ default: mermaid }, { default: DOMPurify }] = await Promise.all([
      import("mermaid"), import("dompurify"),
    ]);
    if (cancelled()) return "";
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: "strict",
      theme: dark ? "dark" : "default",
      htmlLabels: false,
      flowchart: { htmlLabels: false },
      maxTextSize: 8_000,
      maxEdges: 100,
      suppressErrorRendering: true,
    });
    // Keep Mermaid's temporary measurement nodes owned and always clean them up,
    // including parse failures or cancellation while an async layout is running.
    const host = document.createElement("div");
    host.style.cssText = "position:absolute;left:-100000px;visibility:hidden";
    document.body.append(host);
    try {
      const { svg } = await mermaid.render(`spark-diagram-${++diagramId}`, source, host);
      if (cancelled()) return "";
      if (svg.length > 500_000) throw new Error("Diagram output exceeds the size limit.");
      return DOMPurify.sanitize(svg, {
        USE_PROFILES: { svg: true, svgFilters: true },
        FORBID_TAGS: ["a", "foreignObject", "image", "use", "script"],
        FORBID_ATTR: ["href", "xlink:href", "tabindex"],
      });
    } finally {
      host.remove();
    }
  });
  renderQueue = job;
  return job;
}

export function MermaidBlock({ source }: { source: string }) {
  const [showSource, setShowSource] = useState(false);
  const [copyStatus, setCopyStatus] = useState("");
  const [result, setResult] = useState<{ source: string; dark: boolean; svg?: string; error?: string }>();
  const [dark, setDark] = useState(() => document.documentElement.dataset.webuiTheme !== "daylight");
  const output = useRef<HTMLDivElement>(null);
  const sourceError = mermaidSourceError(source);
  const current = result?.source === source && result.dark === dark ? result : undefined;
  const error = sourceError || current?.error;

  useEffect(() => {
    const observer = new MutationObserver(() => {
      setDark(document.documentElement.dataset.webuiTheme !== "daylight");
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-webui-theme"] });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (sourceError || showSource) return;
    let cancelled = false;
    void renderDiagram(source, dark, () => cancelled).then(
      (svg) => { if (!cancelled) setResult({ source, dark, svg }); },
      () => { if (!cancelled) setResult({ source, dark, error: "Could not render diagram. Check the Mermaid source." }); },
    );
    return () => { cancelled = true; };
  }, [source, dark, sourceError, showSource]);

  useEffect(() => {
    // Never call bindFunctions: diagrams are passive, with no click callbacks.
    if (output.current && current?.svg) output.current.innerHTML = current.svg;
  }, [current?.svg, showSource]);

  async function copySource() {
    try {
      await navigator.clipboard.writeText(source);
      setCopyStatus("Copied");
    } catch {
      setCopyStatus("Copy failed");
    }
  }

  return (
    <section aria-label="Mermaid diagram" className="min-w-0 overflow-hidden rounded-md border border-border bg-secondary/20">
      <div className="flex items-center gap-3 border-b border-border px-3 py-1.5 text-xs">
        <span className="mr-auto text-muted-foreground">mermaid</span>
        <button type="button" aria-pressed={showSource} onClick={() => setShowSource((value) => !value)}>{showSource ? "Diagram" : "Source"}</button>
        <button type="button" onClick={() => { void copySource(); }}>Copy source</button>
        <span role="status">{copyStatus}</span>
      </div>
      {error ? <p role="status" className="px-3 py-2 text-sm text-muted-foreground">{error}</p> : null}
      {showSource || error || !current?.svg ? (
        <>
          {!showSource && !error ? <p role="status" className="px-3 pt-2 text-xs text-muted-foreground">Rendering diagram…</p> : null}
          <pre className="max-h-96 overflow-auto whitespace-pre p-3 text-xs"><code>{source}</code></pre>
        </>
      ) : <div ref={output} role="img" aria-label="Rendered Mermaid diagram" className="max-h-[36rem] overflow-auto p-3" />}
    </section>
  );
}
