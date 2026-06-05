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
} from "lucide-react";
import { api, type ConnectorStatus, type GoogleSetupInfo } from "@/lib/api";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

// What the agent can do once Google is connected (public free tier).
const GOOGLE_CAPABILITIES = [
  "Send email (Gmail OAuth)",
  "Read Gmail via App Password",
  "Create & edit Google Docs, Sheets, Slides",
  "Manage Google Calendar events",
  "Create Drive files & edit files you pick",
];

export default function ConnectorsPage() {
  const [google, setGoogle] = useState<ConnectorStatus | null>(null);
  const [setup, setSetup] = useState<GoogleSetupInfo | null>(null);
  const [showSetup, setShowSetup] = useState(false);
  const [copied, setCopied] = useState(false);
  const [imapEmail, setImapEmail] = useState("");
  const [imapPassword, setImapPassword] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [status, setupInfo] = await Promise.all([
        api.getGoogleStatus(),
        api.getGoogleSetup().catch(() => null),
      ]);
      setGoogle(status);
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

  // Poll status for up to ~2 min after opening the consent popup.
  const startPolling = useCallback(() => {
    if (pollRef.current) window.clearInterval(pollRef.current);
    let elapsed = 0;
    pollRef.current = window.setInterval(async () => {
      elapsed += 2000;
      try {
        const status = await api.getGoogleStatus();
        setGoogle(status);
        if (status.connected || elapsed >= 120_000) {
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
        window.open(resp.auth_url, "_blank", "width=520,height=640");
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

  return (
    <div className="mx-auto max-w-2xl p-6 space-y-6">
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

      <p className="text-center text-xs text-muted-foreground">
        More connectors coming soon. Connections work on desktop, local web, and
        remote/VPS installs.
      </p>
    </div>
  );
}
