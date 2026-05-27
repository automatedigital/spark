import { useEffect, useRef, useState } from "react";
import { contextApi } from "@/lib/context";
import type { ContextEstimate, ContextItem } from "@/lib/context";

export function useTokenEstimate(
  prompt: string,
  contextItems: ContextItem[],
  sessionId?: string | null,
) {
  const [estimate, setEstimate] = useState<ContextEstimate | null>(null);
  const [loading, setLoading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);

    timerRef.current = setTimeout(() => {
      if (abortRef.current) abortRef.current.abort();
      abortRef.current = new AbortController();
      setLoading(true);

      contextApi
        .estimateTokens({ sessionId: sessionId ?? undefined, promptText: prompt, contextItems })
        .then((result) => {
          setEstimate(result);
          setLoading(false);
        })
        .catch((err) => {
          if (err?.name !== "AbortError") {
            setEstimate(null);
            setLoading(false);
          }
        });
    }, 500);

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [prompt, contextItems, sessionId]);

  return { estimate, loading };
}
