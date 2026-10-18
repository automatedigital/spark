import { useCallback, useEffect, useRef, useState } from "react";
import { api, type SubagentNavigation } from "@/lib/api";
import { useSessionStore } from "@/lib/sessionStore";
import { setGlobalNavTarget } from "@/lib/globalNavigation";
import { SIDEBAR_SCOPE_EVENT, sidebarPreferenceKey, sidebarPreferenceScopeReady } from "@/lib/sidebarPrefs";
import { activateChildNavigation } from "@/lib/subagentNavigation";

export function useSubagentNavigation(sessionId: string | null | undefined, childId: string) {
  const { selectedId, reloadProjects } = useSessionStore();
  const [navigation, setNavigation] = useState<SubagentNavigation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const generation = useRef(0);
  const selection = useRef(selectedId);
  selection.current = selectedId;

  useEffect(() => {
    const invalidate = () => { ++generation.current; setRevision((value) => value + 1); setNavigation(null); };
    window.addEventListener(SIDEBAR_SCOPE_EVENT, invalidate);
    return () => window.removeEventListener(SIDEBAR_SCOPE_EVENT, invalidate);
  }, []);

  useEffect(() => {
    const fence = generation;
    const gen = ++fence.current;
    const request = new AbortController();
    setNavigation(null);
    setError(null);
    setBusy(false);
    if (sessionId && sidebarPreferenceScopeReady()) {
      void api.getSubagentNavigation(sessionId, childId, request.signal).then((value) => {
        if (generation.current === gen && value.schema_version === 1 && value.subagent_id === childId) setNavigation(value);
      }).catch(() => { if (generation.current === gen) setError("Navigation destinations could not be verified. Refresh destinations to try again."); });
    }
    return () => { ++fence.current; request.abort(); };
  }, [sessionId, childId, revision]);

  const open = useCallback(async (kind: "task" | "worktree") => {
    if (!sessionId || busy || !sidebarPreferenceScopeReady()) return;
    const gen = generation.current;
    const scope = sidebarPreferenceKey("child-navigation");
    const current = () => generation.current === gen && selection.current === sessionId && sidebarPreferenceScopeReady() && sidebarPreferenceKey("child-navigation") === scope;
    setBusy(true);
    setError(null);
    try {
      await activateChildNavigation(kind, childId, {
        current,
        read: () => api.getSubagentNavigation(sessionId, childId),
        openWorktree: () => api.openSubagentWorktree(sessionId, childId),
        refreshProjects: reloadProjects,
        navigate: setGlobalNavTarget,
      });
    } catch (err) { if (current()) setError(err instanceof Error ? err.message : "The destination could not be opened."); }
    finally { if (current()) setBusy(false); }
  }, [sessionId, childId, busy, reloadProjects]);

  return { navigation, error, busy, open, refresh: () => setRevision((value) => value + 1) };
}
