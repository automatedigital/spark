import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  Archive,
  Boxes,
  CheckCircle2,
  Database,
  Download,
  HardDrive,
  Play,
  Plug,
  RefreshCw,
  Search,
  Server,
  Shield,
  Upload,
  Wrench,
  XCircle,
} from "lucide-react";
import {
  api,
  sseUrl,
  type AdminActionMeta,
  type DiagnosticsSummary,
  type GatewayAdminStatus,
  type McpServersResponse,
  type PluginInfo,
  type ProfileInfo,
} from "@/lib/api";

type TabId = "setup" | "gateway" | "profiles" | "diagnostics" | "plugins" | "mcp" | "backups" | "updates";

const TABS: Array<{ id: TabId; label: string; icon: typeof Shield }> = [
  { id: "setup", label: "Setup", icon: Shield },
  { id: "gateway", label: "Gateway", icon: Server },
  { id: "profiles", label: "Profiles", icon: Database },
  { id: "diagnostics", label: "Diagnostics", icon: Wrench },
  { id: "plugins", label: "Plugins", icon: Boxes },
  { id: "mcp", label: "MCP", icon: Plug },
  { id: "backups", label: "Backups", icon: Archive },
  { id: "updates", label: "Updates", icon: Download },
];

function riskClass(risk: string): string {
  if (risk === "high") return "border-red-500/40 text-red-300";
  if (risk === "medium") return "border-amber-500/40 text-amber-300";
  return "border-emerald-500/40 text-emerald-300";
}

function ShellButton({
  children,
  onClick,
  disabled = false,
  tone = "normal",
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
  tone?: "normal" | "danger" | "primary";
}) {
  const cls =
    tone === "danger"
      ? "border-red-600/50 text-red-300 hover:bg-red-950/30"
      : tone === "primary"
        ? "border-accent text-accent hover:bg-accent/10"
        : "border-border hover:bg-foreground/5";
  return (
    <button
      type="button"
      disabled={disabled}
      className={`px-2.5 py-1.5 text-xs uppercase tracking-wider border disabled:opacity-40 disabled:cursor-not-allowed ${cls}`}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

export default function AdminPage() {
  const [tab, setTab] = useState<TabId>("setup");
  const [query, setQuery] = useState("");
  const [actions, setActions] = useState<AdminActionMeta[]>([]);
  const [gateway, setGateway] = useState<GatewayAdminStatus | null>(null);
  const [profiles, setProfiles] = useState<ProfileInfo[]>([]);
  const [plugins, setPlugins] = useState<PluginInfo[]>([]);
  const [mcp, setMcp] = useState<McpServersResponse | null>(null);
  const [diag, setDiag] = useState<DiagnosticsSummary | null>(null);
  const [newProfile, setNewProfile] = useState("");
  const [cloneProfile, setCloneProfile] = useState("");
  const [pluginName, setPluginName] = useState("");
  const [mcpName, setMcpName] = useState("");
  const [mcpUrl, setMcpUrl] = useState("");
  const [mcpCommand, setMcpCommand] = useState("");
  const [importPath, setImportPath] = useState("");
  const [outputLines, setOutputLines] = useState<string[]>([]);
  const [runStatus, setRunStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadAll = useCallback(async () => {
    setError(null);
    try {
      const [actionResp, gw, prof, pluginResp, mcpResp, summary] = await Promise.all([
        api.getAdminActions(),
        api.getGatewayAdminStatus(),
        api.getProfiles(),
        api.getPlugins(),
        api.getMcpServers(),
        api.getDiagnosticsSummary(),
      ]);
      setActions(actionResp.actions);
      setGateway(gw);
      setProfiles(prof.profiles);
      setPlugins(pluginResp.plugins);
      setMcp(mcpResp);
      setDiag(summary);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  const filteredActions = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return actions;
    return actions.filter((a) => `${a.id} ${a.label} ${a.description}`.toLowerCase().includes(q));
  }, [actions, query]);

  const streamRun = (runId: string) => {
    setRunStatus("queued");
    setOutputLines([]);
    const es = new EventSource(sseUrl(`/api/admin/actions/runs/${encodeURIComponent(runId)}/stream`));
    es.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data) as { type?: string; status?: string; stream?: string; text?: string; run?: { status?: string } };
        if (data.status) setRunStatus(data.status);
        if (data.type === "output" && data.text != null) {
          setOutputLines((prev) => [...prev.slice(-300), `[${data.stream ?? "out"}] ${data.text}`]);
        }
        if (data.type === "done") {
          setRunStatus(data.run?.status ?? "done");
          es.close();
          void loadAll();
        }
      } catch {
        setOutputLines((prev) => [...prev.slice(-300), ev.data]);
      }
    };
    es.onerror = () => es.close();
  };

  const runAction = async (id: string, args: Record<string, unknown> = {}, confirm = false) => {
    setError(null);
    try {
      const resp = await api.runAdminAction(id, args, confirm);
      streamRun(resp.run_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const runActionWithPrompt = async (action: AdminActionMeta, args: Record<string, unknown> = {}) => {
    const ok = !action.requires_confirmation || window.confirm(`Run ${action.label}?`);
    if (ok) await runAction(action.id, args, action.requires_confirmation);
  };

  const gatewayAction = async (action: string) => {
    const ok = window.confirm(`${action} gateway?`);
    if (!ok) return;
    try {
      const resp = await api.controlGateway(action, true);
      streamRun(resp.run_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const createProfile = async () => {
    if (!newProfile.trim()) return;
    try {
      const resp = await api.createProfile({
        name: newProfile.trim(),
        clone_from: cloneProfile || null,
        clone_config: Boolean(cloneProfile),
        no_alias: true,
      });
      setProfiles(resp.profiles);
      setNewProfile("");
      setCloneProfile("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const setupItems = [
    { label: "Model/provider configured", ok: Boolean(diag?.config_version), target: "Config" },
    { label: "Dashboard auth available", ok: Boolean(diag?.dashboard_auth.configured), target: "Keys" },
    { label: "Gateway checked", ok: Boolean(gateway), target: "Gateway" },
    { label: "Kanban dispatch policy reviewed", ok: true, target: "Tasks" },
    { label: "Required environment keys present", ok: (diag?.missing_required_env.length ?? 0) === 0, target: "Keys" },
  ];

  return (
    <div className="flex flex-col gap-4 min-h-[70vh]">
      <header className="border border-border bg-background/80 p-4 flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Shield className="h-5 w-5 text-accent" />
            <h1 className="font-display text-lg uppercase tracking-[0.15em]">Admin</h1>
          </div>
          <div className="flex items-center gap-2">
            <div className="relative">
              <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 opacity-50" />
              <input
                className="pl-7 pr-2 py-1.5 border border-border bg-background text-sm min-w-[220px]"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search admin actions"
              />
            </div>
            <ShellButton onClick={() => void loadAll()}>Refresh</ShellButton>
          </div>
        </div>
        <div className="flex flex-wrap gap-1">
          {TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              className={`px-3 py-2 text-xs uppercase tracking-wider border flex items-center gap-1.5 ${
                tab === id ? "border-accent text-accent bg-accent/10" : "border-border hover:bg-foreground/5"
              }`}
              onClick={() => setTab(id)}
            >
              <Icon className="h-3.5 w-3.5" />
              {label}
            </button>
          ))}
        </div>
      </header>

      {error && <div className="border border-red-900/60 text-red-300 p-3 text-sm">{error}</div>}

      {query.trim() && (
        <section className="border border-border bg-background/70 p-3">
          <div className="text-xs uppercase tracking-wider opacity-70 mb-2">Matching Actions</div>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-2">
            {filteredActions.map((action) => (
              <button
                key={action.id}
                type="button"
                disabled={!action.available}
                onClick={() => void runActionWithPrompt(action)}
                className="text-left border border-border p-3 hover:border-accent/50 disabled:opacity-50"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium text-sm">{action.label}</span>
                  <span className={`text-[10px] border px-1.5 py-0.5 uppercase ${riskClass(action.risk)}`}>{action.risk}</span>
                </div>
                <p className="text-xs opacity-70 mt-1">{action.description}</p>
              </button>
            ))}
          </div>
        </section>
      )}

      {tab === "setup" && (
        <section className="border border-border bg-background/70 p-4">
          <div className="text-xs uppercase tracking-wider opacity-70 mb-3">Setup Wizard</div>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-2">
            {setupItems.map((item) => (
              <div key={item.label} className="border border-border p-3 flex items-start gap-2">
                {item.ok ? <CheckCircle2 className="h-4 w-4 text-emerald-400 mt-0.5" /> : <XCircle className="h-4 w-4 text-amber-300 mt-0.5" />}
                <div>
                  <div className="text-sm">{item.label}</div>
                  <div className="text-xs opacity-60">{item.target}</div>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {tab === "gateway" && (
        <section className="border border-border bg-background/70 p-4 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-sm font-medium">Gateway: {gateway?.state ?? "unknown"}</div>
              <div className="text-xs opacity-60">PID {gateway?.pid ?? "none"} · {gateway?.service_system ?? "unknown"}</div>
            </div>
            <div className="flex flex-wrap gap-2">
              {["start", "stop", "restart", "install", "uninstall", "status"].map((action) => (
                <ShellButton key={action} tone={action === "stop" || action === "uninstall" ? "danger" : "normal"} onClick={() => void gatewayAction(action)}>
                  {action}
                </ShellButton>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-sm">
            <div className="border border-border p-3">
              <div className="text-xs uppercase tracking-wider opacity-70 mb-2">Configured Platforms</div>
              {(gateway?.configured_platforms ?? []).length ? gateway?.configured_platforms.map((p) => <div key={p.id}>{p.id}</div>) : <div className="opacity-60">None</div>}
            </div>
            <div className="border border-border p-3">
              <div className="text-xs uppercase tracking-wider opacity-70 mb-2">Last Error</div>
              <div className="opacity-80 whitespace-pre-wrap">{gateway?.last_error ?? "None"}</div>
            </div>
          </div>
        </section>
      )}

      {tab === "profiles" && (
        <section className="border border-border bg-background/70 p-4 space-y-3">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-2">
            <input className="border border-border bg-background px-2 py-1.5 text-sm" value={newProfile} onChange={(e) => setNewProfile(e.target.value)} placeholder="New profile name" />
            <select className="border border-border bg-background px-2 py-1.5 text-sm" value={cloneProfile} onChange={(e) => setCloneProfile(e.target.value)}>
              <option value="">Fresh profile</option>
              {profiles.map((p) => <option key={p.name} value={p.name}>Clone {p.name}</option>)}
            </select>
            <ShellButton tone="primary" onClick={() => void createProfile()}>Create</ShellButton>
            <ShellButton onClick={() => importPath && void api.importProfile(importPath, undefined, window.confirm("Import profile archive?")).then(loadAll).catch((e) => setError(String(e)))}>Import</ShellButton>
          </div>
          <input className="w-full border border-border bg-background px-2 py-1.5 text-sm" value={importPath} onChange={(e) => setImportPath(e.target.value)} placeholder="Import archive path" />
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
            {profiles.map((p) => (
              <div key={p.name} className="border border-border p-3 text-sm">
                <div className="flex justify-between gap-2">
                  <div>
                    <div className="font-medium">{p.name} {p.is_active ? "(active)" : ""}</div>
                    <div className="text-xs opacity-60 truncate">{p.path}</div>
                  </div>
                  <div className="flex gap-1">
                    <ShellButton disabled={p.is_active} onClick={() => void api.useProfile(p.name).then(loadAll)}>Use</ShellButton>
                    <ShellButton onClick={() => void api.exportProfile(p.name, undefined, window.confirm(`Export ${p.name}?`)).then(loadAll)}>Export</ShellButton>
                    {!p.is_default && <ShellButton tone="danger" onClick={() => void api.deleteProfile(p.name, window.confirm(`Delete profile ${p.name}?`)).then(loadAll)}>Delete</ShellButton>}
                  </div>
                </div>
                <div className="mt-2 text-xs opacity-70">{p.model ?? "no model"} · {p.skill_count} skills · gateway {p.gateway_running ? "running" : "stopped"}</div>
              </div>
            ))}
          </div>
        </section>
      )}

      {tab === "diagnostics" && (
        <section className="border border-border bg-background/70 p-4 space-y-3">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-2 text-sm">
            <div className="border border-border p-3"><Activity className="h-4 w-4 mb-2 opacity-70" />Python {diag?.python ?? "unknown"}</div>
            <div className="border border-border p-3"><HardDrive className="h-4 w-4 mb-2 opacity-70" />{diag?.spark_home ?? "unknown"}</div>
            <div className="border border-border p-3">{diag?.missing_required_env.length ?? 0} missing required env keys</div>
          </div>
          <div className="flex flex-wrap gap-2">
            {actions.filter((a) => a.id.startsWith("diagnostics.")).map((action) => (
              <ShellButton key={action.id} onClick={() => void runActionWithPrompt(action, action.id === "diagnostics.debug" ? { lines: 200 } : {})}>{action.label}</ShellButton>
            ))}
          </div>
        </section>
      )}

      {tab === "plugins" && (
        <section className="border border-border bg-background/70 p-4 space-y-3">
          <div className="flex flex-wrap gap-2">
            <input className="border border-border bg-background px-2 py-1.5 text-sm min-w-[260px]" value={pluginName} onChange={(e) => setPluginName(e.target.value)} placeholder="Plugin id or source" />
            {["install", "update", "enable", "disable", "remove"].map((action) => (
              <ShellButton key={action} tone={action === "remove" ? "danger" : "normal"} onClick={() => pluginName && void api.runPluginAction(action, pluginName, action !== "enable" && action !== "disable").then((r) => streamRun(r.run_id)).catch((e) => setError(String(e)))}>{action}</ShellButton>
            ))}
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {plugins.map((p) => (
              <div key={p.id} className="border border-border p-3 text-sm">
                <div className="flex justify-between gap-2"><span className="font-medium">{p.name}</span><span className="text-xs opacity-60">{p.enabled ? "enabled" : "disabled"}</span></div>
                <div className="text-xs opacity-70">{p.description ?? p.path}</div>
              </div>
            ))}
          </div>
        </section>
      )}

      {tab === "mcp" && (
        <section className="border border-border bg-background/70 p-4 space-y-3">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-2">
            <input className="border border-border bg-background px-2 py-1.5 text-sm" value={mcpName} onChange={(e) => setMcpName(e.target.value)} placeholder="Server name" />
            <input className="border border-border bg-background px-2 py-1.5 text-sm" value={mcpUrl} onChange={(e) => setMcpUrl(e.target.value)} placeholder="HTTP URL" />
            <input className="border border-border bg-background px-2 py-1.5 text-sm" value={mcpCommand} onChange={(e) => setMcpCommand(e.target.value)} placeholder="stdio command" />
            <ShellButton tone="primary" onClick={() => mcpName && void api.addMcpServer({ name: mcpName, url: mcpUrl || null, command: mcpCommand || null }).then(loadAll).catch((e) => setError(String(e)))}>Add</ShellButton>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {Object.entries(mcp?.servers ?? {}).map(([name, cfg]) => (
              <div key={name} className="border border-border p-3 text-sm">
                <div className="flex justify-between gap-2">
                  <span className="font-medium">{name}</span>
                  <span className="flex gap-1">
                    <ShellButton onClick={() => void api.testMcpServer(name).then((r) => streamRun(r.run_id)).catch((e) => setError(String(e)))}>Test</ShellButton>
                    <ShellButton tone="danger" onClick={() => void api.deleteMcpServer(name, window.confirm(`Remove MCP server ${name}?`)).then(loadAll).catch((e) => setError(String(e)))}>Remove</ShellButton>
                  </span>
                </div>
                <pre className="mt-2 text-xs opacity-70 whitespace-pre-wrap">{JSON.stringify(cfg, null, 2)}</pre>
              </div>
            ))}
          </div>
        </section>
      )}

      {(tab === "backups" || tab === "updates") && (
        <section className="border border-border bg-background/70 p-4">
          <div className="flex flex-wrap gap-2">
            {(tab === "backups" ? actions.filter((a) => a.id.startsWith("backup.")) : actions.filter((a) => a.id.startsWith("update."))).map((action) => (
              <ShellButton key={action.id} tone={action.risk === "high" ? "danger" : "normal"} onClick={() => void runActionWithPrompt(action)}>
                {tab === "backups" ? <Upload className="inline h-3.5 w-3.5 mr-1" /> : <RefreshCw className="inline h-3.5 w-3.5 mr-1" />}
                {action.label}
              </ShellButton>
            ))}
          </div>
        </section>
      )}

      {runStatus && (
        <section className="border border-border bg-background/90">
          <div className="flex items-center justify-between px-3 py-2 border-b border-border">
            <div className="text-xs uppercase tracking-wider flex items-center gap-2"><Play className="h-3.5 w-3.5" />Run output: {runStatus}</div>
            <button type="button" className="text-xs opacity-70" onClick={() => { setRunStatus(null); setOutputLines([]); }}>Close</button>
          </div>
          <pre className="p-3 text-xs max-h-80 overflow-y-auto whitespace-pre-wrap">{outputLines.join("\n") || "(waiting for output)"}</pre>
        </section>
      )}
    </div>
  );
}
