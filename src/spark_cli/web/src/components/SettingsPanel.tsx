import { useState, useEffect } from "react";
import { X, Activity, BarChart3, Brain, FileText, Shield, Settings, KeyRound, Download, Palette } from "lucide-react";
import StatusPage from "@/pages/StatusPage";
import AnalyticsPage from "@/pages/AnalyticsPage";
import LogsPage from "@/pages/LogsPage";
import AdminPage from "@/pages/AdminPage";
import ConfigPage from "@/pages/ConfigPage";
import EnvPage from "@/pages/EnvPage";
import UpdatesPage from "@/pages/UpdatesPage";
import AppearancePage from "@/pages/AppearancePage";
import MemoryPage from "@/pages/MemoryPage";

const SETTINGS_TABS = [
  { id: "status", label: "Status", icon: Activity, component: StatusPage },
  { id: "analytics", label: "Analytics", icon: BarChart3, component: AnalyticsPage },
  { id: "logs", label: "Logs", icon: FileText, component: LogsPage },
  { id: "admin", label: "Admin", icon: Shield, component: AdminPage },
  { id: "appearance", label: "Appearance", icon: Palette, component: AppearancePage },
  { id: "memory", label: "Memory", icon: Brain, component: MemoryPage },
  { id: "config", label: "Config", icon: Settings, component: ConfigPage },
  { id: "keys", label: "Keys", icon: KeyRound, component: EnvPage },
  { id: "updates", label: "Updates", icon: Download, component: UpdatesPage },
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
        className="fixed inset-0 z-50 bg-black/48 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        className="fixed inset-0 z-50 flex items-center justify-center p-4"
        onClick={onClose}
      >
        <div
          className="flex h-[86vh] w-full max-w-6xl overflow-hidden rounded-lg border border-border bg-background/88 shadow-2xl shadow-black/45 backdrop-blur-2xl"
          role="dialog"
          aria-modal="true"
          aria-label="Settings"
          style={{ animation: "fade-in 150ms ease-out" }}
          onClick={(e) => e.stopPropagation()}
        >
          <aside className="hidden w-52 shrink-0 flex-col border-r border-border bg-card/38 p-2 md:flex">
            <div className="flex h-10 items-center px-2">
              <span className="text-sm font-semibold text-foreground">Settings</span>
            </div>
            <div className="mt-2 flex min-w-0 flex-1 flex-col gap-1" role="tablist" aria-label="Settings sections">
              {SETTINGS_TABS.map(({ id, label, icon: Icon }) => (
                <button
                  key={id}
                  type="button"
                  role="tab"
                  aria-selected={activeTab === id}
                  aria-label={label}
                  onClick={() => handleTabChange(id)}
                  className={`relative flex h-8 shrink-0 items-center gap-2 rounded-md px-2.5 text-[13px] font-medium transition ${
                    activeTab === id
                      ? "bg-foreground/9 text-foreground"
                      : "text-muted-foreground hover:bg-foreground/6 hover:text-foreground"
                  }`}
                >
                  {activeTab === id && <span className="absolute left-0 top-1.5 bottom-1.5 w-px rounded-full bg-foreground/70" />}
                  <Icon className="h-4 w-4" />
                  {label}
                </button>
              ))}
            </div>
          </aside>

          <div className="flex min-w-0 flex-1 flex-col">
            <div className="flex h-12 shrink-0 items-center gap-2 border-b border-border bg-card/34 px-3 backdrop-blur-xl">
              <span className="text-sm font-semibold text-foreground md:hidden">Settings</span>
              <div className="flex min-w-0 flex-1 gap-1 overflow-x-auto scrollbar-none md:hidden" role="tablist" aria-label="Settings sections">
                {SETTINGS_TABS.map(({ id, label, icon: Icon }) => (
                  <button
                    key={id}
                    type="button"
                    role="tab"
                    aria-selected={activeTab === id}
                    aria-label={label}
                    onClick={() => handleTabChange(id)}
                    className={`flex h-8 shrink-0 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium transition ${
                      activeTab === id
                        ? "bg-foreground/9 text-foreground"
                        : "text-muted-foreground hover:bg-foreground/6 hover:text-foreground"
                    }`}
                  >
                    <Icon className="h-3.5 w-3.5" />
                    {label}
                  </button>
                ))}
              </div>
              <div className="hidden min-w-0 flex-1 md:block">
                <div className="truncate text-sm font-medium text-foreground">
                  {SETTINGS_TABS.find((t) => t.id === activeTab)?.label}
                </div>
              </div>
              <button
                type="button"
                className="ml-auto grid h-8 w-8 shrink-0 place-items-center rounded-md text-muted-foreground transition hover:bg-foreground/7 hover:text-foreground"
                onClick={onClose}
                aria-label="Close settings"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto">
              <div
                key={animKey}
                className="mx-auto w-full px-4 py-5 sm:px-8 sm:py-8"
                style={{ animation: "fade-in 120ms ease-out" }}
              >
                <ActiveComponent />
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
