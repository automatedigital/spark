import { useEffect, useState } from "react";
import { API_CONNECTION_EVENT } from "@/lib/apiHelpers";
import { describeRecordedRoute, getRecordedRoutes, type RecordedRoute } from "@/lib/api_routing";
import { BUS_GAP_TOPIC, BUS_RECONNECTED_TOPIC, STATE_SNAPSHOT_TOPIC, useEventBus } from "@/hooks/useEventBus";

export function RecordedRoutingDetails({ sessionId }: { sessionId?: string | null }) {
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<{ owner: string; turns: RecordedRoute[]; error?: boolean } | null>(null);
  useEventBus((event) => {
    if ([BUS_GAP_TOPIC, BUS_RECONNECTED_TOPIC, STATE_SNAPSHOT_TOPIC].includes(event.topic)
      || (event.session_id === sessionId && ["chat.turn_done", "chat.error"].includes(event.topic))) {
      setRevision((value) => value + 1);
    }
  });
  useEffect(() => {
    const changed = () => { setState(null); setRevision((value) => value + 1); };
    window.addEventListener(API_CONNECTION_EVENT, changed);
    return () => window.removeEventListener(API_CONNECTION_EVENT, changed);
  }, []);
  useEffect(() => {
    if (!sessionId) return;
    const controller = new AbortController();
    void getRecordedRoutes(sessionId, controller.signal).then((result) => {
      if (!controller.signal.aborted) setState({ owner: sessionId, turns: result.turns });
    }).catch(() => {
      if (!controller.signal.aborted) setState({ owner: sessionId, turns: [], error: true });
    });
    return () => controller.abort();
  }, [sessionId, revision]);
  const current = state?.owner === sessionId ? state : null;
  return <details className="rounded-lg border border-border p-2 text-xs">
    <summary className="cursor-pointer font-medium">Recorded turn routing</summary>
    <p className="mt-2 text-muted-foreground">Actual stored decisions only. Changing settings does not rewrite past turns.</p>
    {!sessionId ? <p>Start a thread to inspect its recorded route.</p>
      : !current ? <p role="status">Loading recorded routes…</p>
      : current.error ? <p role="alert">Recorded routes unavailable. Reopen to retry.</p>
      : !current.turns.length ? <p>No recorded route. Explanation unknown.</p>
      : <div className="max-h-52 overflow-auto">{current.turns.slice().reverse().map((turn) => <article key={turn.turn_id} className="mt-2 border-t border-border pt-2">
        <p className="break-all">Turn {turn.turn_id} · {turn.model || "Model unknown"}{turn.provider ? ` · ${turn.provider}` : ""}</p>
        {turn.status === "unknown" ? <p>Explanation unknown: this turn did not record a routing decision.</p> : <>
          <p>Role: {turn.role || turn.routing_decision?.role || "Unknown"}</p>
          <p>{describeRecordedRoute(turn)}</p>
          {turn.routing_reason && <p className="text-muted-foreground">Recorded reason: {turn.routing_reason}</p>}
          {turn.routing_decision && <>
            <p>Role: {turn.routing_decision.role} · preferred: {turn.routing_decision.desired_role}</p>
            <p>Signals: {Object.entries(turn.routing_decision.signals).map(([key, value]) => `${key}: ${String(value)}`).join("; ")}</p>
            <p>Policy scores (not confidence estimates): {Object.entries(turn.routing_decision.scores).map(([key, value]) => `${key}: ${value}`).join("; ")}</p>
          </>}
        </>}
      </article>)}</div>}
  </details>;
}
