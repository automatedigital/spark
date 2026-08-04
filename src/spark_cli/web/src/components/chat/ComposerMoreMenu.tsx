import { useEffect, useRef, useState, type ReactNode } from "react";
import { ChevronDown, SlidersHorizontal } from "lucide-react";
import { COMPOSER_A11Y_LABELS, COMPOSER_COMPACT_ONLY } from "./composerContracts";

export interface ComposerMoreMenuProps {
  disabled?: boolean;
  hasModelSettings?: boolean;
  projectControl?: ReactNode;
  onOpenModelSettings?: () => void;
}

/** Secondary composer controls for compact widths. */
export function ComposerMoreMenu({
  disabled = false,
  hasModelSettings = false,
  projectControl,
  onOpenModelSettings,
}: ComposerMoreMenuProps) {
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

  const openModelSettings = () => {
    setOpen(false);
    onOpenModelSettings?.();
  };

  return (
    <div ref={rootRef} className={`relative ${COMPOSER_COMPACT_ONLY}`}>
      <button
        ref={triggerRef}
        type="button"
        disabled={disabled}
        aria-label={COMPOSER_A11Y_LABELS.more}
        aria-haspopup="menu"
        aria-expanded={open}
        title={COMPOSER_A11Y_LABELS.more}
        onClick={() => setOpen((value) => !value)}
        className="flex h-8 items-center gap-0.5 rounded-md px-1.5 text-muted-foreground/65 transition hover:bg-foreground/7 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 disabled:pointer-events-none disabled:opacity-40"
      >
        <SlidersHorizontal aria-hidden className="h-3.5 w-3.5" />
        <ChevronDown aria-hidden className={`h-2.5 w-2.5 opacity-45 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div
          role="menu"
          aria-label={COMPOSER_A11Y_LABELS.more}
          className="absolute bottom-full left-0 z-50 mb-2 w-[min(20rem,calc(100vw-2rem))] rounded-xl border border-border bg-popover/95 p-2 shadow-xl shadow-black/25 backdrop-blur-xl"
        >
          <div className="px-2 pb-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground/50">
            Composer options
          </div>
          {hasModelSettings && (
            <button
              type="button"
              role="menuitem"
              onClick={openModelSettings}
              className="mb-1 flex min-h-9 w-full items-center rounded-lg px-2 text-left text-xs text-foreground transition hover:bg-foreground/8 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
            >
              <span>Model &amp; reasoning</span>
              <span className="ml-auto text-[10px] text-muted-foreground/45">Configure</span>
            </button>
          )}
          {projectControl && (
            <div className="border-t border-border/70 px-1 pt-2" onClick={() => setOpen(false)}>
              <div className="mb-1 px-1 text-[10px] uppercase tracking-[0.14em] text-muted-foreground/45">Project</div>
              {projectControl}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
