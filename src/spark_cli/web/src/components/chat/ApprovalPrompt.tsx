import { ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/button";

export function ApprovalPrompt({
  command,
  description,
  disabled,
  onChoice,
}: {
  command?: string;
  description?: string;
  disabled?: boolean;
  onChoice: (c: "once" | "session" | "always" | "deny") => void;
}) {
  return (
    <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 space-y-2">
      <div className="flex items-center gap-2 text-destructive">
        <ShieldAlert className="h-4 w-4 shrink-0" />
        <span className="text-xs font-semibold uppercase tracking-wide">Approval required</span>
      </div>
      {description && <p className="text-xs text-destructive/90">{description}</p>}
      {command && (
        <pre className="text-[11px] bg-background/80 rounded p-2 overflow-x-auto font-mono border border-border max-h-32 overflow-y-auto">
          {command}
        </pre>
      )}
      <div className="flex flex-wrap gap-2 pt-1">
        <Button size="sm" variant="secondary" className="h-7 text-xs" disabled={disabled} onClick={() => onChoice("once")}>
          Once
        </Button>
        <Button size="sm" variant="secondary" className="h-7 text-xs" disabled={disabled} onClick={() => onChoice("session")}>
          Session
        </Button>
        <Button size="sm" variant="secondary" className="h-7 text-xs" disabled={disabled} onClick={() => onChoice("always")}>
          Always
        </Button>
        <Button size="sm" variant="destructive" className="h-7 text-xs" disabled={disabled} onClick={() => onChoice("deny")}>
          Deny
        </Button>
      </div>
    </div>
  );
}
