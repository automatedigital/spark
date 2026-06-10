import { cn } from "@/lib/utils";

export function Switch({
  checked,
  onCheckedChange,
  className,
  disabled,
}: {
  checked: boolean;
  onCheckedChange: (v: boolean) => void;
  className?: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      className={cn(
        "peer inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border border-border transition-colors",
        "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-foreground/20",
        "disabled:cursor-not-allowed disabled:opacity-50",
        checked ? "bg-foreground/20 border-foreground/24" : "bg-background/50",
        className,
      )}
      onClick={() => onCheckedChange(!checked)}
    >
      <span
        className={cn(
          "pointer-events-none block h-3.5 w-3.5 rounded-full transition-transform",
          checked ? "translate-x-4 bg-foreground" : "translate-x-0.5 bg-muted-foreground",
        )}
      />
    </button>
  );
}
