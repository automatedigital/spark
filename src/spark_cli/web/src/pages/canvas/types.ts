import {
  MessageSquare,
  StickyNote,
  Bot,
  Wrench,
  LogIn,
  LogOut,
  type LucideIcon,
} from "lucide-react";

export type CanvasNodeKind = "note" | "chat" | "agent" | "tool" | "input" | "output";

export interface PaletteItem {
  kind: CanvasNodeKind;
  label: string;
  description: string;
  icon: LucideIcon;
  /** Default `data` payload for a freshly-dropped node of this kind. */
  defaults: () => Record<string, unknown>;
}

export const PALETTE: PaletteItem[] = [
  {
    kind: "note",
    label: "Note",
    description: "A sticky text note",
    icon: StickyNote,
    defaults: () => ({ text: "" }),
  },
  {
    kind: "chat",
    label: "Chat",
    description: "Talk to the agent (canvas-local)",
    icon: MessageSquare,
    defaults: () => ({ messages: [] as Array<{ role: string; content: string }> }),
  },
  {
    kind: "agent",
    label: "Agent",
    description: "Run a prompt through the agent",
    icon: Bot,
    defaults: () => ({ prompt: "", model: "", output: "" }),
  },
  {
    kind: "tool",
    label: "Tool",
    description: "Wrap a Spark tool call",
    icon: Wrench,
    defaults: () => ({ tool: "", args: "{}", output: "" }),
  },
  {
    kind: "input",
    label: "Input",
    description: "A value fed into the graph",
    icon: LogIn,
    defaults: () => ({ value: "" }),
  },
  {
    kind: "output",
    label: "Output",
    description: "A terminal result",
    icon: LogOut,
    defaults: () => ({ value: "" }),
  },
];

export const PALETTE_BY_KIND: Record<CanvasNodeKind, PaletteItem> = Object.fromEntries(
  PALETTE.map((p) => [p.kind, p]),
) as Record<CanvasNodeKind, PaletteItem>;

/** dataTransfer MIME used when dragging a palette item onto the canvas. */
export const CANVAS_DND_MIME = "application/spark-canvas-node";
