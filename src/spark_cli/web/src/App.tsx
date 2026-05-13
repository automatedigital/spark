import { useState, useEffect, useRef } from "react";
import {
  Activity,
  BarChart3,
  ChevronLeft,
  ChevronRight,
  Clock,
  FileText,
  FolderOpen,
  KeyRound,
  LayoutGrid,
  MessageSquare,
  Package,
  Settings,
  Shield,
} from "lucide-react";
import StatusPage from "@/pages/StatusPage";
import ConfigPage from "@/pages/ConfigPage";
import EnvPage from "@/pages/EnvPage";
import ConversationsPage from "@/pages/ConversationsPage";
import LogsPage from "@/pages/LogsPage";
import AnalyticsPage from "@/pages/AnalyticsPage";
import CronPage from "@/pages/CronPage";
import SkillsPage from "@/pages/SkillsPage";
import KanbanPage from "@/pages/KanbanPage";
import AdminPage from "@/pages/AdminPage";
import WorkspacePage from "@/pages/WorkspacePage";
import { useI18n } from "@/i18n";
import { api, getDashboardToken, setDashboardToken } from "@/lib/api";

const NAV_ITEMS = [
  { id: "kanban", labelKey: "kanban" as const, icon: LayoutGrid },
  { id: "workspace", labelKey: "workspace" as const, icon: FolderOpen },
  { id: "status", labelKey: "status" as const, icon: Activity },
  { id: "conversations", labelKey: "conversations" as const, icon: MessageSquare },
  { id: "analytics", labelKey: "analytics" as const, icon: BarChart3 },
  { id: "logs", labelKey: "logs" as const, icon: FileText },
  { id: "cron", labelKey: "cron" as const, icon: Clock },
  { id: "skills", labelKey: "skills" as const, icon: Package },
  { id: "admin", labelKey: "admin" as const, icon: Shield },
  { id: "config", labelKey: "config" as const, icon: Settings },
  { id: "env", labelKey: "keys" as const, icon: KeyRound },
] as const;

type PageId = (typeof NAV_ITEMS)[number]["id"];

const PAGE_COMPONENTS: Record<PageId, React.FC> = {
  kanban: KanbanPage,
  workspace: WorkspacePage,
  status: StatusPage,
  conversations: ConversationsPage,
  analytics: AnalyticsPage,
  logs: LogsPage,
  cron: CronPage,
  skills: SkillsPage,
  admin: AdminPage,
  config: ConfigPage,
  env: EnvPage,
};

function SparkLogo({ className = "" }: { className?: string }) {
  return (
    <img
      src="/icon_small-dark.png"
      alt=""
      aria-hidden="true"
      className={`block h-7 w-7 object-contain ${className}`}
      draggable={false}
    />
  );
}

export default function App() {
  const [page, setPage] = useState<PageId>("kanban");
  const [navExpanded, setNavExpanded] = useState(false);
  const [animKey, setAnimKey] = useState(0);
  const initialRef = useRef(true);
  const { t } = useI18n();
  const [authWall, setAuthWall] = useState(false);
  const [tokenHint, setTokenHint] = useState<string | null>(null);
  const [tokenInput, setTokenInput] = useState("");
  const [authChecking, setAuthChecking] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const info = await api.getDashboardAuthInfo();
        if (!cancelled) setTokenHint(info.token_file);
        if (!info.require_auth_nonlocal) {
          if (!cancelled) setAuthWall(false);
          return;
        }
        const storedToken = getDashboardToken();
        const probe = await fetch("/api/config", {
          headers: storedToken
            ? { Authorization: `Bearer ${storedToken}` }
            : undefined,
        });
        if (!cancelled) setAuthWall(probe.status === 401);
      } catch {
        if (!cancelled) setAuthWall(false);
      } finally {
        if (!cancelled) setAuthChecking(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    // Skip the animation key bump on initial mount to avoid re-mounting
    // the default page component (which causes duplicate API requests).
    if (initialRef.current) {
      initialRef.current = false;
      return;
    }
    setAnimKey((k) => k + 1);
  }, [page]);

  const PageComponent = PAGE_COMPONENTS[page];

  const saveToken = () => {
    const trimmed = tokenInput.trim();
    if (!trimmed) return;
    setDashboardToken(trimmed);
    setAuthWall(false);
    setTokenInput("");
    window.location.reload();
  };

  return (
    <div className="min-h-screen bg-background text-foreground overflow-x-hidden">
      {/* Global graphite texture + signal wash */}
      <div className="noise-overlay" />
      <div className="warm-glow" />

      <div className={`relative z-2 grid min-h-screen grid-cols-1 transition-[grid-template-columns] duration-200 md:grid-cols-[var(--sidebar-width)_1fr] ${navExpanded ? "[--sidebar-width:248px]" : "[--sidebar-width:84px]"}`}>
        <aside className="hidden min-w-0 border-r border-border bg-card/78 backdrop-blur-xl md:flex md:flex-col">
          <div className={`flex h-20 items-center border-b border-border px-4 ${navExpanded ? "justify-between" : "justify-center"}`}>
            <span className="grid h-10 w-10 place-items-center rounded-sm border border-primary/35 bg-background shadow-lg shadow-primary/20">
              <SparkLogo />
            </span>
            {navExpanded && (
              <div className="min-w-0 flex-1 px-3">
                <div className="truncate text-sm font-bold uppercase tracking-[0.12em] text-foreground">Spark</div>
                <div className="truncate text-xs text-muted-foreground">Web UI</div>
              </div>
            )}
            <button
              type="button"
              className="grid h-8 w-8 place-items-center rounded-sm border border-border text-muted-foreground transition hover:bg-secondary hover:text-foreground"
              title={navExpanded ? "Collapse navigation" : "Expand navigation"}
              aria-label={navExpanded ? "Collapse navigation" : "Expand navigation"}
              onClick={() => setNavExpanded((value) => !value)}
            >
              {navExpanded ? <ChevronLeft className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
            </button>
          </div>
          <nav className={`flex flex-1 flex-col gap-2 px-3 py-4 ${navExpanded ? "items-stretch" : "items-center"}`}>
            {NAV_ITEMS.map(({ id, labelKey, icon: Icon }) => (
              <button
                key={id}
                type="button"
                title={t.app.nav[labelKey]}
                aria-label={t.app.nav[labelKey]}
                onClick={() => setPage(id)}
                className={`group relative flex h-12 items-center rounded-sm border transition ${
                  page === id
                    ? "border-primary/50 bg-primary text-primary-foreground shadow-lg shadow-primary/15"
                    : "border-transparent text-muted-foreground hover:border-border hover:bg-secondary hover:text-foreground"
                } ${navExpanded ? "w-full justify-start gap-3 px-3" : "w-12 justify-center"}`}
              >
                <Icon className="h-5 w-5" />
                {navExpanded && (
                  <span className="truncate text-sm font-medium">{t.app.nav[labelKey]}</span>
                )}
                <span className={`pointer-events-none absolute left-[calc(100%+12px)] top-1/2 z-50 -translate-y-1/2 whitespace-nowrap rounded-sm border border-border bg-popover px-2 py-1 text-xs text-popover-foreground shadow-xl ${navExpanded ? "hidden" : "hidden group-hover:block"}`}>
                  {t.app.nav[labelKey]}
                </span>
              </button>
            ))}
          </nav>
          <div className={`border-t border-border p-3 text-[0.62rem] uppercase tracking-[0.12em] text-muted-foreground ${navExpanded ? "text-left" : "text-center"}`}>
            {navExpanded ? t.app.footer.name : "Web UI"}
          </div>
        </aside>

        <div className="flex min-w-0 flex-col">
          <header className="sticky top-0 z-40 border-b border-border bg-background/82 backdrop-blur-xl">
            <div className="flex min-h-16 items-center gap-3 px-3 sm:px-6">
              <div className="flex items-center gap-3 md:hidden">
                <span className="grid h-9 w-9 place-items-center rounded-sm border border-primary/35 bg-background shadow-sm shadow-primary/20">
                  <SparkLogo className="h-6 w-6" />
                </span>
                <span className="font-collapse text-lg font-bold uppercase tracking-wide">Spark</span>
              </div>
              <div className="hidden md:block">
                <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Spark</div>
                <div className="text-sm font-semibold text-foreground">{t.app.nav[NAV_ITEMS.find((item) => item.id === page)?.labelKey ?? "kanban"]}</div>
              </div>
              <nav className="ml-auto flex items-center gap-1 overflow-x-auto rounded-sm border border-border bg-card/70 p-1 shadow-inner scrollbar-none md:hidden">
                {NAV_ITEMS.map(({ id, labelKey, icon: Icon }) => (
                  <button
                    key={id}
                    type="button"
                    title={t.app.nav[labelKey]}
                    onClick={() => setPage(id)}
                    className={`grid h-9 w-9 shrink-0 place-items-center rounded-sm transition ${
                      page === id ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-secondary hover:text-foreground"
                    }`}
                  >
                    <Icon className="h-4 w-4" />
                  </button>
                ))}
              </nav>
              <div className="ml-auto hidden items-center gap-2 md:flex">
                <span className="h-2 w-2 rounded-full bg-success shadow-[0_0_18px_rgba(20,184,166,0.75)]" />
                <span className="text-xs uppercase tracking-[0.12em] text-muted-foreground">{t.app.webUi}</span>
              </div>
            </div>
          </header>

          <main
            key={animKey}
            className="relative mx-auto w-full max-w-[1480px] flex-1 px-3 py-4 sm:px-6 sm:py-8"
            style={{ animation: "fade-in 150ms ease-out" }}
          >
            {authChecking ? (
              <div className="mx-auto mt-24 max-w-md rounded-sm border border-border bg-card/90 p-6 text-sm text-muted-foreground shadow-2xl">
                Checking dashboard access...
              </div>
            ) : authWall ? (
              <section className="mx-auto mt-16 grid max-w-5xl grid-cols-1 overflow-hidden rounded-sm border border-border bg-card shadow-2xl md:grid-cols-[1.1fr_0.9fr]">
                <div className="p-7 sm:p-10">
                  <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-primary/25 bg-primary/12 px-3 py-1 text-xs font-medium text-primary">
                    LAN access locked
                  </div>
                  <h1 className="max-w-xl text-3xl font-semibold leading-tight tracking-normal text-foreground sm:text-4xl">
                    Enter your Spark dashboard token to unlock this browser.
                  </h1>
                  <p className="mt-4 max-w-xl text-sm leading-6 text-muted-foreground">
                    Remote dashboard sessions need the token from the Spark host. Paste the contents of{" "}
                    <code>{tokenHint ?? "~/.spark/dashboard.token"}</code>. The token is stored only in this browser.
                  </p>
                  <div className="mt-7 flex flex-col gap-3 sm:flex-row">
                    <input
                      type="password"
                      className="h-11 min-w-0 flex-1 rounded-sm border border-input bg-background px-3 text-sm shadow-inner outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/15"
                      placeholder="Dashboard token"
                      value={tokenInput}
                      onChange={(e) => setTokenInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") saveToken();
                      }}
                      autoFocus
                    />
                    <button
                      type="button"
                      className="h-11 rounded-sm bg-primary px-5 text-sm font-semibold text-primary-foreground shadow-sm transition hover:bg-primary/90"
                      onClick={saveToken}
                    >
                      Unlock
                    </button>
                  </div>
                  <p className="mt-4 text-xs text-muted-foreground">
                    Server-side alternative: set <code>SPARK_DASHBOARD_TOKEN</code> and restart the gateway.
                  </p>
                </div>
                <div className="auth-panel hidden border-l border-border bg-secondary/60 p-8 md:block">
                  <div className="grid h-full content-between">
                    <div>
                      <div className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                        Spark Web UI
                      </div>
                      <div className="mt-8 space-y-3">
                        {["Tasks", "Chat", "Config", "Admin"].map((label) => (
                          <div key={label} className="rounded-sm border border-border bg-background/70 px-4 py-3 text-sm shadow-sm">
                            {label}
                          </div>
                        ))}
                      </div>
                    </div>
                    <div className="text-xs leading-5 text-muted-foreground">
                      Protected routes are not loaded until this token is present, so the board no longer fills with API errors.
                    </div>
                  </div>
                </div>
              </section>
            ) : (
              <PageComponent />
            )}
          </main>
        </div>
      </div>
    </div>
  );
}
