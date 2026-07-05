/**
 * Global-sidebar session navigator: search, PINNED section and SESSIONS
 * grouped by workspace project. Hermes-style layout; backed by the shared
 * session store.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  ArrowLeft,
  ArrowRight,
  AppWindow,
  BookOpen,
  Brain,
  ChevronDown,
  ChevronRight,
  Check,
  Code2,
  Container,
  FileText,
  Film,
  FolderOpen,
  Github,
  Globe2,
  Layers,
  Loader2,
  MessageSquare,
  MonitorCog,
  Package,
  Paintbrush,
  Palette,
  PanelsTopLeft,
  PenTool,
  Pencil,
  Pin,
  Plus,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  SquareTerminal,
  SwatchBook,
  TestTube2,
  Trash2,
  type LucideIcon,
  Video,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import type {
  PackageManager,
  ProjectCreateRequest,
  ProjectTemplatesResponse,
  ProjectType,
  SessionInfo,
  WorkspaceProject,
} from "@/lib/api";
import { cn, timeAgo } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { threadTitle } from "@/components/chat/ThreadRow";
import { useSessionStore, slugFromSource } from "@/lib/sessionStore";
import { chooseDefaultStarter, toggleProjectWizardValue } from "@/lib/projectWizard";

const SESSION_DRAG_MIME = "application/x-spark-session-id";
type DropTarget = "pinned" | "chats" | `project:${string}` | null;

// ── SessionRow ────────────────────────────────────────────────────────────────

function SessionRow({
  session,
  active,
  indent = false,
  pinned = false,
  unread = false,
  onOpen,
  onTogglePin,
  onDelete,
  onDragStart,
  onDragEnd,
}: {
  session: SessionInfo;
  active: boolean;
  indent?: boolean;
  pinned?: boolean;
  unread?: boolean;
  onOpen: () => void;
  onTogglePin: () => void;
  onDelete: () => void;
  onDragStart?: (id: string) => void;
  onDragEnd?: () => void;
}) {
  const handleClick = (e: React.MouseEvent | React.KeyboardEvent) => {
    // Shift-click pins/unpins a chat (hinted in the PINNED empty state).
    if (e.shiftKey) {
      onTogglePin();
      return;
    }
    onOpen();
  };

  return (
    <div
      role="button"
      tabIndex={0}
      draggable
      onDragStart={(e) => {
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData(SESSION_DRAG_MIME, session.id);
        e.dataTransfer.setData("text/plain", session.id);
        onDragStart?.(session.id);
      }}
      onDragEnd={() => onDragEnd?.()}
      onClick={handleClick}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          handleClick(e);
        }
      }}
      className={cn(
        "group relative flex w-full min-w-0 cursor-pointer select-none items-center gap-2 rounded-sm py-1.5 pr-2 text-left transition",
        indent ? "pl-7" : "pl-2.5",
        active
          ? "bg-primary/12 text-foreground"
          : "text-muted-foreground hover:bg-secondary/50 hover:text-foreground",
      )}
    >
      {pinned ? (
        <Pin className={cn("h-3 w-3 shrink-0", active ? "text-primary" : "text-muted-foreground/60")} />
      ) : (
        <MessageSquare className={cn("h-3.5 w-3.5 shrink-0", active ? "text-primary" : "text-muted-foreground/60")} />
      )}
      <span className="min-w-0 flex-1 truncate text-[13px] font-medium leading-5">
        {threadTitle(session)}
      </span>
      {unread && (
        <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary" title="New response" />
      )}
      <span className="shrink-0 text-[10px] text-muted-foreground/50 group-hover:hidden">
        {timeAgo(session.last_active)}
      </span>
      <button
        type="button"
        className="absolute right-1.5 hidden rounded p-0.5 text-muted-foreground/50 hover:text-destructive group-hover:block"
        onClick={(e) => {
          e.stopPropagation();
          onDelete();
        }}
        aria-label="Delete thread"
      >
        <Trash2 className="h-3 w-3" />
      </button>
    </div>
  );
}

// ── ProjectGroup ──────────────────────────────────────────────────────────────

function ProjectGroup({
  project,
  threads,
  isExpanded,
  selectedId,
  unreadSessionIds,
  pinnedIds,
  onToggle,
  onOpen,
  onTogglePin,
  onDelete,
  onNewThread,
  onDeleteProject,
  onRenameProject,
  onDragSessionStart,
  onDragSessionEnd,
  dragOverTarget,
  onDragOverProject,
  onDropOnProject,
  onClearDragOver,
}: {
  project: WorkspaceProject;
  threads: SessionInfo[];
  isExpanded: boolean;
  selectedId: string | null;
  unreadSessionIds: Set<string>;
  pinnedIds: Set<string>;
  onToggle: () => void;
  onOpen: (id: string) => void;
  onTogglePin: (id: string) => void;
  onDelete: (id: string) => void;
  onNewThread: (slug: string) => void;
  onDeleteProject: (slug: string) => void;
  onRenameProject: (slug: string, name: string) => Promise<string>;
  onDragSessionStart: (id: string) => void;
  onDragSessionEnd: () => void;
  dragOverTarget: DropTarget;
  onDragOverProject: (slug: string, e: React.DragEvent) => void;
  onDropOnProject: (slug: string, e: React.DragEvent) => void;
  onClearDragOver: () => void;
}) {
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [renameValue, setRenameValue] = useState(project.name);
  const [renameError, setRenameError] = useState<string | null>(null);
  const [savingRename, setSavingRename] = useState(false);
  const dropActive = dragOverTarget === `project:${project.slug}`;

  const commitRename = async () => {
    const nextName = renameValue.trim();
    if (!nextName || nextName === project.name || savingRename) {
      setRenaming(false);
      setRenameValue(project.name);
      setRenameError(null);
      return;
    }
    setSavingRename(true);
    setRenameError(null);
    try {
      await onRenameProject(project.slug, nextName);
      setRenaming(false);
    } catch (err) {
      setRenameError(err instanceof Error ? err.message : "Rename failed");
    } finally {
      setSavingRename(false);
    }
  };

  return (
    <div>
      <div
        className={cn(
          "group flex items-center gap-1.5 rounded-sm px-1.5 py-1 transition hover:bg-secondary/50",
          dropActive && "bg-primary/10 ring-1 ring-primary/40",
        )}
        onDragOver={(e) => onDragOverProject(project.slug, e)}
        onDragLeave={onClearDragOver}
        onDrop={(e) => onDropOnProject(project.slug, e)}
      >
        {renaming ? (
          <form
            className="flex min-w-0 flex-1 items-center gap-1"
            onSubmit={(e) => {
              e.preventDefault();
              void commitRename();
            }}
          >
            <Input
              autoFocus
              className="h-6 min-w-0 flex-1 px-1.5 text-[12px]"
              value={renameValue}
              disabled={savingRename}
              onChange={(e) => setRenameValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") {
                  e.preventDefault();
                  setRenaming(false);
                  setRenameValue(project.name);
                  setRenameError(null);
                }
              }}
              onBlur={() => {
                if (!savingRename) void commitRename();
              }}
            />
            {savingRename && <Loader2 className="h-3 w-3 shrink-0 animate-spin text-muted-foreground" />}
          </form>
        ) : (
          <button type="button" className="flex min-w-0 flex-1 items-center gap-1.5 text-left" onClick={onToggle}>
            <span className="text-muted-foreground/50">
              {isExpanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
            </span>
            <FolderOpen className="h-3.5 w-3.5 shrink-0 text-amber-300/70" />
            <span className="min-w-0 flex-1 truncate text-[12px] font-medium text-foreground/80">
              {project.name}
            </span>
          </button>
        )}
        <div className="flex shrink-0 items-center gap-0.5 opacity-0 transition group-hover:opacity-100">
          <button
            type="button"
            title="Rename project"
            className="rounded p-0.5 text-muted-foreground/60 hover:text-foreground"
            onClick={(e) => {
              e.stopPropagation();
              setRenameValue(project.name);
              setRenameError(null);
              setRenaming(true);
            }}
          >
            <Pencil className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            title="New thread in this project"
            className="rounded p-0.5 text-muted-foreground/60 hover:text-foreground"
            onClick={(e) => {
              e.stopPropagation();
              onNewThread(project.slug);
            }}
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            title="Delete project"
            className="rounded p-0.5 text-muted-foreground/60 hover:text-destructive"
            onClick={(e) => {
              e.stopPropagation();
              setShowDeleteConfirm(true);
            }}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
        {threads.length > 0 && (
          <Badge variant="secondary" className="h-4 shrink-0 px-1 text-[10px]">
            {threads.length}
          </Badge>
        )}
      </div>
      {renameError && (
        <p className="px-2 pb-1 text-[11px] text-destructive">{renameError}</p>
      )}

      {showDeleteConfirm && (
        <div className="mx-1 mb-1 rounded-sm border border-destructive/40 bg-background p-2 text-xs">
          <p className="mb-1.5 text-foreground">
            Delete <span className="font-semibold">{project.name}</span>?
          </p>
          <p className="mb-2 text-muted-foreground">Removes all project files permanently.</p>
          <div className="flex gap-1">
            <Button
              size="sm"
              variant="destructive"
              className="h-6 flex-1 text-xs"
              onClick={() => {
                onDeleteProject(project.slug);
                setShowDeleteConfirm(false);
              }}
            >
              Delete
            </Button>
            <Button size="sm" variant="ghost" className="h-6 w-6 p-0" onClick={() => setShowDeleteConfirm(false)}>
              <X className="h-3 w-3" />
            </Button>
          </div>
        </div>
      )}

      {isExpanded && (
        <div className="pb-1">
          {threads.length === 0 ? (
            <p className="py-1 pl-9 text-[11px] italic text-muted-foreground/40">No chats</p>
          ) : (
            threads.map((t) => (
              <SessionRow
                key={t.id}
                session={t}
                active={selectedId === t.id}
                indent
                pinned={pinnedIds.has(t.id)}
                unread={unreadSessionIds.has(t.id)}
                onOpen={() => onOpen(t.id)}
                onTogglePin={() => onTogglePin(t.id)}
                onDelete={() => onDelete(t.id)}
                onDragStart={onDragSessionStart}
                onDragEnd={onDragSessionEnd}
              />
            ))
          )}
        </div>
      )}
    </div>
  );
}

// ── Project wizard ─────────────────────────────────────────────────────────────

const PROJECT_TYPE_ICONS: Record<ProjectType, LucideIcon> = {
  blank: FileText,
  static_website: Globe2,
  web_application: PanelsTopLeft,
  design_project: Palette,
  productivity_workspace: AppWindow,
  video_project: Video,
};

const STARTER_ICONS: Record<string, LucideIcon> = {
  scratch: Sparkles,
  static: Globe2,
  webapp: AppWindow,
  productivity: PanelsTopLeft,
  astro: Sparkles,
  eleventy: FileText,
  nextjs: Code2,
  sveltekit: Layers,
  nuxt: Layers,
  docs_workspace: BookOpen,
  research_workspace: Brain,
  knowledge_base: BookOpen,
  design_system: SwatchBook,
  brand_kit: Paintbrush,
  hyperframes: Film,
  remotion: Video,
  ffmpeg: SquareTerminal,
};

const PACKAGE_MANAGER_ICONS: Record<PackageManager, LucideIcon> = {
  pnpm: Package,
  npm: Package,
  yarn: Package,
  bun: Package,
};

const DEV_TOOL_OPTIONS = [
  { id: "eslint", label: "ESLint", icon: ShieldCheck },
  { id: "prettier", label: "Prettier", icon: Code2 },
  { id: "husky", label: "Husky", icon: Settings2 },
  { id: "vscode_config", label: "VS Code", icon: MonitorCog },
];

const DESIGN_TOOL_OPTIONS = [
  { id: "design_tokens", label: "Design Tokens", icon: SwatchBook },
  { id: "brand_kit", label: "Brand Kit", icon: Paintbrush },
  { id: "figma_notes", label: "Figma Handoff", icon: PenTool },
];

const INTEGRATION_OPTIONS = [
  { id: "docker", label: "Docker", icon: Container },
  { id: "github_actions", label: "GitHub Actions", icon: Github },
  { id: "playwright", label: "Playwright", icon: AppWindow },
  { id: "vitest", label: "Vitest", icon: TestTube2 },
  { id: "storybook", label: "Storybook", icon: BookOpen },
];

const DESIGN_INTEGRATION_OPTIONS = [
  { id: "figma", label: "Figma", icon: PenTool },
];

function ProjectWizard({
  open,
  onClose,
  onCreate,
}: {
  open: boolean;
  onClose: () => void;
  onCreate: (request: ProjectCreateRequest) => Promise<void>;
}) {
  const [templatesData, setTemplatesData] = useState<ProjectTemplatesResponse | null>(null);
  const [loadingTemplates, setLoadingTemplates] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [step, setStep] = useState(0);
  const [projectName, setProjectName] = useState("");
  const [projectType, setProjectType] = useState<ProjectType>("blank");
  const [starterId, setStarterId] = useState("scratch");
  const [packageManager, setPackageManager] = useState<PackageManager>("pnpm");
  const [initGit, setInitGit] = useState(true);
  const [initialCommit, setInitialCommit] = useState(false);
  const [aiSkillsMode, setAiSkillsMode] = useState<"recommended" | "manual">("recommended");
  const [selectedSkills, setSelectedSkills] = useState<string[]>([]);
  const [devTools, setDevTools] = useState<string[]>([]);
  const [integrations, setIntegrations] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setLoadingTemplates(true);
    setError(null);
    api
      .listProjectTemplates()
      .then((data) => setTemplatesData(data))
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load project templates"))
      .finally(() => setLoadingTemplates(false));
  }, [open]);

  const projectTypes = templatesData?.project_types ?? [];
  const starters = useMemo(
    () => templatesData?.templates.filter((tpl) => tpl.project_type === projectType) ?? [],
    [templatesData, projectType],
  );
  const starter = starters.find((tpl) => tpl.id === starterId) ?? starters[0];
  const isDesignProject = projectType === "design_project";
  const devToolOptions = useMemo(
    () => (isDesignProject ? [...DEV_TOOL_OPTIONS, ...DESIGN_TOOL_OPTIONS] : DEV_TOOL_OPTIONS),
    [isDesignProject],
  );
  const integrationOptions = useMemo(
    () => (isDesignProject ? [...INTEGRATION_OPTIONS, ...DESIGN_INTEGRATION_OPTIONS] : INTEGRATION_OPTIONS),
    [isDesignProject],
  );

  useEffect(() => {
    if (!starters.length) return;
    const nextStarter = chooseDefaultStarter(starters);
    if (!nextStarter) return;
    setStarterId(nextStarter.id);
    setPackageManager(nextStarter.default_package_manager ?? "pnpm");
    setSelectedSkills(nextStarter.recommended_skills);
  }, [starters]);

  useEffect(() => {
    const allowedDevTools = new Set(devToolOptions.map((option) => option.id));
    const allowedIntegrations = new Set(integrationOptions.map((option) => option.id));
    setDevTools((prev) => prev.filter((tool) => allowedDevTools.has(tool)));
    setIntegrations((prev) => prev.filter((integration) => allowedIntegrations.has(integration)));
  }, [devToolOptions, integrationOptions]);

  if (!open) return null;

  const canContinue =
    (step === 0 && projectName.trim() && projectType) ||
    (step === 1 && starter?.available) ||
    step >= 2;

  const resetAndClose = () => {
    setStep(0);
    setProjectName("");
    setProjectType("blank");
    setStarterId("scratch");
    setPackageManager("pnpm");
    setInitGit(true);
    setInitialCommit(false);
    setAiSkillsMode("recommended");
    setSelectedSkills([]);
    setDevTools([]);
    setIntegrations([]);
    setError(null);
    onClose();
  };

  const submit = async () => {
    if (!starter || saving) return;
    setSaving(true);
    setError(null);
    try {
      await onCreate({
        name: projectName.trim(),
        project_type: projectType,
        starter_stack: starter.id,
        package_manager: starter.package_managers.length ? packageManager : undefined,
        init_git: initGit,
        initial_commit: initGit && initialCommit,
        ai_skills_mode: aiSkillsMode,
        selected_skills: aiSkillsMode === "recommended" ? starter.recommended_skills : selectedSkills,
        dev_tools: devTools,
        integrations,
      });
      resetAndClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create project failed");
    } finally {
      setSaving(false);
    }
  };

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 p-4 backdrop-blur-sm">
      <div className="flex max-h-[88vh] w-full max-w-2xl flex-col overflow-hidden rounded-md border border-border bg-background shadow-xl">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div>
            <h2 className="text-sm font-semibold text-foreground">Create Project</h2>
            <div className="mt-2 flex gap-1">
              {["Details", "Starter", "Options", "Review"].map((label, index) => (
                <div
                  key={label}
                  className={cn(
                    "h-1.5 w-14 rounded-full",
                    index <= step ? "bg-primary" : "bg-muted",
                  )}
                />
              ))}
            </div>
          </div>
          <Button variant="ghost" size="sm" className="h-8 w-8 p-0" onClick={resetAndClose}>
            <X className="h-4 w-4" />
          </Button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {loadingTemplates ? (
            <div className="flex h-48 items-center justify-center text-muted-foreground">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Loading
            </div>
          ) : (
            <>
              {step === 0 && (
                <div className="space-y-4">
                  <label className="block space-y-1.5">
                    <span className="text-xs font-medium text-muted-foreground">Project Name</span>
                    <Input
                      autoFocus
                      value={projectName}
                      onChange={(e) => setProjectName(e.target.value)}
                      placeholder="Acme Dashboard"
                    />
                  </label>
                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                    {projectTypes.map((type) => {
                      const TypeIcon = PROJECT_TYPE_ICONS[type.id] ?? FolderOpen;
                      return (
                        <button
                          key={type.id}
                          type="button"
                          onClick={() => setProjectType(type.id)}
                          className={cn(
                            "flex items-center justify-between gap-3 rounded-md border px-3 py-2 text-left text-sm transition",
                            projectType === type.id
                              ? "border-primary bg-primary/10 text-foreground"
                              : "border-border text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
                          )}
                        >
                          <span className="flex min-w-0 items-center gap-2">
                            <TypeIcon className="h-4 w-4 shrink-0" />
                            <span className="truncate">{type.label}</span>
                          </span>
                          {projectType === type.id && <Check className="h-4 w-4 shrink-0 text-primary" />}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}

              {step === 1 && (
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {starters.map((tpl) => {
                    const StarterIcon = STARTER_ICONS[tpl.id] ?? FolderOpen;
                    return (
                      <button
                        key={tpl.id}
                        type="button"
                        disabled={!tpl.available}
                        onClick={() => {
                          setStarterId(tpl.id);
                          setPackageManager(tpl.default_package_manager ?? "pnpm");
                          setSelectedSkills(tpl.recommended_skills);
                        }}
                        className={cn(
                          "min-h-24 rounded-md border px-3 py-2 text-left transition",
                          starterId === tpl.id
                            ? "border-primary bg-primary/10 text-foreground"
                            : "border-border text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
                          !tpl.available && "cursor-not-allowed opacity-45 hover:bg-transparent",
                        )}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <span className="flex min-w-0 items-center gap-2 text-sm font-medium">
                            <StarterIcon className="h-4 w-4 shrink-0" />
                            <span className="truncate">{tpl.label}</span>
                          </span>
                          {tpl.recommended && <Badge variant="secondary">Recommended</Badge>}
                        </div>
                        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{tpl.description}</p>
                        {!tpl.available && <p className="mt-2 text-[11px] text-muted-foreground/70">Coming soon</p>}
                      </button>
                    );
                  })}
                </div>
              )}

              {step === 2 && starter && (
                <div className="space-y-5">
                  {starter.package_managers.length > 0 && (
                    <div>
                      <p className="mb-2 text-xs font-medium text-muted-foreground">Package Manager</p>
                      <div className="flex flex-wrap gap-2">
                        {starter.package_managers.map((pm) => {
                          const PackageIcon = PACKAGE_MANAGER_ICONS[pm] ?? Package;
                          return (
                            <Button
                              key={pm}
                              size="sm"
                              variant={packageManager === pm ? "default" : "outline"}
                              onClick={() => setPackageManager(pm)}
                            >
                              <PackageIcon className="mr-1.5 h-3.5 w-3.5" />
                              {pm}
                            </Button>
                          );
                        })}
                      </div>
                    </div>
                  )}
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    <label className="flex items-center gap-2 text-sm">
                      <input type="checkbox" checked={initGit} onChange={(e) => setInitGit(e.target.checked)} />
                      <Github className="h-4 w-4 text-muted-foreground" />
                      Initialize Git repository
                    </label>
                    <label className="flex items-center gap-2 text-sm text-muted-foreground">
                      <input
                        type="checkbox"
                        checked={initialCommit}
                        disabled={!initGit}
                        onChange={(e) => setInitialCommit(e.target.checked)}
                      />
                      <Check className="h-4 w-4" />
                      Create initial commit
                    </label>
                  </div>
                  <div>
                    <p className="mb-2 text-xs font-medium text-muted-foreground">AI Skills</p>
                    <div className="flex gap-2">
                      <Button size="sm" variant={aiSkillsMode === "recommended" ? "default" : "outline"} onClick={() => setAiSkillsMode("recommended")}>
                        <Sparkles className="mr-1.5 h-3.5 w-3.5" />
                        Recommended
                      </Button>
                      <Button size="sm" variant={aiSkillsMode === "manual" ? "default" : "outline"} onClick={() => setAiSkillsMode("manual")}>
                        <Settings2 className="mr-1.5 h-3.5 w-3.5" />
                        Manual
                      </Button>
                    </div>
                    {starter.recommended_skills.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {aiSkillsMode === "recommended"
                          ? starter.recommended_skills.map((skill) => (
                              <Badge key={skill} variant="outline">{skill}</Badge>
                            ))
                          : starter.recommended_skills.map((skill) => (
                              <label key={skill} className="flex items-center gap-1.5 rounded-md border border-border px-2 py-1 text-xs">
                                <input
                                  type="checkbox"
                                  checked={selectedSkills.includes(skill)}
                                  onChange={() => setSelectedSkills((prev) => toggleProjectWizardValue(prev, skill))}
                                />
                                {skill}
                              </label>
                            ))}
                      </div>
                    )}
                  </div>
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    <OptionGroup title="Development Tools" options={devToolOptions} values={devTools} onToggle={(id) => setDevTools((prev) => toggleProjectWizardValue(prev, id))} />
                    <OptionGroup title="Integrations" options={integrationOptions} values={integrations} onToggle={(id) => setIntegrations((prev) => toggleProjectWizardValue(prev, id))} />
                  </div>
                </div>
              )}

              {step === 3 && starter && (
                <div className="space-y-3 text-sm">
                  <ReviewRow label="Project Name" value={projectName.trim()} />
                  <ReviewRow label="Project Type" value={projectTypes.find((type) => type.id === projectType)?.label ?? projectType} />
                  <ReviewRow label="Starter Stack" value={starter.label} />
                  <ReviewRow label="Package Manager" value={starter.package_managers.length ? packageManager : "None"} />
                  <ReviewRow label="AI Skills" value={aiSkillsMode === "recommended" ? starter.recommended_skills.join(", ") || "Recommended" : selectedSkills.join(", ") || "Manual"} />
                  <ReviewRow label="Development Tools" value={devTools.join(", ") || "None"} />
                  <ReviewRow label="Integrations" value={integrations.join(", ") || "None"} />
                  <ReviewRow label="Git" value={initGit ? (initialCommit ? "Initialize with initial commit" : "Initialize") : "None"} />
                </div>
              )}
            </>
          )}

          {error && <p className="mt-4 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">{error}</p>}
        </div>

        <div className="flex items-center justify-between border-t border-border px-4 py-3">
          <Button variant="ghost" size="sm" onClick={() => (step === 0 ? resetAndClose() : setStep((s) => s - 1))}>
            <ArrowLeft className="mr-2 h-4 w-4" />
            {step === 0 ? "Cancel" : "Back"}
          </Button>
          {step < 3 ? (
            <Button size="sm" disabled={!canContinue || loadingTemplates} onClick={() => setStep((s) => s + 1)}>
              Next
              <ArrowRight className="ml-2 h-4 w-4" />
            </Button>
          ) : (
            <Button size="sm" disabled={saving || !starter?.available} onClick={() => void submit()}>
              {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Check className="mr-2 h-4 w-4" />}
              Create Project
            </Button>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}

function OptionGroup({
  title,
  options,
  values,
  onToggle,
}: {
  title: string;
  options: { id: string; label: string; icon?: LucideIcon }[];
  values: string[];
  onToggle: (id: string) => void;
}) {
  return (
    <div>
      <p className="mb-2 text-xs font-medium text-muted-foreground">{title}</p>
      <div className="space-y-1.5">
        {options.map((option) => {
          const OptionIcon = option.icon;
          return (
            <label key={option.id} className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={values.includes(option.id)} onChange={() => onToggle(option.id)} />
              {OptionIcon && <OptionIcon className="h-4 w-4 text-muted-foreground" />}
              <span>{option.label}</span>
            </label>
          );
        })}
      </div>
    </div>
  );
}

function ReviewRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[140px_1fr] gap-3 border-b border-border/60 pb-2">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-foreground">{value}</span>
    </div>
  );
}

// ── Collapsible section header ──────────────────────────────────────────────────

const SECTION_COLLAPSE_KEY = "spark.sidebar.collapsedSections";

function loadCollapsedSections(): Set<string> {
  try {
    const raw = localStorage.getItem(SECTION_COLLAPSE_KEY);
    return raw ? new Set(JSON.parse(raw) as string[]) : new Set();
  } catch {
    return new Set();
  }
}

function saveCollapsedSections(collapsed: Set<string>) {
  try {
    localStorage.setItem(SECTION_COLLAPSE_KEY, JSON.stringify([...collapsed]));
  } catch {
    // ignore (e.g. private browsing)
  }
}

function SectionHeader({
  label,
  collapsed,
  onToggle,
  actions,
}: {
  label: string;
  collapsed: boolean;
  onToggle: () => void;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between px-2 pb-1">
      <button
        type="button"
        onClick={onToggle}
        className="flex min-w-0 items-center gap-1.5 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/50 hover:text-foreground"
      >
        {collapsed ? <ChevronRight className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
        <span>{label}</span>
      </button>
      {actions && <div className="flex items-center gap-0.5">{actions}</div>}
    </div>
  );
}

// ── SidebarSessions ───────────────────────────────────────────────────────────

export function SidebarSessions({
  onOpenSession,
  onNewProjectThread,
}: {
  /** Navigate to the chat page + select the session. */
  onOpenSession: (id: string) => void;
  /** Navigate to the chat page + open the project compose view. */
  onNewProjectThread: (slug: string) => void;
}) {
  const {
    projects,
    loadingProjects,
    loadingSessions,
    sessions,
    displayedSessions,
    searchQ,
    setSearchQ,
    searchResults,
    searching,
    pinnedIds,
    togglePin,
    selectedId,
    unreadSessionIds,
    expandedProjects,
    toggleProjectExpanded,
    deleteSession,
    deleteProject,
    createProject,
    moveSessionToProject,
    renameProject,
  } = useSessionStore();

  const searchInputRef = useRef<HTMLInputElement>(null);
  const [creatingProject, setCreatingProject] = useState(false);
  const [collapsedSections, setCollapsedSections] = useState<Set<string>>(loadCollapsedSections);
  const [draggingSessionId, setDraggingSessionId] = useState<string | null>(null);
  const [dragOverTarget, setDragOverTarget] = useState<DropTarget>(null);
  const [dragError, setDragError] = useState<string | null>(null);

  const toggleSection = (section: string) => {
    setCollapsedSections((prev) => {
      const next = new Set(prev);
      if (next.has(section)) {
        next.delete(section);
      } else {
        next.add(section);
      }
      saveCollapsedSections(next);
      return next;
    });
  };

  // Cmd+F focuses the session search; Cmd+K stays reserved for the palette.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "f") {
        e.preventDefault();
        searchInputRef.current?.focus();
        searchInputRef.current?.select();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const pinnedSessions = useMemo(
    () => displayedSessions.filter((s) => pinnedIds.has(s.id)),
    [displayedSessions, pinnedIds],
  );

  const ungrouped = useMemo(
    () => displayedSessions.filter((s) => !slugFromSource(s.source)),
    [displayedSessions],
  );

  const bySlug = useMemo(() => {
    const map = new Map<string, SessionInfo[]>();
    for (const s of displayedSessions) {
      const slug = slugFromSource(s.source);
      if (!slug) continue;
      const list = map.get(slug) ?? [];
      list.push(s);
      map.set(slug, list);
    }
    return map;
  }, [displayedSessions]);

  const draggedSessionFromEvent = (e: React.DragEvent): string => (
    e.dataTransfer.getData(SESSION_DRAG_MIME) || e.dataTransfer.getData("text/plain")
  );

  const allowDrop = (target: Exclude<DropTarget, null>, e: React.DragEvent) => {
    if (!draggingSessionId) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    setDragOverTarget(target);
  };

  const dropSession = async (target: Exclude<DropTarget, null>, e: React.DragEvent) => {
    e.preventDefault();
    const sessionId = draggedSessionFromEvent(e) || draggingSessionId;
    setDragOverTarget(null);
    setDraggingSessionId(null);
    if (!sessionId) return;
    setDragError(null);
    try {
      if (target === "pinned") {
        if (!pinnedIds.has(sessionId)) togglePin(sessionId);
        return;
      }
      if (target === "chats") {
        if (pinnedIds.has(sessionId)) togglePin(sessionId);
        await moveSessionToProject(sessionId, null);
        return;
      }
      const slug = target.slice("project:".length);
      await moveSessionToProject(sessionId, slug);
    } catch (err) {
      setDragError(err instanceof Error ? err.message : "Could not move chat");
    }
  };

  const handleDragStart = (id: string) => {
    setDraggingSessionId(id);
    setDragError(null);
  };

  const handleDragEnd = () => {
    setDraggingSessionId(null);
    setDragOverTarget(null);
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <ProjectWizard
        open={creatingProject}
        onClose={() => setCreatingProject(false)}
        onCreate={async (request) => {
          await createProject(request);
        }}
      />

      {/* Search */}
      <div className="shrink-0 px-2 pb-1 pt-2">
        <div className="relative">
          <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground/60" />
          <Input
            ref={searchInputRef}
            className="h-7 pl-7 pr-8 text-[12px]"
            placeholder="Search sessions…"
            value={searchQ}
            onChange={(e) => setSearchQ(e.target.value)}
          />
          {searching && (
            <Loader2 className="absolute right-2 top-1/2 h-3 w-3 -translate-y-1/2 animate-spin text-muted-foreground/60" />
          )}
          {searchQ && !searching && (
            <button
              type="button"
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground/60 hover:text-foreground"
              onClick={() => setSearchQ("")}
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </div>
      </div>

      {/* Scrollable list */}
      <div className="scrollbar-always min-h-0 flex-1 overflow-y-auto px-1 pb-2">
        {/* PINNED */}
        <div
          className={cn(
            "pt-2",
            dragOverTarget === "pinned" && "rounded-sm bg-primary/10 ring-1 ring-primary/40",
          )}
          onDragOver={(e) => allowDrop("pinned", e)}
          onDragLeave={() => setDragOverTarget(null)}
          onDrop={(e) => void dropSession("pinned", e)}
        >
          <div className="flex items-center gap-1.5 px-2 pb-1">
            <Pin className="h-3 w-3 text-muted-foreground/50" />
            <span className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/50">
              Pinned
            </span>
          </div>
          {pinnedSessions.length === 0 ? (
            <p className="px-2.5 pb-1 text-[11px] italic text-muted-foreground/40">
              Shift-click a chat to pin
            </p>
          ) : (
            pinnedSessions.map((s) => (
              <SessionRow
                key={`pin-${s.id}`}
                session={s}
                active={selectedId === s.id}
                pinned
                unread={unreadSessionIds.has(s.id)}
                onOpen={() => onOpenSession(s.id)}
                onTogglePin={() => togglePin(s.id)}
                onDelete={() => void deleteSession(s.id)}
                onDragStart={handleDragStart}
                onDragEnd={handleDragEnd}
              />
            ))
          )}
        </div>
        {dragError && (
          <p className="px-2.5 pt-1 text-[11px] text-destructive">{dragError}</p>
        )}

        {/* SESSIONS */}
        <div className="pt-3">
          <SectionHeader
            label="Sessions"
            collapsed={collapsedSections.has("sessions")}
            onToggle={() => toggleSection("sessions")}
            actions={
              <>
                {(loadingSessions || loadingProjects) && !sessions.length && (
                  <Loader2 className="h-3 w-3 animate-spin text-muted-foreground/40" />
                )}
                <button
                  type="button"
                  title="New project workspace"
                  className="rounded p-0.5 text-muted-foreground/50 transition hover:bg-secondary hover:text-foreground"
                  onClick={() => setCreatingProject(true)}
                >
                  <Plus className="h-3.5 w-3.5" />
                </button>
              </>
            }
          />

          {!collapsedSections.has("sessions") && (
            <>
              {/* Project workspace groups */}
              {projects.map((project) => (
                <ProjectGroup
                  key={project.slug}
                  project={project}
                  threads={bySlug.get(project.slug) ?? []}
                  isExpanded={expandedProjects.has(project.slug) || Boolean(searchResults)}
                  selectedId={selectedId}
                  unreadSessionIds={unreadSessionIds}
                  pinnedIds={pinnedIds}
                  onToggle={() => toggleProjectExpanded(project.slug)}
                  onOpen={onOpenSession}
                  onTogglePin={togglePin}
                  onDelete={(id) => void deleteSession(id)}
                  onNewThread={onNewProjectThread}
                  onDeleteProject={(slug) => void deleteProject(slug)}
                  onRenameProject={renameProject}
                  onDragSessionStart={handleDragStart}
                  onDragSessionEnd={handleDragEnd}
                  dragOverTarget={dragOverTarget}
                  onDragOverProject={(slug, e) => allowDrop(`project:${slug}`, e)}
                  onDropOnProject={(slug, e) => void dropSession(`project:${slug}`, e)}
                  onClearDragOver={() => setDragOverTarget(null)}
                />
              ))}

              {searchResults !== null && displayedSessions.length === 0 && (
                <p className="px-2.5 py-2 text-[11px] text-muted-foreground/50">
                  No results for "{searchQ}"
                </p>
              )}
              {searchResults === null && !loadingSessions && ungrouped.length === 0 && projects.length === 0 && (
                <p className="px-2.5 py-2 text-[11px] text-muted-foreground/40">No sessions yet</p>
              )}
            </>
          )}
        </div>

        {/* CHATS (ungrouped sessions) */}
        {(ungrouped.length > 0 || draggingSessionId) && (
          <div
            className={cn(
              "pt-3",
              dragOverTarget === "chats" && "rounded-sm bg-primary/10 ring-1 ring-primary/40",
            )}
            onDragOver={(e) => allowDrop("chats", e)}
            onDragLeave={() => setDragOverTarget(null)}
            onDrop={(e) => void dropSession("chats", e)}
          >
            <SectionHeader
              label="Chats"
              collapsed={collapsedSections.has("chats")}
              onToggle={() => toggleSection("chats")}
            />
            {!collapsedSections.has("chats") &&
              (ungrouped.length > 0 ? (
                ungrouped.map((s) => (
                  <SessionRow
                    key={s.id}
                    session={s}
                    active={selectedId === s.id}
                    pinned={pinnedIds.has(s.id)}
                    unread={unreadSessionIds.has(s.id)}
                    onOpen={() => onOpenSession(s.id)}
                    onTogglePin={() => togglePin(s.id)}
                    onDelete={() => void deleteSession(s.id)}
                    onDragStart={handleDragStart}
                    onDragEnd={handleDragEnd}
                  />
                ))
              ) : (
                <p className="px-2.5 pb-1 text-[11px] italic text-muted-foreground/40">Drop here to unfile</p>
              ))}
          </div>
        )}
      </div>
    </div>
  );
}
