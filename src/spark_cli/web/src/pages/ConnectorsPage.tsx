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
} from "lucide-react";
import { api, openExternal, type ConnectorStatus, type GoogleSetupInfo } from "@/lib/api";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

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
  if (connector.state === "not_installed") return "Not installed";
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
  const [setupConnector, setSetupConnector] = useState<ConnectorStatus | null>(null);
  const [connectorSecrets, setConnectorSecrets] = useState<Record<string, string>>({});
  const [deviceFlow, setDeviceFlow] = useState<DeviceFlowState | null>(null);
  const [setup, setSetup] = useState<GoogleSetupInfo | null>(null);
  const [showSetup, setShowSetup] = useState(false);
  const [copied, setCopied] = useState(false);
  const [imapEmail, setImapEmail] = useState("");
  const [imapPassword, setImapPassword] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [testingConnector, setTestingConnector] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [allConnectors, setupInfo] = await Promise.all([
        api.listConnectors(),
        api.getGoogleSetup().catch(() => null),
      ]);
      setConnectors(allConnectors.filter((connector) => connector.id !== "google"));
      setGoogle(allConnectors.find((connector) => connector.id === "google") ?? null);
      setSetup(setupInfo);
      // Auto-expand the setup helper when no client is configured yet.
      if (setupInfo && !setupInfo.configured) setShowSetup(true);
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

  const handleDisconnect = async () => {
    setError(null);
    setBusy(true);
    try {
      await api.disconnectGoogle();
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
    setError(null);
    setBusy(true);
    try {
      const entries = Object.entries(connectorSecrets)
        .map(([key, value]) => [key, value.trim()] as const)
        .filter(([key, value]) => key && value);
      if (entries.length === 0) {
        setError("Paste the key or credentials first.");
        setBusy(false);
        return;
      }
      for (const [key, value] of entries) {
        await api.setEnvVar(key, value);
      }
      setSetupConnector(null);
      setConnectorSecrets({});
      await refresh();
      const status = await api.getConnectorStatus(setupConnector.id);
      if (!status.connected) {
        setError(status.detail || status.status?.detail || `${setupConnector.name} credentials did not validate.`);
      }
    } catch (e) {
      setError(`Could not save connector credentials: ${e}`);
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

  const handleConnectConnector = async (connector: ConnectorStatus) => {
    const extra = connectorExtra(connector);
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

  return (
    <div className="mx-auto max-w-3xl p-6 space-y-6">
      <div className="flex items-center gap-3">
        <Plug className="h-6 w-6 text-muted-foreground" />
        <div>
          <h1 className="text-xl font-semibold">Connectors</h1>
          <p className="text-sm text-muted-foreground">
            Link external platforms so the agent can act on your behalf.
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
              <button
                className="flex w-full items-center gap-2 p-3 text-left text-xs font-medium text-foreground"
                onClick={() => setShowSetup((s) => !s)}
              >
                <Settings2 className="h-3.5 w-3.5" />
                {setup.configured
                  ? "Set up your own Google client (advanced)"
                  : "Set up your Google client to connect"}
                <span className="ml-auto text-muted-foreground">
                  {showSetup ? "Hide" : "Show"}
                </span>
              </button>

              {showSetup && (
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
              )}
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center gap-2 pt-1">
            {google?.connected ? (
              <Button
                variant="outline"
                onClick={handleDisconnect}
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
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-3 md:grid-cols-2">
        {connectors.map((connector) => (
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
              <div className="flex flex-wrap gap-2">
                {connector.transport && (
                  <Badge variant="outline">via {connector.transport}</Badge>
                )}
                {connector.status?.extra?.cli && (
                  <Badge variant="outline">{connector.status.extra.cli}</Badge>
                )}
              </div>
              <p className="text-xs text-muted-foreground">
                {connector.connected && (connector.account || connector.email)
                  ? `Ready: ${connector.account || connector.email}`
                  : connector.detail || connector.status?.detail || "Configure credentials, then refresh."}
              </p>
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
                    Skills
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
                <Button
                  size="sm"
                  onClick={() => handleConnectConnector(connector)}
                  disabled={connector.connected || busy}
                >
                  <KeyRound className="h-3.5 w-3.5" />
                  {connector.connected ? "Connected" : "Connect"}
                </Button>
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
            </CardContent>
          </Card>
        ))}
      </div>

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
              {connectorExtra(setupConnector).api_key_url && (
                <Button
                  variant="outline"
                  onClick={() => {
                    const url = connectorExtra(setupConnector).api_key_url;
                    if (url) void openExternal(url);
                  }}
                >
                  <ExternalLink className="h-4 w-4" />
                  Open {setupConnector.name} key page
                </Button>
              )}

              <div className="space-y-3">
                {Object.keys(connectorSecrets).map((key) => (
                  <div key={key} className="space-y-1.5">
                    <Label htmlFor={`connector-secret-${key}`}>{fieldMeta(key).label}</Label>
                    <Input
                      id={`connector-secret-${key}`}
                      type={key.includes("PASSWORD") || key.includes("TOKEN") || key.includes("KEY") ? "password" : "text"}
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
