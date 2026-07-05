import { useEffect, useState, useCallback, useRef } from "react";
import {
  Plug,
  ShieldCheck,
  LogOut,
  RefreshCw,
  ExternalLink,
  AlertTriangle,
  Loader2,
  Copy,
  Check,
  Settings2,
  Mail,
  KeyRound,
  X,
  ChevronDown,
  ChevronRight,
  Terminal,
  Server,
  Plus,
  Trash2,
} from "lucide-react";
import {
  api,
  openExternal,
  type ConnectorStatus,
  type GoogleSetupInfo,
  type CliToolInfo,
} from "@/lib/api";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useToast } from "@/hooks/useToast";
import { Toast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/** Window event fired whenever connecting/disconnecting changes skill enablement. */
export const SKILLS_UPDATED_EVENT = "spark-skills-updated";

// What the agent can do once Google is connected (public free tier).
const GOOGLE_CAPABILITIES = [
  "Send email (Gmail OAuth)",
  "Read Gmail via App Password",
  "Create & edit Google Docs, Sheets, Slides",
  "Manage Google Calendar events",
  "Create Drive files & edit files you pick",
];

function connectorStatusLabel(connector: ConnectorStatus) {
  if (connector.connected) return "Connected";
  if (connector.state === "not_installed") return "Needs setup";
  return "Not connected";
}

function connectorBadgeVariant(connector: ConnectorStatus): "default" | "secondary" | "destructive" {
  if (connector.connected) return "default";
  if (connector.state === "error") return "destructive";
  return "secondary";
}

function connectorExtra(connector: ConnectorStatus) {
  return connector.status?.extra ?? {};
}

function connectorPrimaryEnv(connector: ConnectorStatus) {
  const extra = connectorExtra(connector);
  return extra.primary_env_var || extra.env_vars?.[0] || "";
}

function isCliAgent(connector: ConnectorStatus) {
  return connectorExtra(connector).auth_type === "cli";
}

function notifySkillsUpdated() {
  window.dispatchEvent(new Event(SKILLS_UPDATED_EVENT));
}

type DeviceFlowState = {
  connectorId: string;
  connectorName: string;
  deviceState: string;
  userCode: string;
  verificationUri: string;
  interval: number;
};

const FIELD_META: Record<string, { label: string; placeholder: string }> = {
  GITHUB_TOKEN: { label: "GitHub token", placeholder: "Paste a GitHub token" },
  NOTION_API_KEY: { label: "Internal integration secret", placeholder: "secret_..." },
  HUBSPOT_ACCESS_TOKEN: { label: "Private app access token", placeholder: "pat-..." },
  HUBSPOT_API_KEY: { label: "Legacy API key", placeholder: "Paste HubSpot API key" },
  ASANA_ACCESS_TOKEN: { label: "Personal access token", placeholder: "Paste Asana token" },
  AIRTABLE_TOKEN: { label: "Personal access token", placeholder: "pat..." },
  AIRTABLE_API_KEY: { label: "Legacy API key", placeholder: "Paste Airtable API key" },
  SLACK_BOT_TOKEN: { label: "Bot token", placeholder: "xoxb-..." },
  SLACK_APP_TOKEN: { label: "App-level token", placeholder: "xapp-..." },
  TINKER_API_KEY: { label: "Tinker API key", placeholder: "Paste Tinker API key" },
  EMAIL_ADDRESS: { label: "Email address", placeholder: "you@example.com" },
  EMAIL_PASSWORD: { label: "Password or app password", placeholder: "Paste password" },
  EMAIL_IMAP_HOST: { label: "IMAP host", placeholder: "imap.example.com" },
  EMAIL_SMTP_HOST: { label: "SMTP host", placeholder: "smtp.example.com" },
};

function fieldMeta(key: string) {
  return FIELD_META[key] ?? { label: key, placeholder: `Paste ${key}` };
}

export default function ConnectorsPage() {
  const [google, setGoogle] = useState<ConnectorStatus | null>(null);
  const [connectors, setConnectors] = useState<ConnectorStatus[]>([]);
  const [cliTools, setCliTools] = useState<CliToolInfo[]>([]);
  const [mcpServers, setMcpServers] = useState<Record<string, Record<string, unknown>>>({});
  const [setupConnector, setSetupConnector] = useState<ConnectorStatus | null>(null);
  const [disconnectTarget, setDisconnectTarget] = useState<ConnectorStatus | null>(null);
  const [connectorSecrets, setConnectorSecrets] = useState<Record<string, string>>({});
  const [deviceFlow, setDeviceFlow] = useState<DeviceFlowState | null>(null);
  const [setup, setSetup] = useState<GoogleSetupInfo | null>(null);
  const [showGoogleAdvanced, setShowGoogleAdvanced] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [showMcpAdd, setShowMcpAdd] = useState(false);
  const [showMcpAdvanced, setShowMcpAdvanced] = useState(false);
  const [search, setSearch] = useState("");
  const [kindFilter, setKindFilter] = useState<string>("all");
  const [mcpPending, setMcpPending] = useState<string | null>(null);
  const [modalError, setModalError] = useState<string | null>(null);
  const [showSecrets, setShowSecrets] = useState(false);
  const [mcpName, setMcpName] = useState("");
  const [mcpTarget, setMcpTarget] = useState("");
  const [mcpRemovePending, setMcpRemovePending] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [imapEmail, setImapEmail] = useState("");
  const [imapPassword, setImapPassword] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [testingConnector, setTestingConnector] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);
  const prevConnectedRef = useRef<Set<string> | null>(null);
  const { toast, showToast } = useToast();

  // 1-click UX: when a connector transitions to connected, ask the backend to
  // enable the skills/toolsets it maps to and surface a toast. Watching state
  // transitions covers every connect path (OAuth popup, device flow, token
  // paste) without instrumenting each handler. Disconnects are handled by the
  // confirm-modal flow, which disables dependent skills server-side.
  useEffect(() => {
    if (loading) return;
    const all = google ? [google, ...connectors] : connectors;
    const connected = new Set(all.filter((c) => c.connected).map((c) => c.id));
    const prev = prevConnectedRef.current;
    prevConnectedRef.current = connected;
    if (prev === null) return; // initial load — no transition to react to

    const enableMapped = async (connector: ConnectorStatus) => {
      try {
        const res = await api.enableConnectorSkills(connector.id);
        const n = (res.skills?.length ?? 0) + (res.toolsets?.length ?? 0);
        showToast(
          n > 0
            ? `${connector.name} connected — ${n} skill${n === 1 ? "" : "s"} enabled`
            : `${connector.name} connected`,
          "success",
        );
        if (n > 0) notifySkillsUpdated();
      } catch {
        showToast(`${connector.name} connected`, "success");
      }
    };

    for (const c of all) {
      if (c.connected && !prev.has(c.id)) void enableMapped(c);
    }
  }, [connectors, google, loading, showToast]);

  const refresh = useCallback(async () => {
    try {
      const [allConnectors, setupInfo, cli, mcp] = await Promise.all([
        api.listConnectors(),
        api.getGoogleSetup().catch(() => null),
        api.getConnectorCliTools().catch(() => [] as CliToolInfo[]),
        api.getMcpServers().catch(() => null),
      ]);
      setConnectors(allConnectors.filter((connector) => connector.id !== "google"));
      setGoogle(allConnectors.find((connector) => connector.id === "google") ?? null);
      setSetup(setupInfo);
      setCliTools(cli);
      setMcpServers(mcp?.servers ?? {});
      // Auto-expand the setup helper when no client is configured yet.
      if (setupInfo && !setupInfo.configured) setShowGoogleAdvanced(true);
    } catch (e) {
      setError(`Failed to load connector status: ${e}`);
    } finally {
      setLoading(false);
    }
  }, []);

  const copyRedirect = async () => {
    if (!setup?.redirect_uri) return;
    try {
      await navigator.clipboard.writeText(setup.redirect_uri);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* ignore */
    }
  };

  useEffect(() => {
    refresh();
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, [refresh]);

  useEffect(() => {
    if (!deviceFlow) return;
    let cancelled = false;
    let timer: number | null = null;

    const poll = async () => {
      try {
        const resp = await api.pollConnectorDevice(deviceFlow.connectorId, deviceFlow.deviceState);
        if (cancelled) return;
        if (resp.connected) {
          setDeviceFlow(null);
          setBusy(false);
          await refresh();
          return;
        }
        const nextInterval = Math.max(2, resp.interval ?? deviceFlow.interval);
        timer = window.setTimeout(poll, nextInterval * 1000);
      } catch (e) {
        if (cancelled) return;
        setError(`GitHub approval check failed: ${e}`);
        setBusy(false);
      }
    };

    timer = window.setTimeout(poll, deviceFlow.interval * 1000);
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [deviceFlow, refresh]);

  // Poll status for up to ~2 min after opening the consent popup.
  const startPolling = useCallback(() => {
    if (pollRef.current) window.clearInterval(pollRef.current);
    let elapsed = 0;
    pollRef.current = window.setInterval(async () => {
      elapsed += 2000;
      try {
        const allConnectors = await api.listConnectors();
        const status = allConnectors.find((connector) => connector.id === "google") ?? null;
        setGoogle(status);
        setConnectors(allConnectors.filter((connector) => connector.id !== "google"));
        if (status?.connected || elapsed >= 120_000) {
          if (pollRef.current) window.clearInterval(pollRef.current);
          pollRef.current = null;
          setBusy(false);
        }
      } catch {
        /* keep polling */
      }
    }, 2000);
  }, []);

  const handleConnect = async () => {
    setError(null);
    setBusy(true);
    try {
      const resp = await api.connectGoogle();
      if (resp.error) {
        setError(resp.message || resp.error);
        setShowGoogleAdvanced(true);
        setBusy(false);
        return;
      }
      if (resp.auth_url) {
        void openExternal(resp.auth_url);
        startPolling();
      } else {
        setBusy(false);
      }
    } catch (e) {
      setError(`Connect failed: ${e}`);
      setBusy(false);
    }
  };

  const handleConfirmDisconnect = async () => {
    if (!disconnectTarget) return;
    const target = disconnectTarget;
    setError(null);
    setBusy(true);
    try {
      const resp =
        target.id === "google"
          ? await api.disconnectGoogle()
          : await api.disconnectConnector(target.id, true);
      const n = resp.skills_disabled?.length ?? 0;
      showToast(
        n > 0
          ? `${target.name} disconnected — ${n} skill${n === 1 ? "" : "s"} disabled`
          : `${target.name} disconnected`,
        "success",
      );
      if (n > 0) notifySkillsUpdated();
      setDisconnectTarget(null);
      // Forget the connected set entry so a future reconnect re-fires auto-enable.
      prevConnectedRef.current?.delete(target.id);
      await refresh();
    } catch (e) {
      setError(`Disconnect failed: ${e}`);
    } finally {
      setBusy(false);
    }
  };

  const handleConnectGmailRead = async () => {
    setError(null);
    setBusy(true);
    try {
      await api.connectGoogleGmailImap(imapEmail, imapPassword);
      setImapPassword("");
      await refresh();
    } catch (e) {
      setError(`Gmail read connect failed: ${e}`);
    } finally {
      setBusy(false);
    }
  };

  const handleDisconnectGmailRead = async () => {
    setError(null);
    setBusy(true);
    try {
      await api.disconnectGoogleGmailImap();
      await refresh();
    } catch (e) {
      setError(`Gmail read disconnect failed: ${e}`);
    } finally {
      setBusy(false);
    }
  };

  const handleSaveConnectorSecrets = async () => {
    if (!setupConnector) return;
    setModalError(null);
    setBusy(true);
    try {
      const entries = Object.entries(connectorSecrets)
        .map(([key, value]) => [key, value.trim()] as const)
        .filter(([key, value]) => key && value);
      if (entries.length === 0) {
        setModalError("Paste the key or credentials first.");
        setBusy(false);
        return;
      }
      const envVars =
        setupConnector.env_vars ?? connectorExtra(setupConnector).env_vars ?? [];
      if (entries.length === 1 && envVars.includes(entries[0][0])) {
        // Guided single-key flow: the backend persists to the profile .env,
        // validates the key, and rolls back if it doesn't check out.
        const res = await api.saveConnectorApiKey(
          setupConnector.id,
          entries[0][1],
          entries[0][0],
        );
        if (!res.connected) {
          setModalError(
            res.detail ||
              res.message ||
              `${setupConnector.name} key did not validate.`,
          );
          setBusy(false);
          return;
        }
      } else {
        for (const [key, value] of entries) {
          await api.setEnvVar(key, value);
        }
      }
      setSetupConnector(null);
      setConnectorSecrets({});
      await refresh();
    } catch (e) {
      setModalError(`${e}`.replace(/^Error:\s*/, ""));
    } finally {
      setBusy(false);
    }
  };

  const openConnectorSetup = (connector: ConnectorStatus) => {
    const extra = connectorExtra(connector);
    const keys = extra.auth_type === "multi_env"
      ? extra.env_vars ?? []
      : [connectorPrimaryEnv(connector)].filter(Boolean);
    setConnectorSecrets(Object.fromEntries(keys.map((key) => [key, ""])));
    setModalError(null);
    setShowSecrets(false);
    setSetupConnector(connector);
  };

  const startConnectorPolling = useCallback((connectorId: string) => {
    if (pollRef.current) window.clearInterval(pollRef.current);
    let elapsed = 0;
    pollRef.current = window.setInterval(async () => {
      elapsed += 2000;
      try {
        const allConnectors = await api.listConnectors();
        setGoogle(allConnectors.find((connector) => connector.id === "google") ?? null);
        setConnectors(allConnectors.filter((connector) => connector.id !== "google"));
        const status = allConnectors.find((connector) => connector.id === connectorId);
        if (status?.connected || elapsed >= 120_000) {
          if (pollRef.current) window.clearInterval(pollRef.current);
          pollRef.current = null;
          setBusy(false);
        }
      } catch {
        /* keep polling */
      }
    }, 2000);
  }, []);

  // Poll a pending MCP OAuth connect until tokens land (or error/timeout).
  const startMcpPolling = useCallback((connectorId: string) => {
    if (pollRef.current) window.clearInterval(pollRef.current);
    let elapsed = 0;
    pollRef.current = window.setInterval(async () => {
      elapsed += 2000;
      try {
        const st = await api.getConnectorConnectStatus(connectorId);
        if (st.connected || st.connect_state === "error" || elapsed >= 300_000) {
          if (pollRef.current) window.clearInterval(pollRef.current);
          pollRef.current = null;
          setBusy(false);
          setMcpPending(null);
          if (st.connect_state === "error") {
            setError(st.connect_error || "MCP authorization failed. Try again.");
          } else if (!st.connected && elapsed >= 300_000) {
            setError("Timed out waiting for browser authorization.");
          }
          await refresh();
        }
      } catch {
        /* keep polling */
      }
    }, 2000);
  }, [refresh]);

  // Single "Connect" affordance: pick the best available method automatically.
  // OAuth redirect/popup where configured → device-flow fallback (GitHub) →
  // token-paste modal as last resort.
  const handleConnectConnector = async (connector: ConnectorStatus) => {
    const extra = connectorExtra(connector);
    if (connector.kind === "mcp") {
      // One-click MCP preset: backend writes the server entry and opens the
      // browser OAuth flow; we poll until tokens are stored.
      setError(null);
      setBusy(true);
      setMcpPending(connector.id);
      try {
        const resp = await api.connectConnector(connector.id);
        if (resp.error) {
          setError(resp.message || resp.error);
          setBusy(false);
          setMcpPending(null);
          return;
        }
        if (resp.connected) {
          setBusy(false);
          setMcpPending(null);
          await refresh();
          return;
        }
        showToast(
          `Approve ${connector.name} in the browser window Spark just opened. ` +
            "New tools apply from your next session.",
          "success",
        );
        startMcpPolling(connector.id);
      } catch (e) {
        setError(`Connect failed: ${e}`);
        setBusy(false);
        setMcpPending(null);
      }
      return;
    }
    if ((extra.auth_type === "oauth" || extra.auth_type === "oauth_or_api_key") && extra.oauth_configured) {
      setError(null);
      setBusy(true);
      try {
        const resp = await api.connectConnector(connector.id);
        if (resp.flow === "device_code" && resp.device_state && resp.user_code && resp.verification_uri) {
          setDeviceFlow({
            connectorId: connector.id,
            connectorName: connector.name,
            deviceState: resp.device_state,
            userCode: resp.user_code,
            verificationUri: resp.verification_uri,
            interval: Math.max(2, resp.interval ?? 5),
          });
          void openExternal(resp.verification_uri);
          return;
        }
        if (resp.auth_url) {
          void openExternal(resp.auth_url);
          startConnectorPolling(connector.id);
          return;
        }
        if (resp.error && resp.error !== "not_configured") {
          setError(resp.message || resp.error);
        }
      } catch (e) {
        setError(`Connect failed: ${e}`);
      } finally {
        setBusy(false);
      }
    }
    openConnectorSetup(connector);
  };

  const handleTestConnector = async (connector: ConnectorStatus) => {
    setError(null);
    setTestingConnector(connector.id);
    try {
      const status = await api.getConnectorStatus(connector.id);
      if (connector.id === "google") {
        setGoogle(status);
      } else {
        setConnectors((prev) => prev.map((item) => item.id === connector.id ? status : item));
      }
      if (!status.connected) {
        setError(status.detail || status.status?.detail || `${connector.name} is not connected.`);
      }
    } catch (e) {
      setError(`Test failed for ${connector.name}: ${e}`);
    } finally {
      setTestingConnector(null);
    }
  };

  const handleAddMcpServer = async () => {
    const name = mcpName.trim();
    const target = mcpTarget.trim();
    if (!name || !target) return;
    setError(null);
    setBusy(true);
    try {
      if (/^https?:\/\//i.test(target)) {
        await api.addMcpServer({ name, url: target });
      } else {
        const parts = target.split(/\s+/);
        await api.addMcpServer({ name, command: parts[0], args: parts.slice(1) });
      }
      showToast(`MCP server "${name}" added`, "success");
      setShowMcpAdd(false);
      setMcpName("");
      setMcpTarget("");
      await refresh();
    } catch (e) {
      setError(`Could not add MCP server: ${e}`);
    } finally {
      setBusy(false);
    }
  };

  const handleRemoveMcpServer = async (name: string) => {
    if (mcpRemovePending !== name) {
      setMcpRemovePending(name);
      window.setTimeout(() => setMcpRemovePending((p) => (p === name ? null : p)), 4000);
      return;
    }
    setMcpRemovePending(null);
    setError(null);
    setBusy(true);
    try {
      await api.deleteMcpServer(name, true);
      showToast(`MCP server "${name}" removed`, "success");
      await refresh();
    } catch (e) {
      setError(`Could not remove MCP server: ${e}`);
    } finally {
      setBusy(false);
    }
  };

  const toggleExpanded = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const matchesSearch = (c: ConnectorStatus) => {
    const q = search.trim().toLowerCase();
    if (!q) return true;
    return (
      c.name.toLowerCase().includes(q) ||
      (c.description ?? "").toLowerCase().includes(q) ||
      c.id.toLowerCase().includes(q)
    );
  };
  const matchesKind = (c: ConnectorStatus) =>
    kindFilter === "all" || (c.kind ?? "api_key") === kindFilter;
  const apps = connectors.filter(
    (c) => !isCliAgent(c) && matchesSearch(c) && matchesKind(c),
  );
  const cliAgents = connectors.filter(isCliAgent);
  const presetServerNames = new Set(
    connectors
      .filter((c) => c.kind === "mcp")
      .map((c) => String(c.status?.extra?.server_name ?? c.id)),
  );
  // Only custom servers show in the advanced list — presets are cards above.
  const mcpEntries = Object.entries(mcpServers).filter(
    ([name]) => !presetServerNames.has(name),
  );
  const KIND_FILTERS: Array<[string, string]> = [
    ["all", "All"],
    ["api_key", "API key"],
    ["mcp", "MCP"],
    ["oauth", "OAuth"],
  ];

  return (
    <div className="mx-auto max-w-3xl p-6 space-y-6">
      <Toast toast={toast} />
      <div className="flex items-center gap-3">
        <Plug className="h-6 w-6 text-muted-foreground" />
        <div>
          <h1 className="text-xl font-semibold">Connected apps</h1>
          <p className="text-sm text-muted-foreground">
            Connect the apps you use — Spark turns on the matching skills automatically.
          </p>
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="ml-auto"
          onClick={refresh}
          disabled={loading}
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
        </Button>
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <CardTitle>Google Workspace</CardTitle>
              {google?.connected ? (
                <Badge className="gap-1" variant="default">
                  <ShieldCheck className="h-3 w-3" /> Connected
                </Badge>
              ) : (
                <Badge variant="secondary">Not connected</Badge>
              )}
            </div>
            <span className="text-xs text-muted-foreground">via gws CLI</span>
          </div>
          <CardDescription>
            {google?.connected && google.email
              ? `Signed in as ${google.email}`
              : "Send email, read Gmail with an App Password, and manage Calendar, Docs, Sheets, Slides & Drive files."}
          </CardDescription>
        </CardHeader>

        <CardContent className="space-y-4">
          {/* Primary action first; everything else is progressive disclosure. */}
          <div className="flex items-center gap-2">
            {google?.connected ? (
              <Button
                variant="outline"
                onClick={() => setDisconnectTarget(google)}
                disabled={busy}
              >
                {busy ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <LogOut className="h-4 w-4" />
                )}
                Disconnect
              </Button>
            ) : (
              <Button
                onClick={handleConnect}
                disabled={busy || (google ? !google.configured : false)}
              >
                {busy ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <ExternalLink className="h-4 w-4" />
                )}
                Connect Google
              </Button>
            )}
            {busy && !google?.connected && (
              <span className="text-xs text-muted-foreground">
                Waiting for you to finish sign-in…
              </span>
            )}
            {!busy && google && !google.configured && !google.connected && (
              <span className="text-xs text-muted-foreground">
                One quick setup step needed — see advanced options below.
              </span>
            )}
          </div>

          <button
            className="flex w-full items-center gap-2 text-left text-xs font-medium text-muted-foreground hover:text-foreground"
            onClick={() => setShowGoogleAdvanced((s) => !s)}
          >
            {showGoogleAdvanced ? (
              <ChevronDown className="h-3.5 w-3.5" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5" />
            )}
            Advanced options
          </button>

          {showGoogleAdvanced && (
            <div className="space-y-4">
              {/* Unverified-app note */}
              <div className="flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-700 dark:text-amber-400">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span>
                  During sign-in Google may show a{" "}
                  <strong>"Google hasn't verified this app"</strong> screen — click{" "}
                  <em>Advanced → Continue</em>. This is expected for self-hosted
                  setups and your data stays in your own Google account.
                </span>
              </div>

              {/* Capabilities */}
              <div>
                <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  What the agent can do
                </p>
                <ul className="space-y-1 text-sm">
                  {GOOGLE_CAPABILITIES.map((cap) => (
                    <li key={cap} className="flex items-center gap-2">
                      <ShieldCheck className="h-3.5 w-3.5 text-emerald-500" />
                      {cap}
                    </li>
                  ))}
                </ul>
              </div>

              <div className="rounded-md border border-border p-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-start gap-2">
                    <Mail className="mt-0.5 h-4 w-4 text-muted-foreground" />
                    <div>
                      <p className="text-sm font-medium">Gmail read access</p>
                      <p className="text-xs text-muted-foreground">
                        Use a Google App Password for inbox search without CASA verification.
                      </p>
                    </div>
                  </div>
                  {google?.gmail_read?.connected ? (
                    <Badge className="gap-1" variant="default">
                      <ShieldCheck className="h-3 w-3" /> Connected
                    </Badge>
                  ) : (
                    <Badge variant="secondary">Optional</Badge>
                  )}
                </div>

                {google?.gmail_read?.connected ? (
                  <div className="mt-3 flex items-center gap-2">
                    <span className="text-xs text-muted-foreground">
                      Reading as {google.gmail_read.email}
                    </span>
                    <Button
                      variant="outline"
                      size="sm"
                      className="ml-auto"
                      onClick={handleDisconnectGmailRead}
                      disabled={busy}
                    >
                      <LogOut className="h-3.5 w-3.5" />
                      Disconnect Gmail read
                    </Button>
                  </div>
                ) : (
                  <div className="mt-3 grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
                    <label className="relative">
                      <Mail className="pointer-events-none absolute left-2 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
                      <input
                        className="h-9 w-full rounded-md border border-input bg-background pl-8 pr-2 text-sm"
                        placeholder="you@gmail.com"
                        value={imapEmail}
                        onChange={(e) => setImapEmail(e.target.value)}
                      />
                    </label>
                    <label className="relative">
                      <KeyRound className="pointer-events-none absolute left-2 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
                      <input
                        className="h-9 w-full rounded-md border border-input bg-background pl-8 pr-2 text-sm"
                        placeholder="16-character App Password"
                        type="password"
                        value={imapPassword}
                        onChange={(e) => setImapPassword(e.target.value)}
                      />
                    </label>
                    <Button
                      size="sm"
                      onClick={handleConnectGmailRead}
                      disabled={busy || !imapEmail.trim() || !imapPassword.trim()}
                    >
                      <KeyRound className="h-3.5 w-3.5" />
                      Connect
                    </Button>
                  </div>
                )}
              </div>

              {/* BYO-client setup helper */}
              {setup && (
                <div className="rounded-md border border-border bg-muted/30">
                  <div className="flex w-full items-center gap-2 p-3 text-left text-xs font-medium text-foreground">
                    <Settings2 className="h-3.5 w-3.5" />
                    {setup.configured
                      ? "Set up your own Google client (advanced)"
                      : "Set up your Google client to connect"}
                  </div>

                  <div className="space-y-3 border-t border-border p-3 text-xs text-muted-foreground">
                    <ol className="list-decimal space-y-2 pl-4">
                      <li>
                        In the{" "}
                        <a
                          href={setup.console_url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-primary underline"
                        >
                          Google Cloud Console
                        </a>
                        , create an OAuth client of type{" "}
                        <strong>{setup.client_type}</strong>.
                      </li>
                      <li>
                        Add this exact <strong>Authorized redirect URI</strong>:
                        <div className="mt-1 flex items-center gap-2">
                          <code className="flex-1 break-all rounded bg-muted px-2 py-1 text-[11px] text-foreground">
                            {setup.redirect_uri}
                          </code>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 px-2"
                            onClick={copyRedirect}
                          >
                            {copied ? (
                              <Check className="h-3.5 w-3.5 text-emerald-500" />
                            ) : (
                              <Copy className="h-3.5 w-3.5" />
                            )}
                          </Button>
                        </div>
                      </li>
                      <li>
                        Add yourself as a <strong>Test user</strong> on the OAuth
                        consent screen (keeps it free — no verification needed).
                      </li>
                      <li>
                        Put the client ID & secret in{" "}
                        <code className="rounded bg-muted px-1">config.yaml</code>:
                        <pre className="mt-1 overflow-x-auto rounded bg-muted p-2 text-[11px] text-foreground">{`connectors:
  google:
    client_id: "…apps.googleusercontent.com"
    client_secret: "…"`}</pre>
                      </li>
                    </ol>
                    {setup.configured && (
                      <p className="flex items-center gap-1 text-emerald-600 dark:text-emerald-400">
                        <Check className="h-3.5 w-3.5" /> A client is configured.
                      </p>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Search + kind filter ── */}
      <div className="flex flex-wrap items-center gap-2">
        <Input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search connectors…"
          className="h-9 max-w-xs"
        />
        <div className="flex gap-1.5">
          {KIND_FILTERS.map(([value, label]) => (
            <Button
              key={value}
              size="sm"
              variant={kindFilter === value ? "default" : "outline"}
              onClick={() => setKindFilter(value)}
            >
              {label}
            </Button>
          ))}
        </div>
      </div>

      {/* ── Apps ── */}
      {apps.length === 0 && !loading && (
        <Card>
          <CardContent className="py-8 text-center text-sm text-muted-foreground">
            {search || kindFilter !== "all"
              ? "No connectors match your search."
              : "No connectable apps found. Refresh, or check that the gateway is running."}
          </CardContent>
        </Card>
      )}
      <div className="grid gap-3 md:grid-cols-2">
        {apps.map((connector) => (
          <Card key={connector.id}>
            <CardHeader className="space-y-2">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <CardTitle className="text-base">{connector.name}</CardTitle>
                  <CardDescription className="mt-1">
                    {connector.description}
                  </CardDescription>
                </div>
                <Badge className="shrink-0" variant={connectorBadgeVariant(connector)}>
                  {connectorStatusLabel(connector)}
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <p className="text-xs text-muted-foreground">
                {mcpPending === connector.id
                  ? "Waiting for browser authorization…"
                  : connector.connected && (connector.account || connector.email)
                    ? `Connected as ${connector.account || connector.email}`
                    : connector.connected
                      ? "Connected and ready to use."
                      : connector.state === "not_installed"
                        ? "Not set up yet — click Connect and Spark will walk you through it."
                        : connector.detail || connector.status?.detail || "Click Connect to link this app."}
              </p>

              <div className="flex flex-wrap gap-2">
                {connector.connected ? (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setDisconnectTarget(connector)}
                    disabled={busy}
                  >
                    <LogOut className="h-3.5 w-3.5" />
                    Disconnect
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    onClick={() => handleConnectConnector(connector)}
                    disabled={busy}
                  >
                    {mcpPending === connector.id ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : connector.kind === "mcp" ? (
                      <Server className="h-3.5 w-3.5" />
                    ) : (
                      <KeyRound className="h-3.5 w-3.5" />
                    )}
                    Connect
                  </Button>
                )}
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => toggleExpanded(connector.id)}
                >
                  {expanded.has(connector.id) ? (
                    <ChevronDown className="h-3.5 w-3.5" />
                  ) : (
                    <ChevronRight className="h-3.5 w-3.5" />
                  )}
                  Details
                </Button>
              </div>

              {expanded.has(connector.id) && (
                <div className="space-y-3 border-t border-border pt-3">
                  <div className="flex flex-wrap gap-2">
                    {connector.transport && (
                      <Badge variant="outline">via {connector.transport}</Badge>
                    )}
                    {connector.status?.extra?.cli && (
                      <Badge variant="outline">{connector.status.extra.cli}</Badge>
                    )}
                  </div>
                  {connector.status?.extra?.cli && connector.connected && (
                    <p className="text-xs text-muted-foreground">
                      {connector.status.extra.cli_sync?.synced
                        ? `${connector.status.extra.cli} CLI is signed in.`
                        : connector.status.extra.cli_sync?.reason === "gh_not_installed"
                          ? `${connector.status.extra.cli} CLI is not installed.`
                          : connector.status.extra.cli_sync?.reason
                            ? `${connector.status.extra.cli} CLI sync: ${connector.status.extra.cli_sync.reason}.`
                            : `${connector.status.extra.cli} CLI can use its existing auth.`}
                    </p>
                  )}
                  {connector.skills && connector.skills.length > 0 && (
                    <div>
                      <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                        Skills enabled on connect
                      </p>
                      <div className="flex flex-wrap gap-1.5">
                        {connector.skills.map((skill) => (
                          <Badge key={skill} variant="secondary">{skill}</Badge>
                        ))}
                      </div>
                    </div>
                  )}
                  {connector.capabilities && connector.capabilities.length > 0 && (
                    <div>
                      <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                        What Spark can do
                      </p>
                      <div className="flex flex-wrap gap-1.5">
                        {connector.capabilities.map((capability) => (
                          <Badge key={capability} variant="outline">{capability}</Badge>
                        ))}
                      </div>
                    </div>
                  )}
                  {connector.status?.extra?.setup_steps && connector.status.extra.setup_steps.length > 0 && (
                    <div>
                      <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                        Setup
                      </p>
                      <ul className="space-y-1 text-xs text-muted-foreground">
                        {connector.status.extra.setup_steps.map((step) => (
                          <li key={step}>{step}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  <div className="flex flex-wrap gap-2">
                    {connector.docs_url && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          if (connector.docs_url) void openExternal(connector.docs_url);
                        }}
                      >
                        <ExternalLink className="h-3.5 w-3.5" />
                        Open docs
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleTestConnector(connector)}
                      disabled={testingConnector === connector.id}
                    >
                      {testingConnector === connector.id ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Check className="h-3.5 w-3.5" />
                      )}
                      Test
                    </Button>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      {/* ── Coding agents (CLI-backed tools) ── */}
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <Terminal className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold">Coding agents</h2>
          <span className="text-xs text-muted-foreground">
            CLI tools Spark can delegate coding work to
          </span>
        </div>
        <Card>
          <CardContent className="divide-y divide-border p-0">
            {cliAgents.map((connector) => {
              const cli = cliTools.find((t) => t.id === connector.id);
              const detected = cli ? cli.detected : connector.status?.extra?.installed === true;
              return (
                <div key={connector.id} className="flex items-start justify-between gap-3 p-4">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-medium">{connector.name}</p>
                      {detected ? (
                        <Badge className="gap-1" variant="default">
                          <Check className="h-3 w-3" /> Detected
                        </Badge>
                      ) : (
                        <Badge variant="secondary">Not detected</Badge>
                      )}
                      {connector.connected && (
                        <Badge variant="outline">Signed in</Badge>
                      )}
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {connector.description}
                    </p>
                    {detected && cli?.path && (
                      <p className="mt-1 truncate font-mono-ui text-[11px] text-muted-foreground/70">
                        {cli.path}
                      </p>
                    )}
                    {!detected && cli?.install_hint && (
                      <p className="mt-1 text-xs text-muted-foreground">
                        Install with:{" "}
                        <code className="rounded bg-muted px-1.5 py-0.5 text-[11px] text-foreground">
                          {cli.install_hint}
                        </code>
                      </p>
                    )}
                  </div>
                  {connector.docs_url && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="shrink-0"
                      onClick={() => {
                        if (connector.docs_url) void openExternal(connector.docs_url);
                      }}
                    >
                      <ExternalLink className="h-3.5 w-3.5" />
                      Docs
                    </Button>
                  )}
                </div>
              );
            })}
            {cliAgents.length === 0 && (
              <p className="p-4 text-sm text-muted-foreground">
                No CLI coding agents available.
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* ── Advanced: custom MCP servers ── */}
      <div className="space-y-3">
        <button
          className="flex items-center gap-2 text-left text-sm font-semibold text-muted-foreground hover:text-foreground"
          onClick={() => setShowMcpAdvanced((v) => !v)}
        >
          {showMcpAdvanced ? (
            <ChevronDown className="h-3.5 w-3.5" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5" />
          )}
          <Server className="h-4 w-4" />
          Advanced — custom MCP servers
          <span className="text-xs font-normal text-muted-foreground">
            {mcpEntries.length > 0 ? `${mcpEntries.length} configured` : "for servers not in the catalog"}
          </span>
        </button>
        {showMcpAdvanced && (
        <>
        <div className="flex items-center">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowMcpAdd(true)}
          >
            <Plus className="h-3.5 w-3.5" />
            Add custom MCP server
          </Button>
        </div>
        <Card>
          <CardContent className="divide-y divide-border p-0">
            {mcpEntries.map(([name, server]) => {
              const target = String(server.url ?? server.command ?? "");
              const args = Array.isArray(server.args) ? (server.args as string[]).join(" ") : "";
              return (
                <div key={name} className="flex items-center justify-between gap-3 p-4">
                  <div className="min-w-0">
                    <p className="text-sm font-medium">{name}</p>
                    <p className="mt-0.5 truncate font-mono-ui text-[11px] text-muted-foreground">
                      {[target, args].filter(Boolean).join(" ")}
                    </p>
                  </div>
                  <Button
                    variant={mcpRemovePending === name ? "destructive" : "ghost"}
                    size="sm"
                    className="shrink-0"
                    onClick={() => handleRemoveMcpServer(name)}
                    disabled={busy}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    {mcpRemovePending === name ? "Confirm remove" : "Remove"}
                  </Button>
                </div>
              );
            })}
            {mcpEntries.length === 0 && (
              <p className="p-4 text-sm text-muted-foreground">
                No custom MCP servers. Popular servers are one-click cards above —
                add a custom one here by URL or launch command.
              </p>
            )}
          </CardContent>
        </Card>
        </>
        )}
      </div>

      {/* ── Token-paste / credentials modal ── */}
      {setupConnector && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-background/70 p-4 backdrop-blur-sm">
          <div className="w-full max-w-lg rounded-md border border-border bg-card shadow-2xl">
            <div className="flex items-start justify-between gap-4 border-b border-border p-4">
              <div>
                <h2 className="text-base font-semibold">Connect {setupConnector.name}</h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  Spark will save these credentials to your local Spark env file.
                </p>
              </div>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setSetupConnector(null)}
                aria-label="Close"
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
            <div className="space-y-4 p-4">
              {(setupConnector.api_key_url || connectorExtra(setupConnector).api_key_url) && (
                <div className="space-y-1.5">
                  <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Step 1 — get your key
                  </p>
                  <Button
                    variant="outline"
                    onClick={() => {
                      const url =
                        setupConnector.api_key_url ||
                        connectorExtra(setupConnector).api_key_url;
                      if (url) void openExternal(url);
                    }}
                  >
                    <ExternalLink className="h-4 w-4" />
                    Open {setupConnector.name} key page
                  </Button>
                </div>
              )}

              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Step 2 — paste it here
                  </p>
                  <button
                    className="text-xs text-muted-foreground hover:text-foreground"
                    onClick={() => setShowSecrets((v) => !v)}
                  >
                    {showSecrets ? "Hide" : "Show"}
                  </button>
                </div>
                {Object.keys(connectorSecrets).map((key) => (
                  <div key={key} className="space-y-1.5">
                    <Label htmlFor={`connector-secret-${key}`}>{fieldMeta(key).label}</Label>
                    <Input
                      id={`connector-secret-${key}`}
                      type={
                        !showSecrets &&
                        (key.includes("PASSWORD") || key.includes("TOKEN") || key.includes("KEY"))
                          ? "password"
                          : "text"
                      }
                      value={connectorSecrets[key] ?? ""}
                      placeholder={fieldMeta(key).placeholder}
                      onChange={(event) => {
                        setConnectorSecrets((prev) => ({
                          ...prev,
                          [key]: event.target.value,
                        }));
                      }}
                    />
                  </div>
                ))}
              </div>

              {setupConnector.status?.extra?.setup_steps && setupConnector.status.extra.setup_steps.length > 0 && (
                <div className="rounded-md border border-border bg-muted/30 p-3 text-xs text-muted-foreground">
                  {setupConnector.status.extra.setup_steps.map((step) => (
                    <p key={step}>{step}</p>
                  ))}
                </div>
              )}

              {modalError && (
                <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>{modalError}</span>
                </div>
              )}

              <div className="flex justify-end gap-2">
                <Button variant="ghost" onClick={() => setSetupConnector(null)}>
                  Cancel
                </Button>
                <Button onClick={handleSaveConnectorSecrets} disabled={busy}>
                  {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                  Save connection
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Disconnect confirmation ── */}
      {disconnectTarget && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-background/70 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-md border border-border bg-card shadow-2xl">
            <div className="flex items-start justify-between gap-4 border-b border-border p-4">
              <div>
                <h2 className="text-base font-semibold">
                  Disconnect {disconnectTarget.name}?
                </h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  Spark will sign out and remove the saved credentials.
                </p>
              </div>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setDisconnectTarget(null)}
                aria-label="Close"
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
            <div className="space-y-4 p-4">
              {disconnectTarget.skills && disconnectTarget.skills.length > 0 ? (
                <div className="rounded-md border border-amber-500/30 bg-amber-500/10 p-3">
                  <p className="flex items-center gap-2 text-xs font-medium text-amber-700 dark:text-amber-400">
                    <AlertTriangle className="h-3.5 w-3.5" />
                    These skills depend on it and will be turned off:
                  </p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {disconnectTarget.skills.map((skill) => (
                      <Badge key={skill} variant="secondary">{skill}</Badge>
                    ))}
                  </div>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  No skills depend on this connection.
                </p>
              )}
              <div className="flex justify-end gap-2">
                <Button variant="ghost" onClick={() => setDisconnectTarget(null)}>
                  Cancel
                </Button>
                <Button
                  variant="destructive"
                  onClick={handleConfirmDisconnect}
                  disabled={busy}
                >
                  {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <LogOut className="h-4 w-4" />}
                  Disconnect
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Add MCP server modal ── */}
      {showMcpAdd && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-background/70 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-md border border-border bg-card shadow-2xl">
            <div className="flex items-start justify-between gap-4 border-b border-border p-4">
              <div>
                <h2 className="text-base font-semibold">Add MCP server</h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  Paste a server URL, or the command that starts a local server.
                </p>
              </div>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setShowMcpAdd(false)}
                aria-label="Close"
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
            <div className="space-y-4 p-4">
              <div className="space-y-1.5">
                <Label htmlFor="mcp-name">Name</Label>
                <Input
                  id="mcp-name"
                  value={mcpName}
                  placeholder="my-tools"
                  onChange={(e) => setMcpName(e.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="mcp-target">Server URL or command</Label>
                <Input
                  id="mcp-target"
                  value={mcpTarget}
                  placeholder="https://example.com/mcp — or — npx my-mcp-server"
                  onChange={(e) => setMcpTarget(e.target.value)}
                />
              </div>
              <div className="flex justify-end gap-2">
                <Button variant="ghost" onClick={() => setShowMcpAdd(false)}>
                  Cancel
                </Button>
                <Button
                  onClick={handleAddMcpServer}
                  disabled={busy || !mcpName.trim() || !mcpTarget.trim()}
                >
                  {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                  Add server
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Device flow modal ── */}
      {deviceFlow && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-background/70 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-md border border-border bg-card shadow-2xl">
            <div className="flex items-start justify-between gap-4 border-b border-border p-4">
              <div>
                <h2 className="text-base font-semibold">Connect {deviceFlow.connectorName}</h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  Approve Spark in GitHub, then this window will update automatically.
                </p>
              </div>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => {
                  setDeviceFlow(null);
                  setBusy(false);
                }}
                aria-label="Close"
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
            <div className="space-y-4 p-4">
              <div className="rounded-md border border-border bg-muted/30 p-4 text-center">
                <p className="text-xs uppercase tracking-wide text-muted-foreground">GitHub code</p>
                <p className="mt-2 font-mono-ui text-3xl font-semibold tracking-[0.16em]">
                  {deviceFlow.userCode}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  onClick={() => void openExternal(deviceFlow.verificationUri)}
                >
                  <ExternalLink className="h-4 w-4" />
                  Open GitHub
                </Button>
                <Button
                  variant="outline"
                  onClick={async () => {
                    await navigator.clipboard.writeText(deviceFlow.userCode);
                    setCopied(true);
                    window.setTimeout(() => setCopied(false), 1500);
                  }}
                >
                  {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                  Copy code
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                Spark is checking for approval in the background.
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
