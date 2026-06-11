import { useEffect } from "react";
import { Button } from "@/components/ui/button";

/** Lightweight modal used in place of window.confirm / window.alert, which feel
 *  broken inside the desktop app. Omit `onCancel` for an info/alert dialog. */
export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  destructive = false,
  onConfirm,
  onCancel,
  onClose,
}: {
  open: boolean;
  title: string;
  body?: React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
  onConfirm?: () => void;
  onCancel?: () => void;
  onClose: () => void;
}) {
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Enter" && onConfirm) { onConfirm(); onClose(); }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose, onConfirm]);

  if (!open) return null;

  return (
    <div
      className="absolute inset-0 z-40 flex items-center justify-center bg-background/60 p-4 backdrop-blur-sm"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="w-full max-w-sm rounded-lg border border-border bg-popover shadow-2xl">
        <div className="border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold text-foreground">{title}</h2>
        </div>
        {body && <div className="max-h-64 overflow-y-auto px-4 py-3 text-[12px] text-muted-foreground">{body}</div>}
        <div className="flex justify-end gap-2 border-t border-border px-4 py-2.5">
          {onCancel !== undefined && (
            <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => { onCancel(); onClose(); }}>
              {cancelLabel}
            </Button>
          )}
          {onConfirm && (
            <Button
              size="sm"
              variant={destructive ? "destructive" : "default"}
              className="h-7 text-xs"
              onClick={() => { onConfirm(); onClose(); }}
            >
              {confirmLabel}
            </Button>
          )}
          {!onConfirm && !onCancel && (
            <Button size="sm" className="h-7 text-xs" onClick={onClose}>OK</Button>
          )}
        </div>
      </div>
    </div>
  );
}
