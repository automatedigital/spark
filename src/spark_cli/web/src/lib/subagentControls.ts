import type { SubagentCapabilities, SubagentControlSupport, SubagentRun } from "./apiTypes";
import { isSubagentRunning } from "./subagents";
import { sidebarPreferenceKey, sidebarPreferenceScopeReady } from "./sidebarPrefs";

const unsupported = (reason: string): SubagentControlSupport => ({ supported: false, reason });
export function childControlSupport(
  control: "inspect" | "interrupt" | "retry", run: SubagentRun,
  runs: SubagentRun[], capabilities: SubagentCapabilities | null,
): SubagentControlSupport {
  if (!capabilities || capabilities.schema_version !== 1) return unsupported("Runtime capabilities are unknown or stale. Reconnect or refresh to check support.");
  const exact = capabilities.children?.[run.id]?.controls?.[control];
  if (capabilities.children && !exact) return unsupported("The runtime has not confirmed this child's current capabilities. Refresh child state to check again.");
  const support = exact ?? capabilities.controls?.[control];
  if (!support || support.supported !== true) return unsupported(support?.reason || "This runtime does not support this control.");
  if (control === "inspect") return support;
  if (!sidebarPreferenceScopeReady()) return unsupported("Waiting for this backend's profile identity before sending child controls.");
  if (exact) return support;
  const eligible = (candidate: SubagentRun) => control === "interrupt"
    ? isSubagentRunning(candidate.status) && candidate.status !== "stale"
    : candidate.execution_mode === "async" && ["failed", "interrupted", "cancelled"].includes(candidate.status);
  if (!eligible(run)) return unsupported(control === "retry"
    ? "Only acknowledged failed or stopped async attempts can be retried. Uncertain effects require review."
    : "This child has no confirmed live execution.");
  // v1 reports any-owned-child support, not ownership per child. Only an
  // unambiguous candidate can inherit that assertion. Never infer by provider.
  if (runs.filter(eligible).length !== 1) return unsupported("The runtime reports conversation-wide support but does not identify which child it owns. Per-child capability data is required.");
  return support;
}

export interface ChildCommand {
  requestId: string;
  state: "uncertain" | "accepted";
  handle?: string;
}
const commands = new Map<string, ChildCommand>();
export function childCommandKey(sessionId: string, childId: string, kind: "interrupt" | "retry") {
  return sidebarPreferenceKey(`spark-child-command:${sessionId}:${childId}:${kind}`);
}
export function readChildCommand(key: string): ChildCommand | null {
  if (commands.has(key)) return commands.get(key)!;
  try {
    const value = JSON.parse(sessionStorage.getItem(key) || "null") as ChildCommand | null;
    if (value && typeof value.requestId === "string" && ["uncertain", "accepted"].includes(value.state)) {
      commands.set(key, value);
      return value;
    }
  } catch { /* Unavailable storage retains this tab's in-memory receipt. */ }
  return null;
}
export function saveChildCommand(key: string, command: ChildCommand) {
  commands.set(key, command);
  try { sessionStorage.setItem(key, JSON.stringify(command)); } catch { /* Best effort persistence. */ }
}
export function beginChildCommand(key: string): ChildCommand {
  const command = readChildCommand(key) ?? { requestId: crypto.randomUUID(), state: "uncertain" };
  saveChildCommand(key, command);
  return command;
}
