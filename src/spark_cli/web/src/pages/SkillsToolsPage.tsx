import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Check,
  ChevronRight,
  FileCode2,
  Pencil,
  RefreshCw,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import type { SkillDetail, SkillInfo, ToolsetInfo } from "@/lib/api";
import { useToast } from "@/hooks/useToast";
import { useEventBus } from "@/hooks/useEventBus";
import { Toast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import ConnectorsPage from "@/pages/ConnectorsPage";
import EnvPage from "@/pages/EnvPage";
import { GLOBAL_NAV_EVENT, takeGlobalNavTarget, type GlobalNavTarget } from "@/lib/globalNavigation";
import { SkillQualitySignals } from "@/components/skills/SkillQualitySignals";

const CATEGORY_LABELS: Record<string, string> = {
  mlops: "MLOps",
  mcp: "MCP",
  ocr: "OCR",
  p5js: "p5.js",
  ai: "AI",
  ux: "UX",
  ui: "UI",
};

function prettyCategory(raw: string | null | undefined): string {
  if (!raw) return "General";
  if (CATEGORY_LABELS[raw]) return CATEGORY_LABELS[raw];
  return raw.split(/[-_/]/).map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
}

type Tab = "skills" | "toolsets" | "tools" | "keys";
type SourceFilter = "all" | NonNullable<SkillInfo["provenance"]>;

const SOURCE_LABELS: Record<SourceFilter, string> = {
  all: "All skills",
  bundled: "Spark built-in",
  spark_created: "Spark-created",
  hub_installed: "Installed",
  local: "Profile skills",
  external: "External",
};

const SOURCE_STYLES: Record<NonNullable<SkillInfo["provenance"]>, string> = {
  bundled: "border-sky-400/30 bg-sky-400/10 text-sky-200",
  spark_created: "border-violet-400/30 bg-violet-400/10 text-violet-200",
  hub_installed: "border-emerald-400/30 bg-emerald-400/10 text-emerald-200",
  local: "border-amber-400/30 bg-amber-400/10 text-amber-200",
  external: "border-border bg-muted/40 text-muted-foreground",
};

function skillId(skill: SkillInfo): string {
  return skill.skill_id ?? skill.name;
}

function sourceOf(skill: SkillInfo): NonNullable<SkillInfo["provenance"]> {
  return skill.provenance ?? "local";
}

function sourceLabel(skill: SkillInfo): string {
  return skill.provenance_detail?.label ?? SOURCE_LABELS[sourceOf(skill)];
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error || "Something went wrong");
}

function SkillSourceBadge({ skill }: { skill: SkillInfo }) {
  const source = sourceOf(skill);
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${SOURCE_STYLES[source]}`}>
      {sourceLabel(skill)}
    </span>
  );
}

function SkillRow({
  skill,
  toggling,
  onOpen,
  onToggle,
}: {
  skill: SkillInfo;
  toggling: boolean;
  onOpen: () => void;
  onToggle: () => void;
}) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpen();
        }
      }}
      className="group flex cursor-pointer items-center gap-4 border-b border-border/40 px-3 py-3 transition hover:bg-foreground/[0.035] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      aria-label={`View ${skill.name}`}
    >
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[13px] font-semibold text-foreground">{skill.name}</span>
          <SkillSourceBadge skill={skill} />
          {skill.modified && <span className="text-[10px] text-amber-300">Modified</span>}
        </div>
        <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-muted-foreground">{skill.description || "No description provided."}</p>
        <SkillQualitySignals skill={skill} />
        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-muted-foreground/70">
          <span>{prettyCategory(skill.category)}</span>
          {skill.location && <span className="truncate">{skill.location}</span>}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2" onClick={(event) => event.stopPropagation()}>
        <Switch checked={skill.enabled} disabled={toggling} onCheckedChange={onToggle} aria-label={`Toggle ${skill.name}`} />
        <ChevronRight className="h-4 w-4 text-muted-foreground/50 transition group-hover:text-foreground" aria-hidden="true" />
      </div>
    </div>
  );
}

function SkillDetailPanel({
  detail,
  loading,
  draft,
  editing,
  busy,
  deleteName,
  deleteArmed,
  onDraftChange,
  onEdit,
  onSave,
  onCancelEdit,
  onDelete,
  onRestore,
  onDeleteNameChange,
  onArmDelete,
  onCancelDelete,
  onClose,
}: {
  detail: SkillDetail | null;
  loading: boolean;
  draft: string;
  editing: boolean;
  busy: boolean;
  deleteName: string;
  deleteArmed: boolean;
  onDraftChange: (value: string) => void;
  onEdit: () => void;
  onSave: () => void;
  onCancelEdit: () => void;
  onDelete: () => void;
  onRestore: () => void;
  onDeleteNameChange: (value: string) => void;
  onArmDelete: () => void;
  onCancelDelete: () => void;
  onClose: () => void;
}) {
  if (!detail && !loading) return null;
  const canEdit = Boolean(detail?.capabilities?.editable);
  const canDelete = Boolean(detail?.capabilities?.deletable);
  const canRestore = Boolean(detail?.capabilities?.restorable);
  const confirmingDelete = deleteArmed;
  const deleteMatches = detail?.name === deleteName;

  return (
    <div className="absolute inset-0 z-30 flex justify-end bg-background/60 backdrop-blur-sm" role="dialog" aria-modal="true" aria-label={detail ? `${detail.name} skill details` : "Skill details"}>
      <div className="flex h-full w-full max-w-2xl flex-col border-l border-border bg-card shadow-2xl">
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <FileCode2 className="h-4 w-4 shrink-0 text-muted-foreground" />
              <h2 className="truncate text-sm font-semibold text-foreground">{detail?.name ?? "Skill"}</h2>
              {detail && <SkillSourceBadge skill={detail} />}
            </div>
            {detail?.provenance_detail?.source && <p className="mt-1 text-[11px] text-muted-foreground">Source: {detail.provenance_detail.source}</p>}
          </div>
          <button type="button" onClick={onClose} className="grid h-8 w-8 place-items-center rounded-md text-muted-foreground hover:bg-foreground/10 hover:text-foreground" aria-label="Close skill details">
            <X className="h-4 w-4" />
          </button>
        </div>

        {loading && <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">Loading skill…</div>}
        {detail && !loading && (
          <>
            <div className="flex flex-wrap items-center gap-2 border-b border-border px-5 py-3 text-[11px] text-muted-foreground">
              <span>{prettyCategory(detail.category)}</span>
              <span>·</span>
              <span>{detail.enabled ? "Enabled" : "Disabled"}</span>
              {detail.modified && <><span>·</span><span className="text-amber-300">User-modified</span></>}
              {detail.location && <><span>·</span><span className="truncate">{detail.location}</span></>}
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
              <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
                <p className="max-w-xl text-xs leading-relaxed text-muted-foreground">{detail.description || "No description provided."}</p>
                <div className="flex shrink-0 gap-2">
                  {canEdit && !editing && <Button size="sm" variant="outline" className="h-8 gap-1.5 text-xs" onClick={onEdit}><Pencil className="h-3.5 w-3.5" />Edit</Button>}
                  {canRestore && <Button size="sm" variant="outline" className="h-8 gap-1.5 text-xs" onClick={onRestore} disabled={busy}><RefreshCw className="h-3.5 w-3.5" />Restore</Button>}
                  {canDelete && !confirmingDelete && <Button size="sm" variant="destructive" className="h-8 gap-1.5 text-xs" onClick={onArmDelete}><Trash2 className="h-3.5 w-3.5" />Delete</Button>}
                </div>
              </div>

              {confirmingDelete ? (
                <div className="mb-4 rounded-md border border-destructive/35 bg-destructive/5 p-3">
                  <p className="text-xs font-medium text-foreground">Remove {detail.name}?</p>
                  <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">This removes the active skill according to its source policy. Type the exact name to confirm.</p>
                  <div className="mt-3 flex gap-2">
                    <input autoFocus value={deleteName} onChange={(event) => onDeleteNameChange(event.target.value)} placeholder={detail.name} className="h-8 min-w-0 flex-1 rounded-md border border-input bg-background px-2.5 text-xs outline-none focus:ring-1 focus:ring-ring" aria-label={`Type ${detail.name} to confirm deletion`} />
                    <Button size="sm" variant="destructive" className="h-8 text-xs" disabled={!deleteMatches || busy} onClick={onDelete}>Confirm</Button>
                    <Button size="sm" variant="ghost" className="h-8 text-xs" onClick={onCancelDelete}>Cancel</Button>
                  </div>
                </div>
              ) : detail.provenance === "external" ? (
                <div className="mb-4 rounded-md border border-border bg-muted/30 p-3 text-[11px] leading-relaxed text-muted-foreground">This skill is outside the Spark profile and is read-only. Spark can inspect it, but will not delete files from its external source.</div>
              ) : null}

              <div className="rounded-md border border-border bg-background/70">
                <div className="flex items-center justify-between border-b border-border px-3 py-2">
                  <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">SKILL.md</span>
                  {editing && <span className="text-[10px] text-amber-300">Unsaved changes</span>}
                </div>
                {editing ? (
                  <div className="p-3">
                    <textarea value={draft} onChange={(event) => onDraftChange(event.target.value)} className="min-h-[28rem] w-full resize-y rounded-md border border-input bg-background p-3 font-mono text-xs leading-relaxed text-foreground outline-none focus:ring-1 focus:ring-ring" aria-label="Edit SKILL.md" spellCheck={false} />
                    <div className="mt-3 flex justify-end gap-2">
                      <Button size="sm" variant="ghost" className="h-8 text-xs" onClick={onCancelEdit} disabled={busy}>Cancel</Button>
                      <Button size="sm" className="h-8 gap-1.5 text-xs" onClick={onSave} disabled={busy || draft === detail.content}><Check className="h-3.5 w-3.5" />{busy ? "Saving…" : "Save changes"}</Button>
                    </div>
                  </div>
                ) : <pre className="max-h-[36rem] overflow-auto whitespace-pre-wrap break-words p-3 font-mono text-xs leading-relaxed text-foreground/90">{detail.content}</pre>}
              </div>

              {detail.supporting_files.length > 0 && <div className="mt-4"><h3 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Supporting files</h3><div className="mt-2 grid gap-1">{detail.supporting_files.map((file) => <div key={file.path} className="flex items-center justify-between rounded border border-border/60 px-2.5 py-2 text-[11px] text-muted-foreground"><span className="truncate">{file.path}</span><span className="ml-3 shrink-0">{file.file_type || "file"} · {file.size.toLocaleString()} B</span></div>)}</div></div>}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default function SkillsToolsPage() {
  const [tab, setTab] = useState<Tab>("skills");
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [toolsets, setToolsets] = useState<ToolsetInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [activeCategory, setActiveCategory] = useState<string | null>(null);
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all");
  const [toggling, setToggling] = useState<Set<string>>(new Set());
  const [selectedSkill, setSelectedSkill] = useState<SkillInfo | null>(null);
  const [detail, setDetail] = useState<SkillDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [actionBusy, setActionBusy] = useState(false);
  const [deleteName, setDeleteName] = useState("");
  const [deleteArmed, setDeleteArmed] = useState(false);
  const { toast, showToast } = useToast();

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([api.getSkills(), api.getToolsets()]).then(([nextSkills, nextToolsets]) => {
      setSkills(nextSkills);
      setToolsets(nextToolsets);
    }).catch((error) => showToast(`Failed to load skills: ${errorMessage(error)}`, "error")).finally(() => setLoading(false));
  }, [showToast]);

  useEffect(() => load(), [load]);

  useEventBus((env) => {
    if (env.topic !== "skills.updated") return;
    api.getSkills().then(setSkills).catch(() => {});
  });

  useEffect(() => {
    const focusSkill = (name: string) => {
      setTab("skills");
      setSourceFilter("all");
      setActiveCategory(null);
      setSearch(name);
    };
    const target = takeGlobalNavTarget("skill");
    if (target) focusSkill(target.id);
    const handler = (event: Event) => {
      const targetEvent = (event as CustomEvent<GlobalNavTarget>).detail;
      if (targetEvent?.type === "skill") focusSkill(targetEvent.id);
    };
    window.addEventListener(GLOBAL_NAV_EVENT, handler);
    return () => window.removeEventListener(GLOBAL_NAV_EVENT, handler);
  }, []);

  useEffect(() => {
    if (!selectedSkill) return;
    const selected = skills.find((skill) => skillId(skill) === skillId(selectedSkill));
    if (selected) setSelectedSkill(selected);
  }, [skills, selectedSkill]);

  useEffect(() => {
    if (!selectedSkill) {
      setDetail(null);
      setEditing(false);
      setDeleteName("");
      setDeleteArmed(false);
      return;
    }
    let alive = true;
    setDetailLoading(true);
    api.getSkill(skillId(selectedSkill)).then((nextDetail) => {
      if (!alive) return;
      setDetail(nextDetail);
      setDraft(nextDetail.content);
    }).catch((error) => alive && showToast(`Failed to load ${selectedSkill.name}: ${errorMessage(error)}`, "error")).finally(() => alive && setDetailLoading(false));
    return () => { alive = false; };
  }, [selectedSkill, showToast]);

  useEffect(() => {
    if (!selectedSkill) return;
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSelectedSkill(null);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [selectedSkill]);

  const handleToggleSkill = async (skill: SkillInfo) => {
    const id = skillId(skill);
    setToggling((prev) => new Set(prev).add(id));
    try {
      await api.toggleSkill(skill.name, !skill.enabled, id);
      setSkills((prev) => prev.map((item) => skillId(item) === id ? { ...item, enabled: !item.enabled } : item));
      if (detail && skillId(detail) === id) setDetail({ ...detail, enabled: !skill.enabled });
    } catch (error) {
      showToast(`Failed to toggle ${skill.name}: ${errorMessage(error)}`, "error");
    } finally {
      setToggling((prev) => { const next = new Set(prev); next.delete(id); return next; });
    }
  };

  const openSkill = (skill: SkillInfo) => {
    setDeleteName("");
    setDeleteArmed(false);
    setEditing(false);
    setDetail(null);
    setSelectedSkill(skill);
  };

  const saveDetail = async () => {
    if (!detail) return;
    setActionBusy(true);
    try {
      const response = await api.saveSkill(skillId(detail), draft);
      setDetail(response.skill);
      setDraft(response.skill.content);
      setSkills((prev) => prev.map((skill) => skillId(skill) === skillId(detail) ? response.skill : skill));
      setEditing(false);
      showToast(`${detail.name} saved. It will apply to a future conversation context.`, "success");
    } catch (error) {
      showToast(`Could not save ${detail.name}: ${errorMessage(error)}`, "error");
    } finally {
      setActionBusy(false);
    }
  };

  const deleteDetail = async () => {
    if (!detail || detail.name !== deleteName) return;
    setActionBusy(true);
    try {
      await api.deleteSkill(skillId(detail));
      showToast(`${detail.name} removed.`, "success");
      setSkills((prev) => prev.filter((skill) => skillId(skill) !== skillId(detail)));
      setDeleteArmed(false);
      setSelectedSkill(null);
    } catch (error) {
      showToast(`Could not remove ${detail.name}: ${errorMessage(error)}`, "error");
    } finally {
      setActionBusy(false);
    }
  };

  const restoreDetail = async () => {
    if (!detail) return;
    setActionBusy(true);
    try {
      const response = await api.restoreSkill(skillId(detail));
      setDetail(response.skill);
      setDraft(response.skill.content);
      setSkills((prev) => prev.map((skill) => skillId(skill) === skillId(detail) ? response.skill : skill));
      showToast(`${detail.name} restored.`, "success");
    } catch (error) {
      showToast(`Could not restore ${detail.name}: ${errorMessage(error)}`, "error");
    } finally {
      setActionBusy(false);
    }
  };

  const lowerSearch = search.toLowerCase();
  const filteredSkills = useMemo(() => skills.filter((skill) => {
    const sourceMatch = sourceFilter === "all" || sourceOf(skill) === sourceFilter;
    const categoryMatch = !activeCategory || (activeCategory === "__none__" ? !skill.category : skill.category === activeCategory);
    const searchMatch = !search || [skill.name, skill.description, skill.category ?? "", sourceLabel(skill)].some((value) => value.toLowerCase().includes(lowerSearch));
    return sourceMatch && categoryMatch && searchMatch;
  }), [skills, sourceFilter, activeCategory, search, lowerSearch]);

  const sourceCounts = useMemo(() => {
    const counts = new Map<SourceFilter, number>([["all", skills.length]]);
    for (const skill of skills) {
      const source = sourceOf(skill);
      counts.set(source, (counts.get(source) ?? 0) + 1);
    }
    return counts;
  }, [skills]);

  const categoryChips = useMemo(() => {
    const counts = new Map<string, number>();
    for (const skill of skills) {
      const key = skill.category || "__none__";
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    return [...counts.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([key, count]) => ({ key, count, label: prettyCategory(key === "__none__" ? null : key) }));
  }, [skills]);

  const filteredToolsets = useMemo(() => toolsets.filter((toolset) => !search || [toolset.name, toolset.label, toolset.description].some((value) => value.toLowerCase().includes(lowerSearch))), [toolsets, search, lowerSearch]);

  if (loading) return <div className="flex items-center justify-center py-24"><div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" /></div>;

  const tabClass = (active: boolean) => `border-b-2 pb-1.5 text-[13px] font-medium transition ${active ? "border-foreground text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"}`;

  return (
    <div className="relative flex h-full min-h-0 flex-col">
      <Toast toast={toast} />
      <div className="flex items-center justify-between gap-4 px-5 pt-4">
        <div className="flex items-center gap-5">
          {(["skills", "toolsets", "tools", "keys"] as Tab[]).map((value) => <button key={value} type="button" className={tabClass(tab === value)} onClick={() => setTab(value)}>{value === "toolsets" ? "Toolsets" : value.charAt(0).toUpperCase() + value.slice(1)}</button>)}
        </div>
        {tab !== "tools" && <div className="flex items-center gap-2"><div className="relative"><Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" /><input className="h-8 w-48 rounded-md border-none bg-transparent pl-8 pr-7 text-[13px] text-foreground outline-none placeholder:text-muted-foreground focus:bg-foreground/5" placeholder={tab === "skills" ? "Search skills…" : "Search toolsets…"} value={search} onChange={(event) => setSearch(event.target.value)} />{search && <button type="button" className="absolute right-1.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground" onClick={() => setSearch("")} aria-label="Clear search"><X className="h-3.5 w-3.5" /></button>}</div><button type="button" className="grid h-7 w-7 place-items-center rounded-md text-muted-foreground transition hover:bg-foreground/6 hover:text-foreground" title="Refresh" aria-label="Refresh" onClick={load}><RefreshCw className="h-3.5 w-3.5" /></button></div>}
      </div>

      {tab === "skills" && <>
        <div className="flex flex-wrap gap-2 px-5 pt-4" role="tablist" aria-label="Skill sources">
          {["all", "bundled", "spark_created", "hub_installed", "local", "external"].map((value) => { const source = value as SourceFilter; const count = sourceCounts.get(source) ?? 0; return <button key={source} type="button" role="tab" aria-selected={sourceFilter === source} onClick={() => setSourceFilter(source)} className={`rounded-full border px-3 py-1.5 text-[11px] font-medium transition ${sourceFilter === source ? "border-foreground/40 bg-foreground/10 text-foreground" : "border-border text-muted-foreground hover:bg-foreground/5 hover:text-foreground"}`}>{SOURCE_LABELS[source]} <span className="ml-1 text-[10px] opacity-70">{count}</span></button>; })}
        </div>
        <div className="flex flex-wrap items-baseline gap-x-5 gap-y-1.5 px-5 pt-4">
          <button type="button" onClick={() => setActiveCategory(null)} className={`text-[12px] font-medium transition ${activeCategory === null ? "text-foreground underline underline-offset-4" : "text-muted-foreground hover:text-foreground"}`}>All categories</button>
          {categoryChips.map((category) => <button key={category.key} type="button" onClick={() => setActiveCategory(activeCategory === category.key ? null : category.key)} className={`text-[12px] font-medium transition ${activeCategory === category.key ? "text-foreground underline underline-offset-4" : "text-muted-foreground hover:text-foreground"}`}>{category.label} <span className="ml-0.5 text-[10px] opacity-70">{category.count}</span></button>)}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-8 pt-3"><div className="mx-auto max-w-5xl">
          <div className="mb-3 flex items-center justify-between text-[11px] text-muted-foreground"><span>{filteredSkills.length} skill{filteredSkills.length === 1 ? "" : "s"}</span><span>Click a row to inspect the actual SKILL.md</span></div>
          {filteredSkills.length === 0 ? <div className="rounded-md border border-dashed border-border px-5 py-16 text-center text-sm text-muted-foreground">No skills match these filters.</div> : <div className="overflow-hidden rounded-md border border-border/70">{[...filteredSkills].sort((a, b) => a.name.localeCompare(b.name)).map((skill) => <SkillRow key={skillId(skill)} skill={skill} toggling={toggling.has(skillId(skill))} onOpen={() => openSkill(skill)} onToggle={() => void handleToggleSkill(skill)} />)}</div>}
        </div></div>
      </>}

      {tab === "toolsets" && <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-8 pt-4"><div className="mx-auto max-w-4xl">{filteredToolsets.length === 0 ? <p className="py-16 text-center text-sm text-muted-foreground">No toolsets match.</p> : filteredToolsets.map((toolset) => <div key={toolset.name} className="flex items-center justify-between gap-6 border-b border-border/40 py-3"><div className="min-w-0"><div className="flex items-center gap-2"><span className="text-[13px] font-semibold text-foreground">{toolset.label || toolset.name}</span>{!toolset.configured && <Badge variant="secondary" className="text-[10px]">Needs setup</Badge>}</div><div className="mt-0.5 text-xs leading-relaxed text-muted-foreground">{toolset.description}</div>{toolset.tools.length > 0 && <div className="mt-1 truncate text-[11px] text-muted-foreground/70">{toolset.tools.slice(0, 8).join(" · ")}{toolset.tools.length > 8 ? ` · +${toolset.tools.length - 8} more` : ""}</div>}</div><Badge variant={toolset.enabled ? "default" : "secondary"} className="shrink-0 text-[10px]">{toolset.enabled ? "Enabled" : "Disabled"}</Badge></div>)}</div></div>}
      {tab === "tools" && <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-8 pt-4"><div className="mx-auto max-w-5xl"><ConnectorsPage /></div></div>}
      {tab === "keys" && <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-8 pt-4"><div className="mx-auto max-w-5xl"><EnvPage /></div></div>}

      {selectedSkill && <SkillDetailPanel detail={detail} loading={detailLoading} draft={draft} editing={editing} busy={actionBusy} deleteName={deleteName} deleteArmed={deleteArmed} onDraftChange={setDraft} onEdit={() => { if (detail) { setDraft(detail.content); setEditing(true); } }} onSave={() => void saveDetail()} onCancelEdit={() => { setDraft(detail?.content ?? ""); setEditing(false); }} onDelete={() => void deleteDetail()} onRestore={() => void restoreDetail()} onDeleteNameChange={setDeleteName} onArmDelete={() => { setDeleteName(""); setDeleteArmed(true); }} onCancelDelete={() => { setDeleteName(""); setDeleteArmed(false); }} onClose={() => setSelectedSkill(null)} />}
    </div>
  );
}
