import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { MoreHorizontal } from "lucide-react";
import type { SessionInfo } from "@/lib/api";
import { useSessionStore } from "@/lib/sessionStore";
import { sidebarStatus } from "@/lib/sidebarOrganization";
import { threadTitle } from "@/components/chat/ThreadRow";

/** Shared pointer and keyboard actions. Keep controls outside the row's open button. */
export function SidebarThreadActions({ session }: { session: SessionInfo }) {
  const store = useSessionStore();
  const [anchor, setAnchor] = useState<{ top: number; left: number } | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const meta = store.sidebarMetadata[session.id];
  const status = sidebarStatus(session, store.sidebarAttention[session.id]);
  const blocked = status === "Running" || status === "Needs you";
  useEffect(() => {
    if (!anchor) return;
    panel.current?.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus();
    const close = (event: MouseEvent) => {
      if (!panel.current?.contains(event.target as Node) && !trigger.current?.contains(event.target as Node)) setAnchor(null);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [anchor]);
  const close = () => { setAnchor(null); trigger.current?.focus(); };
  const act = (action: () => void) => { close(); action(); };
  const buttonClass = "w-full rounded px-3 py-1.5 text-left text-xs hover:bg-secondary focus-visible:outline-2 focus-visible:outline-primary disabled:opacity-40";
  return <>
    <button ref={trigger} type="button" aria-label="Thread actions" aria-description={`Organize ${threadTitle(session)}`} title={`Actions for ${threadTitle(session)}`} aria-expanded={Boolean(anchor)}
      aria-haspopup="dialog" className="shrink-0 rounded p-1 text-muted-foreground hover:bg-secondary focus-visible:outline-2 focus-visible:outline-primary"
      onClick={(event) => {
        event.stopPropagation();
        const rect = event.currentTarget.getBoundingClientRect();
        setAnchor(anchor ? null : { top: Math.min(rect.bottom, window.innerHeight - 280), left: Math.max(8, Math.min(rect.left, window.innerWidth - 232)) });
      }}><MoreHorizontal className="h-3.5 w-3.5" /></button>
    {anchor && createPortal(<div ref={panel} role="dialog" aria-label={`Organize ${threadTitle(session)}`} aria-modal="false"
      style={{ top: anchor.top, left: anchor.left }} className="fixed z-[300] w-56 rounded-md border border-border bg-popover p-1 text-popover-foreground shadow-xl"
      onKeyDown={(event) => {
        event.stopPropagation();
        if (event.key === "Escape") { event.preventDefault(); close(); }
        if (["ArrowDown", "ArrowUp", "Home", "End", "Tab"].includes(event.key)) {
          const buttons = [...event.currentTarget.querySelectorAll<HTMLButtonElement>("button:not(:disabled)")];
          const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
          const next = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1 : (index + (event.key === "ArrowUp" || (event.key === "Tab" && event.shiftKey) ? -1 : 1) + buttons.length) % buttons.length;
          event.preventDefault(); buttons[next]?.focus();
        }
      }}>
      <button className={buttonClass} disabled={store.sidebarBusy || !store.sidebarMetadataReady} onClick={() => act(() => store.togglePin(session.id))}>{meta?.pinned ? "Unpin" : "Pin"}</button>
      <button className={buttonClass} disabled={store.sidebarBusy || !store.sidebarMetadataReady || (!meta?.settled && blocked)} onClick={() => act(() => store.toggleSettled(session.id))}>{meta?.settled ? "Unsettle" : "Settle"}</button>
      {!meta?.settled && blocked && <p className="px-3 py-1 text-[11px] text-muted-foreground">{status === "Needs you" ? "Resolve the pending decision first" : "Wait for live work to finish"}</p>}
      <button className={buttonClass} disabled={store.sidebarBusy || !store.sidebarMetadataReady} onClick={() => act(() => store.moveSidebarSession(session.id, -1))}>Move up</button>
      <button className={buttonClass} disabled={store.sidebarBusy || !store.sidebarMetadataReady} onClick={() => act(() => store.moveSidebarSession(session.id, 1))}>Move down</button>
      <button className={buttonClass} onClick={() => act(() => void store.deleteSession(session.id))}>Delete thread</button>
      <button className={buttonClass} onClick={close}>Close</button>
    </div>, document.body)}
  </>;
}

export function SidebarMetadataFeedback() {
  const store = useSessionStore();
  const undoButton = useRef<HTMLButtonElement>(null);
  useEffect(() => { if (store.sidebarUndo) undoButton.current?.focus(); }, [store.sidebarUndo, store.sidebarBusy]);
  return <div className="shrink-0 px-2 text-xs">
    {store.sidebarMetadataError && <div role="alert" className="py-1 text-destructive">{store.sidebarMetadataError} <button type="button" className="underline" onClick={() => void store.reloadSidebarMetadata()}>Refresh</button></div>}
    {store.sidebarUndo && <div role="status" className="py-1">Thread {store.sidebarUndo.settled ? "unsettled" : "settled"}. <button type="button" ref={undoButton} className="underline" disabled={store.sidebarBusy} onClick={store.undoSidebarChange}>Undo</button></div>}
    {store.canImportLocalPins && <button type="button" disabled={store.sidebarBusy} className="py-1 underline" onClick={store.importLocalPins}>Import this browser’s old pins into this profile</button>}
  </div>;
}
