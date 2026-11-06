import { useEffect, useRef } from "react";
import { Markdown } from "@/components/Markdown";
import type { MessageWindow } from "@/lib/messageAnchorClient";

export function MessageAnchorView({ window, loading, error, onPage, onLatest }: {
  window: MessageWindow | null;
  loading: boolean;
  error: string | null;
  onPage: (direction: "older" | "newer") => void;
  onLatest: () => void;
}) {
  const match = useRef<HTMLElement | null>(null);
  const heading = useRef<HTMLHeadingElement | null>(null);
  useEffect(() => {
    if (!window) return;
    const frame = requestAnimationFrame(() => {
      if (match.current) {
        match.current.scrollIntoView({ block: "center" });
        match.current.focus({ preventScroll: true });
      } else heading.current?.focus({ preventScroll: true });
    });
    return () => cancelAnimationFrame(frame);
  }, [window]);
  return <section aria-label="Search message context" className="absolute inset-0 z-40 flex min-h-0 flex-col bg-background" data-testid="message-anchor-view">
    <div className="flex shrink-0 items-center justify-between gap-3 border-b border-border p-3">
      <h2 ref={heading} tabIndex={-1} className="text-sm">Search message context</h2>
      <button className="rounded border border-border px-3 py-1 text-sm" onClick={onLatest}>Return to latest</button>
    </div>
    <div role="status" className="px-4 text-sm text-muted-foreground">
      {loading ? "Loading message context…" : error ?? window?.notice ?? (window && window.history_session_id !== window.session_id ? "Saved context before compression. Latest replies continue in the current thread." : "Latest replies continue while you browse this saved context.")}
    </div>
    <div className="min-h-0 flex-1 overflow-y-auto p-4" data-testid="message-anchor-scroll">
      {window?.has_earlier && <button disabled={loading} className="mb-3 rounded border px-3 py-1" onClick={() => onPage("older")}>Load older context</button>}
      {window?.messages.map((message) => {
        const selected = String(message.id) === String(window.anchor_id);
        return <article key={message.id} ref={selected ? match : undefined} tabIndex={selected ? -1 : undefined}
          data-message-id={message.id} data-anchor-highlight={selected ? "true" : undefined}
          aria-label={selected ? "Search result message" : undefined}
          className={`mx-auto mb-4 max-w-3xl rounded-lg border p-4 ${selected ? "border-primary bg-primary/10 ring-2 ring-primary" : "border-border"}`}>
          <p className="mb-2 text-xs font-medium text-muted-foreground">{message.role === "user" ? "You" : message.role === "tool" ? "Tool" : "Spark"}{selected ? " · Search result" : ""}</p>
          <Markdown content={message.content ?? message.reasoning ?? ""} />
        </article>;
      })}
      {window?.has_newer && <button disabled={loading} className="rounded border px-3 py-1" onClick={() => onPage("newer")}>Load newer context</button>}
    </div>
  </section>;
}
