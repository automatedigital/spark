import { useContext, useEffect, useState, type ReactNode } from "react";
import { SIDEBAR_SCOPE_EVENT } from "@/lib/sidebarPrefs";
import { DraftContext, SettingsDraftOwner, settingsDraftScope } from "./settingsDrafts";

export function SettingsDraftProvider({ children, tab }: { children: ReactNode; tab?: string }) {
  const parent = useContext(DraftContext);
  const [scope, setScope] = useState(settingsDraftScope);
  const [owner, setOwner] = useState(() => new SettingsDraftOwner(scope));
  useEffect(() => {
    if (parent) return;
    const reconcile = () => {
      const next = settingsDraftScope();
      setScope(next);
      setOwner((current) => current.scope === next ? current : new SettingsDraftOwner(next));
    };
    // Connection helpers advance an epoch synchronously; fence the first input
    // even when a same-window credential change has no storage event.
    const fenceInput = (event: Event) => {
      if (settingsDraftScope() === owner.scope) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      reconcile();
    };
    document.addEventListener("click", fenceInput, true);
    document.addEventListener("keydown", fenceInput, true);
    document.addEventListener("submit", fenceInput, true);
    window.addEventListener(SIDEBAR_SCOPE_EVENT, reconcile);
    window.addEventListener("storage", reconcile);
    window.addEventListener("focus", reconcile);
    return () => {
      document.removeEventListener("click", fenceInput, true);
      document.removeEventListener("keydown", fenceInput, true);
      document.removeEventListener("submit", fenceInput, true);
      window.removeEventListener(SIDEBAR_SCOPE_EVENT, reconcile);
      window.removeEventListener("storage", reconcile);
      window.removeEventListener("focus", reconcile);
    };
  }, [parent, owner]);
  return <DraftContext.Provider key={parent ? tab : scope} value={parent ? { owner: parent.owner, tab: tab ?? parent.tab } : { owner, tab: "" }}>{children}</DraftContext.Provider>;
}

