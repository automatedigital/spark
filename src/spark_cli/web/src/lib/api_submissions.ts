import { fetchJSON } from "./apiHelpers";
import { sidebarPreferenceKey } from "./sidebarPrefs";

// The receipt belongs to the originating draft, not a mounted panel. Retain it
// across navigation/refresh and ambiguous HTTP failure until acknowledgement.
const pendingSubmissions = new Map<string, string>();
export function beginComposerSubmission(effect: unknown): { key: string; id: string } {
  const key = sidebarPreferenceKey(`spark-root-submission:${JSON.stringify(effect)}`);
  let id = pendingSubmissions.get(key);
  try { id ??= sessionStorage.getItem(key) ?? undefined; } catch { /* Memory fallback. */ }
  id ??= crypto.randomUUID();
  pendingSubmissions.set(key, id);
  try { sessionStorage.setItem(key, id); } catch { /* Memory fallback. */ }
  return { key, id };
}
export function acknowledgeComposerSubmission(submission: { key: string; id: string }): void {
  if (pendingSubmissions.get(submission.key) !== submission.id) return;
  pendingSubmissions.delete(submission.key);
  try { if (sessionStorage.getItem(submission.key) === submission.id) sessionStorage.removeItem(submission.key); } catch { /* Memory fallback. */ }
}

export async function postRootSubmission<T extends { ok: boolean; session_id: string }>(
  url: string, payload: Record<string, unknown>, submissionId?: string,
): Promise<T> {
  const submission = submissionId ? null : beginComposerSubmission({ url, payload });
  const result = await fetchJSON<T>(url, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...payload, submission_id: submissionId ?? submission!.id }),
  });
  if (result.ok !== true || typeof result.session_id !== "string" || !result.session_id) throw new Error("Could not confirm submission. Your draft is kept.");
  if (submission) acknowledgeComposerSubmission(submission);
  return result;
}

