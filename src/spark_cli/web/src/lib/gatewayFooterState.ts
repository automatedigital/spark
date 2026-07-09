import type { StatusResponse } from "./api";

export type GatewayFooterState = {
  label: string;
  dot: string;
  title: string;
};

export function gatewayFooterState(status: StatusResponse | null, pollFailed: boolean): GatewayFooterState {
  if (pollFailed) {
    return {
      label: "Reconnecting",
      dot: "bg-amber-400 animate-pulse",
      title: "The web UI is retrying the status connection.",
    };
  }
  if (!status) {
    return {
      label: "Gateway starting",
      dot: "bg-amber-400 animate-pulse",
      title: "Waiting for the first status response.",
    };
  }

  const failedPlatforms = Object.values(status.gateway_platforms ?? {}).filter((p) => (
    p.state === "fatal" || p.state === "disconnected"
  ));
  if (status.gateway_running) {
    if (failedPlatforms.length > 0) {
      return {
        label: "Gateway degraded",
        dot: "bg-amber-400",
        title: `${failedPlatforms.length} configured platform${failedPlatforms.length === 1 ? "" : "s"} need attention.`,
      };
    }
    return {
      label: "Gateway ready",
      dot: "bg-emerald-400",
      title: status.gateway_pid ? `Gateway process ${status.gateway_pid} is running.` : "Gateway runtime is healthy.",
    };
  }
  if (status.gateway_state === "starting") {
    return {
      label: "Gateway starting",
      dot: "bg-amber-400 animate-pulse",
      title: "Gateway runtime is starting.",
    };
  }
  if (status.gateway_state === "startup_failed") {
    return {
      label: "Gateway failed",
      dot: "bg-destructive",
      title: status.gateway_exit_reason || "Gateway startup failed.",
    };
  }
  if (status.active_sessions > 0) {
    return {
      label: "Web chat active",
      dot: "bg-emerald-400",
      title: "The web UI is connected and chat work is active; the messaging gateway process is not running.",
    };
  }
  return {
    label: "Gateway stopped",
    dot: "bg-muted-foreground/45",
    title: "The web UI is connected; the messaging gateway process is stopped.",
  };
}
