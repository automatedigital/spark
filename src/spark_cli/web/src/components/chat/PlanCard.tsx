import { Check, Circle, CircleDashed, ListChecks, Maximize2 } from "lucide-react";
import type { WebPlan } from "@/lib/api";
import { Markdown } from "@/components/Markdown";

export interface PlanCardProps {
  plan: WebPlan | null | undefined;
  onOpenPlan?: (plan: WebPlan) => void;
}

function statusLabel(status: WebPlan["status"]): string {
  if (status === "completed") return "Complete";
  if (status === "active") return "In progress";
  return status === "empty" ? "No steps yet" : status;
}

function StepIcon({ status }: { status: string }) {
  if (status === "completed" || status === "cancelled") return <Check className="h-3.5 w-3.5 text-success" aria-hidden="true" />;
  if (status === "in_progress") return <CircleDashed className="h-3.5 w-3.5 animate-pulse text-primary" aria-hidden="true" />;
  return <Circle className="h-3.5 w-3.5 text-muted-foreground/60" aria-hidden="true" />;
}

export function PlanCard({ plan, onOpenPlan }: PlanCardProps) {
  if (!plan || (plan.steps.length === 0 && !plan.markdown)) return null;
  const completed = plan.steps.filter((step) => step.status === "completed" || step.status === "cancelled").length;

  return (
    <section aria-label="Turn plan" data-testid="plan-card" className="rounded-xl border border-border/70 bg-foreground/[0.025] p-3 text-xs">
      <div className="flex items-center gap-2">
        <ListChecks className="h-4 w-4 text-primary" aria-hidden="true" />
        <h3 className="font-medium text-foreground">Plan</h3>
        <span className="text-muted-foreground">{statusLabel(plan.status)}</span>
        {plan.steps.length > 0 && <span className="text-muted-foreground">{completed}/{plan.steps.length}</span>}
        {onOpenPlan && (
          <button
            type="button"
            className="ml-auto inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-muted-foreground hover:bg-foreground/[0.06] hover:text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
            aria-label="Open full plan"
            onClick={() => onOpenPlan(plan)}
          >
            <Maximize2 className="h-3.5 w-3.5" aria-hidden="true" />
            <span className="sr-only">Open full plan</span>
          </button>
        )}
      </div>
      {plan.steps.length > 0 && (
        <ol className="mt-2 space-y-1.5" aria-label="Plan steps">
          {plan.steps.map((step) => (
            <li key={step.id} className="flex items-start gap-2 leading-5">
              <span className="mt-0.5 shrink-0"><StepIcon status={step.status} /></span>
              <span className={step.status === "completed" || step.status === "cancelled" ? "text-muted-foreground line-through" : "text-foreground/85"}>{step.content}</span>
            </li>
          ))}
        </ol>
      )}
      {plan.markdown && (
        <div className="mt-2 border-t border-border/50 pt-2 text-muted-foreground [&_p:first-child]:mt-0">
          <Markdown content={plan.markdown} safeMode />
        </div>
      )}
    </section>
  );
}
