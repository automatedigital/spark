import { useState } from "react";
import { MessageSquare, CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/button";

const AREAS = ["Workspace", "Tasks", "Chat", "Cron", "Skills", "Settings"] as const;
type Area = (typeof AREAS)[number];

interface FeedbackFormProps {
  onSubmit: (data: { name: string; email: string; area: string; note: string }) => Promise<void>;
  submitted?: boolean;
}

export function FeedbackForm({ onSubmit, submitted }: FeedbackFormProps) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [area, setArea] = useState<Area | "">("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!note.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await onSubmit({ name, email, area, note });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit feedback.");
      setBusy(false);
    }
  };

  if (submitted) {
    return (
      <div className="rounded-lg border border-border bg-secondary/40 p-4 flex items-center gap-3 text-sm text-muted-foreground">
        <CheckCircle2 className="h-4 w-4 text-success shrink-0" />
        <span>Feedback submitted — thank you!</span>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border bg-secondary/20 p-4 space-y-3">
      <div className="flex items-center gap-2 text-sm font-medium">
        <MessageSquare className="h-4 w-4 shrink-0 text-muted-foreground" />
        <span>Submit Feedback</span>
      </div>

      <form onSubmit={handleSubmit} className="space-y-3">
        <div className="grid grid-cols-2 gap-2">
          <div className="space-y-1">
            <label className="text-[11px] text-muted-foreground uppercase tracking-wide">Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Your name"
              disabled={busy}
              className="w-full rounded border border-input bg-background px-2.5 py-1.5 text-sm placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-50"
            />
          </div>
          <div className="space-y-1">
            <label className="text-[11px] text-muted-foreground uppercase tracking-wide">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              disabled={busy}
              className="w-full rounded border border-input bg-background px-2.5 py-1.5 text-sm placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-50"
            />
          </div>
        </div>

        <div className="space-y-1">
          <label className="text-[11px] text-muted-foreground uppercase tracking-wide">Area</label>
          <div className="flex flex-wrap gap-1.5">
            {AREAS.map((a) => (
              <button
                key={a}
                type="button"
                disabled={busy}
                onClick={() => setArea(area === a ? "" : a)}
                className={`rounded-full px-3 py-0.5 text-xs border transition-colors ${
                  area === a
                    ? "bg-primary text-primary-foreground border-primary"
                    : "border-border bg-background text-muted-foreground hover:border-primary/50 hover:text-foreground"
                } disabled:opacity-50`}
              >
                {a}
              </button>
            ))}
          </div>
        </div>

        <div className="space-y-1">
          <label className="text-[11px] text-muted-foreground uppercase tracking-wide">
            Feedback <span className="text-destructive">*</span>
          </label>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="What's on your mind?"
            required
            rows={3}
            disabled={busy}
            className="w-full rounded border border-input bg-background px-2.5 py-1.5 text-sm placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-ring resize-none disabled:opacity-50"
          />
        </div>

        {error && (
          <p className="text-xs text-destructive">{error}</p>
        )}

        <div className="flex justify-end">
          <Button type="submit" size="sm" className="h-7 text-xs" disabled={busy || !note.trim()}>
            {busy ? "Submitting…" : "Submit Feedback"}
          </Button>
        </div>
      </form>
    </div>
  );
}
