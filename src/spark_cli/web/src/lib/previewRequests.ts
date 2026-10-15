/** One visible preview observer owns its reads and their browser connections.
 * Poll after settlement so a slow local-server scan cannot fan out. Teardown
 * aborts transport as well as fencing responses that raced project selection.
 */
export function observePreviewRequest<T>(
  request: (signal: AbortSignal) => Promise<T>,
  apply: (value: T) => void,
  intervalMs?: number,
  onError?: (error: unknown) => void,
): () => void {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const tick = async () => {
    try {
      const value = await request(controller.signal);
      if (!controller.signal.aborted) apply(value);
    } catch (error) {
      if (!controller.signal.aborted) onError?.(error);
    } finally {
      if (!controller.signal.aborted && intervalMs !== undefined) timer = setTimeout(() => void tick(), intervalMs);
    }
  };
  void tick();
  return () => {
    controller.abort();
    clearTimeout(timer);
  };
}
