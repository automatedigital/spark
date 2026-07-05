import { useEffect, useMemo, useState } from "react";
import { RefreshCw, Search, X } from "lucide-react";
import { api } from "@/lib/api";
import type { SkillInfo, ToolsetInfo } from "@/lib/api";
import { useToast } from "@/hooks/useToast";
import { useEventBus } from "@/hooks/useEventBus";
import { Toast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import ConnectorsPage from "@/pages/ConnectorsPage";
import { GLOBAL_NAV_EVENT, takeGlobalNavTarget, type GlobalNavTarget } from "@/lib/globalNavigation";

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

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
  return raw
    .split(/[-_/]/)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join("-");
}

type Tab = "skills" | "toolsets" | "tools";

interface CategoryGroup {
  key: string;
  name: string;
  skills: SkillInfo[];
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function SkillsToolsPage() {
  const [tab, setTab] = useState<Tab>("skills");
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [toolsets, setToolsets] = useState<ToolsetInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [activeCategory, setActiveCategory] = useState<string | null>(null);
  const [toggling, setToggling] = useState<Set<string>>(new Set());
  const { toast, showToast } = useToast();

  const load = () => {
    Promise.all([api.getSkills(), api.getToolsets()])
      .then(([s, ts]) => {
        setSkills(s);
        setToolsets(ts);
      })
      .catch(() => showToast("Failed to load skills", "error"))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  useEventBus((env) => {
    if (env.topic !== "skills.updated") return;
    api.getSkills().then(setSkills).catch(() => {});
  });

  // Deep link from the command palette / global nav: focus a specific skill.
  useEffect(() => {
    const focusSkill = (name: string) => {
      setTab("skills");
      setActiveCategory(null);
      setSearch(name);
    };
    const target = takeGlobalNavTarget("skill");
    if (target) focusSkill(target.id);
    const handler = (event: Event) => {
      const t = (event as CustomEvent<GlobalNavTarget>).detail;
      if (t?.type === "skill") focusSkill(t.id);
    };
    window.addEventListener(GLOBAL_NAV_EVENT, handler);
    return () => window.removeEventListener(GLOBAL_NAV_EVENT, handler);
  }, []);

  const handleToggleSkill = async (skill: SkillInfo) => {
    setToggling((prev) => new Set(prev).add(skill.name));
    try {
      await api.toggleSkill(skill.name, !skill.enabled);
      setSkills((prev) =>
        prev.map((s) => (s.name === skill.name ? { ...s, enabled: !s.enabled } : s)),
      );
    } catch {
      showToast(`Failed to toggle ${skill.name}`, "error");
    } finally {
      setToggling((prev) => {
        const next = new Set(prev);
        next.delete(skill.name);
        return next;
      });
    }
  };

  /* ---- Derived data ---- */
  const lowerSearch = search.toLowerCase();

  const filteredSkills = useMemo(
    () =>
      skills.filter((s) => {
        const matchesSearch =
          !search ||
          s.name.toLowerCase().includes(lowerSearch) ||
          s.description.toLowerCase().includes(lowerSearch);
        const matchesCategory =
          !activeCategory ||
          (activeCategory === "__none__" ? !s.category : s.category === activeCategory);
        return matchesSearch && matchesCategory;
      }),
    [skills, search, lowerSearch, activeCategory],
  );

  const groups: CategoryGroup[] = useMemo(() => {
    const map = new Map<string, SkillInfo[]>();
    for (const s of filteredSkills) {
      const key = s.category || "__none__";
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(s);
    }
    return [...map.entries()]
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([key, list]) => ({
        key,
        name: prettyCategory(key === "__none__" ? null : key),
        skills: list.sort((a, b) => a.name.localeCompare(b.name)),
      }));
  }, [filteredSkills]);

  const categoryChips = useMemo(() => {
    const counts = new Map<string, number>();
    for (const s of skills) {
      const key = s.category || "__none__";
      counts.set(key, (counts.get(key) || 0) + 1);
    }
    return [...counts.entries()]
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([key, count]) => ({ key, name: prettyCategory(key === "__none__" ? null : key), count }));
  }, [skills]);

  const filteredToolsets = useMemo(
    () =>
      toolsets.filter(
        (ts) =>
          !search ||
          ts.name.toLowerCase().includes(lowerSearch) ||
          ts.label.toLowerCase().includes(lowerSearch) ||
          ts.description.toLowerCase().includes(lowerSearch),
      ),
    [toolsets, search, lowerSearch],
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      </div>
    );
  }

  const tabClass = (active: boolean) =>
    `border-b-2 pb-1.5 text-[13px] font-medium transition ${
      active
        ? "border-foreground text-foreground"
        : "border-transparent text-muted-foreground hover:text-foreground"
    }`;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <Toast toast={toast} />

      {/* ── Header: tabs left, search right ── */}
      <div className="flex items-center justify-between gap-4 px-5 pt-4">
        <div className="flex items-center gap-5">
          <button type="button" className={tabClass(tab === "skills")} onClick={() => setTab("skills")}>
            Skills
          </button>
          <button type="button" className={tabClass(tab === "toolsets")} onClick={() => setTab("toolsets")}>
            Toolsets
          </button>
          <button type="button" className={tabClass(tab === "tools")} onClick={() => setTab("tools")}>
            Tools
          </button>
        </div>
        {tab !== "tools" && (
          <div className="flex items-center gap-2">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
              <input
                className="h-8 w-44 rounded-md border-none bg-transparent pl-8 pr-7 text-[13px] text-foreground outline-none placeholder:text-muted-foreground focus:bg-foreground/5"
                placeholder={tab === "skills" ? "Search skills..." : "Search toolsets..."}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              {search && (
                <button
                  type="button"
                  className="absolute right-1.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                  onClick={() => setSearch("")}
                  aria-label="Clear search"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
            <button
              type="button"
              className="grid h-7 w-7 place-items-center rounded-md text-muted-foreground transition hover:bg-foreground/6 hover:text-foreground"
              title="Refresh"
              aria-label="Refresh"
              onClick={load}
            >
              <RefreshCw className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
      </div>

      {/* ── Skills tab ── */}
      {tab === "skills" && (
        <>
          {/* Category chips */}
          <div className="flex flex-wrap items-baseline gap-x-5 gap-y-1.5 px-5 pt-4">
            <button
              type="button"
              onClick={() => setActiveCategory(null)}
              className={`text-[13px] font-medium transition ${
                activeCategory === null
                  ? "text-foreground underline underline-offset-4"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              All <span className="ml-0.5 text-[11px] text-muted-foreground">{skills.length}</span>
            </button>
            {categoryChips.map((c) => (
              <button
                key={c.key}
                type="button"
                onClick={() => setActiveCategory(activeCategory === c.key ? null : c.key)}
                className={`text-[13px] font-medium transition ${
                  activeCategory === c.key
                    ? "text-foreground underline underline-offset-4"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {c.name} <span className="ml-0.5 text-[11px] text-muted-foreground">{c.count}</span>
              </button>
            ))}
          </div>

          {/* Flat grouped list */}
          <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-8 pt-2">
            <div className="mx-auto max-w-4xl">
              {groups.length === 0 && (
                <p className="py-16 text-center text-sm text-muted-foreground">No skills match.</p>
              )}
              {groups.map((g) => (
                <section key={g.key} className="pt-5">
                  <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                    {g.name}
                  </h2>
                  <div className="mt-1">
                    {g.skills.map((s) => (
                      <div
                        key={s.name}
                        className="flex items-center justify-between gap-6 border-b border-border/40 py-3 last:border-b-0"
                      >
                        <div className="min-w-0">
                          <div className="text-[13px] font-semibold text-foreground">{s.name}</div>
                          <div className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                            {s.description}
                          </div>
                        </div>
                        <Switch
                          checked={s.enabled}
                          disabled={toggling.has(s.name)}
                          onCheckedChange={() => handleToggleSkill(s)}
                          aria-label={`Toggle ${s.name}`}
                        />
                      </div>
                    ))}
                  </div>
                </section>
              ))}
            </div>
          </div>
        </>
      )}

      {/* ── Toolsets tab ── */}
      {tab === "toolsets" && (
        <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-8 pt-4">
          <div className="mx-auto max-w-4xl">
            {filteredToolsets.length === 0 && (
              <p className="py-16 text-center text-sm text-muted-foreground">No toolsets match.</p>
            )}
            {filteredToolsets.map((ts) => (
              <div
                key={ts.name}
                className="flex items-center justify-between gap-6 border-b border-border/40 py-3 last:border-b-0"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-[13px] font-semibold text-foreground">{ts.label || ts.name}</span>
                    {!ts.configured && (
                      <Badge variant="secondary" className="text-[10px]">
                        Needs setup
                      </Badge>
                    )}
                  </div>
                  <div className="mt-0.5 text-xs leading-relaxed text-muted-foreground">{ts.description}</div>
                  {ts.tools.length > 0 && (
                    <div className="mt-1 truncate text-[11px] text-muted-foreground/70">
                      {ts.tools.slice(0, 8).join(" · ")}
                      {ts.tools.length > 8 ? ` · +${ts.tools.length - 8} more` : ""}
                    </div>
                  )}
                </div>
                <Badge variant={ts.enabled ? "default" : "secondary"} className="shrink-0 text-[10px]">
                  {ts.enabled ? "Enabled" : "Disabled"}
                </Badge>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Tools tab: connectors / plugins to external apps ── */}
      {tab === "tools" && (
        <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-8 pt-4">
          <div className="mx-auto max-w-5xl">
            {/* Connectors page owns all app/tool connections, including MCP. */}
            <ConnectorsPage />
          </div>
        </div>
      )}
    </div>
  );
}
