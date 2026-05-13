import { useState, useEffect } from "react";
import { X, Activity, BarChart3, FileText, Shield, Settings, KeyRound } from "lucide-react";
import StatusPage from "@/pages/StatusPage";
import AnalyticsPage from "@/pages/AnalyticsPage";
import LogsPage from "@/pages/LogsPage";
import AdminPage from "@/pages/AdminPage";
import ConfigPage from "@/pages/ConfigPage";
import EnvPage from "@/pages/EnvPage";

const SETTINGS_TABS = [
  { id: "status", label: "Status", icon: Activity, component: StatusPage },
  { id: "analytics", label: "Analytics", icon: BarChart3, component: AnalyticsPage },
  { id: "logs", label: "Logs", icon: FileText, component: LogsPage },
  { id: "admin", label: "Admin", icon: Shield, component: AdminPage },
  { id: "config", label: "Config", icon: Settings, component: ConfigPage },
  { id: "keys", label: "Keys", icon: KeyRound, component: EnvPage },
] as const;

type SettingsTabId = (typeof SETTINGS_TABS)[number]["id"];

interface SettingsPanelProps {
  onClose: () => void;
  initialTab?: SettingsTabId;
}

export default function SettingsPanel({ onClose, initialTab = "status" }: SettingsPanelProps) {
  const [activeTab, setActiveTab] = useState<SettingsTabId>(initialTab);
  const [animKey, setAnimKey] = useState(0);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  const handleTabChange = (id: SettingsTabId) => {
    setActiveTab(id);
    setAnimKey((k) => k + 1);
  };

  const { component: ActiveComponent } = SETTINGS_TABS.find((t) => t.id === activeTab)!;

  return (
    <>
      <div
        className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        className="fixed inset-y-0 right-0 z-50 flex w-full flex-col bg-background shadow-2xl md:w-[min(960px,92vw)]"
        role="dialog"
        aria-modal="true"
        aria-label="Settings"
        style={{ animation: "slide-in-right 180ms ease-out" }}
      >
        {/* Header */}
        <div className="flex h-14 shrink-0 items-center gap-3 border-b border-border bg-card/80 px-4 backdrop-blur-xl">
          <span className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
            Settings
          </span>
          <div className="ml-2 flex min-w-0 flex-1 gap-1 overflow-x-auto scrollbar-none">
            {SETTINGS_TABS.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                type="button"
                onClick={() => handleTabChange(id)}
                className={`flex h-8 shrink-0 items-center gap-1.5 rounded-sm px-3 text-xs font-medium transition ${
                  activeTab === id
                    ? "bg-primary text-primary-foreground shadow-sm shadow-primary/20"
                    : "text-muted-foreground hover:bg-secondary hover:text-foreground"
                }`}
              >
                <Icon className="h-3.5 w-3.5" />
                {label}
              </button>
            ))}
          </div>
          <button
            type="button"
            className="ml-2 grid h-8 w-8 shrink-0 place-items-center rounded-sm border border-border text-muted-foreground transition hover:bg-secondary hover:text-foreground"
            onClick={onClose}
            aria-label="Close settings"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto">
          <div
            key={animKey}
            className="mx-auto w-full max-w-[1480px] px-3 py-4 sm:px-6 sm:py-8"
            style={{ animation: "fade-in 120ms ease-out" }}
          >
            <ActiveComponent />
          </div>
        </div>
      </div>
    </>
  );
}
