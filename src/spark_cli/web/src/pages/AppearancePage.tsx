import { Check } from "lucide-react";
import { WEBUI_THEMES, useWebUITheme, type WebUITheme } from "@/lib/theme";
import { cn } from "@/lib/utils";

const THEME_SWATCHES: Record<WebUITheme, string[]> = {
  spark: ["#1a1a1a", "#272727", "#FDA632"],
  codex: ["#101112", "#202326", "#d7dde5"],
  daylight: ["#f6f3ea", "#ffffff", "#276ef1"],
  signal: ["#07110d", "#14211a", "#7ee787"],
  aurora: ["#07131f", "#102a36", "#5eead4"],
  ember: ["#190f0b", "#2a1710", "#ff7a45"],
  orchid: ["#160d21", "#241433", "#c084fc"],
  harbor: ["#071827", "#102f3d", "#38bdf8"],
};

export default function AppearancePage() {
  const { theme, setTheme } = useWebUITheme();

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-5">
        <h2 className="text-lg font-semibold text-foreground">Appearance</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Choose the color and surface treatment for the WebUI.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {WEBUI_THEMES.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setTheme(item.id)}
            className={cn(
              "flex min-h-24 flex-col items-start justify-between rounded-sm border bg-card/70 p-3 text-left transition",
              theme === item.id
                ? "border-primary/70 ring-1 ring-primary/30"
                : "border-border hover:border-foreground/25 hover:bg-secondary/60",
            )}
          >
            <span className="flex w-full items-start justify-between gap-3">
              <span>
                <span className="block text-sm font-semibold text-foreground">{item.name}</span>
                <span className="mt-1 block text-xs text-muted-foreground">{item.description}</span>
              </span>
              {theme === item.id && <Check className="h-4 w-4 shrink-0 text-primary" />}
            </span>
            <span className="mt-4 flex gap-1.5">
              {THEME_SWATCHES[item.id].map((color) => (
                <span
                  key={color}
                  className="h-5 w-8 rounded-sm border border-white/15"
                  style={{ backgroundColor: color }}
                />
              ))}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
