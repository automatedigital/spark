import { useState, useEffect, useRef } from "react";
import {
  ChevronLeft,
  ChevronRight,
  Clock,
  FolderOpen,
  LayoutGrid,
  MessageSquare,
  Package,
  Settings,
} from "lucide-react";
import ConversationsPage from "@/pages/ConversationsPage";
import CronPage from "@/pages/CronPage";
import KanbanPage from "@/pages/KanbanPage";
import SkillsPage from "@/pages/SkillsPage";
import WorkspacePage from "@/pages/WorkspacePage";
import SettingsPanel from "@/components/SettingsPanel";
import { useI18n } from "@/i18n";
import { api, getDashboardToken, setDashboardToken } from "@/lib/api";

const NAV_ITEMS = [
  { id: "workspace", labelKey: "workspace" as const, icon: FolderOpen },
  { id: "kanban", labelKey: "kanban" as const, icon: LayoutGrid },
  { id: "conversations", labelKey: "conversations" as const, icon: MessageSquare },
  { id: "cron", labelKey: "cron" as const, icon: Clock },
  { id: "skills", labelKey: "skills" as const, icon: Package },
] as const;

type PageId = (typeof NAV_ITEMS)[number]["id"];

const PAGE_COMPONENTS: Record<PageId, React.FC> = {
  kanban: KanbanPage,
  workspace: WorkspacePage,
  conversations: ConversationsPage,
  cron: CronPage,
  skills: SkillsPage,
};

const FULL_WIDTH_PAGES = new Set<PageId>(["workspace", "conversations"]);

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
  const [page, setPage] = useState<PageId>(() => {
    const saved = localStorage.getItem("spark-active-page");
    return (saved && NAV_ITEMS.some((item) => item.id === saved)) ? (saved as PageId) : "workspace";
  });
  const [navExpanded, setNavExpanded] = useState(false);
  const [navHovered, setNavHovered] = useState(false);
  const [animKey, setAnimKey] = useState(0);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const initialRef = useRef(true);
  const { t } = useI18n();
  const [authWall, setAuthWall] = useState(false);
  const [tokenHint, setTokenHint] = useState<string | null>(null);
  const [tokenInput, setTokenInput] = useState("");
  const [authChecking, setAuthChecking] = useState(true);
  const [blobPos, setBlobPos] = useState({ x: -400, y: -400 });

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      setBlobPos({ x: e.clientX, y: e.clientY });
    };
    window.addEventListener("mousemove", handleMouseMove);
    return () => window.removeEventListener("mousemove", handleMouseMove);
  }, []);

  const navigateTo = (id: PageId) => {
    setPage(id);
    localStorage.setItem("spark-active-page", id);
  };

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
    if (initialRef.current) {
      initialRef.current = false;
      return;
    }
    setAnimKey((k) => k + 1);
  }, [page]);

  const sidebarOpen = navExpanded || navHovered;

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
      {/* Cursor-following glow blob */}
      <div
        className="cursor-blob"
        style={{ left: blobPos.x, top: blobPos.y }}
        aria-hidden="true"
      />
      {/* Global graphite texture + signal wash */}
      <div className="noise-overlay" />
      <div className="warm-glow" />

      <div className={`relative z-2 grid min-h-screen grid-cols-1 transition-[grid-template-columns] duration-200 md:grid-cols-[var(--sidebar-width)_1fr] ${navExpanded ? "[--sidebar-width:248px]" : "[--sidebar-width:84px]"}`}>
        <aside
          onMouseEnter={() => !navExpanded && setNavHovered(true)}
          onMouseLeave={() => setNavHovered(false)}
          className={`hidden min-w-0 border-r border-border bg-card/78 backdrop-blur-xl md:flex md:flex-col transition-[width] duration-200 ease-in-out${
            navHovered && !navExpanded
              ? " absolute left-0 top-0 bottom-0 z-50 w-[248px] shadow-2xl shadow-black/50"
              : sidebarOpen
              ? " w-[248px]"
              : " w-[84px]"
          }`}
        >
          <div className={`flex h-20 items-center border-b border-border px-4 ${sidebarOpen ? "justify-between" : "justify-center"}`}>
            <span className="grid h-10 w-10 shrink-0 place-items-center">
              <SparkLogo />
            </span>
            {sidebarOpen && (
              <div className="min-w-0 flex-1 px-3">
                <div className="truncate text-sm font-bold uppercase tracking-[0.12em] text-foreground">Spark</div>
                <div className="truncate text-xs text-muted-foreground">Web UI</div>
              </div>
            )}
            <button
              type="button"
              className="grid h-8 w-8 shrink-0 place-items-center rounded-sm border border-border text-muted-foreground transition hover:bg-secondary hover:text-foreground"
              title={navExpanded ? "Collapse navigation" : "Expand navigation"}
              aria-label={navExpanded ? "Collapse navigation" : "Expand navigation"}
              onClick={() => { setNavExpanded((v) => !v); setNavHovered(false); }}
            >
              {navExpanded ? <ChevronLeft className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
            </button>
          </div>
          <nav className={`flex flex-1 flex-col gap-2 px-3 py-4 ${sidebarOpen ? "items-stretch" : "items-center"}`}>
            {NAV_ITEMS.map(({ id, labelKey, icon: Icon }) => (
              <button
                key={id}
                type="button"
                title={t.app.nav[labelKey]}
                aria-label={t.app.nav[labelKey]}
                onClick={() => navigateTo(id)}
                className={`group relative flex h-12 items-center rounded-sm border transition ${
                  page === id
                    ? "border-primary/50 bg-primary text-primary-foreground shadow-lg shadow-primary/15"
                    : "border-transparent text-muted-foreground hover:border-border hover:bg-secondary hover:text-foreground"
                } ${sidebarOpen ? "w-full justify-start gap-3 px-3" : "w-12 justify-center"}`}
              >
                <Icon className="h-5 w-5 shrink-0" />
                {sidebarOpen && (
                  <span className="truncate text-sm font-medium">{t.app.nav[labelKey]}</span>
                )}
                <span className={`pointer-events-none absolute left-[calc(100%+12px)] top-1/2 z-50 -translate-y-1/2 whitespace-nowrap rounded-sm border border-border bg-popover px-2 py-1 text-xs text-popover-foreground shadow-xl ${sidebarOpen ? "hidden" : "hidden group-hover:block"}`}>
                  {t.app.nav[labelKey]}
                </span>
              </button>
            ))}
          </nav>

          {/* Settings button */}
          <div className={`border-t border-border px-3 py-3 ${sidebarOpen ? "items-stretch" : "flex justify-center"}`}>
            <button
              type="button"
              title="Settings"
              aria-label="Settings"
              onClick={() => setSettingsOpen(true)}
              className={`group relative flex h-12 items-center rounded-sm border transition ${
                settingsOpen
                  ? "border-primary/50 bg-primary text-primary-foreground shadow-lg shadow-primary/15"
                  : "border-transparent text-muted-foreground hover:border-border hover:bg-secondary hover:text-foreground"
              } ${sidebarOpen ? "w-full justify-start gap-3 px-3" : "w-12 justify-center"}`}
            >
              <Settings className="h-5 w-5 shrink-0" />
              {sidebarOpen && (
                <span className="truncate text-sm font-medium">Settings</span>
              )}
              <span className={`pointer-events-none absolute left-[calc(100%+12px)] top-1/2 z-50 -translate-y-1/2 whitespace-nowrap rounded-sm border border-border bg-popover px-2 py-1 text-xs text-popover-foreground shadow-xl ${sidebarOpen ? "hidden" : "hidden group-hover:block"}`}>
                Settings
              </span>
            </button>
          </div>

          <div className={`border-t border-border p-3 text-[0.62rem] uppercase tracking-[0.12em] text-muted-foreground ${sidebarOpen ? "text-left" : "text-center"}`}>
            {sidebarOpen ? t.app.footer.name : ""}
          </div>
        </aside>

        <div className="flex min-w-0 flex-col">
          <header className="sticky top-0 z-40 border-b border-border bg-background/82 backdrop-blur-xl">
            <div className="flex min-h-16 items-center gap-3 px-3 sm:px-6">
              <div className="flex items-center gap-3 md:hidden">
                <SparkLogo className="h-6 w-6" />
                <span className="font-collapse text-lg font-bold uppercase tracking-wide">Spark</span>
              </div>
              <div className="hidden md:block">
                <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Spark</div>
                <div className="text-sm font-semibold text-foreground">{t.app.nav[NAV_ITEMS.find((item) => item.id === page)?.labelKey ?? "workspace"]}</div>
              </div>
              {/* Mobile nav */}
              <nav className="ml-auto flex items-center gap-1 overflow-x-auto rounded-sm border border-border bg-card/70 p-1 shadow-inner scrollbar-none md:hidden">
                {NAV_ITEMS.map(({ id, labelKey, icon: Icon }) => (
                  <button
                    key={id}
                    type="button"
                    title={t.app.nav[labelKey]}
                    onClick={() => navigateTo(id)}
                    className={`grid h-9 w-9 shrink-0 place-items-center rounded-sm transition ${
                      page === id ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-secondary hover:text-foreground"
                    }`}
                  >
                    <Icon className="h-4 w-4" />
                  </button>
                ))}
                {/* Settings button for mobile */}
                <button
                  type="button"
                  title="Settings"
                  onClick={() => setSettingsOpen(true)}
                  className={`grid h-9 w-9 shrink-0 place-items-center rounded-sm transition ${
                    settingsOpen ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-secondary hover:text-foreground"
                  }`}
                >
                  <Settings className="h-4 w-4" />
                </button>
              </nav>
              <div className="ml-auto hidden items-center gap-2 md:flex">
                <span className="h-2 w-2 rounded-full bg-primary shadow-[0_0_18px_rgba(253,166,50,0.8)]" />
                <span className="text-xs uppercase tracking-[0.12em] text-muted-foreground">{t.app.webUi}</span>
              </div>
            </div>
          </header>

          <main
            key={animKey}
            className={FULL_WIDTH_PAGES.has(page) ? "relative flex-1 flex flex-col overflow-hidden" : "relative mx-auto w-full max-w-[1480px] flex-1 px-3 py-4 sm:px-6 sm:py-8"}
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

      {settingsOpen && <SettingsPanel onClose={() => setSettingsOpen(false)} />}
    </div>
  );
}
