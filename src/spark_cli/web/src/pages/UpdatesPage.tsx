import { useCallback, useEffect, useState } from "react";
import { Play, RefreshCw } from "lucide-react";
import { api, sseUrl, type AdminActionMeta } from "@/lib/api";

function ShellButton({
  children,
  onClick,
  disabled = false,
  tone = "normal",
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
  tone?: "normal" | "danger" | "primary";
}) {
  const cls =
    tone === "danger"
      ? "border-red-600/50 text-red-300 hover:bg-red-950/30"
      : tone === "primary"
        ? "border-accent text-accent hover:bg-accent/10"
        : "border-border hover:bg-foreground/5";
  return (
    <button
      type="button"
      disabled={disabled}
      className={`px-2.5 py-1.5 text-xs uppercase tracking-wider border disabled:opacity-40 disabled:cursor-not-allowed ${cls}`}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

export default function UpdatesPage() {
  const [actions, setActions] = useState<AdminActionMeta[]>([]);
  const [runStatus, setRunStatus] = useState<string | null>(null);
  const [outputLines, setOutputLines] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const loadActions = useCallback(async () => {
    try {
      const resp = await api.getAdminActions();
      setActions(resp.actions.filter((a) => a.id.startsWith("update.")));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void loadActions();
  }, [loadActions]);

  const streamRun = (runId: string) => {
    setRunStatus("queued");
    setOutputLines([]);
    const es = new EventSource(sseUrl(`/api/admin/actions/runs/${encodeURIComponent(runId)}/stream`));
    es.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data) as { type?: string; status?: string; stream?: string; text?: string; run?: { status?: string } };
        if (data.status) setRunStatus(data.status);
        if (data.type === "output" && data.text != null) {
          setOutputLines((prev) => [...prev.slice(-300), `[${data.stream ?? "out"}] ${data.text}`]);
        }
        if (data.type === "done") {
          setRunStatus(data.run?.status ?? "done");
          es.close();
          void loadActions();
        }
      } catch {
        setOutputLines((prev) => [...prev.slice(-300), ev.data]);
      }
    };
    es.onerror = () => es.close();
  };

  const runAction = async (action: AdminActionMeta) => {
    const ok = !action.requires_confirmation || window.confirm(`Run ${action.label}?`);
    if (!ok) return;
    setError(null);
    try {
      const resp = await api.runAdminAction(action.id, {}, action.requires_confirmation);
      streamRun(resp.run_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="flex flex-col gap-4 min-h-[70vh]">
      {error && <div className="border border-red-900/60 text-red-300 p-3 text-sm">{error}</div>}

      <section className="border border-border bg-background/70 p-4">
        <div className="flex flex-wrap gap-2">
          {actions.map((action) => (
            <ShellButton
              key={action.id}
              tone={action.risk === "high" ? "danger" : "normal"}
              onClick={() => void runAction(action)}
            >
              <RefreshCw className="inline h-3.5 w-3.5 mr-1" />
              {action.label}
            </ShellButton>
          ))}
        </div>
      </section>

      {runStatus && (
        <section className="border border-border bg-background/90">
          <div className="flex items-center justify-between px-3 py-2 border-b border-border">
            <div className="text-xs uppercase tracking-wider flex items-center gap-2">
              <Play className="h-3.5 w-3.5" />
              Run output: {runStatus}
            </div>
            <button type="button" className="text-xs opacity-70" onClick={() => { setRunStatus(null); setOutputLines([]); }}>
              Close
            </button>
          </div>
          <pre className="p-3 text-xs max-h-80 overflow-y-auto whitespace-pre-wrap">
            {outputLines.join("\n") || "(waiting for output)"}
          </pre>
        </section>
      )}
    </div>
  );
}
