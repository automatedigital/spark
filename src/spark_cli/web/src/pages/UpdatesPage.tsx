import { useCallback, useEffect, useState } from "react";
import { Download, RefreshCw } from "lucide-react";
import { api, sseUrl, type AdminActionMeta } from "@/lib/api";
import { useUpdateModal } from "@/lib/UpdateModalContext";

export default function UpdatesPage() {
  const { openUpdateModal } = useUpdateModal();
  const [checkAction, setCheckAction] = useState<AdminActionMeta | null>(null);
  const [runStatus, setRunStatus] = useState<string | null>(null);
  const [outputLines, setOutputLines] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const loadActions = useCallback(async () => {
    try {
      const resp = await api.getAdminActions();
      const updateActions = resp.actions.filter((a) => a.id.startsWith("update."));
      setCheckAction(updateActions.find((a) => a.id === "update.check") ?? null);
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

  const runCheck = async () => {
    if (!checkAction) return;
    setError(null);
    try {
      const resp = await api.runAdminAction(checkAction.id, {}, false);
      streamRun(resp.run_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="flex flex-col gap-4 min-h-[70vh]">
      {error && <div className="border border-red-900/60 text-red-300 p-3 text-sm">{error}</div>}

      <section className="border border-border bg-background/70 p-4 flex flex-wrap gap-3 items-center">
        {checkAction && (
          <button
            type="button"
            className="px-2.5 py-1.5 text-xs uppercase tracking-wider border border-border hover:bg-foreground/5 disabled:opacity-40 disabled:cursor-not-allowed"
            onClick={() => void runCheck()}
          >
            <RefreshCw className="inline h-3.5 w-3.5 mr-1" />
            {checkAction.label}
          </button>
        )}
        <button
          type="button"
          className="px-2.5 py-1.5 text-xs uppercase tracking-wider border border-amber-500/50 text-amber-300 hover:bg-amber-500/10 flex items-center gap-1.5"
          onClick={openUpdateModal}
        >
          <Download className="h-3.5 w-3.5" />
          Run Update
        </button>
      </section>

      {runStatus && (
        <section className="border border-border bg-background/90">
          <div className="flex items-center justify-between px-3 py-2 border-b border-border">
            <div className="text-xs uppercase tracking-wider flex items-center gap-2">
              <RefreshCw className="h-3.5 w-3.5" />
              Check output: {runStatus}
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
