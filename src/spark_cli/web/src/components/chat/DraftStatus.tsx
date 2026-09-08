import { ContextTray } from "./ContextTray";

import type { ReturnTypeOfDraft } from "@/hooks/useChatDraft";

export function DraftStatus({ draft }: { draft: ReturnTypeOfDraft }) {
  if (draft.status === "idle") return null;
  return <div className="flex flex-wrap items-center gap-2 px-3 pb-1 text-xs text-muted-foreground">
    <span role="status">{{ checking: "Checking draft location…", saving: "Saving draft…", saved: "Draft saved", recovered: "Draft recovered", unavailable: "Draft kept in memory; browser storage is unavailable", conflict: "Draft changed in another tab. Your text is kept here." }[draft.status]}</span>
    {draft.status === "conflict" ? <>
      <button type="button" className="underline" onClick={draft.keepMine}>Keep my draft</button>
      <button type="button" className="underline" onClick={draft.useStored}>Use other tab’s draft</button>
    </> : draft.ready && <button type="button" className="underline" onClick={draft.discard}>Discard draft</button>}
  </div>;
}

export function DraftContextTray({ draft }: { draft: ReturnTypeOfDraft }) {
  return <ContextTray items={draft.contextItems}
    onRemove={(id) => draft.setContextItems((items) => items.filter((item) => item.id !== id))}
    onUpdateMode={(id, inclusion_mode) => draft.setContextItems((items) => items.map((item) => item.id === id ? { ...item, inclusion_mode } : item))}
    onUpdateScope={(id, scope) => draft.setContextItems((items) => items.map((item) => item.id === id ? { ...item, scope } : item))}
  />;
}
