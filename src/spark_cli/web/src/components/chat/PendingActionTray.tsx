import { useState } from "react";
import type { FormEvent } from "react";
import { AlertTriangle, Check, CircleHelp, ShieldAlert } from "lucide-react";
import type { WebPendingAction } from "@/lib/api";

export type PendingApprovalChoice = "once" | "session" | "always" | "deny";

export interface PendingActionTrayProps {
  actions: readonly WebPendingAction[];
  busyActionIds?: readonly string[] | ReadonlySet<string>;
  onApprovalChoice?: (action: WebPendingAction, choice: PendingApprovalChoice) => void | Promise<void>;
  onSubmitInput?: (action: WebPendingAction, response: string) => void | Promise<void>;
}

function isBusy(actionId: string, busyActionIds: PendingActionTrayProps["busyActionIds"]): boolean {
  if (!busyActionIds) return false;
  if ("has" in busyActionIds) return busyActionIds.has(actionId);
  return busyActionIds.includes(actionId);
}

function PendingApproval({ action, busy, onChoice }: { action: WebPendingAction; busy: boolean; onChoice?: PendingActionTrayProps["onApprovalChoice"] }) {
  const { command, description } = action.payload;
  const choose = (choice: PendingApprovalChoice) => { void onChoice?.(action, choice); };
  return (
    <article className="rounded-lg border border-amber-400/30 bg-amber-400/[0.07] p-3" data-action-id={action.action_id} data-action-kind="approval">
      <div className="flex items-start gap-2">
        <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-300" aria-hidden="true" />
        <div className="min-w-0">
          <h3 className="font-medium text-foreground">Approval needed</h3>
          {description && <p className="mt-1 text-muted-foreground">{description}</p>}
          {command && <code className="mt-2 block truncate rounded bg-background/60 px-2 py-1 font-mono text-[11px] text-foreground/80" title={command}>{command}</code>}
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5" aria-label="Approval choices">
        <button type="button" disabled={busy} onClick={() => choose("once")} className="rounded-md bg-primary px-2.5 py-1.5 text-[11px] font-medium text-primary-foreground hover:bg-primary/90 focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-50">Allow once</button>
        <button type="button" disabled={busy} onClick={() => choose("session")} className="rounded-md border border-border px-2.5 py-1.5 text-[11px] text-foreground hover:bg-foreground/[0.06] focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-50">For this session</button>
        <button type="button" disabled={busy} onClick={() => choose("always")} className="rounded-md border border-border px-2.5 py-1.5 text-[11px] text-foreground hover:bg-foreground/[0.06] focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-50">Always</button>
        <button type="button" disabled={busy} onClick={() => choose("deny")} className="rounded-md border border-destructive/35 px-2.5 py-1.5 text-[11px] text-destructive hover:bg-destructive/10 focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-50">Deny</button>
      </div>
    </article>
  );
}

function PendingInput({ action, busy, onSubmit }: { action: WebPendingAction; busy: boolean; onSubmit?: PendingActionTrayProps["onSubmitInput"] }) {
  const [value, setValue] = useState("");
  const prompt = action.payload.question ?? action.payload.prompt ?? "Spark is waiting for your input.";
  const choices = Array.isArray(action.payload.choices) ? action.payload.choices.filter((choice): choice is string => typeof choice === "string" && choice.trim().length > 0) : [];
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const response = value.trim();
    if (!response || !onSubmit) return;
    void onSubmit(action, response);
  };
  const choose = (choice: string) => {
    setValue(choice);
    void onSubmit?.(action, choice);
  };
  return (
    <article className="rounded-lg border border-primary/30 bg-primary/[0.07] p-3" data-action-id={action.action_id} data-action-kind="requested_input">
      <div className="flex items-start gap-2">
        <CircleHelp className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
        <div className="min-w-0">
          <h3 className="font-medium text-foreground">Input needed</h3>
          <p className="mt-1 text-muted-foreground">{prompt}</p>
        </div>
      </div>
      {choices.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5" aria-label="Suggested answers">
          {choices.map((choice) => <button key={choice} type="button" disabled={busy} onClick={() => choose(choice)} className="rounded-md border border-primary/35 px-2.5 py-1.5 text-[11px] text-foreground hover:bg-primary/10 focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-50">{choice}</button>)}
        </div>
      )}
      <form className="mt-3 flex gap-2" onSubmit={submit}>
        <label className="sr-only" htmlFor={`pending-input-${action.action_id}`}>Response</label>
        <input id={`pending-input-${action.action_id}`} value={value} onChange={(event) => setValue(event.target.value)} disabled={busy} placeholder="Type a response…" className="min-w-0 flex-1 rounded-md border border-border bg-background/70 px-2.5 py-1.5 text-xs text-foreground outline-none placeholder:text-muted-foreground/60 focus:border-ring focus:ring-1 focus:ring-ring" />
        <button type="submit" disabled={busy || !value.trim()} className="inline-flex items-center gap-1 rounded-md bg-primary px-2.5 py-1.5 text-[11px] font-medium text-primary-foreground hover:bg-primary/90 focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-50"><Check className="h-3 w-3" aria-hidden="true" /> Send</button>
      </form>
    </article>
  );
}

export function PendingActionTray({ actions, busyActionIds, onApprovalChoice, onSubmitInput }: PendingActionTrayProps) {
  const pending = actions.filter((action) => action.status === "pending");
  if (pending.length === 0) return null;
  return (
    <section aria-label="Pending actions" data-testid="pending-action-tray" className="mx-3 mb-2 rounded-xl border-2 border-dashed border-amber-400/35 bg-background p-3 shadow-lg shadow-black/10">
      <div className="mb-2 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-amber-200">
        <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" /> Waiting for you
      </div>
      <div className="space-y-2">
        {pending.map((action) => {
          const busy = isBusy(action.action_id, busyActionIds);
          return action.kind === "approval"
            ? <PendingApproval key={action.action_id} action={action} busy={busy} onChoice={onApprovalChoice} />
            : action.kind === "requested_input"
              ? <PendingInput key={action.action_id} action={action} busy={busy} onSubmit={onSubmitInput} />
              : null;
        })}
      </div>
    </section>
  );
}
