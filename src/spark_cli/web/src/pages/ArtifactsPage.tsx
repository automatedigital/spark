import { useEffect, useState } from "react";
import { Download, ExternalLink, FileText, Image as ImageIcon, Link2 } from "lucide-react";
import { api, openExternal } from "@/lib/api";
import type { ArtifactInfo, ArtifactsResponse } from "@/lib/api";

type Tab = "all" | "images" | "files" | "links";

const TABS: Array<{ id: Tab; label: string }> = [
  { id: "all", label: "All" },
  { id: "images", label: "Images" },
  { id: "files", label: "Files" },
  { id: "links", label: "Links" },
];

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function timeAgo(mtime: number): string {
  const secs = Math.max(0, Date.now() / 1000 - mtime);
  if (secs < 3600) return `${Math.max(1, Math.floor(secs / 60))}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}

function ArtifactCard({ artifact }: { artifact: ArtifactInfo }) {
  const Icon = artifact.type === "image" ? ImageIcon : artifact.type === "link" ? Link2 : FileText;
  const open = () => {
    if (artifact.type === "link") {
      void openExternal(artifact.url);
    } else {
      window.open(artifact.url, "_blank", "noopener");
    }
  };
  return (
    <button
      type="button"
      onClick={open}
      className="group flex flex-col overflow-hidden rounded-lg border border-border/50 bg-card/30 text-left transition hover:border-border hover:bg-card/60"
    >
      {artifact.type === "image" ? (
        <div className="aspect-video w-full overflow-hidden bg-foreground/4">
          <img
            src={artifact.url}
            alt={artifact.name}
            loading="lazy"
            className="h-full w-full object-cover transition group-hover:scale-[1.02]"
          />
        </div>
      ) : (
        <div className="grid aspect-video w-full place-items-center bg-foreground/4">
          <Icon className="h-8 w-8 text-muted-foreground/40" />
        </div>
      )}
      <div className="flex items-center justify-between gap-2 px-3 py-2.5">
        <div className="min-w-0">
          <div className="truncate text-[12px] font-medium text-foreground">{artifact.name}</div>
          <div className="mt-0.5 truncate text-[11px] text-muted-foreground">
            {artifact.project_name} · {artifact.type === "link" ? "link" : formatSize(artifact.size)} ·{" "}
            {timeAgo(artifact.mtime)}
          </div>
        </div>
        {artifact.type === "link" ? (
          <ExternalLink className="h-3.5 w-3.5 shrink-0 text-muted-foreground opacity-0 transition group-hover:opacity-100" />
        ) : (
          <Download className="h-3.5 w-3.5 shrink-0 text-muted-foreground opacity-0 transition group-hover:opacity-100" />
        )}
      </div>
    </button>
  );
}

export default function ArtifactsPage() {
  const [tab, setTab] = useState<Tab>("all");
  const [data, setData] = useState<ArtifactsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .listArtifacts(tab)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tab]);

  const counts = data?.counts;
  const artifacts = data?.artifacts ?? [];

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Tabs */}
      <div className="flex items-baseline gap-5 px-5 pt-4">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`border-b-2 pb-1.5 text-[13px] font-medium transition ${
              tab === t.id
                ? "border-foreground text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {t.label}{" "}
            <span className="ml-0.5 text-[11px] text-muted-foreground">
              {counts ? counts[t.id] : ""}
            </span>
          </button>
        ))}
      </div>

      {/* Body */}
      <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-8 pt-4">
        {loading ? (
          <div className="flex justify-center py-24">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          </div>
        ) : error ? (
          <p className="py-24 text-center text-sm text-muted-foreground">Failed to load artifacts: {error}</p>
        ) : artifacts.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-32 text-center">
            <p className="text-sm font-semibold text-foreground">No artifacts found</p>
            <p className="mt-1.5 max-w-sm text-[13px] text-muted-foreground">
              Generated images and file outputs will appear here as sessions produce them.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
            {artifacts.map((a) => (
              <ArtifactCard key={a.id} artifact={a} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
