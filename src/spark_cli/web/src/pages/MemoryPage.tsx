import { useCallback, useEffect, useState } from "react";
import { Brain, Trash2, Plus, Loader2, Pencil, Check, X } from "lucide-react";
import { api } from "@/lib/api";
import type { MemoryTargetPayload } from "@/lib/api";
import { useEventBus } from "@/hooks/useEventBus";

const TARGETS: { id: string; title: string; hint: string }[] = [
  { id: "memory", title: "Memory", hint: "Facts the agent has learned about your work and projects" },
  { id: "user", title: "About you", hint: "Persona, preferences, and how you want the agent to behave" },
];

function TargetCard({ target, title, hint }: { target: string; title: string; hint: string }) {
  const [data, setData] = useState<MemoryTargetPayload | null>(null);
  const [adding, setAdding] = useState("");
  const [editIdx, setEditIdx] = useState<number | null>(null);
  const [editText, setEditText] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api.getMemory().then((r) => setData(r.targets[target] ?? null)).catch(() => {});
  }, [target]);

  useEffect(load, [load]);
  useEventBus((env) => {
    if (env.topic === "memory.updated") load();
  });

  const add = async () => {
    const content = adding.trim();
    if (!content) return;
    setBusy(true);
    try {
      setData(await api.addMemoryEntry(target, content));
      setAdding("");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (entry: string) => {
    setBusy(true);
    try {
      setData(await api.removeMemoryEntry(target, entry));
    } finally {
      setBusy(false);
    }
  };

  const saveEdit = async (oldEntry: string) => {
    const next = editText.trim();
    if (!next || next === oldEntry) {
      setEditIdx(null);
      return;
    }
    setBusy(true);
    try {
      setData(await api.replaceMemoryEntry(target, oldEntry, next));
      setEditIdx(null);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="mb-1 flex items-center gap-2">
        <Brain className="h-4 w-4 text-primary/70" />
        <h2 className="text-sm font-semibold text-foreground">{title}</h2>
        {data && (
          <span className="ml-auto text-[11px] tabular-nums text-muted-foreground/60">
            {data.entry_count} · {data.percent}%
          </span>
        )}
      </div>
      <p className="mb-3 text-xs text-muted-foreground/70">{hint}</p>

      <ul className="space-y-1.5">
        {(data?.entries ?? []).map((entry, idx) => (
          <li key={`${entry}-${idx}`} className="group flex items-start gap-2 rounded-md border border-border/50 bg-background px-2.5 py-1.5 text-sm">
            {editIdx === idx ? (
              <>
                <textarea
                  value={editText}
                  onChange={(e) => setEditText(e.target.value)}
                  className="min-h-[40px] flex-1 resize-y rounded bg-secondary/40 p-1 text-sm focus:outline-none"
                  autoFocus
                />
                <button type="button" disabled={busy} onClick={() => void saveEdit(entry)} title="Save" className="text-success/80 hover:text-success">
                  <Check className="h-4 w-4" />
                </button>
                <button type="button" onClick={() => setEditIdx(null)} title="Cancel" className="text-muted-foreground hover:text-foreground">
                  <X className="h-4 w-4" />
                </button>
              </>
            ) : (
              <>
                <span className="min-w-0 flex-1 whitespace-pre-wrap break-words text-foreground/90">{entry}</span>
                <button
                  type="button"
                  onClick={() => { setEditIdx(idx); setEditText(entry); }}
                  title="Edit"
                  className="opacity-0 transition group-hover:opacity-100 text-muted-foreground/60 hover:text-foreground"
                >
                  <Pencil className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void remove(entry)}
                  title="Forget"
                  className="opacity-0 transition group-hover:opacity-100 text-muted-foreground/60 hover:text-destructive"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </>
            )}
          </li>
        ))}
        {data && data.entries.length === 0 && (
          <li className="rounded-md border border-dashed border-border/50 px-2.5 py-3 text-center text-xs text-muted-foreground/50">
            Nothing here yet — entries accumulate as you chat.
          </li>
        )}
      </ul>

      <div className="mt-2 flex items-center gap-2">
        <input
          value={adding}
          onChange={(e) => setAdding(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void add()}
          placeholder="Add an entry…"
          className="h-8 flex-1 rounded-md border border-input bg-background px-2.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary/40"
        />
        <button
          type="button"
          disabled={busy || !adding.trim()}
          onClick={() => void add()}
          className="flex h-8 items-center gap-1 rounded-md bg-primary px-2.5 text-sm text-primary-foreground transition hover:bg-primary/90 disabled:opacity-40"
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
          Add
        </button>
      </div>
    </div>
  );
}

export default function MemoryPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4">
      <div>
        <h1 className="text-lg font-semibold text-foreground">Memory</h1>
        <p className="text-sm text-muted-foreground/70">Browse, edit, and forget what the agent remembers.</p>
      </div>
      {TARGETS.map((t) => (
        <TargetCard key={t.id} target={t.id} title={t.title} hint={t.hint} />
      ))}
    </div>
  );
}
