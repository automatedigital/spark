import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { ConversationModelEntry } from "@/lib/api";

export function ModelPicker({
  value,
  onChange,
  disabled,
}: {
  value: string;
  onChange: (m: string) => void;
  disabled?: boolean;
}) {
  const [models, setModels] = useState<ConversationModelEntry[]>([]);

  useEffect(() => {
    api
      .getConversationModels()
      .then((r) => setModels(r.models))
      .catch(() => setModels([]));
  }, []);

  return (
    <div className="flex flex-col gap-1 min-w-0">
      <label className="text-[10px] text-muted-foreground uppercase tracking-wider">Model</label>
      <div className="flex gap-2 min-w-0">
        <select
          className="flex-1 min-w-0 rounded border border-input bg-background px-2 py-1.5 text-xs font-mono focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-50"
          disabled={disabled}
          value=""
          onChange={(e) => {
            const v = e.target.value;
            if (v) onChange(v);
          }}
        >
          <option value="">Pick…</option>
          {models.map((m) => (
            <option key={m.id} value={m.id}>
              {m.id}{m.hint ? ` — ${m.hint}` : ""}
            </option>
          ))}
        </select>
      </div>
      <input
        type="text"
        className="w-full rounded border border-input bg-background px-2 py-1.5 text-xs font-mono focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-50"
        disabled={disabled}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="provider/model"
      />
    </div>
  );
}
