import { memo, type ReactNode } from "react";

/** Native disclosure keeps keyboard, focus, find/reveal and toggle behavior in
 * the browser. Toggling does not update React or re-render the transcript.
 * Summary is deliberately text-only; untrusted props are never spread to HTML.
 */
export const MarkdownDetails = memo(function MarkdownDetails({
  summary, open, children,
}: { summary: string; open: boolean; children: ReactNode }) {
  return (
    <details open={open} className="my-2 min-w-0 rounded-md border border-border bg-secondary/20">
      <summary className="cursor-pointer break-words px-3 py-2 font-medium focus-visible:outline-2 focus-visible:outline-primary">{summary}</summary>
      <div className="min-w-0 space-y-2 border-t border-border px-3 py-2">{children}</div>
    </details>
  );
});
