import { useEffect, useState } from "react";
import { Check, WrapText } from "lucide-react";
import { api } from "@/lib/api";
import { WEBUI_THEMES, useWebUITheme, type WebUITheme } from "@/lib/theme";
import { cn } from "@/lib/utils";
import { Switch } from "@/components/ui/switch";

const THEME_SWATCHES: Record<WebUITheme, string[]> = {
  spark: ["#1a1a1a", "#272727", "#FDA632"],
  codex: ["#090a0b", "#181a1d", "#d8dde4"],
  daylight: ["#f6f3ea", "#ffffff", "#276ef1"],
  signal: ["#07110d", "#14211a", "#7ee787"],
  aurora: ["#07131f", "#102a36", "#5eead4"],
  ember: ["#190f0b", "#2a1710", "#ff7a45"],
  orchid: ["#160d21", "#241433", "#c084fc"],
  harbor: ["#071827", "#102f3d", "#38bdf8"],
};
const CHAT_WORD_WRAP_CHANGED_EVENT = "spark:chat-word-wrap-changed";

export default function AppearancePage() {
  const { theme, setTheme } = useWebUITheme();
  const [config, setConfig] = useState<Record<string, unknown> | null>(null);
  const [chatWordWrap, setChatWordWrap] = useState(false);
  const [savingWrap, setSavingWrap] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void api.getConfig()
      .then((nextConfig) => {
        if (cancelled) return;
        setConfig(nextConfig);
        const display = nextConfig.display;
        setChatWordWrap(Boolean(
          display &&
            typeof display === "object" &&
            (display as Record<string, unknown>).chat_word_wrap,
        ));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const handleWrapChange = (checked: boolean) => {
    setChatWordWrap(checked);
    const base = config ?? {};
    const display = base.display && typeof base.display === "object"
      ? { ...(base.display as Record<string, unknown>) }
      : {};
    const nextConfig = {
      ...base,
      display: {
        ...display,
        chat_word_wrap: checked,
      },
    };
    setConfig(nextConfig);
    setSavingWrap(true);
    void api.saveConfig(nextConfig)
      .then(() => {
        window.dispatchEvent(new CustomEvent(CHAT_WORD_WRAP_CHANGED_EVENT, { detail: { enabled: checked } }));
      })
      .catch(() => {
        setChatWordWrap(!checked);
        setConfig(base);
      })
      .finally(() => setSavingWrap(false));
  };

  return (
    <div className="settings-page">
      <div className="mb-5">
        <h2 className="text-base font-semibold text-foreground">Appearance</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          Choose the color and surface treatment for the WebUI.
        </p>
      </div>

      <div className="mb-5 flex items-center justify-between gap-4 rounded-lg border border-border/60 bg-foreground/[0.035] px-3 py-3">
        <div className="flex min-w-0 items-center gap-3">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-foreground/10 text-foreground">
            <WrapText className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <div className="text-sm font-medium text-foreground">Chat word wrap</div>
            <div className="mt-0.5 text-xs text-muted-foreground">
              Code blocks and markdown tables
            </div>
          </div>
        </div>
        <Switch
          checked={chatWordWrap}
          disabled={savingWrap}
          onCheckedChange={handleWrapChange}
          aria-label="Chat word wrap"
        />
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {WEBUI_THEMES.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setTheme(item.id)}
            className={cn(
              "flex min-h-24 flex-col items-start justify-between rounded-lg bg-foreground/[0.035] p-3 text-left transition",
              theme === item.id
                ? "ring-1 ring-foreground/25"
                : "hover:bg-foreground/[0.055]",
            )}
          >
            <span className="flex w-full items-start justify-between gap-3">
              <span>
                <span className="block text-sm font-semibold text-foreground">{item.name}</span>
                <span className="mt-1 block text-xs text-muted-foreground">{item.description}</span>
              </span>
              {theme === item.id && <Check className="h-4 w-4 shrink-0 text-foreground" />}
            </span>
            <span className="mt-4 flex gap-1.5">
              {THEME_SWATCHES[item.id].map((color) => (
                <span
                  key={color}
                  className="h-4 w-7 rounded border border-white/12"
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
