import { useEffect, useState, useCallback, useRef } from "react";
import {
  Plug,
  ShieldCheck,
  LogOut,
  RefreshCw,
  ExternalLink,
  AlertTriangle,
  Loader2,
} from "lucide-react";
import { api, type ConnectorStatus } from "@/lib/api";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

// What the agent can do once Google is connected on the free tier.
const GOOGLE_CAPABILITIES = [
  "Send email (Gmail — send only)",
  "Create & edit Google Docs, Sheets, Slides",
  "Manage Google Calendar events",
  "Create Drive files & edit files you pick",
];

export default function ConnectorsPage() {
  const [google, setGoogle] = useState<ConnectorStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      const status = await api.getGoogleStatus();
      setGoogle(status);
    } catch (e) {
      setError(`Failed to load connector status: ${e}`);
    } finally {
      setLoading(false);
    }
  }, []);

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
              : "Send email, manage your calendar, and create Docs/Sheets/Slides & Drive files."}
          </CardDescription>
        </CardHeader>

        <CardContent className="space-y-4">
          {/* Free-tier limitation note */}
          <div className="flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-700 dark:text-amber-400">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>
              Free-tier connection: Gmail is <strong>send-only</strong>. Reading
              your inbox needs a restricted scope (paid verification) and isn't
              included.
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

          {/* Not-configured guidance */}
          {google && !google.configured && (
            <div className="rounded-md border border-border bg-muted/40 p-3 text-xs text-muted-foreground">
              Google OAuth isn't configured yet. Add a client to{" "}
              <code className="rounded bg-muted px-1">config.yaml</code> under{" "}
              <code className="rounded bg-muted px-1">connectors.google</code>, or
              set <code className="rounded bg-muted px-1">GOOGLE_OAUTH_CLIENT_ID</code>{" "}
              and <code className="rounded bg-muted px-1">GOOGLE_OAUTH_CLIENT_SECRET</code>.
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
