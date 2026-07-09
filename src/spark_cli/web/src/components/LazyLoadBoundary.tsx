import { Component, Suspense, type ErrorInfo, type ReactNode } from "react";
import { Loader2, RefreshCw } from "lucide-react";

export function LazyLoadFallback({
  label = "Loading view",
  overlay = false,
}: {
  label?: string;
  overlay?: boolean;
}) {
  return (
    <div
      className={overlay
        ? "fixed inset-0 z-[100] flex items-center justify-center bg-background/60 backdrop-blur-sm"
        : "flex h-full min-h-40 w-full items-center justify-center"}
      role="status"
      aria-live="polite"
    >
      <div className="flex min-w-48 items-center justify-center gap-2 rounded-md border border-border bg-card/80 px-4 py-3 text-sm text-muted-foreground shadow-lg backdrop-blur">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        <span>{label}…</span>
      </div>
    </div>
  );
}

type LazyLoadErrorBoundaryProps = {
  children: ReactNode;
  label?: string;
  overlay?: boolean;
};

type LazyLoadErrorBoundaryState = {
  error: Error | null;
};

class LazyLoadErrorBoundary extends Component<LazyLoadErrorBoundaryProps, LazyLoadErrorBoundaryState> {
  state: LazyLoadErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): LazyLoadErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Failed to load a deferred WebUI feature", error, info);
  }

  private retry = () => {
    // React.lazy caches rejected imports. A reload creates a fresh module graph
    // while preserving the current route in localStorage.
    window.location.reload();
  };

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div
        className={this.props.overlay
          ? "fixed inset-0 z-[100] flex items-center justify-center bg-background/60 p-4 backdrop-blur-sm"
          : "flex h-full min-h-40 w-full items-center justify-center p-4"}
        role="alert"
      >
        <div className="max-w-sm rounded-md border border-destructive/40 bg-card p-5 text-center shadow-xl">
          <p className="text-sm font-medium text-foreground">
            {this.props.label ?? "This view"} could not be loaded.
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            The application may have updated while this tab was open.
          </p>
          <button
            type="button"
            onClick={this.retry}
            className="mx-auto mt-4 flex items-center gap-2 rounded-md bg-primary px-3 py-2 text-xs font-semibold text-primary-foreground transition hover:bg-primary/90"
          >
            <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
            Reload and retry
          </button>
        </div>
      </div>
    );
  }
}

export function LazyLoadBoundary({
  children,
  label,
  overlay = false,
}: {
  children: ReactNode;
  label?: string;
  overlay?: boolean;
}) {
  return (
    <LazyLoadErrorBoundary label={label} overlay={overlay}>
      <Suspense fallback={<LazyLoadFallback label={label ? `Loading ${label}` : undefined} overlay={overlay} />}>
        {children}
      </Suspense>
    </LazyLoadErrorBoundary>
  );
}
