import { useEffect, useState } from "react";
import { contextApi } from "@/lib/context";
import type { ContextEstimate, ContextItem } from "@/lib/context";

export function useTokenEstimate(
  prompt: string,
  contextItems: ContextItem[],
  sessionId?: string | null,
) {
  const [estimate, setEstimate] = useState<ContextEstimate | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    // An estimate belongs to these inputs, including during the next debounce.
    setEstimate(null);
    setLoading(false);

    const timer = setTimeout(() => {
      setLoading(true);

      contextApi
        .estimateTokens(
          { sessionId: sessionId ?? undefined, promptText: prompt, contextItems },
          controller.signal,
        )
        .then((result) => {
          if (!active) return;
          setEstimate(result);
          setLoading(false);
        })
        .catch(() => {
          if (!active) return;
          setEstimate(null);
          setLoading(false);
        });
    }, 500);

    return () => {
      // Fence callbacks even if a transport ignores abort or already resolved.
      active = false;
      clearTimeout(timer);
      controller.abort();
    };
  }, [prompt, contextItems, sessionId]);

  return { estimate, loading };
}
