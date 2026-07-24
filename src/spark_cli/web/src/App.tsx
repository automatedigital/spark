import { lazy, memo, useState, useEffect, useRef } from "react";
import {
  Clock,
  Download,
  FolderOpen,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Settings,
} from "lucide-react";
import ChatPage from "@/pages/ChatPage";
import { InboxSidebarSessions } from "@/components/sidebar/InboxSidebarSessions";
import { SessionStoreProvider, useSessionStore } from "@/lib/sessionStore";
import { useI18n } from "@/i18n";
import { api, getDashboardToken, setDashboardToken, getApiBase } from "@/lib/api";
import type { StatusResponse } from "@/lib/api";
import { useUpdateModal } from "@/lib/updateModal";
import { GlobalToasts } from "@/components/GlobalToasts";
import { NotificationBell } from "@/components/NotificationBell";
import { CodexUsageBadge } from "@/components/CodexUsageBadge";
import { BrandLogo } from "@/components/BrandLogo";
import { LazyLoadBoundary } from "@/components/LazyLoadBoundary";
import { CursorGlow } from "@/components/CursorGlow";
import { GLOBAL_NAV_EVENT, setGlobalNavTarget, type GlobalNavTarget } from "@/lib/globalNavigation";
import { onDeepLink, onNewChat, deepLinkToNavTarget, hideAgentCursor, updateAgentCursor } from "@/lib/desktop";
import { isTauri } from "@/sidecar";
import { useEventBus } from "@/hooks/useEventBus";
import { gatewayFooterState } from "@/lib/gatewayFooterState";
import { recordActivePageRender } from "@/lib/renderHealth";
import {
  isEditableShortcutTarget,
  isSidebarToggleShortcut,
  readSidebarExpanded,
  writeSidebarExpanded,
} from "@/lib/sidebarPrefs";


// Primary sections shown after the "New chat" action.
const PRIMARY_NAV = [
  { id: "files", labelKey: "files" as const, icon: FolderOpen },
  { id: "cron", labelKey: "cron" as const, icon: Clock },
] as const;

const CronPage = lazy(() => import("@/pages/CronPage"));
const FilesPage = lazy(() => import("@/pages/FilesPage"));
const SkillsPage = lazy(() => import("@/pages/SkillsPage"));
const ConnectorsPage = lazy(() => import("@/pages/ConnectorsPage"));
const SkillsToolsPage = lazy(() => import("@/pages/SkillsToolsPage"));
const MessagingPage = lazy(() => import("@/pages/MessagingPage"));
const SettingsPanel = lazy(() => import("@/components/SettingsPanel"));
const CommandPalette = lazy(() =>
  import("@/components/CommandPalette").then((module) => ({ default: module.CommandPalette })),
);
const KeyboardShortcutsModal = lazy(() =>
  import("@/components/KeyboardShortcutsModal").then((module) => ({ default: module.KeyboardShortcutsModal })),
);
const OnboardingWizard = lazy(() =>
  import("@/components/OnboardingWizard").then((module) => ({ default: module.OnboardingWizard })),
);

const PAGE_COMPONENTS = {
  chat: ChatPage,
  cron: CronPage,
  skills: SkillsPage,
  files: FilesPage,
  connectors: ConnectorsPage,
  skillsTools: SkillsToolsPage,
  messaging: MessagingPage,
} as const;

type PageId = keyof typeof PAGE_COMPONENTS;

type NavLabelKey =
  | (typeof PRIMARY_NAV)[number]["labelKey"]
  | "chat"
  | "newSession"
  | "skills"
  | "connectors"
  | "skillsAndTools"
  | "messaging";

const PAGE_LABEL_KEYS: Record<PageId, NavLabelKey> = {
  chat: "chat",
  files: "files",
  cron: "cron",
  skills: "skills",
  connectors: "connectors",
  skillsTools: "skillsAndTools",
  messaging: "messaging",
};

const FULL_WIDTH_PAGES = new Set<PageId>(["chat", "files", "messaging", "skillsTools"]);

const ActivePageOutlet = memo(function ActivePageOutlet({
  page,
  label,
}: {
  page: PageId;
  label: string;
}) {
  useEffect(() => {
    recordActivePageRender();
  });
  const PageComponent = PAGE_COMPONENTS[page];
  return (
    <LazyLoadBoundary label={label}>
      <PageComponent />
    </LazyLoadBoundary>
  );
});

function pageForGlobalNavTarget(target: GlobalNavTarget): PageId {
  switch (target.type) {
    case "file":
      return "files";
    case "task":
      return "chat";
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
    return readSidebarExpanded();
  });
  const [navHovered, setNavHovered] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsInitialTab, setSettingsInitialTab] = useState("model");

  const openSettings = (tab = "model") => {
    setSettingsInitialTab(tab);
    setSettingsOpen(true);
  };

  // Pages (e.g. Skills & Tools → "Manage MCP servers") can open Settings.
  useEffect(() => {
    const handler = () => {
      setSettingsInitialTab("model");
      setSettingsOpen(true);
    };
    window.addEventListener("spark-open-settings", handler);
    return () => window.removeEventListener("spark-open-settings", handler);
  }, []);
  const { t } = useI18n();
  const [authWall, setAuthWall] = useState(false);
  const [tokenHint, setTokenHint] = useState<string | null>(null);
  const [tokenInput, setTokenInput] = useState("");
  const [authChecking, setAuthChecking] = useState(true);
  const [versionLabel, setVersionLabel] = useState(`v${formatVersionDate()}`);
  const [commitUrl, setCommitUrl] = useState<string | null>(null);
  const [statusSnapshot, setStatusSnapshot] = useState<StatusResponse | null>(null);
  const [statusPollFailed, setStatusPollFailed] = useState(false);
  const [scheduledJobCount, setScheduledJobCount] = useState(0);
  const [activeModel, setActiveModel] = useState<string | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const agentCursorHideTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastAgentCursorRef = useRef<{ screenX: number; screenY: number } | null>(null);
  const { updateAvailable, latestVersion, openUpdateModal, macUpdateAvailable, macLatestVersion, openMacUpdateModal } = useUpdateModal();
  const [needsOnboarding, setNeedsOnboarding] = useState<boolean | null>(null);

  // ── Shared session store (global sidebar + ChatPage) ──
  const { selectSession, newProjectThread } = useSessionStore();

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
      } else if (isSidebarToggleShortcut(e)) {
        if (isEditableShortcutTarget(e.target)) return;
        e.preventDefault();
        setNavExpanded((expanded) => {
          const next = !expanded;
          writeSidebarExpanded(next);
          setNavHovered(false);
          return next;
        });
      } else if (e.key === "?" && !e.metaKey && !e.ctrlKey) {
        if (!isEditableShortcutTarget(e.target)) {
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

  // "New chat" — clear selection so ChatPage shows the hero composer.
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
    writeSidebarExpanded(value);
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
          const shortCommit = status.commit?.slice(0, 7) ?? null;
          setVersionLabel(`v${status.version}_${formatVersionDate()}${shortCommit ? ` · ${shortCommit}` : ""}`);
          setCommitUrl(
            status.commit && status.repository_url
              ? `${status.repository_url}/commit/${status.commit}`
              : null,
          );
          setStatusSnapshot(status);
          setStatusPollFailed(false);
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
          setStatusPollFailed(true);
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

  const sidebarOpen = navExpanded || navHovered;

  const gatewayFooter = gatewayFooterState(statusSnapshot, statusPollFailed);

  const saveToken = () => {
    const trimmed = tokenInput.trim();
    if (!trimmed) return;
    setDashboardToken(trimmed);
    setAuthWall(false);
    setTokenInput("");
    window.location.reload();
  };

  if (needsOnboarding) {
    return (
      <LazyLoadBoundary label="onboarding" overlay>
        <OnboardingWizard onComplete={() => setNeedsOnboarding(false)} />
      </LazyLoadBoundary>
    );
  }

  return (
    <div className="h-screen overflow-hidden bg-background text-foreground">
      {paletteOpen && (
        <LazyLoadBoundary label="command palette" overlay>
          <CommandPalette
            open
            onClose={() => setPaletteOpen(false)}
            onNavigate={(id) => navigateTo(id as PageId)}
            onOpenSettings={() => openSettings()}
          />
        </LazyLoadBoundary>
      )}
      {shortcutsOpen && (
        <LazyLoadBoundary label="keyboard shortcuts" overlay>
          <KeyboardShortcutsModal open onClose={() => setShortcutsOpen(false)} />
        </LazyLoadBoundary>
      )}
      <GlobalToasts />

      <CursorGlow />
      {/* Global graphite texture + signal wash */}
      <div className="noise-overlay" />
      <div className="warm-glow" />

      <div className={`relative z-2 grid h-full grid-cols-1 transition-[grid-template-columns] duration-200 md:grid-cols-[var(--sidebar-width)_1fr] ${navExpanded ? "[--sidebar-width:288px]" : "[--sidebar-width:58px]"}`}>
        <aside
          onMouseEnter={() => !navExpanded && setNavHovered(true)}
          onMouseLeave={() => setNavHovered(false)}
          className={`hidden min-h-0 min-w-0 overflow-hidden border-r border-border bg-card/58 backdrop-blur-xl md:flex md:flex-col transition-[width] duration-200 ease-in-out${
            navHovered && !navExpanded
              ? " absolute left-0 top-0 bottom-0 z-50 w-[288px] shadow-2xl shadow-black/35"
              : sidebarOpen
              ? " w-[288px]"
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
              className={`grid h-7 w-7 shrink-0 place-items-center rounded-md text-muted-foreground transition hover:bg-foreground/7 hover:text-foreground ${
                navExpanded || navHovered
                  ? "opacity-100"
                  : "pointer-events-none opacity-0"
              }`}
              title={navExpanded ? "Collapse sidebar (⌘\\)" : "Expand sidebar (⌘\\)"}
              aria-label={navExpanded ? "Collapse sidebar" : "Expand sidebar"}
              onClick={() => toggleNav(!navExpanded)}
            >
              {navExpanded ? <PanelLeftClose className="h-4 w-4" /> : <PanelLeftOpen className="h-4 w-4" />}
            </button>
          </div>
          <nav className={`flex shrink-0 flex-col gap-1 px-2 pt-3 ${sidebarOpen ? "items-stretch" : "items-center"}`}>
            {/* New chat */}
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
            <InboxSidebarSessions
              onOpenSession={openSidebarSession}
              onNewProjectThread={openProjectCompose}
            />
          ) : (
            <div className="flex-1" />
          )}

          {/* Settings + update buttons */}
          <div className={`border-t border-border px-2 py-2 flex flex-col gap-1 ${sidebarOpen ? "items-stretch" : "items-center"}`}>
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
              onClick={() => openSettings()}
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
                {/* Settings button for mobile */}
                <button
                  type="button"
                  title="Settings"
                  onClick={() => openSettings()}
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
              <ActivePageOutlet page={page} label={navLabel(PAGE_LABEL_KEYS[page])} />
            )}
          </main>
          {!authChecking && !authWall && (
            <footer className="hidden h-7 shrink-0 items-center gap-3 border-t border-border/60 bg-card/35 px-3 text-[11px] text-muted-foreground backdrop-blur md:flex">
              <button
                type="button"
                onClick={() => openSettings("gateway")}
                className="inline-flex items-center gap-1.5 rounded-sm transition hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                title={gatewayFooter.title}
              >
                <span
                  className={`h-1.5 w-1.5 rounded-full ${gatewayFooter.dot}`}
                />
                <span>{gatewayFooter.label}</span>
              </button>
              <span className="text-border">·</span>
              <button
                type="button"
                onClick={() => navigateTo("cron")}
                className="rounded-sm transition hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                Schedule {scheduledJobCount}
              </button>
              {activeModel && (
                <>
                  <span className="text-border">·</span>
                  <span className="max-w-48 truncate">{activeModel}</span>
                </>
              )}
              {commitUrl ? (
                <a
                  className="ml-auto rounded-sm transition hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  href={commitUrl}
                  target="_blank"
                  rel="noreferrer"
                  title="Open this commit on GitHub"
                >
                  {versionLabel}
                </a>
              ) : (
                <span className="ml-auto">{versionLabel}</span>
              )}
            </footer>
          )}
        </div>
      </div>

      {settingsOpen && (
        <LazyLoadBoundary label="settings" overlay>
          <SettingsPanel onClose={() => setSettingsOpen(false)} initialTab={settingsInitialTab} />
        </LazyLoadBoundary>
      )}
    </div>
  );
}
