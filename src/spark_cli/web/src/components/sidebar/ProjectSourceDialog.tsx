import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import {
  ArrowLeft,
  Cloud,
  FolderOpen,
  FolderPlus,
  Github,
  GitBranch,
  Link2,
  Loader2,
  Search,
  X,
} from "lucide-react";
import type { ProjectCreateRequest } from "@/lib/api";
import { cn } from "@/lib/utils";

type SourceId = "local_folder" | "git_url" | "github" | "azure" | "bitbucket" | "gitlab";

const SOURCES: Array<{
  id: SourceId;
  label: string;
  description: string;
  icon: typeof FolderOpen;
  enabled?: boolean;
}> = [
  { id: "local_folder", label: "Local folder", description: "Browse a folder on disk", icon: FolderPlus },
  { id: "git_url", label: "Git URL", description: "Clone from a remote URL", icon: Link2 },
  { id: "github", label: "GitHub repository", description: "Clone GitHub owner/repo", icon: Github },
  { id: "azure", label: "Azure DevOps repository", description: "Clone Azure DevOps project/repository", icon: Cloud },
  { id: "bitbucket", label: "Bitbucket repository", description: "Clone Bitbucket workspace/repository", icon: GitBranch },
  { id: "gitlab", label: "GitLab repository", description: "Clone GitLab group/project", icon: GitBranch },
];

function sourceTitle(source: SourceId) {
  return SOURCES.find((item) => item.id === source)?.label ?? "Add project";
}

export function ProjectSourceDialog({
  open,
  onClose,
  onChooseNewFolder,
  onCreate,
}: {
  open: boolean;
  onClose: () => void;
  onChooseNewFolder: () => void;
  onCreate: (request: ProjectCreateRequest) => Promise<void>;
}) {
  const [source, setSource] = useState<SourceId | null>(null);
  const [query, setQuery] = useState("");
  const [name, setName] = useState("");
  const [path, setPath] = useState("");
  const [cloneUrl, setCloneUrl] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) return;
    setSource(null);
    setQuery("");
    setName("");
    setPath("");
    setCloneUrl("");
    setSaving(false);
    setError(null);
  }, [open]);

  if (!open) return null;

  const close = () => {
    if (!saving) onClose();
  };

  const filteredSources = SOURCES.filter((item) => {
    const haystack = `${item.label} ${item.description}`.toLowerCase();
    return !query.trim() || haystack.includes(query.trim().toLowerCase());
  });

  const submit = async () => {
    if (!source || saving) return;
    if (source !== "local_folder" && source !== "git_url" && source !== "github") return;
    const trimmedPath = path.trim();
    const trimmedUrl = cloneUrl.trim();
    if (source === "local_folder" && !trimmedPath) {
      setError("Enter the path to an existing folder.");
      return;
    }
    if ((source === "git_url" || source === "github") && !trimmedUrl) {
      setError("Enter a repository URL to clone.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await onCreate({
        name: name.trim(),
        source,
        ...(source === "local_folder" ? { path: trimmedPath } : { clone_url: trimmedUrl }),
      });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add project");
    } finally {
      setSaving(false);
    }
  };

  const body = source === null ? (
    <>
      <div className="flex items-center gap-2 border-b border-border/70 px-4 py-3">
        <Search className="h-4 w-4 shrink-0 text-muted-foreground/65" />
        <input
          autoFocus
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search…"
          className="min-w-0 flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground/45"
          aria-label="Search project sources"
        />
        <button type="button" onClick={close} className="rounded-md p-1 text-muted-foreground/60 hover:bg-foreground/8 hover:text-foreground" aria-label="Close">
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="px-4 pb-2 pt-4 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground/45">Sources</div>
      <div className="px-2 pb-3">
        <button
          type="button"
          onClick={onChooseNewFolder}
          className="flex w-full items-center gap-3 rounded-md px-2.5 py-2.5 text-left transition hover:bg-foreground/[0.07]"
        >
          <FolderOpen className="h-4 w-4 shrink-0 text-muted-foreground/75" />
          <span className="min-w-0 flex-1">
            <span className="block text-[13px] text-foreground">New folder</span>
            <span className="mt-0.5 block text-[11px] text-muted-foreground/45">Create a fresh project workspace</span>
          </span>
        </button>
        {filteredSources.map((item) => {
          const Icon = item.icon;
          const enabled = item.enabled !== false;
          return (
            <button
              key={item.id}
              type="button"
              disabled={!enabled}
              onClick={() => {
                setSource(item.id);
                setQuery("");
                setError(null);
              }}
              className={cn(
                "flex w-full items-center gap-3 rounded-md px-2.5 py-2.5 text-left transition",
                enabled ? "hover:bg-foreground/[0.07]" : "cursor-not-allowed opacity-35",
              )}
            >
              <Icon className="h-4 w-4 shrink-0 text-muted-foreground/75" />
              <span className="min-w-0 flex-1">
                <span className="block text-[13px] text-foreground">{item.label}</span>
                <span className="mt-0.5 block text-[11px] text-muted-foreground/45">{item.description}</span>
              </span>
              {!enabled && <span className="rounded border border-amber-400/20 px-1.5 py-0.5 text-[10px] text-amber-300/75">Setup required</span>}
            </button>
          );
        })}
      </div>
      <div className="border-t border-border/60 px-4 py-2 text-[10px] text-muted-foreground/45">
        <kbd className="rounded bg-foreground/10 px-1.5 py-0.5 text-foreground/70">Esc</kbd> Close
      </div>
    </>
  ) : (
    <>
      <div className="flex items-center gap-2 border-b border-border/70 px-4 py-3">
        <button type="button" onClick={() => setSource(null)} className="rounded-md p-1 text-muted-foreground/65 hover:bg-foreground/8 hover:text-foreground" aria-label="Back to project sources">
          <ArrowLeft className="h-4 w-4" />
        </button>
        <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">{sourceTitle(source)}</span>
        <button type="button" onClick={close} className="rounded-md p-1 text-muted-foreground/60 hover:bg-foreground/8 hover:text-foreground" aria-label="Close">
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="space-y-4 p-4">
        <div>
          <label className="mb-1.5 block text-[11px] font-medium text-muted-foreground/70">{source === "local_folder" ? "Folder path" : "Repository URL"}</label>
          <input
            autoFocus
            value={source === "local_folder" ? path : cloneUrl}
            onChange={(event) => source === "local_folder" ? setPath(event.target.value) : setCloneUrl(event.target.value)}
            placeholder={source === "local_folder" ? "/Users/you/Developer/project" : source === "github" ? "https://github.com/owner/repository" : "https://… or git@…"}
            className="h-9 w-full rounded-md border border-border bg-background/65 px-2.5 text-sm text-foreground outline-none transition placeholder:text-muted-foreground/35 focus:border-foreground/35"
          />
          <p className="mt-1.5 text-[10px] leading-4 text-muted-foreground/45">
            {source === "local_folder" ? "Spark will link the folder in place. Your existing files stay where they are." : "Spark clones a shallow checkout into your Spark workspace."}
          </p>
        </div>
        <div>
          <label className="mb-1.5 block text-[11px] font-medium text-muted-foreground/70">Project name <span className="font-normal text-muted-foreground/40">(optional)</span></label>
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Use the folder or repository name"
            className="h-9 w-full rounded-md border border-border bg-background/65 px-2.5 text-sm text-foreground outline-none transition placeholder:text-muted-foreground/35 focus:border-foreground/35"
          />
        </div>
        {error && <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/10 px-2.5 py-2 text-[11px] text-destructive">{error}</p>}
        <button
          type="button"
          onClick={() => void submit()}
          disabled={saving}
          className="flex h-9 w-full items-center justify-center gap-2 rounded-md bg-foreground px-3 text-xs font-semibold text-background transition hover:bg-foreground/90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          {saving ? "Adding project…" : source === "local_folder" ? "Add local folder" : "Clone repository"}
        </button>
      </div>
    </>
  );

  return createPortal(
    <div className="fixed inset-0 z-[180] flex items-start justify-center bg-background/55 p-4 pt-[12vh] backdrop-blur-sm" role="dialog" aria-modal="true" aria-label="New project">
      <div className="w-full max-w-[520px] overflow-hidden rounded-2xl border border-border/80 bg-card/95 shadow-2xl shadow-black/40 backdrop-blur-xl">
        {body}
      </div>
    </div>,
    document.body,
  );
}
