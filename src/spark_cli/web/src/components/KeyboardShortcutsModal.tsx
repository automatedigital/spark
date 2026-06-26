import { useEffect } from "react";
import { X, Keyboard } from "lucide-react";
import { Button } from "@/components/ui/button";

interface KeyboardShortcutsModalProps {
  open: boolean;
  onClose: () => void;
}

const SHORTCUTS = [
  {
    context: "Global",
    items: [
      { keys: ["⌘", "K"], description: "Open command palette" },
      { keys: ["?"], description: "Show keyboard shortcuts" },
    ],
  },
  {
    context: "Chat",
    items: [
      { keys: ["⌘", "F"], description: "Search messages" },
      { keys: ["Enter"], description: "Send message" },
      { keys: ["Shift", "Enter"], description: "New line in message" },
      { keys: ["Esc"], description: "Cancel streaming / close search" },
    ],
  },
  {
    context: "Navigation",
    items: [
      { keys: ["⌘", "K"], description: "Navigate pages via command palette" },
    ],
  },
  {
    context: "Project panel",
    items: [
      { keys: ["⇧", "⌘", "P"], description: "Open Preview" },
      { keys: ["⌃", "`"], description: "Open Terminal" },
      { keys: ["⇧", "⌘", "F"], description: "Open Files" },
      { keys: ["⇧", "⌘", "D"], description: "Open Changes" },
    ],
  },
];

function Kbd({ children }: { children: string }) {
  return (
    <kbd className="inline-flex items-center justify-center min-w-[1.6rem] h-6 px-1.5 rounded border border-border bg-muted text-[11px] font-mono text-muted-foreground">
      {children}
    </kbd>
  );
}

export function KeyboardShortcutsModal({ open, onClose }: KeyboardShortcutsModalProps) {
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-background/60 backdrop-blur-sm"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="w-full max-w-md rounded-xl border border-border bg-popover shadow-2xl overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-border">
          <Keyboard className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold flex-1">Keyboard Shortcuts</h2>
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onClose}>
            <X className="h-3.5 w-3.5" />
          </Button>
        </div>

        <div className="overflow-y-auto max-h-[70vh] p-4 flex flex-col gap-5">
          {SHORTCUTS.map((section) => (
            <div key={section.context}>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-2">
                {section.context}
              </p>
              <div className="flex flex-col gap-1.5">
                {section.items.map((item) => (
                  <div key={item.description} className="flex items-center justify-between gap-4">
                    <span className="text-sm text-muted-foreground">{item.description}</span>
                    <div className="flex items-center gap-1 shrink-0">
                      {item.keys.map((k) => <Kbd key={k}>{k}</Kbd>)}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>

        <div className="border-t border-border px-4 py-2 text-[11px] text-muted-foreground">
          Press <Kbd>Esc</Kbd> or click outside to close · Press <Kbd>?</Kbd> to toggle
        </div>
      </div>
    </div>
  );
}
