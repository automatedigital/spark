import { cn } from "@/lib/utils";

interface SkeletonProps {
  className?: string;
}

export function Skeleton({ className }: SkeletonProps) {
  return (
    <div className={cn("animate-pulse rounded bg-muted/50", className)} />
  );
}

export function MessageRowSkeleton() {
  return (
    <div className="flex flex-col gap-3 px-4 py-2">
      <div className="flex items-start gap-2 justify-end">
        <div className="flex flex-col gap-1.5 items-end max-w-[75%]">
          <Skeleton className="h-4 w-48" />
          <Skeleton className="h-4 w-32" />
        </div>
        <Skeleton className="h-7 w-7 rounded-full shrink-0" />
      </div>
      <div className="flex items-start gap-2">
        <Skeleton className="h-7 w-7 rounded-full shrink-0" />
        <div className="flex flex-col gap-1.5 max-w-[75%]">
          <Skeleton className="h-4 w-64" />
          <Skeleton className="h-4 w-48" />
          <Skeleton className="h-4 w-40" />
        </div>
      </div>
      <div className="flex items-start gap-2 justify-end">
        <div className="flex flex-col gap-1.5 items-end max-w-[75%]">
          <Skeleton className="h-4 w-56" />
        </div>
        <Skeleton className="h-7 w-7 rounded-full shrink-0" />
      </div>
    </div>
  );
}

export function SessionRowSkeleton() {
  return (
    <div className="flex flex-col gap-2 px-3 py-2.5 border-b border-border">
      <div className="flex items-center gap-2">
        <Skeleton className="h-4 w-4 rounded shrink-0" />
        <Skeleton className="h-4 flex-1 max-w-[60%]" />
        <Skeleton className="h-3 w-12 ml-auto" />
      </div>
      <Skeleton className="h-3 w-full max-w-[80%]" />
    </div>
  );
}

export function CronCardSkeleton() {
  return (
    <div className="rounded-lg border border-border p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-6 w-16 rounded-full" />
      </div>
      <Skeleton className="h-3 w-full" />
      <Skeleton className="h-3 w-3/4" />
      <div className="flex items-center gap-2 mt-1">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-4 w-24" />
      </div>
    </div>
  );
}

export function FileRowSkeleton() {
  return (
    <div className="flex items-center gap-2 px-2 py-1.5">
      <Skeleton className="h-4 w-4 rounded shrink-0" />
      <Skeleton className="h-4 flex-1 max-w-[70%]" />
      <Skeleton className="h-3 w-12 ml-auto" />
    </div>
  );
}
