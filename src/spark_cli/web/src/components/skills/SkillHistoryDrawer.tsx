import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { SkillHistory } from "@/lib/api_skill";
import { Button } from "@/components/ui/button";

export function SkillHistoryDrawer({ skillId, onClose }: { skillId: string; onClose: () => void }) {
  const [history, setHistory] = useState<SkillHistory | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    api.getSkillHistory(skillId).then((value) => { if (alive) setHistory(value); })
      .catch(() => { if (alive) setError("History could not be loaded. Close and reopen to retry."); });
    return () => { alive = false; };
  }, [skillId]);
  return <section role="dialog" aria-modal="true" aria-label="Dashboard skill edit history" className="absolute inset-y-0 right-0 z-40 flex w-full max-w-2xl flex-col border-l border-border bg-card shadow-2xl">
    <header className="flex items-center justify-between border-b border-border p-4">
      <h2 className="text-sm font-semibold">Dashboard edit history</h2>
      <Button variant="ghost" onClick={onClose} autoFocus>Close history</Button>
    </header>
    <div className="min-h-0 flex-1 overflow-y-auto p-4 text-xs">
      <p>Dashboard SKILL.md edits only. External editors, agent edits and supporting files are excluded.</p>
      <p className="my-3 text-muted-foreground">Read-only. The latest {history?.retention ?? 20} edits across this profile are retained. Times are informational; entries are ordered by dashboard save sequence.</p>
      {error ? <p role="alert">{error}</p> : !history ? <p role="status">Loading history…</p> : history.entries.length === 0 ? <p>No retained dashboard edits for this skill.</p> : history.entries.map((entry) => <details key={entry.id} className="mb-3 rounded border border-border p-3">
        <summary className="cursor-pointer">Saved {new Date(entry.saved_at).toLocaleString()} · {entry.id.slice(0, 8)}</summary>
        <h3 className="my-2 font-semibold">Before</h3>
        <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded bg-background p-3">{entry.before}</pre>
        <h3 className="my-2 font-semibold">After</h3>
        <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded bg-background p-3">{entry.after}</pre>
      </details>)}
    </div>
  </section>;
}
