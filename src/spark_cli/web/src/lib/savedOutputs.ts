export interface SavedOutput {
  id: string;
  title: string;
  sourceSessionId: string;
  projectSlug: string | null;
  content: string;
  savedAt: number;
}

export interface ProjectHandoff {
  decisions: string;
  openQuestions: string;
  nextActions: string;
  updatedAt: number;
}

const outputsKey = (projectSlug: string | null) => `spark-saved-outputs:${projectSlug || "chat"}`;
const handoffKey = (projectSlug: string) => `spark-project-handoff:${projectSlug}`;

function read<T>(key: string, fallback: T): T {
  try { return JSON.parse(localStorage.getItem(key) || "null") ?? fallback; } catch { return fallback; }
}

export function listSavedOutputs(projectSlug: string | null): SavedOutput[] {
  return read<SavedOutput[]>(outputsKey(projectSlug), []).sort((a, b) => b.savedAt - a.savedAt);
}

export function saveOutput(output: Omit<SavedOutput, "savedAt">): SavedOutput {
  const item = { ...output, savedAt: Date.now() };
  const existing = listSavedOutputs(output.projectSlug).filter((entry) => entry.id !== output.id);
  localStorage.setItem(outputsKey(output.projectSlug), JSON.stringify([item, ...existing].slice(0, 100)));
  return item;
}

export function removeSavedOutput(projectSlug: string | null, id: string): void {
  localStorage.setItem(outputsKey(projectSlug), JSON.stringify(listSavedOutputs(projectSlug).filter((item) => item.id !== id)));
}

export function getProjectHandoff(projectSlug: string): ProjectHandoff {
  return read<ProjectHandoff>(handoffKey(projectSlug), { decisions: "", openQuestions: "", nextActions: "", updatedAt: 0 });
}

export function saveProjectHandoff(projectSlug: string, handoff: Omit<ProjectHandoff, "updatedAt">): ProjectHandoff {
  const value = { ...handoff, updatedAt: Date.now() };
  localStorage.setItem(handoffKey(projectSlug), JSON.stringify(value));
  return value;
}
