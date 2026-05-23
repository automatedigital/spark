import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { SlashCommand } from "@/lib/api";

interface SlashCommandMenuProps {
  query: string;
  onSelect: (command: string) => void;
  onClose: () => void;
  onItemCountChange?: (count: number) => void;
}

function fuzzyMatch(query: string, cmd: SlashCommand): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  if (cmd.name.startsWith(q)) return true;
  if (cmd.aliases?.some((a) => a.startsWith(q))) return true;
  if (cmd.name.includes(q)) return true;
  return false;
}

const CATEGORY_ORDER = ["Session", "Configuration", "Tools & Skills", "Skills", "Info"];

export function SlashCommandMenu({ query, onSelect, onClose, onItemCountChange }: SlashCommandMenuProps) {
  const [commands, setCommands] = useState<SlashCommand[]>([]);
  const [activeIdx, setActiveIdx] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.getCommands().then(setCommands).catch(() => {});
  }, []);

  const filtered = commands.filter((c) => fuzzyMatch(query, c));

  // Group by category in order
  const grouped: Record<string, SlashCommand[]> = {};
  for (const cmd of filtered) {
    const cat = cmd.category || "Other";
    (grouped[cat] ??= []).push(cmd);
  }
  const categories = CATEGORY_ORDER.filter((c) => grouped[c]?.length).concat(
    Object.keys(grouped).filter((c) => !CATEGORY_ORDER.includes(c) && grouped[c]?.length),
  );

  const flat = categories.flatMap((c) => grouped[c] ?? []);

  // Keep activeIdx in bounds
  useEffect(() => {
    setActiveIdx(0);
  }, [query]);

  // Notify parent of visible item count
  useEffect(() => {
    onItemCountChange?.(flat.length);
  }, [flat.length, onItemCountChange]);

  // Keyboard navigation
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (flat.length === 0) return;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActiveIdx((i) => (i + 1) % flat.length);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setActiveIdx((i) => (i - 1 + flat.length) % flat.length);
      } else if (e.key === "Tab" || e.key === "Enter") {
        e.preventDefault();
        if (flat[activeIdx]) onSelect(flat[activeIdx].name);
      } else if (e.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", handler, { capture: true });
    return () => window.removeEventListener("keydown", handler, { capture: true });
  }, [flat, activeIdx, onSelect, onClose]);

  // Scroll active item into view
  useEffect(() => {
    const el = containerRef.current?.querySelector(`[data-idx="${activeIdx}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [activeIdx]);

  if (flat.length === 0 && commands.length === 0) return null;
  if (flat.length === 0) return null;

  return (
    <div
      ref={containerRef}
      className="absolute bottom-full left-4 right-4 mb-1 z-50 rounded-lg border border-border bg-popover shadow-xl max-h-[280px] overflow-y-auto"
    >
      {categories.map((cat) => (
        <div key={cat}>
          <div className="px-3 py-1 text-[9px] uppercase tracking-widest text-muted-foreground/60 font-semibold border-b border-border/40 sticky top-0 bg-popover">
            {cat}
          </div>
          {(grouped[cat] ?? []).map((cmd) => {
            const idx = flat.indexOf(cmd);
            const isActive = idx === activeIdx;
            return (
              <button
                key={cmd.name}
                type="button"
                data-idx={idx}
                className={`w-full flex items-center gap-3 px-3 py-1.5 text-left transition-colors ${
                  isActive ? "bg-primary/10 text-foreground" : "hover:bg-secondary/60 text-foreground/90"
                }`}
                onClick={() => onSelect(cmd.name)}
                onMouseEnter={() => setActiveIdx(idx)}
              >
                <span className="font-mono text-xs text-primary shrink-0">/{cmd.name}</span>
                <span className="text-xs text-muted-foreground truncate flex-1">{cmd.description}</span>
                {cmd.args_hint && (
                  <span className="text-[10px] text-muted-foreground/50 font-mono shrink-0 hidden sm:block">
                    {cmd.args_hint}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );
}
