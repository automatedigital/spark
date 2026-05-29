import { useEffect, useState, useCallback } from "react";
import { Plug, RefreshCw, ExternalLink } from "lucide-react";
import { api } from "@/lib/api";
import type { ConnectorStatus } from "@/lib/api";
import { useToast } from "@/hooks/useToast";
import { Toast } from "@/components/Toast";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

/* ------------------------------------------------------------------ */
/*  Google icon (inline SVG — no extra dep)                           */
/* ------------------------------------------------------------------ */

function GoogleIcon({ className = "h-8 w-8" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
      <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
      <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
      <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
      <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
    </svg>
  );
}

/* ------------------------------------------------------------------ */
/*  Setup instructions card                                            */
/* ------------------------------------------------------------------ */

function SetupInstructions() {
  return (
    <Card className="border-amber-500/30 bg-amber-500/5">
      <CardContent className="py-4 px-5">
        <p className="text-sm font-medium text-amber-400 mb-2">Google OAuth not configured</p>
        <ol className="text-xs text-muted-foreground space-y-1.5 list-decimal list-inside">
          <li>
            Go to{" "}
            <a
              href="https://console.cloud.google.com/apis/credentials"
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary underline inline-flex items-center gap-0.5"
            >
              Google Cloud Console <ExternalLink className="h-3 w-3" />
            </a>
          </li>
          <li>Create OAuth 2.0 credentials — type: <strong>Web application</strong></li>
          <li>
            Add authorized redirect URI:{" "}
            <code className="text-xs bg-muted px-1 py-0.5 rounded">
              http://localhost:9119/oauth/google/callback
            </code>
          </li>
          <li>
            Add to <code className="bg-muted px-1 py-0.5 rounded">~/.spark/config.yaml</code>:
            <pre className="mt-1.5 bg-muted rounded p-2 text-[11px] leading-relaxed overflow-x-auto">
{`connectors:
  google:
    client_id: "YOUR_CLIENT_ID.apps.googleusercontent.com"
    client_secret: "YOUR_CLIENT_SECRET"`}
            </pre>
          </li>
        </ol>
      </CardContent>
    </Card>
  );
}

/* ------------------------------------------------------------------ */
/*  Google connector card                                              */
/* ------------------------------------------------------------------ */

function GoogleConnectorCard() {
  const [status, setStatus] = useState<ConnectorStatus | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const { toast, showToast } = useToast();

  const loadStatus = useCallback(async () => {
    try {
      const s = await api.getGoogleStatus();
      setStatus(s);
    } catch {
      setStatus({ id: "google", name: "Google Workspace", connected: false, configured: false });
    }
  }, []);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  const handleConnect = async () => {
    setConnecting(true);
    try {
      const res = await api.connectGoogle();
      if (res.error) {
        showToast(res.message ?? res.error, "error");
        return;
      }
      if (!res.auth_url) {
        showToast("No auth URL returned", "error");
        return;
      }

      // Open the OAuth consent screen in a popup
      const popup = window.open(
        res.auth_url,
        "google-oauth",
        "width=520,height=620,left=200,top=100",
      );

      // Poll for completion (popup closes or status flips to connected)
      const poll = setInterval(async () => {
        try {
          const s = await api.getGoogleStatus();
          if (s.connected) {
            clearInterval(poll);
            setStatus(s);
            showToast(`Connected as ${s.email ?? "Google account"}`, "success");
            setConnecting(false);
            try { popup?.close(); } catch {}
          } else if (popup?.closed) {
            clearInterval(poll);
            // Final check in case callback just completed
            const final = await api.getGoogleStatus();
            setStatus(final);
            if (!final.connected) showToast("Connection cancelled", "error");
            setConnecting(false);
          }
        } catch {
          clearInterval(poll);
          setConnecting(false);
        }
      }, 1500);

      // Timeout after 3 minutes
      setTimeout(() => {
        clearInterval(poll);
        if (connecting) {
          setConnecting(false);
          showToast("Connection timed out", "error");
        }
      }, 180_000);
    } catch (err) {
      showToast("Failed to start connection", "error");
      setConnecting(false);
    }
  };

  const handleDisconnect = async () => {
    setDisconnecting(true);
    try {
      await api.disconnectGoogle();
      await loadStatus();
      showToast("Disconnected from Google", "success");
    } catch {
      showToast("Failed to disconnect", "error");
    } finally {
      setDisconnecting(false);
    }
  };

  const isConnected = status?.connected ?? false;
  const isConfigured = status?.configured ?? true;

  return (
    <>
      <Toast toast={toast} />
      <Card>
        <CardContent className="py-5 px-5">
          <div className="flex items-start gap-4">
            <div className="shrink-0 mt-0.5">
              <GoogleIcon className="h-8 w-8" />
            </div>

            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <span className="font-medium text-sm">Google Workspace</span>
                <Badge variant={isConnected ? "success" : "outline"} className="text-[10px]">
                  {isConnected ? "Connected" : "Not connected"}
                </Badge>
              </div>

              {isConnected && status?.email ? (
                <p className="text-xs text-muted-foreground mb-3">
                  Signed in as <span className="text-foreground">{status.email}</span>
                </p>
              ) : (
                <p className="text-xs text-muted-foreground mb-3">
                  Gmail search &amp; Google Calendar
                </p>
              )}

              {isConnected ? (
                <button
                  type="button"
                  onClick={handleDisconnect}
                  disabled={disconnecting}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md border border-border hover:bg-muted/50 transition-colors disabled:opacity-50"
                >
                  {disconnecting ? (
                    <RefreshCw className="h-3 w-3 animate-spin" />
                  ) : null}
                  Disconnect
                </button>
              ) : (
                <button
                  type="button"
                  onClick={handleConnect}
                  disabled={connecting || !isConfigured}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
                >
                  {connecting ? (
                    <RefreshCw className="h-3 w-3 animate-spin" />
                  ) : (
                    <GoogleIcon className="h-3.5 w-3.5" />
                  )}
                  {connecting ? "Connecting…" : "Connect Google"}
                </button>
              )}
            </div>

            {isConnected && (
              <div className="shrink-0 text-xs text-muted-foreground/60 space-y-1 text-right">
                <div>gmail_search</div>
                <div>calendar_list_events</div>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* SetupInstructions only shown if someone has explicitly cleared the baked-in client_id */}
      {!isConfigured && <SetupInstructions />}
    </>
  );
}

/* ------------------------------------------------------------------ */
/*  Page                                                               */
/* ------------------------------------------------------------------ */

export default function ConnectorsPage() {
  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-3">
        <Plug className="h-5 w-5 text-muted-foreground" />
        <h1 className="text-base font-semibold">Connectors</h1>
        <span className="text-xs text-muted-foreground">
          Connect external services to give Spark access to your data
        </span>
      </div>

      <div className="flex flex-col gap-3">
        <GoogleConnectorCard />
      </div>
    </div>
  );
}
