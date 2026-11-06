/** One mounted terminal owns its created runs; reconnect only attaches that run. */
export type TerminalStatus = "connecting" | "running" | "disconnected" | "stopped" | "failed";
export interface TerminalStream {
  onmessage: ((event: MessageEvent) => void) | null;
  onerror: ((event: Event) => void) | null;
  close(): void;
}
export function createTerminalLifecycle(deps: {
  start(): Promise<{ run_id: string }>;
  stop(id: string): Promise<unknown>;
  stream(id: string): TerminalStream;
  state(status: TerminalStatus, id: string | null): void;
  event(data: { type: string; status?: string; text?: string; exit_code?: number | null }): void;
  error(message: string): void;
}) {
  let retired = false;
  let generation = 0;
  let runId: string | null = null;
  let source: TerminalStream | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let retries = 0;
  const stopped = new Set<string>();
  const stop = (id: string) => {
    if (stopped.has(id)) return;
    stopped.add(id);
    void deps.stop(id).catch((error) => deps.error(`Shell cleanup failed: ${String(error)}`));
  };
  const detach = () => {
    clearTimeout(timer);
    source?.close();
    source = null;
  };
  const attach = (ownedGeneration: number, id: string) => {
    if (retired || generation !== ownedGeneration || runId !== id) return;
    detach();
    deps.state("connecting", id);
    const lost = () => {
      if (retired || generation !== ownedGeneration || runId !== id) return;
      detach();
      if (retries++ < 2) {
        deps.state("connecting", id);
        timer = setTimeout(() => attach(ownedGeneration, id), 500 * retries);
      } else {
        deps.state("disconnected", id);
        deps.error("Terminal stream disconnected; Reconnect attaches this shell. Restart creates a new shell.");
      }
    };
    try {
      const stream = deps.stream(id);
      source = stream;
      const current = () => !retired && generation === ownedGeneration && runId === id && source === stream;
      stream.onmessage = (event) => {
        if (!current()) return;
        try {
          const data = JSON.parse(event.data);
          if (data.type === "done" || (data.type === "state" && ["done", "stopped", "failed"].includes(data.status))) {
            deps.state(data.status === "failed" ? "failed" : "stopped", id);
            detach();
          } else if (data.type === "state") {
            deps.state(data.status === "running" ? "running" : "connecting", id);
          }
          deps.event(data);
        } catch { lost(); }
      };
      stream.onerror = () => { if (current()) lost(); };
    } catch { lost(); }
  };
  const restart = () => {
    if (retired) return;
    const ownedGeneration = ++generation;
    detach();
    if (runId) stop(runId);
    runId = null;
    retries = 0;
    deps.state("connecting", null);
    void deps.start().then(({ run_id: id }) => {
      if (retired || generation !== ownedGeneration) { stop(id); return; }
      runId = id;
      attach(ownedGeneration, id);
    }).catch((error) => {
      if (retired || generation !== ownedGeneration) return;
      deps.state("failed", null);
      deps.error(`Failed to start shell: ${String(error)}`);
    });
  };
  return {
    restart,
    reconnect() { if (!retired && runId) { retries = 0; attach(generation, runId); } },
    retire() {
      retired = true;
      generation++;
      detach();
      if (runId) stop(runId);
      runId = null;
    },
  };
}
