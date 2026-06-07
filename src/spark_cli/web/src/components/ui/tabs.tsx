import { useState } from "react";
import { cn } from "@/lib/utils";

export function Tabs({
  defaultValue,
  children,
  className,
}: {
  defaultValue: string;
  children: (active: string, setActive: (v: string) => void) => React.ReactNode;
  className?: string;
}) {
  const [active, setActive] = useState(defaultValue);
  return <div className={cn("flex flex-col gap-4", className)}>{children(active, setActive)}</div>;
}

export function TabsList({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "inline-flex h-8 items-center justify-start gap-1 text-muted-foreground",
        className,
      )}
      {...props}
    />
  );
}

export function TabsTrigger({
  active,
  onClick,
  className,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { active: boolean; value: string }) {
  return (
    <button
      type="button"
      className={cn(
        "relative inline-flex items-center justify-center whitespace-nowrap rounded-md px-2.5 py-1.5 font-display text-sm font-medium transition-all cursor-pointer",
        "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
        active
          ? "bg-foreground/8 text-foreground"
          : "hover:bg-foreground/6 hover:text-foreground",
        className,
      )}
      onClick={onClick}
      {...props}
    />
  );
}
