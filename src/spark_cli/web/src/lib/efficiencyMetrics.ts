export interface WebEfficiencySnapshot {
  version: "1.0";
  eventPayloads: number;
  eventPayloadBytes: number;
  reconnects: number;
  httpPolls: number;
  reactCommits: number;
  streamRecoveryActions: number;
}

const counters: Omit<WebEfficiencySnapshot, "version"> = {
  eventPayloads: 0,
  eventPayloadBytes: 0,
  reconnects: 0,
  httpPolls: 0,
  reactCommits: 0,
  streamRecoveryActions: 0,
};

export type WebEfficiencyCounter = keyof typeof counters;

export function recordWebEfficiency(counter: WebEfficiencyCounter, amount = 1): void {
  counters[counter] += Math.max(0, amount);
}

export function snapshotWebEfficiencyMetrics(reset = false): WebEfficiencySnapshot {
  const result: WebEfficiencySnapshot = { version: "1.0", ...counters };
  if (reset) Object.keys(counters).forEach((key) => { counters[key as WebEfficiencyCounter] = 0; });
  return result;
}
