/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type React from "react";

export const WEBUI_THEMES = [
  { id: "spark", name: "Spark", description: "Amber graphite glass" },
  { id: "codex", name: "Codex", description: "Neutral compact console" },
  { id: "daylight", name: "Daylight", description: "Bright workspace" },
  { id: "signal", name: "Signal", description: "Green terminal glow" },
  { id: "aurora", name: "Aurora", description: "Polar ink with cyan light" },
  { id: "ember", name: "Ember", description: "Charcoal with hot copper" },
  { id: "orchid", name: "Orchid", description: "Night violet command deck" },
  { id: "harbor", name: "Harbor", description: "Deep navy and sea glass" },
] as const;

export type WebUITheme = (typeof WEBUI_THEMES)[number]["id"];

const STORAGE_KEY = "spark-webui-theme";

type ThemeContextValue = {
  theme: WebUITheme;
  setTheme: (theme: WebUITheme) => void;
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

function isTheme(value: string | null): value is WebUITheme {
  return WEBUI_THEMES.some((theme) => theme.id === value);
}

export function WebUIThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<WebUITheme>(() => {
    const saved = typeof localStorage === "undefined" ? null : localStorage.getItem(STORAGE_KEY);
    return isTheme(saved) ? saved : "spark";
  });

  useEffect(() => {
    document.documentElement.dataset.webuiTheme = theme;
    localStorage.setItem(STORAGE_KEY, theme);
  }, [theme]);

  const value = useMemo(
    () => ({
      theme,
      setTheme: setThemeState,
    }),
    [theme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useWebUITheme() {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("useWebUITheme must be used inside WebUIThemeProvider");
  return context;
}
