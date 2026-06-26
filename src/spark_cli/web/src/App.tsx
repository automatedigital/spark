import { useState, useEffect, useRef } from "react";
import {
  Blocks,
  ChevronLeft,
  ChevronRight,
  Clock,
  Download,
  FolderOpen,
  LayoutGrid,
  MessageCircle,
  MoreHorizontal,
  Plus,
  Settings,
  Square,
} from "lucide-react";
import ChatPage from "@/pages/ChatPage";
import CronPage from "@/pages/CronPage";
import FilesPage from "@/pages/FilesPage";
import KanbanPage from "@/pages/KanbanPage";
import CanvasPage from "@/pages/CanvasPage";
import SkillsPage from "@/pages/SkillsPage";
import ConnectorsPage from "@/pages/ConnectorsPage";
import SkillsToolsPage from "@/pages/SkillsToolsPage";
import MessagingPage from "@/pages/MessagingPage";
import SettingsPanel from "@/components/SettingsPanel";
import { SidebarSessions } from "@/components/sidebar/SidebarSessions";
import { SessionStoreProvider, useSessionStore } from "@/lib/sessionStore";
import { useI18n } from "@/i18n";
import { api, getDashboardToken, setDashboardToken, getConnectionMode, getRemoteBaseUrl, getApiBase } from "@/lib/api";
import { displayHost } from "@/lib/connection";
import { useUpdateModal } from "@/lib/updateModal";
import { CommandPalette } from "@/components/CommandPalette";
import { KeyboardShortcutsModal } from "@/components/KeyboardShortcutsModal";
import { GlobalToasts } from "@/components/GlobalToasts";
import { NotificationBell } from "@/components/NotificationBell";
import { CodexUsageBadge } from "@/components/CodexUsageBadge";
import { OnboardingWizard } from "@/components/OnboardingWizard";
import { BrandLogo } from "@/components/BrandLogo";
import { GLOBAL_NAV_EVENT, setGlobalNavTarget, type GlobalNavTarget } from "@/lib/globalNavigation";
import { onDeepLink, onNewChat, deepLinkToNavTarget, hideAgentCursor, updateAgentCursor } from "@/lib/desktop";
import { isTauri } from "@/sidecar";
import { useEventBus } from "@/hooks/useEventBus";


// Primary sections shown after the "New session" action.
const PRIMARY_NAV = [
  { id: "skillsTools", labelKey: "skillsAndTools" as const, icon: Blocks },
  { id: "messaging", labelKey: "messaging" as const, icon: MessageCircle },
  { id: "files", labelKey: "files" as const, icon: FolderOpen },
  { id: "cron", labelKey: "cron" as const, icon: Clock },
] as const;

// Demoted pages — reachable via the "More" menu + command palette.
const MORE_NAV = [
  { id: "canvas", labelKey: "canvas" as const, icon: Square },
  { id: "kanban", labelKey: "kanban" as const, icon: LayoutGrid },
] as const;

const PAGE_COMPONENTS = {
  chat: ChatPage,
  kanban: KanbanPage,
  cron: CronPage,
  skills: SkillsPage,
  files: FilesPage,
  canvas: CanvasPage,
  connectors: ConnectorsPage,
  skillsTools: SkillsToolsPage,
  messaging: MessagingPage,
} as const;

type PageId = keyof typeof PAGE_COMPONENTS;

type NavLabelKey =
  | (typeof PRIMARY_NAV)[number]["labelKey"]
  | (typeof MORE_NAV)[number]["labelKey"]
  | "chat"
  | "newSession"
  | "skills"
  | "connectors";

const PAGE_LABEL_KEYS: Record<PageId, NavLabelKey> = {
  chat: "chat",
  files: "files",
  canvas: "canvas",
  kanban: "kanban",
  cron: "cron",
  skills: "skills",
  connectors: "connectors",
  skillsTools: "skillsAndTools",
  messaging: "messaging",
};

const FULL_WIDTH_PAGES = new Set<PageId>(["chat", "files", "canvas", "messaging", "skillsTools"]);

function pageForGlobalNavTarget(target: GlobalNavTarget): PageId {
  switch (target.type) {
    case "canvas":
      return "canvas";
    case "file":
      return "files";
    case "task":
      return "kanban";
    case "scheduled-task":
      return "cron";
    case "skill":
      return "skills";
    case "thread":
    case "project":
    default:
      return "chat";
  }
}

function formatVersionDate(date = new Date()) {
  const day = String(date.getDate()).padStart(2, "0");
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const year = String(date.getFullYear()).slice(-2);
  return `${day}${month}${year}`;
}

function numberFrom(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function pointerFromComputerUse(data: Record<string, unknown>): { screenX: number; screenY: number; label?: string } | null {
  const result = typeof data.result === "string" ? data.result : "";
  if (!result) return null;
  try {
    const parsed = JSON.parse(result) as { data?: { pointer?: Record<string, unknown> } };
    const pointer = parsed.data?.pointer;
    if (!pointer) return null;
    const screenX = numberFrom(pointer.screen_x);
    const screenY = numberFrom(pointer.screen_y);
    if (screenX !== null && screenY !== null) {
      return {
        screenX,
        screenY,
        label: typeof pointer.kind === "string" ? pointer.kind : undefined,
      };
    }
    const windowX = numberFrom(pointer.window_x);
    const windowY = numberFrom(pointer.window_y);
    const x = numberFrom(pointer.x);
    const y = numberFrom(pointer.y);
    if (windowX !== null && windowY !== null && x !== null && y !== null) {
      return {
        screenX: windowX + x,
        screenY: windowY + y,
        label: typeof pointer.kind === "string" ? pointer.kind : undefined,
      };
    }
  } catch {
    /* best effort only */
  }
  return null;
}

function actionLabelFromComputerUse(data: Record<string, unknown>, fallback = "Agent") {
  const args = (data.args && typeof data.args === "object" ? data.args : {}) as Record<string, unknown>;
  const action = args.action;
  if (typeof action !== "string" || !action.trim()) return fallback;
  return action.replace(/_/g, " ");
}

function scheduleAgentCursorHide(timerRef: React.MutableRefObject<ReturnType<typeof setTimeout> | null>) {
  timerRef.current = setTimeout(() => {
    void hideAgentCursor();
  }, 1400);
}

function SparkLogo({ className = "" }: { className?: string }) {
  return <BrandLogo className={`h-7 w-7 ${className}`} />;
}

// ── More menu (demoted pages: Chat, Canvas, Kanban) ──────────────────────────

function MoreMenu({
  page,
  navigateTo,
  runningTaskCount,
  sidebarOpen,
  direction,
  navLabel,
}: {
  page: PageId;
  navigateTo: (id: PageId) => void;
  runningTaskCount: number;
  sidebarOpen: boolean;
  direction: "up" | "down";
  navLabel: (key: NavLabelKey) => string;
}) {
  const [open, setOpen] = useState(false);
  const moreActive = MORE_NAV.some((item) => item.id === page);

  return (
    <div className="relative">
      <button
        type="button"
        title="More"
        aria-label="More pages"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className={`group relative flex h-8 items-center rounded-md transition ${
          moreActive || open
            ? "bg-foreground/10 text-foreground"
            : "text-muted-foreground hover:bg-foreground/6 hover:text-foreground"
        } ${sidebarOpen ? "w-full justify-start gap-2.5 px-2.5" : "w-8 justify-center"}`}
      >
        <div className="relative shrink-0">
          <MoreHorizontal className="h-4 w-4" />
          {runningTaskCount > 0 && (
            <span className="absolute -right-1.5 -top-1.5 flex h-4 w-4 items-center justify-center rounded-full bg-amber-500 text-[9px] font-bold text-white ring-2 ring-background">
              {runningTaskCount > 9 ? "9+" : runningTaskCount}
            </span>
          )}
        </div>
        {sidebarOpen && <span className="truncate text-[13px] font-medium">More</span>}
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} aria-hidden="true" />
          <div
            className={`z-50 w-44 rounded-md border border-border bg-popover/95 p-1 shadow-xl backdrop-blur-xl ${
              direction === "up" ? "absolute bottom-full left-0 mb-1" : "fixed right-2 top-12"
            }`}
            role="menu"
          >
            {MORE_NAV.map(({ id, labelKey, icon: Icon }) => (
              <button
                key={id}
                type="button"
                role="menuitem"
                onClick={() => {
                  navigateTo(id);
                  setOpen(false);
                }}
                className={`flex w-full items-center gap-2.5 rounded-sm px-2.5 py-1.5 text-left text-[13px] transition ${
                  page === id
                    ? "bg-foreground/10 text-foreground"
                    : "text-muted-foreground hover:bg-foreground/6 hover:text-foreground"
                }`}
              >
                <Icon className="h-4 w-4 shrink-0" />
                <span className="flex-1 truncate">{navLabel(labelKey)}</span>
                {id === "kanban" && runningTaskCount > 0 && (
                  <span className="flex h-4 min-w-4 items-center justify-center rounded-full bg-amber-500 px-1 text-[9px] font-bold text-white">
                    {runningTaskCount > 9 ? "9+" : runningTaskCount}
                  </span>
                )}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

export default function App() {
  return (
    <SessionStoreProvider>
      <AppShell />
    </SessionStoreProvider>
  );
}

function AppShell() {
  const [page, setPage] = useState<PageId>(() => {
    const saved = localStorage.getItem("spark-active-page");
    return saved && saved in PAGE_COMPONENTS ? (saved as PageId) : "chat";
  });
  const [navExpanded, setNavExpanded] = useState(() => {
    const saved = localStorage.getItem("spark-nav-expanded");
    return saved === null ? true : saved === "true";
  });
  const [navHovered, setNavHovered] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);

  // Pages (e.g. Skills & Tools → "Manage MCP servers") can open Settings.
  useEffect(() => {
    const handler = () => setSettingsOpen(true);
    window.addEventListener("spark-open-settings", handler);
    return () => window.removeEventListener("spark-open-settings", handler);
  }, []);
  const { t } = useI18n();
  const [authWall, setAuthWall] = useState(false);
  const [tokenHint, setTokenHint] = useState<string | null>(null);
  const [tokenInput, setTokenInput] = useState("");
  const [authChecking, setAuthChecking] = useState(true);
  const [blobPos, setBlobPos] = useState({ x: -400, y: -400 });
  const [versionLabel, setVersionLabel] = useState(`v${formatVersionDate()}`);
  const [gatewayReady, setGatewayReady] = useState(false);
  const [scheduledJobCount, setScheduledJobCount] = useState(0);
  const [activeModel, setActiveModel] = useState<string | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const agentCursorHideTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastAgentCursorRef = useRef<{ screenX: number; screenY: number } | null>(null);
  const { updateAvailable, latestVersion, openUpdateModal, macUpdateAvailable, macLatestVersion, openMacUpdateModal } = useUpdateModal();
  const [needsOnboarding, setNeedsOnboarding] = useState<boolean | null>(null);

  // ── Activity badge counts ──
  const [runningTaskCount, setRunningTaskCount] = useState(0);

  // ── Shared session store (global sidebar + ChatPage) ──
  const { selectSession, newProjectThread } = useSessionStore();

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      setBlobPos({ x: e.clientX, y: e.clientY });
    };
    window.addEventListener("mousemove", handleMouseMove);
    return () => window.removeEventListener("mousemove", handleMouseMove);
  }, []);

  useEventBus((env) => {
    if (!isTauri()) return;
    const data = env.data ?? {};
    if (data.name !== "computer_use") return;

    if (agentCursorHideTimer.current) {
      clearTimeout(agentCursorHideTimer.current);
      agentCursorHideTimer.current = null;
    }

    const nextPointer = pointerFromComputerUse(data);
    const label = nextPointer?.label ?? actionLabelFromComputerUse(data);
    if (env.topic === "chat.tool_start") {
      const lastPointer = lastAgentCursorRef.current;
      if (lastPointer) {
        void updateAgentCursor(lastPointer.screenX, lastPointer.screenY, label, true);
      }
      return;
    }

    if (env.topic === "chat.tool_end") {
      if (nextPointer) {
        lastAgentCursorRef.current = {
          screenX: nextPointer.screenX,
          screenY: nextPointer.screenY,
        };
        void updateAgentCursor(nextPointer.screenX, nextPointer.screenY, label, false);
      }
      scheduleAgentCursorHide(agentCursorHideTimer);
    }
  });

  useEffect(() => {
    return () => {
      if (agentCursorHideTimer.current) clearTimeout(agentCursorHideTimer.current);
      void hideAgentCursor();
    };
  }, []);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setPaletteOpen((o) => !o);
      } else if (e.key === "?" && !e.metaKey && !e.ctrlKey) {
        const tag = (e.target as HTMLElement).tagName;
        if (tag !== "INPUT" && tag !== "TEXTAREA" && !(e.target as HTMLElement).isContentEditable) {
          setShortcutsOpen((o) => !o);
        }
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  const navigateTo = (id: PageId) => {
    setPage(id);
    localStorage.setItem("spark-active-page", id);
  };

  const navLabel = (key: NavLabelKey) => t.app.nav[key];

  // "New session" — clear selection so ChatPage shows the hero composer.
  // Same path as the desktop tray "new chat" action.
  const handleNewSession = () => {
    navigateTo("chat");
    window.dispatchEvent(new CustomEvent("spark-new-chat"));
  };

  const openSidebarSession = (id: string) => {
    navigateTo("chat");
    selectSession(id);
  };

  const openProjectCompose = (slug: string) => {
    navigateTo("chat");
    newProjectThread(slug);
  };

  // ── Desktop shell: tray "new chat" + spark:// deep links (§3.2) ──
  useEffect(() => {
    if (!isTauri()) return;
    let disposed = false;
    const unsubs: Array<() => void> = [];

    void onNewChat(() => {
      navigateTo("chat");
      // ChatPage listens for this to spin up a fresh thread.
      window.dispatchEvent(new CustomEvent("spark-new-chat"));
    }).then((u) => (disposed ? u() : unsubs.push(u)));

    void onDeepLink((url) => {
      const target = deepLinkToNavTarget(url);
      if (!target) return;
      navigateTo(pageForGlobalNavTarget(target));
      setGlobalNavTarget(target);
    }).then((u) => (disposed ? u() : unsubs.push(u)));

    return () => {
      disposed = true;
      unsubs.forEach((u) => u());
    };
  }, []);

  // Global nav switches to the owning page first; that page consumes the
  // one-shot localStorage target after it mounts.
  useEffect(() => {
    const handler = (event: Event) => {
      const target = (event as CustomEvent<GlobalNavTarget>).detail;
      if (target) navigateTo(pageForGlobalNavTarget(target));
    };
    window.addEventListener(GLOBAL_NAV_EVENT, handler);
    return () => window.removeEventListener(GLOBAL_NAV_EVENT, handler);
  }, []);

  const toggleNav = (value: boolean) => {
    setNavExpanded(value);
    setNavHovered(false);
    localStorage.setItem("spark-nav-expanded", String(value));
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
        const probe = await fetch(`${getApiBase()}/api/config`, {
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

  // ── Live status footer: poll every ~8s (paused while tab is hidden) ──
  useEffect(() => {
    let cancelled = false;
    let interval: ReturnType<typeof setInterval> | null = null;

    const fetchStatus = async () => {
      try {
        const [status, modelStatus, cronJobs] = await Promise.all([
          api.getStatus(),
          api.getModelStatus().catch(() => null),
          api.getCronJobs().catch(() => []),
        ]);
        if (!cancelled) {
          setVersionLabel(`v${status.version}_${formatVersionDate()}`);
          setGatewayReady(status.gateway_running);
          setScheduledJobCount(cronJobs.length);
          setActiveModel(
            modelStatus
              ? (modelStatus.multi_model_enabled && modelStatus.fast_model) ||
                  modelStatus.smart_model ||
                  null
              : null,
          );
        }
      } catch {
        if (!cancelled) {
          setVersionLabel(`v${formatVersionDate()}`);
          setGatewayReady(false);
        }
      }
    };

    const startPolling = () => {
      if (interval !== null) return;
      void fetchStatus();
      interval = setInterval(() => void fetchStatus(), 8_000);
    };

    const stopPolling = () => {
      if (interval !== null) {
        clearInterval(interval);
        interval = null;
      }
    };

    const handleVisibility = () => {
      if (document.visibilityState === "hidden") {
        stopPolling();
      } else {
        startPolling();
      }
    };

    if (document.visibilityState !== "hidden") startPolling();
    document.addEventListener("visibilitychange", handleVisibility);

    return () => {
      cancelled = true;
      stopPolling();
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, []);


  // ── First-run onboarding gate ──
  useEffect(() => {
    let cancelled = false;
    const onboardingKey = isTauri()
      ? "spark-desktop-onboarding-complete"
      : "spark-onboarding-complete";

    // Browser: trust local opt-out. Desktop uses a separate key (same origin as
    // spark dashboard in a browser tab would otherwise skip onboarding).
    if (!isTauri() && localStorage.getItem(onboardingKey)) {
      setNeedsOnboarding(false);
      return;
    }

    const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

    (async () => {
      const attempts = isTauri() ? 24 : 1;
      for (let i = 0; i < attempts; i++) {
        try {
          const status = await api.getOnboardingStatus();
          if (cancelled) return;
          if (status.needs_onboarding) {
            setNeedsOnboarding(true);
            return;
          }
          if (localStorage.getItem(onboardingKey)) {
            setNeedsOnboarding(false);
            return;
          }
          setNeedsOnboarding(false);
          return;
        } catch {
          if (i < attempts - 1) await sleep(500);
        }
      }
      if (!cancelled) {
        // Desktop: if the API never answered, show onboarding rather than skip it.
        setNeedsOnboarding(
          isTauri() ? !localStorage.getItem(onboardingKey) : false,
        );
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // ── Activity counts: initial fetch ──
  useEffect(() => {
    // Running kanban tasks — poll every 30s (kanban has its own SSE in KanbanPage)
    const fetchKanban = () => {
      api.getKanbanBoard({ board: "default", tenant: null, assignee: null, q: null })
        .then((b) => setRunningTaskCount(b.columns?.running?.length ?? 0))
        .catch(() => {});
    };
    fetchKanban();
    const interval = setInterval(fetchKanban, 30_000);
    return () => clearInterval(interval);
  }, []);

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

  if (needsOnboarding) {
    return <OnboardingWizard onComplete={() => setNeedsOnboarding(false)} />;
  }

  return (
    <div className="h-screen overflow-hidden bg-background text-foreground">
      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        onNavigate={(id) => navigateTo(id as PageId)}
        onOpenSettings={() => setSettingsOpen(true)}
      />
      <KeyboardShortcutsModal open={shortcutsOpen} onClose={() => setShortcutsOpen(false)} />
      <GlobalToasts />

      {/* Cursor-following glow blob */}
      <div
        className="cursor-blob"
        style={{ left: blobPos.x, top: blobPos.y }}
        aria-hidden="true"
      />
      {/* Global graphite texture + signal wash */}
      <div className="noise-overlay" />
      <div className="warm-glow" />

      <div className={`relative z-2 grid h-full grid-cols-1 transition-[grid-template-columns] duration-200 md:grid-cols-[var(--sidebar-width)_1fr] ${navExpanded ? "[--sidebar-width:224px]" : "[--sidebar-width:58px]"}`}>
        <aside
          onMouseEnter={() => !navExpanded && setNavHovered(true)}
          onMouseLeave={() => setNavHovered(false)}
          className={`hidden min-h-0 min-w-0 overflow-hidden border-r border-border bg-card/58 backdrop-blur-xl md:flex md:flex-col transition-[width] duration-200 ease-in-out${
            navHovered && !navExpanded
              ? " absolute left-0 top-0 bottom-0 z-50 w-[224px] shadow-2xl shadow-black/35"
              : sidebarOpen
              ? " w-[224px]"
              : " w-[58px]"
          }`}
        >
          <div className={`flex h-12 items-center border-b border-border px-2.5 ${sidebarOpen ? "justify-between" : "justify-center"}`}>
            <button
              type="button"
              className={`flex shrink-0 items-center gap-0 rounded-md transition hover:bg-foreground/6 cursor-pointer ${sidebarOpen ? "h-8 w-auto" : "h-8 w-8 justify-center"}`}
              title="Go to Chat"
              aria-label="Go to Chat"
              onClick={() => navigateTo("chat")}
            >
              <div className="grid h-8 w-8 shrink-0 place-items-center">
                <SparkLogo className="h-5 w-5" />
              </div>
              {sidebarOpen && (
                <div className="min-w-0 flex-1 px-2 text-left">
                  <div className="truncate text-sm font-semibold text-foreground">Spark</div>
                </div>
              )}
            </button>
            <button
              type="button"
              className="grid h-7 w-7 shrink-0 place-items-center rounded-md text-muted-foreground transition hover:bg-foreground/7 hover:text-foreground"
              title={navExpanded ? "Collapse navigation" : "Expand navigation"}
              aria-label={navExpanded ? "Collapse navigation" : "Expand navigation"}
              onClick={() => toggleNav(!navExpanded)}
            >
              {navExpanded ? <ChevronLeft className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
            </button>
          </div>
          <nav className={`flex shrink-0 flex-col gap-1 px-2 pt-3 ${sidebarOpen ? "items-stretch" : "items-center"}`}>
            {/* New session */}
            <button
              type="button"
              title={navLabel("newSession")}
              aria-label={navLabel("newSession")}
              onClick={handleNewSession}
              className={`group relative flex h-8 items-center rounded-md text-muted-foreground transition hover:bg-foreground/6 hover:text-foreground ${sidebarOpen ? "w-full justify-start gap-2.5 px-2.5" : "w-8 justify-center"}`}
            >
              <Plus className="h-4 w-4 shrink-0" />
              {sidebarOpen && (
                <span className="truncate text-[13px] font-medium">{navLabel("newSession")}</span>
              )}
              <span className={`pointer-events-none absolute left-[calc(100%+10px)] top-1/2 z-50 -translate-y-1/2 whitespace-nowrap rounded-md border border-border bg-popover/95 px-2 py-1 text-xs text-popover-foreground shadow-xl backdrop-blur-xl ${sidebarOpen ? "hidden" : "hidden group-hover:block"}`}>
                {navLabel("newSession")}
              </span>
            </button>
            {PRIMARY_NAV.map(({ id, labelKey, icon: Icon }) => (
              <button
                key={id}
                type="button"
                title={navLabel(labelKey)}
                aria-label={navLabel(labelKey)}
                onClick={() => navigateTo(id)}
                className={`group relative flex h-8 items-center rounded-md transition ${
                  page === id
                    ? "bg-foreground/10 text-foreground"
                    : "text-muted-foreground hover:bg-foreground/6 hover:text-foreground"
                } ${sidebarOpen ? "w-full justify-start gap-2.5 px-2.5" : "w-8 justify-center"}`}
              >
                {page === id && sidebarOpen && (
                  <span className="absolute left-0 top-1.5 bottom-1.5 w-px rounded-full bg-foreground/70" />
                )}
                <Icon className="h-4 w-4 shrink-0" />
                {sidebarOpen && (
                  <span className="truncate text-[13px] font-medium">{navLabel(labelKey)}</span>
                )}
                <span className={`pointer-events-none absolute left-[calc(100%+10px)] top-1/2 z-50 -translate-y-1/2 whitespace-nowrap rounded-md border border-border bg-popover/95 px-2 py-1 text-xs text-popover-foreground shadow-xl backdrop-blur-xl ${sidebarOpen ? "hidden" : "hidden group-hover:block"}`}>
                  {navLabel(labelKey)}
                </span>
              </button>
            ))}
          </nav>

          {/* Search + Pinned + Sessions (hidden when collapsed; hover-expand reveals) */}
          {sidebarOpen ? (
            <SidebarSessions
              onOpenSession={openSidebarSession}
              onNewProjectThread={openProjectCompose}
            />
          ) : (
            <div className="flex-1" />
          )}

          {/* More + Settings + Update buttons */}
          <div className={`border-t border-border px-2 py-2 flex flex-col gap-1 ${sidebarOpen ? "items-stretch" : "items-center"}`}>
            <MoreMenu
              page={page}
              navigateTo={navigateTo}
              runningTaskCount={runningTaskCount}
              sidebarOpen={sidebarOpen}
              direction="up"
              navLabel={navLabel}
            />
            {!isTauri() && updateAvailable && (
              <button
                type="button"
                title="Update available"
                aria-label="Update Spark"
                onClick={openUpdateModal}
                className={`group relative flex h-8 items-center rounded-md transition bg-amber-500/10 text-amber-300 hover:bg-amber-500/16 ${sidebarOpen ? "w-full justify-start gap-2.5 px-2.5" : "w-8 justify-center"}`}
              >
                <Download className="h-4 w-4 shrink-0" />
                {sidebarOpen && (
                  <span className="truncate text-[13px] font-medium">Update available</span>
                )}
                <span className={`pointer-events-none absolute left-[calc(100%+12px)] top-1/2 z-50 -translate-y-1/2 whitespace-nowrap rounded-sm border border-border bg-popover px-2 py-1 text-xs text-popover-foreground shadow-xl ${sidebarOpen ? "hidden" : "hidden group-hover:block"}`}>
                  Update available{latestVersion ? ` · ${latestVersion}` : ""}
                </span>
              </button>
            )}
            {macUpdateAvailable && (
              <button
                type="button"
                title="macOS app update available"
                aria-label="Update macOS App"
                onClick={openMacUpdateModal}
                className={`group relative flex h-8 items-center rounded-md transition bg-amber-500/10 text-amber-300 hover:bg-amber-500/16 ${sidebarOpen ? "w-full justify-start gap-2.5 px-2.5" : "w-8 justify-center"}`}
              >
                <Download className="h-4 w-4 shrink-0" />
                {sidebarOpen && (
                  <span className="truncate text-[13px] font-medium">App update available</span>
                )}
                <span className={`pointer-events-none absolute left-[calc(100%+12px)] top-1/2 z-50 -translate-y-1/2 whitespace-nowrap rounded-sm border border-border bg-popover px-2 py-1 text-xs text-popover-foreground shadow-xl ${sidebarOpen ? "hidden" : "hidden group-hover:block"}`}>
                  macOS app update{macLatestVersion ? ` · v${macLatestVersion}` : ""}
                </span>
              </button>
            )}
            <button
              type="button"
              title="Settings"
              aria-label="Settings"
              onClick={() => setSettingsOpen(true)}
              className={`group relative flex h-8 items-center rounded-md transition ${
                settingsOpen
                  ? "bg-foreground/10 text-foreground"
                  : "text-muted-foreground hover:bg-foreground/6 hover:text-foreground"
              } ${sidebarOpen ? "w-full justify-start gap-2.5 px-2.5" : "w-8 justify-center"}`}
            >
              <Settings className="h-4 w-4 shrink-0" />
              {sidebarOpen && (
                <span className="truncate text-[13px] font-medium">Settings</span>
              )}
              <span className={`pointer-events-none absolute left-[calc(100%+12px)] top-1/2 z-50 -translate-y-1/2 whitespace-nowrap rounded-sm border border-border bg-popover px-2 py-1 text-xs text-popover-foreground shadow-xl ${sidebarOpen ? "hidden" : "hidden group-hover:block"}`}>
                Settings
              </span>
            </button>
          </div>
        </aside>

        <div className="relative flex min-w-0 flex-col h-full overflow-hidden md:col-start-2">
          {navHovered && !navExpanded && (
            <div className="pointer-events-none absolute inset-0 z-10 bg-background/40 backdrop-blur-sm transition-opacity duration-200" />
          )}
          <header className="sticky top-0 z-40 border-b border-border bg-background/72 backdrop-blur-xl">
            <div className="flex min-h-12 items-center gap-3 px-3 sm:px-4">
              <div className="flex items-center gap-3 md:hidden">
                <SparkLogo className="h-5 w-5" />
                <span className="text-sm font-semibold">Spark</span>
              </div>
              <div className="hidden md:block">
                <div className="text-[13px] font-medium text-foreground">{navLabel(PAGE_LABEL_KEYS[page])}</div>
              </div>
              {/* Mobile nav */}
              <nav className="ml-auto flex items-center gap-1 overflow-x-auto rounded-md bg-card/45 p-1 scrollbar-none md:hidden">
                <button
                  type="button"
                  title={navLabel("newSession")}
                  onClick={handleNewSession}
                  className="relative grid h-8 w-8 shrink-0 place-items-center rounded-md text-muted-foreground transition hover:bg-foreground/7 hover:text-foreground"
                >
                  <Plus className="h-4 w-4" />
                </button>
                {PRIMARY_NAV.map(({ id, labelKey, icon: Icon }) => (
                  <button
                    key={id}
                    type="button"
                    title={navLabel(labelKey)}
                    onClick={() => navigateTo(id)}
                    className={`relative grid h-8 w-8 shrink-0 place-items-center rounded-md transition ${
                      page === id ? "bg-foreground/10 text-foreground" : "text-muted-foreground hover:bg-foreground/7 hover:text-foreground"
                    }`}
                  >
                    <Icon className="h-4 w-4" />
                  </button>
                ))}
                <MoreMenu
                  page={page}
                  navigateTo={navigateTo}
                  runningTaskCount={runningTaskCount}
                  sidebarOpen={false}
                  direction="down"
                  navLabel={navLabel}
                />
                {/* Settings button for mobile */}
                <button
                  type="button"
                  title="Settings"
                  onClick={() => setSettingsOpen(true)}
                  className={`grid h-8 w-8 shrink-0 place-items-center rounded-md transition ${
                    settingsOpen ? "bg-foreground/10 text-foreground" : "text-muted-foreground hover:bg-foreground/7 hover:text-foreground"
                  }`}
                >
                  <Settings className="h-4 w-4" />
                </button>
              </nav>
              <div className="ml-auto hidden items-center gap-2 md:flex">
                <CodexUsageBadge />
                <NotificationBell />
                <span className="text-xs text-muted-foreground">{versionLabel}</span>
              </div>
            </div>
          </header>

          <main
            key={page}
            className={FULL_WIDTH_PAGES.has(page) ? "relative flex-1 flex flex-col overflow-hidden" : "relative mx-auto min-h-0 w-full max-w-[1320px] flex-1 overflow-y-auto px-3 py-4 sm:px-5 sm:py-6"}
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
          {!authChecking && !authWall && (
            <footer className="hidden h-7 shrink-0 items-center gap-3 border-t border-border/60 bg-card/35 px-3 text-[11px] text-muted-foreground backdrop-blur md:flex">
              <span className="inline-flex items-center gap-1.5">
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    gatewayReady ? "bg-emerald-400" : "bg-muted-foreground/45"
                  }`}
                />
                {gatewayReady ? "Gateway ready" : "Gateway offline"}
              </span>
              <span className="text-border">·</span>
              <span>
                {getConnectionMode() === "remote"
                  ? `Remote @ ${displayHost(getRemoteBaseUrl()) || "remote"}`
                  : "Local"}
              </span>
              <span className="text-border">·</span>
              <span>Agents {runningTaskCount}</span>
              <span className="text-border">·</span>
              <span>Cron {scheduledJobCount}</span>
              {activeModel && (
                <>
                  <span className="text-border">·</span>
                  <span className="max-w-48 truncate">{activeModel}</span>
                </>
              )}
              <span className="ml-auto">{versionLabel}</span>
            </footer>
          )}
        </div>
      </div>

      {settingsOpen && <SettingsPanel onClose={() => setSettingsOpen(false)} />}
    </div>
  );
}
