// Mounted correctness fixture: deliberately adopt between render and passive effects.
import { createElement, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useChatStreamController, type UseChatStreamControllerResult } from "../src/hooks/useChatStreamController";

export async function checkPendingHandoff(host: HTMLElement, buffered: boolean) {
  const trace: { kind: string; id: string | null; status?: string | null }[] = [];
  let controller: UseChatStreamControllerResult;
  let arm: () => void = () => {};
  let acknowledged = false;
  let staleSnapshots = 0;
  function Fixture() {
    const [id, setId] = useState("A");
    const [armed, setArmed] = useState(false);
    const scroll = useRef<HTMLDivElement>(null);
    const stream = useChatStreamController({ activeSessionId: id, recoverySequence: 1, sessionAliases: [id], callbacks: {
      onStateChange: (transition) => { if (acknowledged) trace.push({ kind: "commit", id: transition.state.activeSessionId, status: transition.state.statusLabel }); },
    } });
    controller = stream;
    const adopt = stream.adoptSession;
    const snapshot = stream.state;
    const isCurrent = stream.isCurrentState;
    arm = () => setArmed(true);
    const virtualizer = useVirtualizer({ count: 100, getScrollElement: () => scroll.current, estimateSize: () => 30 });
    const measured = useRef(id);
    useLayoutEffect(() => {
      if (measured.current === id) return;
      measured.current = id;
      trace.push({ kind: "measure", id });
      virtualizer.measure();
    }, [id, virtualizer]);
    useLayoutEffect(() => {
      if (!armed) return;
      acknowledged = true;
      adopt("B", ["A", "B"]);
      setId("B");
    }, [armed, adopt]); // Deliberately intervene before this render's pending passive effects.
    useEffect(() => {
      if (!isCurrent(snapshot)) { staleSnapshots += 1; return; }
      trace.push({ kind: "publish", id: snapshot.activeSessionId, status: snapshot.statusLabel });
      if (snapshot.activeSessionId) setId(snapshot.activeSessionId);
    }, [armed, snapshot, isCurrent]);
    return createElement("div", { ref: scroll, "data-handoff-id": id, "data-status": stream.state.statusLabel, style: { height: 200, overflow: "auto" } },
      createElement("div", { style: { height: virtualizer.getTotalSize() } }, stream.state.messages.map((message, index) => createElement("div", { key: index }, message.content))));
  }
  const root = createRoot(host);
  const frames = async () => { for (let i = 0; i < 5; i++) await new Promise(requestAnimationFrame); };
  try {
    root.render(createElement(Fixture));
    await frames();
    const node = host.firstElementChild;
    if (buffered) controller!.handleEvent({ topic: "chat.token", session_id: "A", data: { t: "ONE_BUFFERED_TOKEN" } });
    arm();
    await frames();
    controller!.flush();
    await frames();
    if (host.firstElementChild !== node || node?.getAttribute("data-handoff-id") !== "B") throw new Error("handoff remounted or failed to settle B");
    if (trace.some((entry) => entry.kind === "commit" && entry.id === "A")) throw new Error("post-ack reducer rollback to A");
    if (trace.filter((entry) => entry.kind === "measure").length !== 1) throw new Error("identity measured more than once");
    if (!staleSnapshots) throw new Error("fixture did not exercise a superseded bridge snapshot");
    if (buffered && host.textContent?.split("ONE_BUFFERED_TOKEN").length !== 2) throw new Error("buffer lost or duplicated");
    // Genuine reducer-driven compression still propagates and fresh status does not stall.
    controller!.handleEvent({ topic: "chat.session_migrated", session_id: "B", data: { old_session_id: "B", new_session_id: "C" } });
    await frames();
    if (node?.getAttribute("data-handoff-id") !== "C" || controller!.state.activeSessionId !== "C") throw new Error("compression identity failed to propagate");
    controller!.handleEvent({ topic: "chat.status", session_id: "C", data: { message: "CURRENT_STATUS" } });
    await frames();
    if (node?.getAttribute("data-status") !== "CURRENT_STATUS") throw new Error("fresh status projection stalled");
    return { buffered, staleSnapshots, trace };
  } finally { root.unmount(); }
}
