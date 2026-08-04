import { useEffect, useRef, useState } from "react";
import { ChevronDown, FilePlus2, FolderSearch, Upload } from "lucide-react";
import { COMPOSER_A11Y_LABELS } from "./composerContracts";

export interface ComposerAttachmentMenuProps {
  disabled?: boolean;
  uploading?: boolean;
  onUpload?: () => void;
  onBrowse?: () => void;
}

/**
 * The composer keeps attachment actions one click away without spending a
 * permanent toolbar slot on two separate buttons. The menu is intentionally
 * native-button based so it remains usable with keyboard and screen readers.
 */
export function ComposerAttachmentMenu({
  disabled = false,
  uploading = false,
  onUpload,
  onBrowse,
}: ComposerAttachmentMenuProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

  const choose = (action: () => void) => {
    setOpen(false);
    action();
  };

  return (
    <div ref={rootRef} className="relative">
      <button
        ref={triggerRef}
        type="button"
        disabled={disabled || uploading}
        aria-label={COMPOSER_A11Y_LABELS.attachments}
        aria-haspopup="menu"
        aria-expanded={open}
        title={COMPOSER_A11Y_LABELS.attachments}
        onClick={() => setOpen((value) => !value)}
        className="flex h-8 min-w-8 items-center justify-center gap-0.5 rounded-md px-1.5 text-muted-foreground/65 transition hover:bg-foreground/7 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 disabled:pointer-events-none disabled:opacity-40"
      >
        {uploading ? <Upload className="h-3.5 w-3.5 animate-pulse" /> : <FilePlus2 className="h-3.5 w-3.5" />}
        <ChevronDown aria-hidden className={`h-2.5 w-2.5 opacity-45 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div
          role="menu"
          aria-label="Attachment actions"
          className="absolute bottom-full left-0 z-50 mb-2 min-w-52 rounded-xl border border-border bg-popover/95 p-1.5 shadow-xl shadow-black/25 backdrop-blur-xl"
        >
          {onUpload && (
            <button
              type="button"
              role="menuitem"
              onClick={() => choose(onUpload)}
              className="flex min-h-9 w-full items-center gap-2 rounded-lg px-2.5 text-left text-xs text-foreground transition hover:bg-foreground/8 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
            >
              <Upload aria-hidden className="h-3.5 w-3.5 text-muted-foreground/70" />
              <span>Upload files</span>
              <span className="ml-auto text-[10px] text-muted-foreground/45">From device</span>
            </button>
          )}
          {onBrowse && (
            <button
              type="button"
              role="menuitem"
              onClick={() => choose(onBrowse)}
              className="flex min-h-9 w-full items-center gap-2 rounded-lg px-2.5 text-left text-xs text-foreground transition hover:bg-foreground/8 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
            >
              <FolderSearch aria-hidden className="h-3.5 w-3.5 text-muted-foreground/70" />
              <span>Browse workspace</span>
              <span className="ml-auto text-[10px] text-muted-foreground/45">@ files</span>
            </button>
          )}
        </div>
      )}
    </div>
  );
}
