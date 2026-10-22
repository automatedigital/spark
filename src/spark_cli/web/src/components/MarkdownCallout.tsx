import { useId, type ReactNode } from "react";
import { Info, Lightbulb, MessageSquareWarning, TriangleAlert, OctagonAlert } from "lucide-react";
import type { CalloutKind } from "./markdownParse";

const presentations = {
  NOTE: { label: "Note", Icon: Info, border: "border-s-blue-500" },
  TIP: { label: "Tip", Icon: Lightbulb, border: "border-s-green-500" },
  IMPORTANT: { label: "Important", Icon: MessageSquareWarning, border: "border-s-purple-500" },
  WARNING: { label: "Warning", Icon: TriangleAlert, border: "border-s-amber-500" },
  CAUTION: { label: "Caution", Icon: OctagonAlert, border: "border-s-red-500" },
};

export function MarkdownCallout({ kind, children }: { kind: CalloutKind; children: ReactNode }) {
  const titleId = useId();
  const { label, Icon, border } = presentations[kind];
  return (
    <aside role="note" aria-labelledby={titleId} className={`border-s-4 ${border} bg-background py-2 ps-3 pe-2 text-foreground rounded-e-sm`}>
      <p id={titleId} className="flex items-center gap-2 font-semibold mb-1">
        <Icon aria-hidden="true" className="size-4 shrink-0" />
        {label}
      </p>
      <div className="space-y-2">{children}</div>
    </aside>
  );
}
