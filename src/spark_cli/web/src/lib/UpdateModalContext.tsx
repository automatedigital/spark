import { useRef, useState, useEffect, type ReactNode } from "react";
import { Download, Loader2, RefreshCw, X } from "lucide-react";
import { api, sseUrl } from "@/lib/api";
import { UpdateModalContext } from "@/lib/updateModal";

type UpdateStatus = "idle" | "running" | "restarting" | "done" | "failed";

export function UpdateModalProvider({ children }: { children: ReactNode }) {
  const [updateAvailable, setUpdateAvailable] = useState(false);
  const [latestVersion, setLatestVersion] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [status, setStatus] = useState<UpdateStatus>("idle");
  const [output, setOutput] = useState<string[]>([]);
  const outputScrollRef = useRef<HTMLDivElement>(null);
  const startedInstanceIdRef = useRef<string | null>(null);
  const sawUnavailableRef = useRef(false);

  // macOS desktop app update (separate from the code/webapp update above)
  const [macUpdateAvailable, setMacUpdateAvailable] = useState(false);
  const [macLatestVersion, setMacLatestVersion] = useState<string | null>(null);
  const [macReleaseNotes, setMacReleaseNotes] = useState<string | null>(null);
  const [macReleaseUrl, setMacReleaseUrl] = useState<string | null>(null);
  const [macModalOpen, setMacModalOpen] = useState(false);
  const [macStatus, setMacStatus] = useState<"idle" | "running" | "installing" | "failed">("idle");
  const [macError, setMacError] = useState<string | null>(null);

  // Check for updates on mount
  useEffect(() => {
    let cancelled = false;
    (async () => {
      let isDesktop = false;
      let desktopPlatform: string | null = null;
      try {
        const s = await api.getStatus();
        isDesktop = Boolean(s.desktop);
        desktopPlatform = s.desktop_platform ?? null;
        if (!cancelled && s.update_available) {
          setUpdateAvailable(true);
          if (s.commits_behind != null)
            setLatestVersion(`${s.commits_behind} new commit${s.commits_behind === 1 ? "" : "s"}`);
        } else {
          try {
            const result = await api.checkForUpdate();
            if (!cancelled && result.update_available) {
              setUpdateAvailable(true);
              if (result.commits_behind != null)
                setLatestVersion(`${result.commits_behind} new commit${result.commits_behind === 1 ? "" : "s"}`);
            }
          } catch { /* ignore */ }
        }
      } catch { /* ignore */ }
      // The in-app installer currently applies only to the bundled macOS shell.
      if (isDesktop && desktopPlatform === "macos") {
        try {
          const mac = await api.checkMacUpdate();
          if (!cancelled && mac.update_available) {
            setMacUpdateAvailable(true);
            setMacLatestVersion(mac.latest_version);
            setMacReleaseNotes(mac.release_notes ?? null);
            setMacReleaseUrl(mac.release_url ?? null);
          }
        } catch { /* ignore */ }
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // Auto-scroll output
  useEffect(() => {
    if (outputScrollRef.current)
      outputScrollRef.current.scrollTop = outputScrollRef.current.scrollHeight;
  }, [output]);

  // Poll for server restart
  useEffect(() => {
    if (status !== "restarting") return;
    const interval = setInterval(async () => {
      try {
        const s = await api.getStatus();
        const instanceChanged =
          Boolean(startedInstanceIdRef.current) &&
          Boolean(s.server_instance_id) &&
          s.server_instance_id !== startedInstanceIdRef.current;
        if (instanceChanged || sawUnavailableRef.current) {
          setStatus("done");
          setUpdateAvailable(false);
        }
      } catch {
        sawUnavailableRef.current = true;
      }
    }, 2000);
    return () => clearInterval(interval);
  }, [status]);

  const openUpdateModal = () => {
    setModalOpen(true);
    setStatus("idle");
    setOutput([]);
  };

  const startUpdate = async () => {
    setStatus("running");
    setOutput([]);
    startedInstanceIdRef.current = null;
    sawUnavailableRef.current = false;
    try {
      const currentStatus = await api.getStatus().catch(() => null);
      startedInstanceIdRef.current = currentStatus?.server_instance_id ?? null;
      const resp = await api.runAdminAction("update.run", {}, true);
      const es = new EventSource(sseUrl(`/api/admin/actions/runs/${encodeURIComponent(resp.run_id)}/stream`));
      es.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data) as { type?: string; stream?: string; text?: string; run?: { status?: string } };
          if (data.type === "output" && data.text != null)
            setOutput((prev) => [...prev.slice(-500), data.text!]);
          if (data.type === "done") {
            const finalStatus = data.run?.status ?? "done";
            setStatus(finalStatus === "done" ? "restarting" : "failed");
            setUpdateAvailable(false);
            es.close();
          }
        } catch {
          setOutput((prev) => [...prev.slice(-500), ev.data]);
        }
      };
      es.onerror = () => {
        es.close();
        sawUnavailableRef.current = true;
        setStatus((prev) => (prev === "running" ? "restarting" : prev));
      };
    } catch (e) {
      setOutput([String(e)]);
      setStatus("failed");
    }
  };

  const openMacUpdateModal = () => {
    setMacModalOpen(true);
    setMacStatus("idle");
    setMacError(null);
  };

  const startMacUpdate = async () => {
    setMacStatus("running");
    setMacError(null);
    try {
      await api.runMacUpdate();
      setMacStatus("installing");
      setMacUpdateAvailable(false);
    } catch (e) {
      setMacError(e instanceof Error ? e.message : String(e));
      setMacStatus("failed");
    }
  };

  return (
    <UpdateModalContext.Provider
      value={{
        updateAvailable,
        latestVersion,
        openUpdateModal,
        macUpdateAvailable,
        macLatestVersion,
        openMacUpdateModal,
      }}
    >
      {children}

      {modalOpen && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="relative flex w-full max-w-lg flex-col rounded-sm border border-border bg-card shadow-2xl">
            {/* Header */}
            <div className="flex items-center justify-between border-b border-border px-5 py-4">
              <div className="flex items-center gap-2">
                <Download className="h-4 w-4 text-amber-400" />
                <span className="text-sm font-semibold text-foreground">
                  Update Spark{latestVersion ? ` (${latestVersion})` : ""}
                </span>
              </div>
              {status !== "running" && (
                <button
                  type="button"
                  onClick={() => setModalOpen(false)}
                  className="grid h-7 w-7 place-items-center rounded-sm text-muted-foreground transition hover:bg-secondary hover:text-foreground"
                >
                  <X className="h-4 w-4" />
                </button>
              )}
            </div>

            {/* Body */}
            <div className="px-5 py-4 flex flex-col gap-3">
              {status === "idle" && (
                <p className="text-sm text-muted-foreground">
                  A new version of Spark is available. The update will pull the latest changes and reinstall the package. The web UI may restart automatically.
                </p>
              )}
              {(status === "running" || status === "restarting" || output.length > 0) && (
                <>
                  <div
                    ref={outputScrollRef}
                    className="h-52 overflow-y-auto rounded-sm border border-border bg-background/60 p-3 font-mono text-xs text-muted-foreground"
                  >
                    {output.length === 0 ? (
                      <span className="animate-pulse">Starting update…</span>
                    ) : (
                      output.map((line, i) => (
                        <div key={i} className="leading-5 whitespace-pre-wrap break-all">{line}</div>
                      ))
                    )}
                  </div>
                  {(status === "running" || status === "restarting") && (
                    <div className="h-1 w-full overflow-hidden rounded-full bg-border">
                      <div
                        className="h-full w-2/5 rounded-full bg-amber-500"
                        style={{ animation: "progress-slide 1.6s ease-in-out infinite" }}
                      />
                    </div>
                  )}
                  {status === "restarting" && (
                    <p className="text-xs text-amber-400 flex items-center gap-1.5">
                      <Loader2 className="h-3 w-3 animate-spin" />
                      Server is restarting — waiting for it to come back…
                    </p>
                  )}
                </>
              )}
              {status === "done" && (
                <p className="text-sm text-emerald-400">Update complete. Reload to load the new version.</p>
              )}
              {status === "failed" && (
                <p className="text-sm text-red-400">Update failed. Check the output above for details.</p>
              )}
            </div>

            {/* Footer */}
            <div className="flex items-center justify-end gap-2 border-t border-border px-5 py-3">
              {status === "idle" && (
                <>
                  <button
                    type="button"
                    onClick={() => setModalOpen(false)}
                    className="h-9 rounded-sm border border-border px-4 text-xs text-muted-foreground transition hover:bg-secondary hover:text-foreground"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={() => void startUpdate()}
                    className="flex h-9 items-center gap-2 rounded-sm bg-amber-500 px-4 text-xs font-semibold text-black transition hover:bg-amber-400"
                  >
                    <Download className="h-3.5 w-3.5" />
                    Start Update
                  </button>
                </>
              )}
              {status === "running" && (
                <span className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Updating…
                </span>
              )}
              {status === "restarting" && (
                <span className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Waiting for server…
                </span>
              )}
              {status === "done" && (
                <button
                  type="button"
                  onClick={() => window.location.reload()}
                  className="flex h-9 items-center gap-2 rounded-sm bg-amber-500 px-4 text-xs font-semibold text-black transition hover:bg-amber-400"
                >
                  <RefreshCw className="h-3.5 w-3.5" />
                  Reload
                </button>
              )}
              {status === "failed" && (
                <button
                  type="button"
                  onClick={() => { setStatus("idle"); setOutput([]); }}
                  className="h-9 rounded-sm border border-border px-4 text-xs text-muted-foreground transition hover:bg-secondary hover:text-foreground"
                >
                  Try Again
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {macModalOpen && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="relative flex w-full max-w-lg flex-col rounded-sm border border-border bg-card shadow-2xl">
            <div className="flex items-center justify-between border-b border-border px-5 py-4">
              <div className="flex items-center gap-2">
                <Download className="h-4 w-4 text-amber-400" />
                <span className="text-sm font-semibold text-foreground">
                  Update macOS App{macLatestVersion ? ` (v${macLatestVersion})` : ""}
                </span>
              </div>
              {macStatus !== "running" && (
                <button
                  type="button"
                  onClick={() => setMacModalOpen(false)}
                  className="grid h-7 w-7 place-items-center rounded-sm text-muted-foreground transition hover:bg-secondary hover:text-foreground"
                >
                  <X className="h-4 w-4" />
                </button>
              )}
            </div>

            <div className="px-5 py-4 flex flex-col gap-3">
              {macStatus === "idle" && (
                <p className="text-sm text-muted-foreground">
                  A new version of the Spark desktop app is available. Spark will download the latest
                  release, quit the running app, install it into Applications, and relaunch.
                </p>
              )}
              {macStatus === "idle" && macReleaseNotes && (
                <div className="flex flex-col gap-1.5">
                  <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground/70">
                    What's new{macLatestVersion ? ` in v${macLatestVersion}` : ""}
                  </span>
                  <div className="max-h-48 overflow-y-auto whitespace-pre-wrap rounded-sm border border-border bg-secondary/40 px-3 py-2 text-xs leading-relaxed text-foreground/80">
                    {macReleaseNotes}
                  </div>
                  {macReleaseUrl && (
                    <a
                      href={macReleaseUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="self-start text-[11px] text-amber-400 underline-offset-2 hover:underline"
                    >
                      View full release notes →
                    </a>
                  )}
                </div>
              )}
              {macStatus === "running" && (
                <p className="text-sm text-amber-400 flex items-center gap-1.5">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Downloading the latest installer…
                </p>
              )}
              {macStatus === "installing" && (
                <p className="text-sm text-emerald-400">
                  Installer started. Spark will quit, replace the app in Applications, and relaunch.
                </p>
              )}
              {macStatus === "failed" && (
                <p className="text-sm text-red-400">Update failed{macError ? `: ${macError}` : "."}</p>
              )}
            </div>

            <div className="flex items-center justify-end gap-2 border-t border-border px-5 py-3">
              {macStatus === "idle" && (
                <>
                  <button
                    type="button"
                    onClick={() => setMacModalOpen(false)}
                    className="h-9 rounded-sm border border-border px-4 text-xs text-muted-foreground transition hover:bg-secondary hover:text-foreground"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={() => void startMacUpdate()}
                    className="flex h-9 items-center gap-2 rounded-sm bg-amber-500 px-4 text-xs font-semibold text-black transition hover:bg-amber-400"
                  >
                    <Download className="h-3.5 w-3.5" />
                    Download & Install
                  </button>
                </>
              )}
              {(macStatus === "running" || macStatus === "installing") && (
                <span className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  {macStatus === "running" ? "Downloading…" : "Installing…"}
                </span>
              )}
              {(macStatus === "installing" || macStatus === "failed") && (
                <button
                  type="button"
                  onClick={() => setMacModalOpen(false)}
                  className="h-9 rounded-sm border border-border px-4 text-xs text-muted-foreground transition hover:bg-secondary hover:text-foreground"
                >
                  Close
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </UpdateModalContext.Provider>
  );
}
